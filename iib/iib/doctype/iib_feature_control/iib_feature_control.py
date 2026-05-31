import frappe
from frappe.model.document import Document

# ---------------------------------------------------------------------------
# FEATURE_MAP: fieldname → (controlled_doctype, is_submittable)
# ---------------------------------------------------------------------------
FEATURE_MAP = {
    "pick_list": ("Pick List", True),
    "packing_slip": ("Packing Slip", True),
    "shipment": ("Shipment", True),
    "delivery_trip": ("Delivery Trip", True),
    "request_for_quotation": ("Request for Quotation", True),
    "supplier_quotation": ("Supplier Quotation", True),
    "quotation": ("Quotation", True),
    "work_order": ("Work Order", True),
    "project": ("Project", False),
    "payment_entry": ("Payment Entry", True),
    "payment_request": ("Payment Request", True),
    "material_request": ("Material Request", False),
    "serial_no": ("Serial No", False),
    "batch_no": ("Batch", False),
    "installation_note": ("Installation Note", True),
    "landed_cost_voucher": ("Landed Cost Voucher", True),
    "quality_inspection_template": ("Quality Inspection Template", False),
    "sales_partner": ("Sales Partner", False),
    "promotional_scheme": ("Promotional Scheme", False),
    "coupon_code": ("Coupon Code", False),
}

# ---------------------------------------------------------------------------
# FORM_BUTTONS: form_doctype → [(feature_fieldname, button_label, button_group)]
# button_group = None means a standalone button (no dropdown group)
# ---------------------------------------------------------------------------
FORM_BUTTONS = {
    "Sales Order": [
        ("pick_list", "Pick List", "Create"),
        ("work_order", "Work Order", "Create"),
        ("material_request", "Material Request", "Create"),
        ("material_request", "Request for Raw Materials", "Create"),
        ("project", "Project", "Create"),
        ("payment_entry", "Payment", "Create"),
        ("payment_request", "Payment Request", "Create"),
        ("quotation", "Quotation", "Get Items From"),
    ],
    "Material Request": [
        ("pick_list", "Pick List", "Create"),
        ("request_for_quotation", "Request for Quotation", "Create"),
        ("supplier_quotation", "Supplier Quotation", "Create"),
    ],
    "Work Order": [
        ("pick_list", "Create Pick List", None),
    ],
    "Delivery Note": [
        ("pick_list", "Pick List", "Get Items From"),
        ("packing_slip", "Packing Slip", "Create"),
        ("shipment", "Shipment", "Create"),
        ("delivery_trip", "Delivery Trip", "Create"),
    ],
    "Opportunity": [
        ("supplier_quotation", "Supplier Quotation", "Create"),
        ("request_for_quotation", "Request For Quotation", "Create"),
    ],
    "Purchase Order": [
        ("supplier_quotation", "Supplier Quotation", "Get Items From"),
    ],
    "Supplier Quotation": [
        ("quotation", "Quotation", "Create"),
    ],
    "Lead": [
        ("quotation", "Quotation", "Create"),
    ],
}


class IIBFeatureControl(Document):
    def on_update(self):
        self._apply_custom_docperms()
        self._rebuild_simplification_scripts()
        frappe.clear_cache()

    # ------------------------------------------------------------------
    # Custom DocPerm management
    # ------------------------------------------------------------------
    def _apply_custom_docperms(self):
        for fieldname, (dt, submittable) in FEATURE_MAP.items():
            frappe.db.delete("Custom DocPerm", {"parent": dt})

            if self.get(fieldname):
                frappe.get_doc(
                    {
                        "doctype": "Custom DocPerm",
                        "parent": dt,
                        "parenttype": "DocType",
                        "parentfield": "permissions",
                        "role": "System Manager",
                        "permlevel": 0,
                        "read": 1,
                        "write": 1,
                        "create": 1,
                        "delete": 1,
                        "report": 1,
                        "export": 1,
                        "print": 1,
                        "email": 1,
                        "share": 1,
                        "submit": int(submittable),
                        "cancel": int(submittable),
                        "amend": int(submittable),
                    }
                ).insert(ignore_permissions=True)

        frappe.db.commit()

    # ------------------------------------------------------------------
    # Client Script Simplification management
    # ------------------------------------------------------------------
    def _rebuild_simplification_scripts(self):
        for form_dt, entries in FORM_BUTTONS.items():
            script_name = f"{form_dt} Simplification"

            # Collect only the buttons whose feature checkbox is currently ON
            active = [(lbl, grp) for feat, lbl, grp in entries if self.get(feat)]

            if not active:
                if frappe.db.exists("Client Script", script_name):
                    frappe.delete_doc("Client Script", script_name, ignore_permissions=True)
                continue

            script = _build_simplification_script(form_dt, active)

            if frappe.db.exists("Client Script", script_name):
                frappe.db.set_value("Client Script", script_name, "script", script)
            else:
                frappe.get_doc(
                    {
                        "doctype": "Client Script",
                        "name": script_name,
                        "dt": form_dt,
                        "script": script,
                        "enabled": 1,
                    }
                ).insert(ignore_permissions=True)

        frappe.db.commit()


# ---------------------------------------------------------------------------
# Helper: build the JS for a Simplification script
# ---------------------------------------------------------------------------
def _build_simplification_script(form_dt, buttons):
    """
    buttons: list of (label, group) tuples
    group=None → standalone button (no dropdown)
    """
    lines = []
    for label, group in buttons:
        if group:
            lines.append(f"\t\t\tfrm.remove_custom_button('{label}', '{group}');")
        else:
            lines.append(f"\t\t\tfrm.remove_custom_button('{label}');")

    inner = "\n".join(lines)
    return (
        f"frappe.ui.form.on('{form_dt}', {{\n"
        f"\trefresh(frm) {{\n"
        f"\t\tsetTimeout(() => {{\n"
        f"{inner}\n"
        f"\t\t}}, 500);\n"
        f"\t}}\n"
        f"}});"
    )
