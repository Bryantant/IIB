// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Job Order Converting WIP to FG", {
	refresh(frm) {
		if (frm.doc.job_order_converting && frm.doc.docstatus !== 2) {
			frm.add_custom_button(
				__("View Job Order Converting"),
				() => frappe.set_route("Form", "Job Order Converting", frm.doc.job_order_converting),
				__("Links")
			);
		}
	},
});
