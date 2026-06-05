frappe.ui.form.on("Job Order Corrugator", {
	setup(frm) {
		// Filter Sales Order link in child rows to open (submitted, not closed) SOs
		frm.set_query("sales_order", "items", () => ({
			filters: {
				docstatus: 1,
				status: ["not in", ["Closed", "Cancelled", "Completed"]],
			},
		}));
		// Filter item_code to Component items that belong to the selected SO in
		// the same row (bundles are expanded to their packed components).
		// Falls back to all Component stock items when no SO is set.
		frm.set_query("item_code", "items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			if (row.sales_order) {
				return {
					query: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_so_component_items",
					filters: { sales_order: row.sales_order },
				};
			}
			return { filters: { is_stock_item: 1, item_group: "Component" } };
		});
	},
	refresh(frm) {
		set_status_indicator(frm);
		add_get_items_button(frm);
		add_create_receipt_button(frm);
		add_status_buttons(frm);
	},
});

// ---------------------------------------------------------------------------
// Child-row events: manual entry helpers
// ---------------------------------------------------------------------------

frappe.ui.form.on("Job Order Corrugator Item", {
	// When SO changes, clear dependent fields so filters reapply cleanly
	sales_order(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "sales_order_item", null);
		frappe.model.set_value(cdt, cdn, "item_code", null);
	},

	// When item_code is selected, auto-populate sales_order_item by looking up
	// which SO Item row on the selected Sales Order owns this component item.
	// Handles both direct SO items and packed components of bundle SO items.
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code || !row.sales_order) return;
		frappe.call({
			method: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_so_item_for_component",
			args: { sales_order: row.sales_order, item_code: row.item_code },
			callback(r) {
				if (r.message) {
					frappe.model.set_value(cdt, cdn, "sales_order_item", r.message);
				}
			},
		});
	},
});

function set_status_indicator(frm) {
	if (frm.doc.docstatus !== 1) return;
	const colors = {
		"To Receive": "orange",
		"Partially Received": "yellow",
		Completed: "green",
		Closed: "grey",
		Cancelled: "red",
	};
	frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
}

// ---------------------------------------------------------------------------
// Get Items From → Sales Order
// ---------------------------------------------------------------------------

function add_get_items_button(frm) {
	if (frm.doc.docstatus !== 0) return;
	frm.add_custom_button(
		__("Sales Order"),
		() => {
			const d = erpnext.utils.map_current_doc({
				method: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_items_from_so_for_corrugator",
				source_doctype: "Sales Order",
				target: frm,
				date_field: "transaction_date",
				setters: {
					customer: null,
					transaction_date: null,
				},
				get_query_filters: {
					docstatus: 1,
					status: ["not in", ["Closed", "Cancelled", "Completed"]],
				},
				allow_child_item_selection: true,
				child_fieldname: "items",
				child_columns: ["item_code", "item_name", "qty", "custom_corrugator_qty"],
			});
			if (d) {
				// Frappe bug: when no parent SOs match the filter, add_parent_filters
				// skips the filter entirely and returns ALL child items instead of none.
				// Fix: always push the filter, using a sentinel when parent list is empty.
				d.add_parent_filters = async function (filters) {
					const parent_names = await d.get_filtered_parents_for_child_search();
					filters.push(["parent", "in", parent_names.length ? parent_names : ["__no_match__"]]);
				};

				d.get_child_datatable_columns = function () {
					return [
						__("Sales Order"),
						__("Item Code"),
						__("Item Name"),
						__("Qty"),
						__("Corrugator Qty"),
					].map((name) => ({ name, editable: false }));
				};
			}
		},
		__("Get Items From")
	);
}

// ---------------------------------------------------------------------------
// Create Receipt button
// ---------------------------------------------------------------------------

function add_create_receipt_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (["Completed", "Closed", "Cancelled"].includes(frm.doc.status)) return;

	frm.add_custom_button(
		__("Job Order Corrugator Receipt"),
		() => {
			frappe.model.open_mapped_doc({
				method: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.make_corrugator_receipt",
				frm: frm,
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}

// ---------------------------------------------------------------------------
// Status buttons
// ---------------------------------------------------------------------------

function add_status_buttons(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (frm.doc.status === "Closed") {
		frm.add_custom_button(
			__("Re-open"),
			() => set_status(frm, "To Receive"),
			__("Status")
		);
	} else if (["To Receive", "Partially Received"].includes(frm.doc.status)) {
		frm.add_custom_button(
			__("Close"),
			() => set_status(frm, "Closed"),
			__("Status")
		);
	}
}

function set_status(frm, status) {
	frappe.call({
		method: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.update_status",
		args: { status, name: frm.doc.name },
		callback() {
			frm.reload_doc();
		},
	});
}
