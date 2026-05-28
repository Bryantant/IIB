frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (["Closed", "Cancelled"].includes(frm.doc.status)) return;

		frm.add_custom_button(
			__("Job Order P1"),
			() => create_jo_p1_from_so(frm),
			__("Create")
		);

		if (!(frm.doc.packed_items || []).some((r) => r.item_code)) return;

		frm.add_custom_button(
			__("Job Order P2"),
			() => create_jo_p2_from_so(frm),
			__("Create")
		);
	},
});

function create_jo_p1_from_so(frm) {
	frappe.call({
		method: "iib.iib.doctype.job_order_p1.job_order_p1.get_so_items_for_jop1",
		args: { sales_orders: [frm.doc.name] },
		freeze: true,
		freeze_message: __("Fetching Sales Order rows..."),
		callback(r) {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.show_alert({
					message: __("No Sales Order lines to convert"),
					indicator: "orange",
				});
				return;
			}

			build_jo_p1(frm, rows);
		},
	});
}

function build_jo_p1(frm, rows) {
	frappe.model.with_doctype("Job Order P1", () => {
		const jo = frappe.model.get_new_doc("Job Order P1");
		jo.company = frm.doc.company;
		jo.customer = frm.doc.customer;
		jo.transaction_date = frappe.datetime.nowdate();
		jo.required_date =
			get_earliest_delivery_date(rows) || frm.doc.delivery_date || frappe.datetime.nowdate();

		rows.forEach((r) => {
			const child = frappe.model.add_child(jo, "items");
			Object.assign(child, r);
		});

		frappe.set_route("Form", "Job Order P1", jo.name);
	});
}

function create_jo_p2_from_so(frm) {
	frappe.call({
		method: "iib.iib.doctype.job_order_p2.job_order_p2.get_sales_orders_for_jo",
		args: { sales_order: frm.doc.name },
		freeze: true,
		freeze_message: __("Fetching open component rows..."),
		callback(r) {
			const open_rows = r.message || [];
			if (!open_rows.length) {
				frappe.show_alert({
					message: __("No open Component rows to convert"),
					indicator: "orange",
				});
				return;
			}

			const unique_items = [...new Set(open_rows.map((row) => row.item_code))];
			if (unique_items.length === 1) {
				build_jo(frm, open_rows, unique_items[0]);
				return;
			}

			frappe.prompt(
				[
					{
						fieldtype: "Link",
						label: __("MC Component"),
						fieldname: "production_item",
						options: "Item",
						reqd: 1,
						get_query: () => ({
							filters: {
								name: ["in", unique_items],
								item_group: "Component",
							},
						}),
					},
				],
				(values) => {
					const selected_rows = open_rows.filter(
						(row) => row.item_code === values.production_item
					);
					build_jo(frm, selected_rows, values.production_item);
				},
				__("Select MC Component"),
				__("Create")
			);
		},
	});
}

function build_jo(frm, open_rows, production_item) {
	frappe.model.with_doctype("Job Order P2", () => {
		const jo = frappe.model.get_new_doc("Job Order P2");
		jo.company = frm.doc.company;
		jo.posting_date = frappe.datetime.nowdate();
		jo.production_item = production_item;
		jo.due_date = get_earliest_delivery_date(open_rows) || frappe.datetime.nowdate();
		let total_qty = 0;
		open_rows.forEach((r) => {
			const open_qty = flt(r.open_qty);
			total_qty += open_qty;
			const child = frappe.model.add_child(jo, "sales_order_items");
			child.sales_order = r.sales_order;
			child.sales_order_item = r.sales_order_item;
			child.item_code = r.item_code;
			child.qty = open_qty;
			child.delivery_date = r.delivery_date;
			child.customer = r.customer;
			child.so_status = r.so_status;
		});
		jo.qty = total_qty;
		if (open_rows[0]) {
			jo.item_name = open_rows[0].item_name || "";
			jo.description = open_rows[0].description || "";
		}
		frappe.set_route("Form", "Job Order P2", jo.name);
	});
}

function get_earliest_delivery_date(rows) {
	return (rows || [])
		.map((row) => row.delivery_date)
		.filter(Boolean)
		.sort()[0];
}

function flt(v) {
	return parseFloat(v || 0) || 0;
}
