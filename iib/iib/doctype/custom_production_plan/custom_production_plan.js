// Copyright (c) 2026, IIB and contributors
// For license information, please see license.txt

frappe.ui.form.on("Custom Production Plan", {
	setup(frm) {
		frm.custom_make_buttons = {
			"Work Order": "Work Order / Subcontract PO",
			"Material Request": "Material Request",
		};
		frm.trigger("setup_queries");
	},

	setup_queries(frm) {
		frm.set_query("for_warehouse", function (doc) {
			return { filters: { company: doc.company, is_group: 0 } };
		});

		frm.set_query("sub_assembly_warehouse", function (doc) {
			return { filters: { company: doc.company } };
		});

		frm.set_query("warehouse", "items", function (doc) {
			return { filters: { company: doc.company } };
		});

		frm.set_query("from_warehouse", "items", function (doc) {
			return { filters: { company: doc.company } };
		});

		frm.set_query("bom_no", "items", function (doc, cdt, cdn) {
			const d = locals[cdt][cdn];
			if (d.item_code) {
				return {
					query: "erpnext.controllers.queries.bom",
					filters: { item: d.item_code, docstatus: 1 },
				};
			}
			frappe.msgprint(__("Please enter Item Code first"));
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Closed" && frm.doc.status !== "Completed") {
			let has_fg_or_sub = (frm.doc.items || []).some(
				(r) => (r.type === "Finished Good" || r.type === "Sub Assembly") && (r.planned_qty || 0) > (r.ordered_qty || 0)
			);
			let has_raw = (frm.doc.items || []).some((r) => r.type === "Raw Material");

			if (has_fg_or_sub) {
				frm.add_custom_button(
					__("Work Order / Subcontract PO"),
					() => frm.trigger("make_work_order"),
					__("Create")
				);
			}

			if (has_raw && frm.doc.status !== "Material Requested") {
				frm.add_custom_button(
					__("Material Request"),
					() => frm.trigger("make_material_request"),
					__("Create")
				);
			}

			if (has_fg_or_sub || has_raw) {
				frm.page.set_inner_btn_group_as_primary(__("Create"));
			}
		}
	},

	get_sales_orders(frm) {
		frappe.call({
			method: "get_open_sales_orders",
			doc: frm.doc,
			freeze: true,
			callback() {
				refresh_field("sales_orders");
			},
		});
	},

	get_items(frm) {
		if (!(frm.doc.sales_orders || []).length) {
			frappe.throw(__("Please click 'Get Sales Orders' and select Sales Orders first."));
			return;
		}
		frappe.call({
			method: "get_items",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Pulling Finished Goods, Sub-Assemblies, and Raw Materials..."),
			callback() {
				refresh_field("items");
				refresh_field("total_planned_qty");
			},
		});
	},

	make_work_order(frm) {
		frappe.call({
			method: "make_work_order",
			doc: frm.doc,
			freeze: true,
			callback() {
				frm.reload_doc();
			},
		});
	},

	make_material_request(frm) {
		frappe.confirm(
			__("Do you want to submit the Material Requests?"),
			() => frm.events._create_mr(frm, 1),
			() => frm.events._create_mr(frm, 0)
		);
	},

	_create_mr(frm, submit) {
		frm.doc.submit_material_request = submit;
		frappe.call({
			method: "make_material_request",
			doc: frm.doc,
			freeze: true,
			callback() {
				frm.reload_doc();
			},
		});
	},
});

// Color the Type column for quick visual scanning of FG / Sub Assy / Raw Material
frappe.ui.form.on("Custom Production Plan Item", {
	type(frm, cdt, cdn) {
		frm.refresh_field("items");
	},
});
