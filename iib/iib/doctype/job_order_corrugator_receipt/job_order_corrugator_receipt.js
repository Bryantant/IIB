// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Job Order Corrugator Receipt", {
	setup(frm) {
		set_account_queries(frm);
	},
	refresh(frm) {
		set_account_queries(frm);
		set_status_indicator(frm);
		add_get_items_button(frm);
		add_view_buttons(frm);
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
		__("Job Order Corrugator"),
		() => open_corrugator_selector(frm),
		__("Get Items From")
	);
}

function add_view_buttons(frm) {
	if (frm.doc.docstatus < 1) return;
	frm.add_custom_button(__("Stock Ledger"), () => {
		frappe.route_options = {
			voucher_no: frm.doc.name,
			from_date: frm.doc.posting_date,
			to_date: moment(frm.doc.modified).format("YYYY-MM-DD"),
			company: frm.doc.company,
			show_cancelled_entries: frm.doc.docstatus === 2,
		};
		frappe.set_route("query-report", "Stock Ledger");
	}, __("View"));

	frm.add_custom_button(__("Accounting Ledger"), () => {
		frappe.route_options = {
			voucher_no: frm.doc.name,
			from_date: frm.doc.posting_date,
			to_date: moment(frm.doc.modified).format("YYYY-MM-DD"),
			company: frm.doc.company,
			show_cancelled_entries: frm.doc.docstatus === 2,
		};
		frappe.set_route("query-report", "General Ledger");
	}, __("View"));
}

// ---------------------------------------------------------------------------
// Get Items From → Job Order Corrugator  (two-step custom dialog)
// ---------------------------------------------------------------------------

/**
 * Step 1: MultiSelectDialog for JO P1 selection.
 * The "Select Job Order Corrugator Item" checkbox (allow_child_item_selection) lets the
 * user expand each JO P1 row and cherry-pick individual items.  Selected child
 * names are forwarded as filtered_children so the server only returns those rows.
 */
function open_corrugator_selector(frm) {
	const picker = new frappe.ui.form.MultiSelectDialog({
		doctype: "Job Order Corrugator",
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

	// Frappe bug: empty parent list skips the filter → shows all child items.
	picker.add_parent_filters = async function (filters) {
		const parent_names = await picker.get_filtered_parents_for_child_search();
		filters.push(["parent", "in", parent_names.length ? parent_names : ["__no_match__"]]);
	};

	picker.get_child_datatable_columns = function () {
		return [
			__("Job Order Corrugator"),
			__("Item Code"),
			__("Item Name"),
			__("Qty"),
			__("Received Qty"),
		].map((name) => ({ name, editable: false }));
	};

	patch_dialog_filter_refresh(picker);
}

/**
 * Step 2: fetch pending items from the server and add them directly to the
 * child table.  filtered_children narrows results to items the user checked
 * in Step 1; empty array means all pending items from the selected JO P1s.
 */
function open_receipt_item_picker(frm, job_order_corrugators, filtered_children) {
	frappe.call({
		method:
			"iib.iib.doctype.job_order_corrugator_receipt.job_order_corrugator_receipt.get_corrugator_items_for_receipt_dialog",
		args: { job_order_corrugators, filtered_children: filtered_children || [] },
		freeze: true,
		freeze_message: __("Loading items…"),
		callback(r) {
			const items = r.message || [];
			if (!items.length) {
				frappe.msgprint(
					__(
						"No pending items found for the selected Job Order Corrugator(s). "
						+ "All lines may already be fully received."
					)
				);
				return;
			}
			// Remove empty rows that Frappe auto-inserts on new documents
			const grid = frm.fields_dict.items.grid;
			(frm.doc.items || [])
				.filter((r) => !r.item_code)
				.forEach((r) => grid.grid_rows_by_docname[r.name]?.remove());

			items.forEach((item) => {
				const row = frm.add_child("items");
				row.job_order_corrugator      = item.job_order_corrugator;
				row.job_order_corrugator_item = item.job_order_corrugator_item;
				row.item_code         = item.item_code;
				row.item_name         = item.item_name;
				row.description       = item.description || "";
				row.sales_order       = item.sales_order || "";
				row.uom               = item.uom;
				row.qty               = item.pending_qty;
				row.due_date          = item.due_date || "";
				row.amount            = 0;
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

// ---------------------------------------------------------------------------
// Shared: patch a MultiSelectDialog so filter changes auto-refresh results.
// ---------------------------------------------------------------------------

function patch_dialog_filter_refresh(dialog_obj) {
	const refresh = frappe.utils.debounce(() => {
		if (dialog_obj.is_child_selection_enabled?.()) {
			dialog_obj.show_child_results?.();
		} else {
			dialog_obj.get_results?.();
		}
	}, 300);

	["customer", "transaction_date"].forEach((fieldname) => {
		const field = dialog_obj.dialog.fields_dict[fieldname];
		if (!field) return;
		const orig = field.validate_and_set_in_model.bind(field);
		field.validate_and_set_in_model = function (value, e, force) {
			const result = orig(value, e, force);
			Promise.resolve(result).then(refresh);
			return result;
		};
	});

	const search_field = dialog_obj.dialog.fields_dict["search_term"];
	if (search_field) {
		search_field.$input?.on("input.iib_child", refresh);
	}
}

// Row-level: recompute totals on qty change
frappe.ui.form.on("Job Order Corrugator Receipt Item", {
	qty: recompute_totals,
});

function recompute_totals(frm, cdt, cdn) {
	frappe.model.set_value(cdt, cdn, "amount", 0);
	let total_qty = 0;
	(frm.doc.items || []).forEach((r) => {
		total_qty += flt(r.qty);
	});
	frm.set_value("total_qty", total_qty);
	frm.set_value("total_amount", 0);
}
