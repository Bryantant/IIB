import frappe
from frappe.utils import nowdate


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters):
    customer = ""
    if filters:
        if isinstance(filters, str):
            import json
            filters = json.loads(filters)
        customer = filters.get("customer") or ""

    values = {
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len,
        "customer": customer,
    }

    return frappe.db.sql(
        f"""
        SELECT i.name, i.item_name, i.item_group
        FROM `tabItem` i
        WHERE i.disabled = 0
          AND i.item_group != 'Master Card'
          AND IFNULL(i.linked_customer, '') != ''
          AND i.linked_customer = %(customer)s
          AND (i.`{searchfield}` LIKE %(txt)s OR i.item_name LIKE %(txt)s)
        ORDER BY
            CASE WHEN i.`{searchfield}` LIKE %(txt)s THEN 0 ELSE 1 END,
            i.name
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        values,
    )
