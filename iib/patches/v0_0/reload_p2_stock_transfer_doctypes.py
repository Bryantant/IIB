import frappe


def execute():
    for module, doctype in [
        ("iib", "Job Order Converting RM to WIP"),
        ("iib", "Job Order Converting RM to WIP Item"),
        ("iib", "Job Order Converting WIP to FG"),
        ("iib", "Job Order Converting WIP to FG Item"),
    ]:
        frappe.reload_doc(module, "doctype", frappe.scrub(doctype))
