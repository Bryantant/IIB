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
		// Filter item_code to stock items in the Component item group
		frm.set_query("item_code", "items", () => ({
			filters: { is_stock_item: 1, item_group: "Component" },
		}));
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
		() => open_jop1_selector(frm),
		__("Get Items From")
	);
}

// ---------------------------------------------------------------------------
// Get Items From → Job Order P1  (two-step custom dialog)
// ---------------------------------------------------------------------------

/**
 * Step 1: MultiSelectDialog for JO P1 selection.
 * The "Select Job Order P1 Item" checkbox (allow_child_item_selection) lets the
 * user expand each JO P1 row and cherry-pick individual items.  Selected child
 * names are forwarded as filtered_children so the server only returns those rows.
 */
function open_jop1_selector(frm) {
	const picker = new frappe.ui.form.MultiSelectDialog({
		doctype: "Job Order P1",
		target: frm,
		date_field: "transaction_date",
		setters: {
			customer: null,
			transaction_date: null,
		},
		allow_child_item_selection: true,
		child_fieldname: "items",
		child_columns: ["item_code", "item_name", "qty", "received_qty"],
		get_query() {
			return {
				filters: {
					docstatus: 1,
					status: ["not in", ["Completed", "Closed", "Cancelled"]],
				},
			};
		},
		action(selections, args) {
			if (!selections || !selections.length) return;
			picker.dialog.hide();
			const filtered_children = (args && args.filtered_children) || [];
			open_receipt_item_picker(frm, selections, filtered_children);
		},
	});
}

/**
 * Step 2: fetch pending items from the server and add them directly to the
 * child table.  filtered_children narrows results to items the user checked
 * in Step 1; empty array means all pending items from the selected JO P1s.
 */
function open_receipt_item_picker(frm, job_order_p1s, filtered_children) {
	frappe.call({
		method:
			"iib.iib.doctype.job_order_p1_receipt.job_order_p1_receipt.get_jop1_items_for_receipt_dialog",
		args: { job_order_p1s, filtered_children: filtered_children || [] },
		freeze: true,
		freeze_message: __("Loading items…"),
		callback(r) {
			const items = r.message || [];
			if (!items.length) {
				frappe.msgprint(
					__(
						"No pending items found for the selected Job Order P1(s). "
						+ "All lines may already be fully received."
					)
				);
				return;
			}
			items.forEach((item) => {
				const row = frm.add_child("items");
				row.job_order_p1      = item.job_order_p1;
				row.job_order_p1_item = item.job_order_p1_item;
				row.item_code         = item.item_code;
				row.item_name         = item.item_name;
				row.description       = item.description || "";
				row.sales_order       = item.sales_order || "";
				row.uom               = item.uom;
				row.qty               = item.pending_qty;
				row.basic_rate        = item.basic_rate;
				row.amount            = flt(item.pending_qty) * flt(item.basic_rate);
				row.target_warehouse  = item.target_warehouse;
			});
			frm.refresh_field("items");
			frappe.show_alert({
				message: __("{0} item(s) added.", [items.length]),
				indicator: "green",
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
