frappe.ui.form.on("Job Order P1", {
	refresh(frm) {
		set_status_indicator(frm);
		add_get_items_button(frm);
		add_create_receipt_button(frm);
		add_status_buttons(frm);
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

function add_get_items_button(frm) {
	if (frm.doc.docstatus !== 0) return;
	frm.add_custom_button(
		__("Sales Order"),
		() => open_so_picker(frm),
		__("Get Items From")
	);
}

function add_create_receipt_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (["Completed", "Closed", "Cancelled"].includes(frm.doc.status)) return;

	frm.add_custom_button(
		__("Job Order P1 Receipt"),
		() => {
			frappe.model.open_mapped_doc({
				method: "iib.iib.doctype.job_order_p1.job_order_p1.make_jop1_receipt",
				frm: frm,
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}

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

function open_so_picker(frm) {
	new frappe.ui.form.MultiSelectDialog({
		doctype: "Sales Order",
		target: frm,
		setters: { customer: null, transaction_date: null },
		add_filters_group: 1,
		date_field: "transaction_date",
		get_query() {
			return {
				filters: {
					docstatus: 1,
					status: ["not in", ["Closed", "Completed", "Cancelled"]],
				},
			};
		},
		action(selected) {
			const sales_orders = selected;
			if (!sales_orders.length) return;
			frappe.call({
				method: "iib.iib.doctype.job_order_p1.job_order_p1.get_so_items_for_jop1",
				args: { sales_orders },
				callback(r) {
					if (!r.message || !r.message.length) {
						frappe.show_alert({
							message: __("No open Sales Order lines found"),
							indicator: "orange",
						});
						return;
					}
					r.message.forEach((item) => {
						const row = frm.add_child("items");
						Object.assign(row, item);
					});
					frm.refresh_field("items");
					frappe.show_alert({
						message: __("{0} item(s) added", [r.message.length]),
						indicator: "green",
					});
				},
			});
		},
	});
}

function set_status(frm, status) {
	frappe.call({
		method: "iib.iib.doctype.job_order_p1.job_order_p1.update_status",
		args: { status, name: frm.doc.name },
		callback() {
			frm.reload_doc();
		},
	});
}
