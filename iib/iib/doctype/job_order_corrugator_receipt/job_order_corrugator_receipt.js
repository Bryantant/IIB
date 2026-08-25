// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Job Order Corrugator Receipt", {
	setup(frm) {
		set_account_queries(frm);
		// Only JO Corrugators still open for receiving — mirrors the picker dialog's filter.
		frm.set_query("job_order_corrugator", "items", () => ({
			filters: {
				docstatus: 1,
				status: ["not in", ["Completed", "Closed", "Cancelled"]],
			},
		}));
	},
	refresh(frm) {
		set_account_queries(frm);
		set_status_indicator(frm);
		add_get_items_button(frm);
		add_view_buttons(frm);
		frm.trigger("set_posting_date_and_time_read_only");
	},
	set_posting_time(frm) {
		frm.trigger("set_posting_date_and_time_read_only");
	},
	set_posting_date_and_time_read_only(frm) {
		// Mirrors erpnext.stock.StockController.setup_posting_date_time_check()
		// (used by Sales Invoice, Purchase Invoice, Delivery Note, etc.): lock
		// Posting Date/Time unless "Edit Posting Date and Time" is checked.
		const editable = frm.doc.docstatus === 0 && frm.doc.set_posting_time;
		frm.set_df_property("posting_date", "read_only", editable ? 0 : 1);
		frm.set_df_property("posting_time", "read_only", editable ? 0 : 1);
	},
	onload_post_render(frm) {
		// Filter item_code to Component items with pending qty on the row's JO
		// Corrugator (bundles are not a concern here — JO Corrugator rows are
		// already resolved to Component items). No JO Corrugator set yet on
		// that row → no options at all (get_corrugator_component_items returns
		// [] in that case); Item Code must not be pickable before JO No is.
		frm.set_query("item_code", "items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query:
					"iib.iib.doctype.job_order_corrugator_receipt.job_order_corrugator_receipt.get_corrugator_component_items",
				filters: { job_order_corrugator: row.job_order_corrugator },
			};
		});
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
		child_columns: ["due_date", "item_code", "qty", "received_qty"],
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
			__("JO Corrugator"),
			__("JO Due Date"),
			__("Item Code"),
			__("Qty"),
			__("Rec Qty"),
		].map((name) => ({ name, editable: false }));
	};

	// picker.dialog only exists once MultiSelectDialog's internal with_doctype() gate
	// resolves — synchronously if "Job Order Corrugator" meta is already cached in this
	// tab, otherwise only after an async round-trip to the server. Poll briefly instead
	// of assuming either case.
	let ready_check_attempts = 0;
	const when_dialog_ready = () => {
		if (!picker.dialog?.fields_dict) {
			if (++ready_check_attempts > 40) return; // ~2s cap; give up quietly
			setTimeout(when_dialog_ready, 50);
			return;
		}

		patch_dialog_filter_refresh(picker);

		if (!picker.dialog.fields_dict.allow_child_item_selection) return;

		// Wait for the modal's own "shown" transition to finish before toggling the
		// child-selection checkbox. Checking it immediately builds the child items
		// frappe.DataTable while the modal is still mid fade-in (effectively hidden),
		// and frappe.DataTable's column-width setup (it injects a CSS rule into a
		// <style> tag sized off the container) throws "Cannot read properties of null
		// (reading 'insertRule')" in that state, leaving the child table stuck on its
		// loading skeleton with the parent list still visible underneath it. A normal
		// user click never hits this because it always happens well after the modal
		// has finished showing.
		picker.dialog.$wrapper.one("shown.bs.modal", () => {
			// Default the "Select Job Order Corrugator Item" checkbox to checked.
			// set_value() already triggers the checkbox's own onchange handler
			// (toggle_child_selection) — calling toggle_child_selection() again here
			// would double-fire it and race two concurrent child-item fetches.
			picker.dialog.set_value("allow_child_item_selection", 1);
		});
		// The dialog may already be fully shown by the time we get here (e.g. meta
		// was cached and the transition already completed) — the "shown.bs.modal"
		// event won't fire again in that case, so check display state directly too.
		if (picker.dialog.display) {
			picker.dialog.set_value("allow_child_item_selection", 1);
		}
	};
	when_dialog_ready();
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
				row.item_name         = item.item_name || "";
				row.description       = item.description || "";
				row.quality           = item.quality || "";
				row.flute             = item.flute || "";
				row.width             = item.width || 0;
				row.length            = item.length || 0;
				row.creasing          = item.crease_w || "";
				row.sales_order       = item.sales_order || "";
				row.uom               = item.uom;
				row.qty               = item.pending_qty;
				row.due_date          = item.due_date || "";
				row.delivery_date     = item.delivery_date || "";
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

// ---------------------------------------------------------------------------
// Row-level: manual JO No / Item Code entry
// ---------------------------------------------------------------------------

frappe.ui.form.on("Job Order Corrugator Receipt Item", {
	qty: recompute_totals,

	// Clear dependent fields so the item_code filter and autofill reapply cleanly
	job_order_corrugator(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "item_code", null);
		frappe.model.set_value(cdt, cdn, "job_order_corrugator_item", null);
	},

	// item_code's own fetch_from (item_name, description, quality, flute, width,
	// length, creasing, uom, basic_rate) fires automatically on manual selection.
	// Fields sourced from the JO Corrugator Item row itself — not Item master —
	// still need an explicit fetch here.
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !row.job_order_corrugator) return;
		frappe.call({
			method:
				"iib.iib.doctype.job_order_corrugator_receipt.job_order_corrugator_receipt.get_corrugator_item_for_receipt_row",
			args: { job_order_corrugator: row.job_order_corrugator, item_code: row.item_code },
			callback(r) {
				if (!r.message) return;
				frappe.model.set_value(cdt, cdn, {
					job_order_corrugator_item: r.message.job_order_corrugator_item,
					sales_order: r.message.sales_order,
					due_date: r.message.due_date,
					delivery_date: r.message.delivery_date,
					qty: r.message.pending_qty,
					target_warehouse: r.message.target_warehouse,
				});
			},
		});
	},
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
