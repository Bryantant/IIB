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
		restrict_required_date(frm);
		fetch_missing_item_specs(frm);
	},
	transaction_date(frm) {
		restrict_required_date(frm);
	},
	required_date(frm) {
		if (!frm.doc.required_date) return;
		(frm.doc.items || []).forEach((row) => {
			if (!row.due_date) {
				frappe.model.set_value(row.doctype, row.name, "due_date", frm.doc.required_date);
			}
		});
	},
});

// ---------------------------------------------------------------------------
// Child-row events: manual entry helpers
// ---------------------------------------------------------------------------

frappe.ui.form.on("Job Order Corrugator Item", {
	items_add(frm, cdt, cdn) {
		if (frm.doc.required_date) {
			frappe.model.set_value(cdt, cdn, "due_date", frm.doc.required_date);
		}
	},
	due_date(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.due_date) return;
		if (frm.doc.transaction_date && row.due_date < frm.doc.transaction_date) {
			frappe.model.set_value(cdt, cdn, "due_date", "");
			frappe.throw(__("Row " + row.idx + ": Due Date cannot be before Transaction Date."));
		}
	},
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
		// fetch_from only fires on manual UI selection; explicitly fetch spec
		// fields so rows added via "Get Items" or loaded from DB are also filled.
		fetch_item_spec(frm, cdt, cdn, row.item_code);
	},

	// Fetch fields fire after the AJAX response for fetch_from resolves — correct
	// timing to recalculate derived production fields for this row.
	// Fetch fields — fire after AJAX fetch_from resolves
	width(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	length(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	dc(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	set_pcs(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	// User-editable fields that feed calculations
	qty(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	running_width(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	running_length(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
	setting(frm, cdt, cdn) {
		recalc_row(frm, cdt, cdn);
	},
});

// ---------------------------------------------------------------------------
// Item spec fetch helpers
// ---------------------------------------------------------------------------

// Fetch spec fields from Item Master for a single row and then recalculate.
// fetch_from in the JSON only fires on manual UI interaction; this covers rows
// loaded from DB or added programmatically via "Get Items From SO".
function fetch_item_spec(frm, cdt, cdn, item_code) {
	if (!item_code) return;
	frappe.db.get_value(
		"Item",
		item_code,
		[
			"custom_board_quality", "custom_flute", "custom_single_double",
			"custom_width", "custom_length", "custom_dc", "custom_set_pcs",
			"custom_crease_w", "custom_crease_l", "custom_slotting",
			"custom_display", "custom_joint_1", "custom_joint_2",
		],
		(r) => {
			if (!r) return;
			frappe.model.set_value(cdt, cdn, {
				quality:       r.custom_board_quality  || "",
				flute:         r.custom_flute          || "",
				single_double: r.custom_single_double  || "",
				width:         r.custom_width          || 0,
				length:        r.custom_length         || 0,
				dc:            r.custom_dc             || 0,
				set_pcs:       r.custom_set_pcs        || 0,
				crease_w:      r.custom_crease_w       || "",
				crease_l:      r.custom_crease_l       || "",
				slotting:      r.custom_slotting       || "",
				display:       r.custom_display        || 0,
				joint_1:       r.custom_joint_1        || "",
				joint_2:       r.custom_joint_2        || "",
			});
			recalc_row(frm, cdt, cdn);
			// Re-render the open row dialog so depends_on conditions re-evaluate
			// and the Board Spec / Crease & Joints sections become visible.
			const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
			if (grid && grid.grid_form && grid.grid_form.fields_dict) {
				grid.grid_form.refresh();
			}
		}
	);
}

// On refresh, find any rows that have item_code but haven't had their spec
// fields populated yet (quality is blank) and fetch them.
function fetch_missing_item_specs(frm) {
	(frm.doc.items || []).forEach((row) => {
		if (row.item_code && !row.quality) {
			fetch_item_spec(frm, row.doctype, row.name, row.item_code);
		} else {
			recalc_row(frm, row.doctype, row.name);
		}
	});
}

// ---------------------------------------------------------------------------
// Production calculation helpers (display / print only — no business logic)
// ---------------------------------------------------------------------------

function recalc_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;

	let up_width = null;
	if (row.running_width && row.width)
		up_width = Math.floor(row.running_width / row.width);

	let up_length = null;
	if (row.running_length && row.length)
		up_length = Math.floor(row.running_length / row.length);

	let upw_upl = null;
	if (up_width !== null && up_length !== null)
		upw_upl = up_width * up_length;

	let qty_production = null;
	if (row.qty && row.dc && upw_upl !== null && upw_upl > 0 && row.set_pcs)
		qty_production = ((row.qty + (row.setting || 0)) / row.dc) / upw_upl * row.set_pcs;

	frappe.model.set_value(cdt, cdn, {
		up_width: up_width !== null ? up_width : 0,
		up_length: up_length !== null ? up_length : 0,
		upw_upl: upw_upl !== null ? upw_upl : 0,
		qty_production: qty_production !== null ? qty_production : 0,
	});
}

function recalc_all_rows(frm) {
	(frm.doc.items || []).forEach((row) => recalc_row(frm, row.doctype, row.name));
}

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

				patch_dialog_filter_refresh(d);
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

// ---------------------------------------------------------------------------
// Shared: patch a MultiSelectDialog so filter changes auto-refresh results.
// Wraps validate_and_set_in_model on setter fields — the only reliable hook
// for Frappe Link/Date controls that don't dispatch DOM change events.
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

function restrict_required_date(frm) {
	if (!frm.doc.transaction_date) return;
	frm.fields_dict["required_date"].datepicker?.update({
		minDate: new Date(frm.doc.transaction_date),
	});
}
