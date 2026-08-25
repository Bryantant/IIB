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
		() => open_so_picker_dialog(frm),
		__("Get Items From")
	);
}

function open_so_picker_dialog(frm) {
	// all_rows: full server result; displayed_rows: after client-side filters.
	// displayed_rows items are references into all_rows so _checked persists
	// across filter toggles.
	let all_rows = [];
	let displayed_rows = [];

	// Client-side filter: open_only + item_code_filter
	function apply_filter(dialog) {
		const open_only = dialog.get_value("open_only");
		// Read raw $input value so partial text typed before dropdown selection also filters
		const item_filter = (
			dialog.fields_dict.item_code_filter?.$input?.val() || ""
		).trim().toLowerCase();

		displayed_rows = all_rows.filter((r) => {
			if (open_only && (r.corrugator_qty || 0) >= (r.available_qty || 0)) return false;
			if (item_filter && !r.item_code.toLowerCase().includes(item_filter)) return false;
			return true;
		});
		render_results(dialog, displayed_rows);
	}

	// Server fetch: customer, transaction_date, sales_order_filter
	function refresh_results(dialog) {
		const customer = dialog.get_value("customer");
		const date = dialog.get_value("transaction_date");
		const so_name = dialog.get_value("sales_order_filter");

		const so_filters = {
			docstatus: 1,
			status: ["not in", ["Closed", "Cancelled", "Completed"]],
		};
		if (customer) so_filters.customer = customer;
		if (date) so_filters.transaction_date = [">=", date];
		if (so_name) so_filters.name = so_name;

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Sales Order",
				filters: so_filters,
				fields: ["name"],
				limit_page_length: 500,
			},
			callback(r) {
				const so_names = (r.message || []).map((row) => row.name);
				if (!so_names.length) {
					all_rows = [];
					displayed_rows = [];
					render_results(dialog, []);
					return;
				}
				frappe.call({
					method: "iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_so_items_for_corrugator_dialog",
					args: { sales_orders: so_names },
					callback(r2) {
						all_rows = (r2.message || []).map((row) => ({ ...row, _checked: false }));
						apply_filter(dialog);
					},
				});
			},
		});
	}

	function render_results(dialog, rows) {
		const $wrapper = dialog.fields_dict.results_html.$wrapper;
		if (!rows.length) {
			$wrapper.html(
				`<p class="text-muted text-center" style="padding: 16px 0;">${__("No items found.")}</p>`
			);
			return;
		}

		let html = `
			<div style="max-height: 360px; overflow-y: auto; margin-top: 8px; border: 1px solid var(--border-color); border-radius: 4px;">
				<table class="table table-bordered" style="margin: 0; font-size: 12px;">
					<thead style="position: sticky; top: 0; background: var(--fg-color); z-index: 1;">
						<tr>
							<th style="width: 32px; text-align: center; padding: 6px;">
								<input type="checkbox" id="jop1_select_all">
							</th>
							<th style="padding: 6px;">${__("Sales Order")}</th>
							<th style="padding: 6px;">${__("SO Date")}</th>
							<th style="padding: 6px;">${__("PO No")}</th>
							<th style="padding: 6px;">${__("Delivery Date")}</th>
							<th style="padding: 6px;">${__("Item Code")}</th>
							<th style="padding: 6px; text-align: right;">${__("Order Qty")}</th>
							<th style="padding: 6px; text-align: right;">${__("Closed Qty")}</th>
							<th style="width: 72px; padding: 6px; text-align: right;">${__("Cor Qty")}</th>
							<th style="padding: 6px;">${__("Remark")}</th>
						</tr>
					</thead>
					<tbody>`;

		rows.forEach((row, idx) => {
			const corr = row.corrugator_qty || 0;
			const so_date = row.so_date ? frappe.datetime.str_to_user(row.so_date) : "";
			const delivery = row.delivery_date
				? frappe.datetime.str_to_user(row.delivery_date)
				: "";
			html += `
				<tr style="cursor: pointer;" data-idx="${idx}">
					<td style="text-align: center; padding: 6px;">
						<input type="checkbox" class="jop1_row_check" data-idx="${idx}" ${row._checked ? "checked" : ""}>
					</td>
					<td style="padding: 6px;">${frappe.utils.escape_html(row.sales_order)}</td>
					<td style="padding: 6px;">${frappe.utils.escape_html(so_date)}</td>
					<td style="padding: 6px;">${frappe.utils.escape_html(row.po_no || "")}</td>
					<td style="padding: 6px;">${frappe.utils.escape_html(delivery)}</td>
					<td style="padding: 6px;">${frappe.utils.escape_html(row.item_code)}</td>
					<td style="padding: 6px; text-align: right; color: var(--text-muted);">${frappe.format(row.qty, { fieldtype: "Float" })}</td>
					<td style="padding: 6px; text-align: right;">${frappe.format(row.closed_qty, { fieldtype: "Float" })}</td>
					<td style="width: 72px; padding: 6px; text-align: right; color: ${corr > 0 ? "var(--text-muted)" : "inherit"};">
						${frappe.format(corr, { fieldtype: "Float" })}
					</td>
					<td style="padding: 6px; color: var(--text-muted);">${frappe.utils.escape_html(row.remark || "")}</td>
				</tr>`;
		});

		html += `</tbody></table></div>`;
		$wrapper.html(html);

		$wrapper.find("tr[data-idx]").on("click", function (e) {
			if ($(e.target).is("input")) return;
			const idx = parseInt($(this).data("idx"), 10);
			const $cb = $(this).find(".jop1_row_check");
			const new_state = !$cb.prop("checked");
			$cb.prop("checked", new_state);
			displayed_rows[idx]._checked = new_state;
		});

		$wrapper.find("#jop1_select_all").on("change", function () {
			const checked = this.checked;
			$wrapper.find(".jop1_row_check").prop("checked", checked);
			displayed_rows.forEach((r) => (r._checked = checked));
		});

		$wrapper.find(".jop1_row_check").on("change", function (e) {
			e.stopPropagation();
			const idx = parseInt($(this).data("idx"), 10);
			displayed_rows[idx]._checked = this.checked;
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Select Sales Order"),
		size: "large",
		fields: [
			// Row 1 (3 columns): Customer | Sales Order | Open qty only
			{
				fieldtype: "Link",
				fieldname: "customer",
				label: __("Customer"),
				options: "Customer",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "sales_order_filter",
				label: __("Sales Order"),
				options: "Sales Order",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Check",
				fieldname: "open_only",
				label: __("Open qty only"),
				default: 1,
			},
			// Row 2 (3 columns): Date | Item Code | (empty)
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Date",
				fieldname: "transaction_date",
				label: __("Date"),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "item_code_filter",
				label: __("Item Code"),
				options: "Item",
			},
			{ fieldtype: "Column Break" },
			// Results
			{ fieldtype: "Section Break" },
			{
				fieldtype: "HTML",
				fieldname: "results_html",
				options: `<p class="text-muted text-center" style="padding: 16px 0;">${__("Loading...")}</p>`,
			},
		],
		primary_action_label: __("Get Items"),
		primary_action() {
			const checked = displayed_rows.filter((r) => r._checked);
			if (!checked.length) {
				frappe.msgprint(__("Please select at least one item."));
				return;
			}
			// Strip any blank placeholder rows Frappe may have added to the empty table
			frm.doc.items = (frm.doc.items || []).filter(
				(row) => row.item_code || row.sales_order
			);
			checked.forEach((dialog_row) => {
				const new_row = frappe.model.add_child(
					frm.doc,
					"Job Order Corrugator Item",
					"items"
				);
				// Direct assignment avoids triggering the sales_order change event
				// (which would clear item_code and sales_order_item).
				new_row.sales_order = dialog_row.sales_order;
				new_row.sales_order_item = dialog_row.sales_order_item;
				new_row.item_name = dialog_row.item_name || "";
				new_row.uom = dialog_row.uom || "Nos";
				new_row.qty = dialog_row.available_qty || 0;
				new_row.delivery_date = dialog_row.delivery_date || null;
				new_row.so_date = dialog_row.so_date || null;
				new_row.customer = dialog_row.customer || "";
				if (frm.doc.required_date) new_row.due_date = frm.doc.required_date;
				// Setting item_code via frappe.model.set_value triggers the item_code
				// event, which calls fetch_item_spec() to populate board spec fields.
				frappe.model.set_value(
					new_row.doctype,
					new_row.name,
					"item_code",
					dialog_row.item_code
				);
			});
			frm.refresh_field("items");
			dialog.hide();
		},
	});

	// Client-side filters (no server call)
	dialog.fields_dict.open_only.$input.on("change", () => apply_filter(dialog));

	const debounced_apply = frappe.utils.debounce(() => apply_filter(dialog), 300);
	// item_code_filter is a Link field: hook both typing (input) and dropdown selection
	// (validate_and_set_in_model). apply_filter reads $input.val() so partial text works.
	const item_field = dialog.fields_dict.item_code_filter;
	item_field.$input.on("input", debounced_apply);
	const orig_item = item_field.validate_and_set_in_model.bind(item_field);
	item_field.validate_and_set_in_model = function (value, e, force) {
		const result = orig_item(value, e, force);
		Promise.resolve(result).then(debounced_apply);
		return result;
	};
	item_field.get_query = () => ({ filters: { item_group: "Component", is_stock_item: 1 } });

	// Server filters: re-fetch on change
	const debounced_refresh = frappe.utils.debounce(() => refresh_results(dialog), 400);
	// Link fields fire validate_and_set_in_model on selection/clear
	["customer", "sales_order_filter"].forEach((fieldname) => {
		const field = dialog.fields_dict[fieldname];
		if (!field) return;
		const orig = field.validate_and_set_in_model.bind(field);
		field.validate_and_set_in_model = function (value, e, force) {
			const result = orig(value, e, force);
			Promise.resolve(result).then(debounced_refresh);
			return result;
		};
	});
	// Date field: Frappe's datepicker calls set_value (not validate_and_set_in_model),
	// which dispatches a 'change' event on the input — hook that instead.
	dialog.fields_dict.transaction_date.$input.on("change", debounced_refresh);

	dialog.show();
	refresh_results(dialog);
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


function restrict_required_date(frm) {
	if (!frm.doc.transaction_date) return;
	frm.fields_dict["required_date"].datepicker?.update({
		minDate: new Date(frm.doc.transaction_date),
	});
}
