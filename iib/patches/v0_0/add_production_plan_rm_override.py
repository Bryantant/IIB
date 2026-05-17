import frappe


def execute():
    # DocType is created automatically by bench migrate.
    # This patch marks the feature as applied and ensures
    # the custom field is present on Production Plan.
    if not frappe.db.exists("Custom Field", "Production Plan-custom_rm_overrides"):
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": "Production Plan",
                "fieldname": "custom_rm_overrides",
                "fieldtype": "Table",
                "label": "Raw Material Overrides",
                "options": "Production Plan RM Override",
                "insert_after": "mr_items",
                "module": "IIB",
            }
        ).insert(ignore_permissions=True)
        frappe.db.commit()
