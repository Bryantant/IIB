// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Job Order P1 Receipt", {
	setup(frm) {
		set_account_queries(frm);
	},
	refresh(frm) {
		set_account_queries(frm);
		set_status_indicator(frm);
		add_get_items_button(frm);
	},
	onload_post_render(frm) {
		// Filter item_code child link to stock items only
		frm.set_query("item_code", "items", () => ({ filters: { is_stock_item: 1 } }));
	},
	company(frm) {
		set_account_queries(frm);
		if (frm.doc.company && !frm.doc.cost_center) {
			frappe.db.get_single_value("IIB Settings", "default_cost_center").then((cc) => {
				if (cc) {
					frm.set_value("cost_center", cc);
				} else {
					frappe.db.get_value("Company", frm.doc.company, "cost_center").then((r) => {
						if (r.message && r.message.cost_center) {
							frm.set_value("cost_center", r.message.cost_center);
						}
					});
				}
			});
		}
	},
	onload(frm) {
		// Auto-fetch GL defaults on new doc
		if (frm.is_new()) {
			if (!frm.doc.cost_center) {
				frappe.db.get_single_value("IIB Settings", "default_cost_center").then((cc) => {
					if (cc) {
						frm.set_value("cost_center", cc);
					} else if (frm.doc.company) {
						frappe.db.get_value("Company", frm.doc.company, "cost_center").then((r) => {
							if (r.message && r.message.cost_center) {
								frm.set_value("cost_center", r.message.cost_center);
							}
						});
					}
				});
			}
			if (!frm.doc.expense_account) {
				frappe.db
					.get_single_value("IIB Settings", "default_expense_account")
					.then((acc) => {
						if (acc) frm.set_value("expense_account", acc);
					});
			}
		}
	},
});

function set_account_queries(frm) {
	frm.set_query("expense_account", () => {
		const filters = { is_group: 0 };
		if (frm.doc.company) filters.company = frm.doc.company;
		return { filters };
	});
}

function set_status_indicator(frm) {
	if (frm.doc.docstatus !== 1 && frm.doc.docstatus !== 2) return;
	const colors = { Draft: "orange", Submitted: "green", Cancelled: "red" };
	frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
}

function add_get_items_button(frm) {
	if (frm.doc.docstatus !== 0) return;
	frm.add_custom_button(
		__("Job Order P1"),
		() => open_jop1_picker(frm),
		__("Get Items From")
	);
}

function open_jop1_picker(frm) {
	new frappe.ui.form.MultiSelectDialog({
		doctype: "Job Order P1",
		target: frm,
		setters: { customer: null, transaction_date: null },
		add_filters_group: 1,
		date_field: "transaction_date",
		get_query() {
			return {
				filters: {
					docstatus: 1,
					status: ["not in", ["Completed", "Closed", "Cancelled"]],
				},
			};
		},
		action(selected) {
			const job_order_p1s = selected;
			if (!job_order_p1s.length) return;
			frappe.call({
				method: "iib.iib.doctype.job_order_p1_receipt.job_order_p1_receipt.get_jop1_items",
				args: { job_order_p1s },
				callback(r) {
					if (!r.message || !r.message.length) {
						frappe.show_alert({
							message: __("No pending Job Order P1 lines found"),
							indicator: "orange",
						});
						return;
					}
					r.message.forEach((item) => {
						const row = frm.add_child("items");
						Object.assign(row, item);
					});
					frm.refresh_field("items");
					frappe.show_alert({
						message: __("{0} item(s) added", [r.message.length]),
						indicator: "green",
					});
				},
			});
		},
	});
}

// Row-level: recompute amount on qty / basic_rate change
frappe.ui.form.on("Job Order P1 Receipt Item", {
	qty: recompute_amount,
	basic_rate: recompute_amount,
});

function recompute_amount(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.basic_rate));
	// Refresh header totals
	let total_qty = 0;
	let total_amount = 0;
	(frm.doc.items || []).forEach((r) => {
		total_qty += flt(r.qty);
		total_amount += flt(r.amount);
	});
	frm.set_value("total_qty", total_qty);
	frm.set_value("total_amount", total_amount);
}
