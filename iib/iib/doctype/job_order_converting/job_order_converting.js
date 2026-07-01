frappe.ui.form.on("Job Order Converting", {
	setup(frm) {
		frm.set_query("production_item", () => {
			if (frm.doc.customer) {
				return {
					query: "iib.iib.doctype.job_order_converting.job_order_converting.get_component_items_for_customer",
					filters: { customer: frm.doc.customer },
				};
			}
			return { filters: { item_group: "Component" } };
		});
		frm.set_query("section", "operations", () => ({
			filters: {
				is_group: 1,
				disabled: 0,
			},
		}));
		frm.set_query("production_section", "operations", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query:
					"iib.iib.doctype.iib_production_section.iib_production_section.get_section_leaf_query",
				filters: {
					section_group: row.section || null,
				},
			};
		});
	},

	onload(frm) {
		ensure_sales_order_items_table_is_optional(frm);
		remove_blank_so_item_rows(frm);
		remember_production_item(frm);
		refresh_on_hand_qty(frm);
	},

	refresh(frm) {
		ensure_sales_order_items_table_is_optional(frm);
		remove_blank_so_item_rows(frm);
		if (!frm._last_production_item) {
			remember_production_item(frm);
		}
		set_status_indicator(frm);
		frm.fields_dict["sales_order_items"]?.grid?.wrapper?.find(".grid-add-row").hide();
		add_view_button(frm);
		add_refresh_operations_button(frm);
		add_stop_button(frm);
		add_close_button(frm);
		add_return_components_button(frm);
	},

	get_sales_orders(frm) {
		if (!frm.doc.production_item) {
			frappe.msgprint({
				message: __("Please set <b>MC Component</b> before fetching Sales Orders."),
				indicator: "orange",
			});
			return;
		}
		frappe.call({
			method: "iib.iib.doctype.job_order_converting.job_order_converting.fetch_all_so_items_for_converting",
			args: {
				production_item: frm.doc.production_item,
				customer: frm.doc.customer || "",
				target_doc: frm.doc,
			},
			freeze: true,
			freeze_message: __("Fetching Sales Orders..."),
			callback(r) {
				if (!r.message) return;
				frappe.model.clear_table(frm.doc, "sales_order_items");
				(r.message.sales_order_items || []).forEach((row) => {
					const new_row = frappe.model.add_child(frm.doc, "sales_order_items");
					Object.assign(new_row, {
						sales_order: row.sales_order,
						sales_order_item: row.sales_order_item,
						item_code: row.item_code,
						qty: row.qty,
						so_date: row.so_date,
						po_no: row.po_no,
						po_date: row.po_date,
						uom: row.uom,
						remark: row.remark || "",
					});
				});
				frm.refresh_field("sales_order_items");
			},
		});
	},

	customer(frm) {
		if (frm.doc.docstatus !== 0) return;
		// Clear production_item so the user re-picks from the now-filtered list
		if (frm.doc.production_item) {
			frm.set_value("production_item", "");
		}
	},

	production_item(frm) {
		// On a real user change, keep only SO rows that belong to the chosen MC Component.
		// The Sales Order Create path preloads matching rows before the form opens.
		if (frm.doc.docstatus !== 0) return;
		if (frm._setting_production_item_from_so_picker) return;

		const previous_item = frm._last_production_item;
		const production_item = frm.doc.production_item;
		if (previous_item && previous_item !== production_item) {
			frm.clear_table("operations");
			frm.refresh_field("operations");
		}
		filter_sales_order_rows_for_item(frm, production_item);
		populate_operations_from_item(frm, frm.doc.production_item);
		remember_production_item(frm);
		refresh_on_hand_qty(frm);
	},
});

frappe.ui.form.on("Job Order Converting Operation", {
	section(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		row.production_section = "";
		frm.refresh_field("operations");
	},
});

// ---- Status indicator ----

function set_status_indicator(frm) {
	const colors = {
		Draft: "red",
		"In Process": "yellow",
		Completed: "green",
		Stopped: "grey",
		Closed: "grey",
		Cancelled: "red",
	};
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}

function ensure_sales_order_items_table_is_optional(frm) {
	if (frm.fields_dict.sales_order_items) {
		frm.fields_dict.sales_order_items.df.reqd = 0;
	}
	frm.set_df_property("sales_order_items", "reqd", 0);
}

function remove_blank_so_item_rows(frm) {
	const rows = frm.doc.sales_order_items || [];
	const rows_to_keep = rows.filter((row) => !is_blank_so_item_row(row));
	if (rows_to_keep.length === rows.length) return;
	frm.doc.sales_order_items = rows_to_keep;
	frm.refresh_field("sales_order_items");
}

function filter_sales_order_rows_for_item(frm, production_item) {
	let rows = frm.doc.sales_order_items || [];
	rows = rows.filter((row) => !is_blank_so_item_row(row));
	if (production_item) {
		rows = rows.filter((row) => !row.item_code || row.item_code === production_item);
	}
	if (rows.length === (frm.doc.sales_order_items || []).length) return;
	frm.doc.sales_order_items = rows;
	frm.refresh_field("sales_order_items");
}

function is_blank_so_item_row(row) {
	return (
		!row.sales_order &&
		!row.sales_order_item &&
		!row.item_code &&
		!row.delivery_date &&
		!row.customer &&
		!row.so_status &&
		!flt(row.qty)
	);
}

function refresh_on_hand_qty(frm) {
	if (!frm.doc.production_item) {
		frm.set_value("on_hand_qty", 0);
		return;
	}
	frappe.call({
		method: "iib.iib.doctype.job_order_converting.job_order_converting.get_item_on_hand_qty",
		args: { item_code: frm.doc.production_item },
		callback(r) {
			frm.set_value("on_hand_qty", r.message || 0);
		},
	});
}

function remember_production_item(frm) {
	frm._last_production_item = frm.doc.production_item || null;
}

function has_nonblank_operation_rows(frm) {
	return (frm.doc.operations || []).some((row) => row.sequence || row.section);
}

async function populate_operations_from_item(frm, production_item) {
	if (!production_item || frm.doc.docstatus !== 0 || has_nonblank_operation_rows(frm)) {
		return;
	}
	const r = await frappe.call({
		method: "iib.iib.doctype.job_order_converting.job_order_converting.get_operations_for_item",
		args: { production_item },
	});
	const data = r.message || {};
	if (data.master_card) {
		await frm.set_value("master_card", data.master_card);
	}
	if (!data.operations || !data.operations.length) {
		return;
	}
	frm.clear_table("operations");
	data.operations.forEach((operation) => {
		const row = frm.add_child("operations");
		row.sequence = operation.sequence;
		row.section = operation.section;
		row.production_section = operation.production_section || "";
		row.est_time_mins = operation.est_time_mins;
		row.description = operation.description;
		row.status = operation.status || "Pending";
		row.completed_qty = operation.completed_qty || 0;
	});
	frm.refresh_field("operations");
}

// ---- Refresh Operations Qty button ----

function add_refresh_operations_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (!(frm.doc.operations && frm.doc.operations.length)) return;
	frm.add_custom_button(__("Refresh Qty"), () => {
		frappe.call({
			method: "iib.iib.doctype.job_order_converting.job_order_converting.refresh_operations_qty",
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __("Refreshing operation quantities…"),
			callback() {
				frm.reload_doc();
				frappe.show_alert({ message: __("Operation quantities refreshed"), indicator: "green" }, 4);
			},
		});
	});
}

// ---- View button (dropdown for Stock Ledger) ----

function add_view_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (!frm.doc.transfer_rm_doc) return;
	frm.add_custom_button(__("Stock Ledger"), () => {
		frappe.set_route("query-report", "Stock Ledger", {
			voucher_type: "Job Order Converting RM to WIP",
			voucher_no: frm.doc.transfer_rm_doc,
		});
	}, __("View"));
}

// ---- Return Components button (WIP -> Raw Material) ----

function add_return_components_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (!["Completed", "Closed"].includes(frm.doc.status)) return;
	if (flt(frm.doc.jo_qty_in_process) <= 0) return;
	frm.add_custom_button(
		__("Return Components"),
		() => {
			frappe.call({
				method:
					"iib.iib.doctype.job_order_converting.job_order_converting.make_return_components",
				args: { source_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Building Return Stock Entry..."),
				callback(r) {
					if (!r.message) return;
					frappe.model.sync(r.message);
					frappe.set_route("Form", "Stock Entry", r.message.name);
				},
			});
		},
		__("Create")
	);
}

// ---- Stop / Re-open ----

function add_stop_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (frm.doc.status === "Stopped") {
		frm.add_custom_button(
			__("Re-open"),
			() => set_status(frm, "In Process"),
			__("Status")
		);
	} else if (!["Completed", "Cancelled", "Closed"].includes(frm.doc.status)) {
		frm.add_custom_button(
			__("Stop"),
			() => set_status(frm, "Stopped"),
			__("Status")
		);
	}
}

// ---- Close ----

function add_close_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (["Completed", "Cancelled", "Closed"].includes(frm.doc.status)) return;
	frm.add_custom_button(
		__("Close"),
		() => {
			frappe.confirm(
				__("Close this Job Order Converting? No further changes will be allowed."),
				() => set_status(frm, "Closed")
			);
		},
		__("Status")
	);
}

function set_status(frm, status) {
	frappe.call({
		method: "iib.iib.doctype.job_order_converting.job_order_converting.stop_job_order",
		args: { name: frm.doc.name, status },
		callback() {
			frm.reload_doc();
		},
	});
}

function flt(v) {
	return parseFloat(v || 0) || 0;
}
