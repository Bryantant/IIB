// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("IIB Settings", {
	onload_post_render(frm) {
		frm.set_query("jop2_start_stock_entry_type", () => ({
			filters: { purpose: "Material Transfer" },
		}));
	},
});
