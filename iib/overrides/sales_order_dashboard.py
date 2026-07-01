import frappe
from frappe import _

# Doctypes that link to Sales Order through a child table.
# Format: doctype → (child doctype name, fieldname on SO, sales_order field in child)
_CHILD_TABLE_LINKS = {
    "Job Order Corrugator": ("Job Order Corrugator Item", "sales_order"),
    "Job Order Converting": ("Job Order Converting Sales Order Item", "sales_order"),
}


def get_data(data):
    # Inject JOP1 and JOP2 into the Manufacturing group
    for group in data.get("transactions", []):
        if group.get("label") == _("Manufacturing"):
            items = group.get("items", [])
            if "Job Order Corrugator" not in items:
                items.insert(0, "Job Order Corrugator")
            if "Job Order Converting" not in items:
                items.insert(1, "Job Order Converting")
            break
    else:
        # Manufacturing group doesn't exist yet — create it
        data.setdefault("transactions", []).append(
            {
                "label": _("Manufacturing"),
                "items": ["Job Order Corrugator", "Job Order Converting"],
            }
        )

    # Use our custom count handler so JOP child-table links resolve correctly
    data["method"] = "iib.overrides.sales_order_dashboard.get_open_count"

    return data


@frappe.whitelist()
def get_open_count(doctype, name, items):
    """Dashboard connection count handler for Sales Order.

    JOP1 and JOP2 link to SO through child tables, so they can't be found by
    the standard WHERE sales_order = name query on their parent. We resolve them
    via child-table queries and return them as internal_links_found (with names),
    so clicking the badge navigates to a correctly-filtered list view.
    Everything else is delegated to Frappe's standard handler.
    """
    import json

    from frappe.desk.notifications import get_open_count as _frappe_get_open_count

    if isinstance(items, str):
        items = json.loads(items)

    jop_set = set(_CHILD_TABLE_LINKS)
    jop_items = [d for d in items if d in jop_set]
    standard_items = [d for d in items if d not in jop_set]

    # Standard counts for all non-JOP doctypes
    if standard_items:
        result = _frappe_get_open_count(doctype, name, standard_items)
    else:
        result = {"count": {"external_links_found": [], "internal_links_found": []}}

    # Child-table counts for JOP1 and JOP2
    for jop_doctype in jop_items:
        child_doctype, so_field = _CHILD_TABLE_LINKS[jop_doctype]
        table = f"tab{child_doctype}"
        rows = frappe.db.sql(
            f"SELECT DISTINCT parent FROM `{table}` WHERE `{so_field}` = %s",
            name,
        )
        names = [r[0] for r in rows]
        result["count"]["internal_links_found"].append(
            {
                "doctype": jop_doctype,
                "count": len(names),
                "open_count": 0,
                "names": names,
            }
        )

    return result
