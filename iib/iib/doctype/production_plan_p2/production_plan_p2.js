frappe.ui.form.on("Production Plan P2", {
	setup(frm) {
		frm.set_query("item_code", () => ({
			filters: { item_group: "Component" },
		}));
		frm.set_query("item_code", "po_items", () => ({
			filters: { item_group: "Component" },
		}));
		frm.set_query("production_section", "section_assignments", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { is_group: 0 };
			if (row.section) {
				filters["parent_iib_production_section"] = row.section;
			}
			return { filters };
		});
	},

	refresh(frm) {
		ensure_items_table_is_optional(frm);
		set_status_indicator(frm);
		render_inline_buttons(frm);
		if (frm.doc.docstatus === 1) {
			add_create_job_orders_button(frm);
		}
	},

	combine_items(frm) {
		if (frm.doc.docstatus === 0 && (frm.doc.sales_orders || []).length) {
			save_then_get_items(frm);
		}
	},
});

// ---- Inline buttons ----

function render_inline_buttons(frm) {
	render_get_sales_orders_btn(frm);
	render_get_items_btn(frm);
}

function render_get_sales_orders_btn(frm) {
	const $table = frm.fields_dict.sales_orders.$wrapper;
	$table.prev(".ppp2-get-sos-wrapper").remove();

	if (frm.doc.docstatus !== 0) return;

	$(`<div class="ppp2-get-sos-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-ppp2-get-sos">
			${__("Get Sales Orders")}
		</button>
	</div>`)
		.insertBefore($table)
		.find(".btn-ppp2-get-sos")
		.on("click", () => run_get_sales_orders(frm));
}

function render_get_items_btn(frm) {
	const $table = frm.fields_dict.po_items.$wrapper;
	$table.prev(".ppp2-get-items-wrapper").remove();

	if (frm.doc.docstatus !== 0) return;

	$(`<div class="ppp2-get-items-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-ppp2-get-items">
			${__("Get Items")}
		</button>
	</div>`)
		.insertBefore($table)
		.find(".btn-ppp2-get-items")
		.on("click", () => {
			if (!(frm.doc.sales_orders || []).length) {
				frappe.show_alert({
					message: __("Please add Sales Orders first"),
					indicator: "orange",
				});
				return;
			}
			save_then_get_items(frm);
		});
}

function save_then_get_items(frm) {
	ensure_items_table_is_optional(frm);
	remove_blank_item_rows(frm);
	run_get_items(frm, frm.doc.name);
}

function ensure_items_table_is_optional(frm) {
	if (frm.fields_dict.po_items) {
		frm.fields_dict.po_items.df.reqd = 0;
	}
	frm.set_df_property("po_items", "reqd", 0);
}

function remove_blank_item_rows(frm) {
	const rows = frm.doc.po_items || [];
	const rows_to_keep = rows.filter((row) => !is_blank_item_row(row));

	if (rows_to_keep.length === rows.length) return;

	frm.doc.po_items = rows_to_keep;
	frm.refresh_field("po_items");
}

function is_blank_item_row(row) {
	return (
		!row.sales_order &&
		!row.sales_order_item &&
		!row.item_code &&
		!row.item_name &&
		!row.description &&
		!row.customer &&
		!row.uom &&
		!row.delivery_date &&
		!row.wip_warehouse &&
		!row.fg_warehouse &&
		!flt(row.planned_qty) &&
		!flt(row.produced_qty) &&
		!flt(row.pending_qty)
	);
}

// ---- Status indicator ----

function set_status_indicator(frm) {
	const colors = {
		Draft: "grey",
		"Not Started": "orange",
		"In Process": "yellow",
		Completed: "green",
		Closed: "grey",
		Cancelled: "red",
	};
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}

// ---- Get Sales Orders ----

function run_get_sales_orders(frm) {
	const filters = {
		customer: frm.doc.customer || null,
		item_code: frm.doc.item_code || null,
		sales_order_status: frm.doc.sales_order_status || null,
		from_date: frm.doc.from_date || null,
		to_date: frm.doc.to_date || null,
		from_delivery_date: frm.doc.from_delivery_date || null,
		to_delivery_date: frm.doc.to_delivery_date || null,
	};

	frappe.call({
		method:
			"iib.iib.doctype.production_plan_p2.production_plan_p2.get_sales_orders",
		args: { filters },
		freeze: true,
		freeze_message: __("Fetching Sales Orders..."),
		callback(r) {
			if (!r.message || !r.message.length) {
				frappe.show_alert({
					message: __("No Sales Orders found matching the filters"),
					indicator: "orange",
				});
				return;
			}
			const existing = new Set(
				(frm.doc.sales_orders || []).map((row) => row.sales_order)
			);
			let added = 0;
			r.message.forEach((so) => {
				if (!existing.has(so.sales_order)) {
					const row = frm.add_child("sales_orders");
					row.sales_order = so.sales_order;
					row.sales_order_date = so.sales_order_date;
					row.customer = so.customer;
					row.grand_total = so.grand_total;
					existing.add(so.sales_order);
					added++;
				}
			});
			frm.refresh_field("sales_orders");
			frappe.show_alert({
				message: __("{0} Sales Order(s) added", [added]),
				indicator: "green",
			});
		},
	});
}

// ---- Get Items ----

function run_get_items(frm, source_name) {
	frappe.call({
		method: "iib.iib.doctype.production_plan_p2.production_plan_p2.get_items",
		args: { source_name: source_name || frm.doc.name, doc: frm.doc },
		freeze: true,
		freeze_message: __("Fetching Items..."),
		callback(r) {
			if (!r.message && r.message !== 0) return;
			const plan_name = (r.message[0] && r.message[0].parent) || source_name;
			if (plan_name && plan_name !== frm.doc.name) {
				frappe.set_route("Form", frm.doctype, plan_name);
			} else {
				frm.reload_doc();
			}
			frappe.show_alert({
				message: __("{0} item(s) loaded", [r.message.length]),
				indicator: "green",
			});
		},
	});
}

// ---- Create Job Orders (toolbar, submitted doc only) ----

function add_create_job_orders_button(frm) {
	if (["Completed", "Closed", "Cancelled"].includes(frm.doc.status)) return;
	frm.add_custom_button(
		__("Job Orders"),
		() => {
			frappe.call({
				method:
					"iib.iib.doctype.production_plan_p2.production_plan_p2.make_job_orders",
				args: { source_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating Job Orders..."),
				callback(r) {
					if (!r.message || !r.message.length) {
						frappe.show_alert({
							message: __("No pending rows to convert"),
							indicator: "orange",
						});
						return;
					}
					frappe.show_alert({
						message: __("{0} Job Order P2 created", [r.message.length]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}
