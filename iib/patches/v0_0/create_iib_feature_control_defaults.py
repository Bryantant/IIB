"""
Initialise IIB Feature Control singleton with all features disabled
(checkboxes = 1).  Saving the document triggers on_update which rebuilds
Custom DocPerms and all {DocType} Simplification client scripts.
"""

import frappe


def execute():
    from iib.iib.doctype.iib_feature_control.iib_feature_control import FEATURE_MAP

    # Build a dict with every checkbox field set to 1
    all_enabled = {fieldname: 1 for fieldname in FEATURE_MAP}

    if frappe.db.exists("IIB Feature Control", "IIB Feature Control"):
        doc = frappe.get_doc("IIB Feature Control")
        doc.update(all_enabled)
    else:
        doc = frappe.get_doc({"doctype": "IIB Feature Control", **all_enabled})

    doc.save(ignore_permissions=True)
    frappe.db.commit()
