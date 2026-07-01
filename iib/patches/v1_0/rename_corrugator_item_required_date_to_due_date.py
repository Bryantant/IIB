import frappe


def execute():
    if frappe.db.has_column("Job Order Corrugator Item", "required_date"):
        frappe.db.sql(
            "UPDATE `tabJob Order Corrugator Item`"
            " SET `due_date` = `required_date`"
            " WHERE `required_date` IS NOT NULL AND (`due_date` IS NULL OR `due_date` = '')"
        )
