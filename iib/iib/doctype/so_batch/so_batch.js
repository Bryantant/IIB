// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("SO Batch", {
	transaction_date(frm) {
		(frm.doc.so_batch_items || []).forEach((row) => {
			if (row.po_type === "FC") {
				frappe.model.set_value(row.doctype, row.name, "po_date", frm.doc.transaction_date);
			}
		});
	},
});

frappe.ui.form.on("SO Batch Item", {
	po_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.po_type === "FC") {
			frappe.model.set_value(cdt, cdn, "po_no", "FC");
			frappe.model.set_value(cdt, cdn, "po_date", frm.doc.transaction_date);
		}
	},
});
