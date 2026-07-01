frappe.ui.form.on("FGTS", {
	setup(frm) {
		frm.set_query("section", () => ({ filters: { is_group: 0 } }));
		// Sales Order options are narrowed by the chosen Customer (pick customer first).
		frm.set_query("sales_order", () => {
			const filters = { docstatus: 1, status: ["not in", ["Closed", "Cancelled"]] };
			if (frm.doc.customer) filters.customer = frm.doc.customer;
			return { filters };
		});
	},

	customer(frm) {
		// Changing the customer invalidates the previously chosen SO and its components.
		if (frm.doc.sales_order) {
			frm.set_value("sales_order", "");
		}
	},

	refresh(frm) {
		set_status_indicator(frm);
		render_approve_qc_btn(frm);
		render_stock_ledger_btns(frm);

		// Populate warehouse qty display fields
		_populate_warehouse_quantities(frm);

		// Re-populate SO item options when loading a saved draft that already has a SO
		if (frm.doc.sales_order && !frm._so_item_options?.length && frm.doc.docstatus === 0) {
			frappe.call({
				method: "iib.iib.doctype.fgts.fgts.get_fgts_details",
				args: { sales_order: frm.doc.sales_order },
				callback(r) {
					if (!r.message || !r.message.length) return;
					frm._so_item_options = r.message;
					_refresh_add_component_select(frm);
				},
			});
		} else {
			_refresh_add_component_select(frm);
		}
	},

	sales_order(frm) {
		// Clear component-dependent data (customer is chosen by the user, keep it)
		frm.clear_table("items");
		frm.refresh_field("items");
		frm.set_value("wip_warehouse", "");
		frm.set_df_property("so_item_select", "options", "");
		frm._so_item_options = [];

		if (!frm.doc.sales_order) {
			frm.set_df_property("so_item_select", "hidden", 1);
			return;
		}

		frappe.call({
			method: "iib.iib.doctype.fgts.fgts.get_fgts_details",
			args: { sales_order: frm.doc.sales_order },
			freeze: true,
			freeze_message: __("Loading SO details..."),
			callback(r) {
				if (!r.message || !r.message.length) return;
				frm._so_item_options = r.message;
				const first = r.message[0];
				if (first.wip_warehouse)    frm.set_value("wip_warehouse", first.wip_warehouse);
				if (first.stores_warehouse) frm.set_value("stores_warehouse", first.stores_warehouse);
				_refresh_add_component_select(frm);
			},
		});
	},

	so_item_select(frm) {
		if (!frm.doc.so_item_select || !frm._so_item_options) return;
		const selected = (frm._so_item_options || []).find(
			(o) => `${o.item_code} — ${o.item_name || ""}` === frm.doc.so_item_select
		);
		if (!selected) return;

		// Prevent duplicates
		const exists = (frm.doc.items || []).find((r) => r.item_code === selected.item_code);
		if (exists) {
			frappe.show_alert(
				{ message: __("{0} is already in the table", [selected.item_code]), indicator: "orange" },
				3
			);
			frm.set_value("so_item_select", "");
			return;
		}

		// Add row to child table
		const row = frappe.model.add_child(frm.doc, "FGTS Item", "items");
		frappe.model.set_value(row.doctype, row.name, {
			item_code:        selected.item_code,
			item_name:        selected.item_name || "",
			sales_order_item: selected.sales_order_item || "",
			master_card:      selected.master_card || "",
			component:        selected.component || "",
		});
		frm.refresh_field("items");

		// Populate warehouse quantities for the newly added row
		_populate_warehouse_quantities(frm);

		// Reset selector and update available options
		frm.set_value("so_item_select", "");
		_refresh_add_component_select(frm);
	},

	// Total Qty mirrors Qty directly; BDL and Loose are informational only
	qty(frm) {
		frm.set_value("total_qty", flt(frm.doc.qty));
	},

	source_warehouse(frm) {
		// When source warehouse changes, refresh the warehouse quantity displays
		_populate_warehouse_quantities(frm);
	},
});

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * Rebuild the "Add Component" dropdown excluding items already in the table.
 * Hidden when doc is submitted/cancelled or all components are already added.
 */
function _refresh_add_component_select(frm) {
	if (!frm.doc.sales_order || frm.doc.docstatus !== 0) {
		frm.set_df_property("so_item_select", "hidden", 1);
		return;
	}
	const opts = frm._so_item_options || [];
	if (!opts.length) {
		frm.set_df_property("so_item_select", "hidden", 1);
		return;
	}

	const added = new Set((frm.doc.items || []).map((r) => r.item_code));
	const available = opts.filter((o) => !added.has(o.item_code));

	if (!available.length) {
		frm.set_df_property("so_item_select", "hidden", 1);
		return;
	}

	const selectOpts = [""].concat(
		available.map((o) => `${o.item_code} — ${o.item_name || ""}`)
	).join("\n");

	frm.set_df_property("so_item_select", "options", selectOpts);
	frm.set_df_property("so_item_select", "hidden", 0);
	frm.refresh_field("so_item_select");
}

function render_stock_ledger_btns(frm) {
	frm.remove_custom_button(__("Stock Ledger"), __("View"));

	// Stock moves (Source → Stores) only once QC is approved.
	if (frm.doc.docstatus !== 1 || frm.doc.status !== "OK QC") return;

	frm.add_custom_button(
		__("Stock Ledger"),
		() => {
			frappe.route_options = {
				voucher_no: frm.doc.name,
				from_date: frm.doc.posting_date,
				to_date: frm.doc.posting_date,
				company: frm.doc.company,
			};
			frappe.set_route("query-report", "Stock Ledger");
		},
		__("View")
	);
}

function render_approve_qc_btn(frm) {
	frm.remove_custom_button(__("Approve QC"));
	if (frm.doc.docstatus !== 1 || frm.doc.status !== "Waiting QC") return;

	frm.add_custom_button(
		__("Approve QC"),
		() => {
			frappe.confirm(
				__("Move stock from WIP to Stores and mark as OK QC?"),
				() => {
					frappe.call({
						method: "iib.iib.doctype.fgts.fgts.approve_qc",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Approving QC..."),
						callback(r) {
							if (r.message) {
								frappe.show_alert(
									{ message: __("Status updated: {0}", [r.message]), indicator: "green" },
									5
								);
								frm.reload_doc();
							}
						},
					});
				}
			);
		},
		null,
		{ css_class: "btn-success" }
	);
}

function set_status_indicator(frm) {
	const colors = {
		Draft: "grey",
		"Waiting QC": "orange",
		"OK QC": "green",
		Cancelled: "red",
	};
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}

/**
 * Populate warehouse quantities (rm_qty, wip_qty, stores_qty) for each item row.
 * Fetches current stock balances in a single batched call. Live stock is only
 * meaningful while drafting, so on submitted docs the saved snapshot is kept.
 * Values are assigned directly (not via set_value) so the form isn't marked dirty.
 */
function _populate_warehouse_quantities(frm) {
	if (frm.doc.docstatus !== 0) return;

	const rows = (frm.doc.items || []).filter((r) => r.item_code);
	if (!rows.length) return;

	const item_codes = [...new Set(rows.map((r) => r.item_code))];
	frappe.call({
		method: "iib.iib.doctype.fgts.fgts.get_items_warehouse_quantities",
		args: {
			item_codes: JSON.stringify(item_codes),
			posting_date: frm.doc.posting_date || frappe.datetime.get_today(),
		},
		callback(r) {
			if (!r.message) return;
			let changed = false;
			rows.forEach((row) => {
				const q = r.message[row.item_code];
				if (!q) return;
				["rm_qty", "wip_qty", "stores_qty"].forEach((f) => {
					const val = flt(q[f] || 0);
					if (flt(row[f]) !== val) {
						row[f] = val;
						changed = true;
					}
				});
			});
			if (changed) frm.refresh_field("items");
		},
	});
}
