import frappe


def execute():
    for module, doctype in [
        ("iib", "Job Order P2 RM to WIP"),
        ("iib", "Job Order P2 RM to WIP Item"),
        ("iib", "Job Order P2 WIP to FG"),
        ("iib", "Job Order P2 WIP to FG Item"),
    ]:
        frappe.reload_doc(module, "doctype", frappe.scrub(doctype))
