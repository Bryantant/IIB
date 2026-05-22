frappe.ui.form.on("Job Order P2", {
	setup(frm) {
		// Restrict MC Component to Item Group = "Component"
		frm.set_query("production_item", () => ({
			filters: { item_group: "Component" },
		}));
	},

	refresh(frm) {
		set_status_indicator(frm);
		add_get_sales_orders_button(frm);
		add_set_finish_button(frm);
		add_stop_button(frm);
		add_close_button(frm);
		add_return_components_button(frm);
	},

	production_item(frm) {
		// On MC Component change while draft: clear operations and trigger re-resolve via save
		if (frm.doc.docstatus !== 0) return;
		frm.clear_table("operations");
		frm.refresh_field("operations");
		frm.clear_table("sales_order_items");
		frm.refresh_field("sales_order_items");
	},
});

// ---- Status indicator ----

function set_status_indicator(frm) {
	const colors = {
		Draft: "red",
		"Not Started": "orange",
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

// ---- Get Sales Orders dialog (Draft only) ----

function add_get_sales_orders_button(frm) {
	if (frm.doc.docstatus !== 0) return;
	frm.add_custom_button(__("Get Sales Orders"), () => open_so_picker(frm));
}

function open_so_picker(frm) {
	if (!frm.doc.production_item) {
		frappe.show_alert({
			message: __("Pick an MC Component first"),
			indicator: "orange",
		});
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Get Sales Orders for {0}", [frm.doc.production_item]),
		fields: [
			{ fieldtype: "Link", label: __("Customer"), fieldname: "customer", options: "Customer" },
			{ fieldtype: "Column Break" },
			{ fieldtype: "Date", label: __("SO From Date"), fieldname: "from_date" },
			{ fieldtype: "Date", label: __("SO To Date"), fieldname: "to_date" },
			{ fieldtype: "Section Break" },
			{ fieldtype: "HTML", fieldname: "results_html" },
		],
		primary_action_label: __("Add Selected"),
		primary_action(values) {
			const $rows = dialog.$wrapper.find(".jo-p2-so-row input[type=checkbox]:checked");
			if (!$rows.length) {
				frappe.show_alert({
					message: __("No rows selected"),
					indicator: "orange",
				});
				return;
			}
			const existing = new Set(
				(frm.doc.sales_order_items || []).map((r) => `${r.sales_order}|${r.sales_order_item}`)
			);
			let added = 0;
			$rows.each(function () {
				const data = JSON.parse($(this).attr("data-row"));
				const key = `${data.sales_order}|${data.sales_order_item}`;
				if (existing.has(key)) return;
				const row = frm.add_child("sales_order_items");
				row.sales_order = data.sales_order;
				row.sales_order_item = data.sales_order_item;
				row.item_code = data.item_code;
				row.qty = data.open_qty;
				row.delivery_date = data.delivery_date;
				row.customer = data.customer;
				row.so_status = data.so_status;
				existing.add(key);
				added++;
			});
			frm.refresh_field("sales_order_items");
			// Auto-set qty = sum of newly populated rows
			let total = 0;
			(frm.doc.sales_order_items || []).forEach((r) => {
				total += parseFloat(r.qty || 0);
			});
			frm.set_value("qty", total);
			dialog.hide();
			frappe.show_alert({
				message: __("{0} row(s) added", [added]),
				indicator: "green",
			});
		},
	});

	// Search button to (re)fetch results
	const $search_btn = $(
		`<button class="btn btn-sm btn-default" style="margin-bottom:10px">${__("Search")}</button>`
	);
	dialog.$wrapper.find(".modal-body").prepend($search_btn);
	$search_btn.on("click", () => run_so_search(frm, dialog));

	dialog.show();
	// Run initial search with no filters
	run_so_search(frm, dialog);
}

function run_so_search(frm, dialog) {
	const v = dialog.get_values(true) || {};
	frappe.call({
		method: "iib.iib.doctype.job_order_p2.job_order_p2.get_sales_orders_for_jo",
		args: {
			production_item: frm.doc.production_item,
			customer: v.customer || null,
			from_date: v.from_date || null,
			to_date: v.to_date || null,
		},
		callback(r) {
			render_so_results(dialog, r.message || []);
		},
	});
}

function render_so_results(dialog, rows) {
	const $wrap = dialog.fields_dict.results_html.$wrapper;
	if (!rows.length) {
		$wrap.html(
			`<div class="text-muted">${__("No open Sales Order Items found")}</div>`
		);
		return;
	}
	const html = [
		`<table class="table table-bordered table-sm" style="font-size:12px">`,
		`<thead><tr>
			<th style="width:30px"><input type="checkbox" class="jo-p2-so-all"></th>
			<th>${__("Sales Order")}</th>
			<th>${__("Customer")}</th>
			<th>${__("Open Qty")}</th>
			<th>${__("Delivery Date")}</th>
			<th>${__("Status")}</th>
		</tr></thead><tbody>`,
	];
	rows.forEach((row) => {
		html.push(
			`<tr class="jo-p2-so-row">
				<td><input type="checkbox" data-row='${JSON.stringify(row).replace(/'/g, "&#39;")}'></td>
				<td>${row.sales_order}</td>
				<td>${row.customer || ""}</td>
				<td>${row.open_qty}</td>
				<td>${row.delivery_date || ""}</td>
				<td>${row.so_status || ""}</td>
			</tr>`
		);
	});
	html.push(`</tbody></table>`);
	$wrap.html(html.join(""));
	$wrap.find(".jo-p2-so-all").on("change", function () {
		$wrap.find(".jo-p2-so-row input[type=checkbox]").prop("checked", this.checked);
	});
}

// ---- Set Finish button (WIP -> FG) ----

function add_set_finish_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (["Completed", "Cancelled", "Stopped", "Closed"].includes(frm.doc.status)) return;
	if (flt(frm.doc.produced_qty) >= flt(frm.doc.qty)) return;
	frm.add_custom_button(
		__("Set Finish (WIP → FG)"),
		() => {
			frappe.call({
				method:
					"iib.iib.doctype.job_order_p2.job_order_p2.make_finish_stock_entry",
				args: { source_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Building Stock Entry..."),
				callback(r) {
					if (!r.message) return;
					frappe.model.sync(r.message);
					frappe.set_route("Form", "Stock Entry", r.message.name);
				},
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
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
					"iib.iib.doctype.job_order_p2.job_order_p2.make_return_components",
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
				__("Close this Job Order P2? No further Job Card edits will be allowed."),
				() => set_status(frm, "Closed")
			);
		},
		__("Status")
	);
}

function set_status(frm, status) {
	frappe.call({
		method: "iib.iib.doctype.job_order_p2.job_order_p2.stop_job_order",
		args: { name: frm.doc.name, status },
		callback() {
			frm.reload_doc();
		},
	});
}

function flt(v) {
	return parseFloat(v || 0) || 0;
}
