import frappe
from frappe.utils import getdate


def autoname(doc, method=None):
    from iib.iib.utils.naming import get_next_iib_number

    d = getdate(doc.posting_date or frappe.utils.today())
    yy = d.strftime("%y")
    seq = get_next_iib_number("delivery_note", period=yy, digits=5)
    doc.name = f"IIB{yy}{seq}"
