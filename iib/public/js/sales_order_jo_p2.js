frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (["Closed", "Cancelled"].includes(frm.doc.status)) return;

		// Only show if there are items with open qty
		const has_open = (frm.doc.items || []).some(
			(r) => parseFloat(r.qty || 0) - parseFloat(r.delivered_qty || 0) > 0
		);
		if (!has_open) return;

		frm.add_custom_button(
			__("Job Order P2"),
			() => create_jo_p2_from_so(frm),
			__("Create")
		);
	},
});

function create_jo_p2_from_so(frm) {
	const open_rows = (frm.doc.items || [])
		.filter((r) => parseFloat(r.qty || 0) - parseFloat(r.delivered_qty || 0) > 0);

	if (!open_rows.length) {
		frappe.show_alert({
			message: __("No open Sales Order Items to convert"),
			indicator: "orange",
		});
		return;
	}

	// Check if all rows share the same item_code → auto-set production_item
	const unique_items = [...new Set(open_rows.map((r) => r.item_code))];
	const production_item = unique_items.length === 1 ? unique_items[0] : null;

	if (!production_item) {
		frappe.confirm(
			__(
				"This Sales Order has multiple items. The Job Order P2 covers one MC Component at a time. Continue with all items pre-loaded so you can choose? (Rows not matching the chosen MC Component must be removed before submit.)"
			),
			() => build_jo(frm, open_rows, null)
		);
		return;
	}

	build_jo(frm, open_rows, production_item);
}

function build_jo(frm, open_rows, production_item) {
	frappe.model.with_doctype("Job Order P2", () => {
		const jo = frappe.model.get_new_doc("Job Order P2");
		jo.company = frm.doc.company;
		jo.posting_date = frappe.datetime.nowdate();
		jo.due_date = frm.doc.delivery_date || frappe.datetime.nowdate();
		if (production_item) {
			jo.production_item = production_item;
		}
		let total_qty = 0;
		open_rows.forEach((r) => {
			const open_qty =
				parseFloat(r.qty || 0) - parseFloat(r.delivered_qty || 0);
			total_qty += open_qty;
			const child = frappe.model.add_child(jo, "sales_order_items");
			child.sales_order = frm.doc.name;
			child.sales_order_item = r.name;
			child.item_code = r.item_code;
			child.qty = open_qty;
			child.delivery_date = r.delivery_date;
			child.customer = frm.doc.customer;
			child.so_status = frm.doc.status;
		});
		jo.qty = total_qty;
		frappe.set_route("Form", "Job Order P2", jo.name);
	});
}
