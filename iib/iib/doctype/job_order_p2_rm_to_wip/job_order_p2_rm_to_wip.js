// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Job Order P2 RM to WIP", {
	refresh(frm) {
		if (frm.doc.job_order_p2 && frm.doc.docstatus !== 2) {
			frm.add_custom_button(
				__("View Job Order P2"),
				() => frappe.set_route("Form", "Job Order P2", frm.doc.job_order_p2),
				__("Links")
			);
		}
	},
});
