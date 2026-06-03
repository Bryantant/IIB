import frappe
from frappe.utils import getdate


def autoname(doc, method=None):
    from iib.iib.utils.naming import get_next_iib_number

    d = getdate(doc.transaction_date or frappe.utils.today())
    yy = d.strftime("%y")
    seq = get_next_iib_number("purchase_order", period=yy, digits=4)
    doc.name = f"{yy}{seq}"
