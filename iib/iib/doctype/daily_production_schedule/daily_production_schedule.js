const DPS_METHOD =
	"iib.iib.doctype.daily_production_schedule.daily_production_schedule";

frappe.ui.form.on("Daily Production Schedule", {
	setup(frm) {
		frm.set_query("section", () => ({ filters: { is_group: 0 } }));
		apply_jo_item_query(frm);
	},

	refresh(frm) {
		render_action_buttons(frm);
	},

	section(frm) {
		apply_jo_item_query(frm);
	},
});

// Job Order picker on each row is filtered to active JOs for the current section.
function apply_jo_item_query(frm) {
	frm.set_query("job_order_converting", "items", () => ({
		query: `${DPS_METHOD}.get_jo_for_section`,
		filters: { section: frm.doc.section || "" },
	}));
}

function render_action_buttons(frm) {
	const $table = frm.fields_dict.items.$wrapper;
	$table.prev(".dps-action-wrapper").remove();

	const $wrap = $(`<div class="dps-action-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-dps-refresh mr-2">
			${__("Update Schedule")}
		</button>
		<button class="btn btn-sm btn-default btn-dps-add-job">
			${__("Add Job by Item")}
		</button>
	</div>`).insertBefore($table);

	$wrap.find(".btn-dps-refresh").on("click", () => run_refresh_carry(frm));
	$wrap.find(".btn-dps-add-job").on("click", () => add_job_dialog(frm));
}

// ---- Refresh & Carry Forward: pull prior day's unstarted jobs + drop started ones ----

function run_refresh_carry(frm) {
	if (!frm.doc.section) {
		frappe.show_alert({ message: __("Set Section first"), indicator: "orange" });
		return;
	}

	// Pass JO name + manual values so the planner's typed input survives the rebuild.
	const current_rows = (frm.doc.items || []).map((r) => ({
		job_order_converting: r.job_order_converting,
		req_qty: r.req_qty,
		proc_qty: r.proc_qty,
		run_qty: r.run_qty,
		waktu: r.waktu,
		remark: r.remark,
	}));

	frappe.call({
		method: `${DPS_METHOD}.refresh_and_carry_forward`,
		args: {
			section: frm.doc.section,
			posting_date: frm.doc.posting_date,
			current_rows: JSON.stringify(current_rows),
		},
		freeze: true,
		freeze_message: __("Refreshing..."),
		callback(r) {
			const rows = r.message || [];
			frm.clear_table("items");
			rows.forEach((row) => Object.assign(frm.add_child("items"), row));
			frm.refresh_field("items");
			frappe.show_alert({
				message: __("Schedule refreshed — {0} job(s)", [rows.length]),
				indicator: "green",
			});
		},
	});
}

// ---- Add Job: unified dialog — filter by Item and/or pick a Job Order directly ----

function add_job_dialog(frm) {
	if (!frm.doc.section) {
		frappe.show_alert({ message: __("Set Section first"), indicator: "orange" });
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __("Add Job"),
		fields: [
			{
				fieldname: "item_code",
				fieldtype: "Link",
				options: "Item",
				label: __("Filter by Item"),
				get_query: () => ({
					query: `${DPS_METHOD}.get_jo_items_for_section`,
					filters: { section: frm.doc.section || "" },
				}),
				onchange: () => d.set_value("job_order_converting", ""),
			},
			{
				fieldname: "job_order_converting",
				fieldtype: "Link",
				options: "Job Order Converting",
				label: __("Job Order"),
				reqd: 1,
				get_query: () => ({
					query: `${DPS_METHOD}.get_jo_for_section`,
					filters: {
						section: frm.doc.section || "",
						item_code: d.get_value("item_code") || "",
					},
				}),
			},
		],
		primary_action_label: __("Add"),
		primary_action(values) {
			const exists = (frm.doc.items || []).some(
				(r) => r.job_order_converting === values.job_order_converting
			);
			if (exists) {
				frappe.show_alert({
					message: __("Already on the schedule"),
					indicator: "orange",
				});
				return;
			}
			frappe.call({
				method: `${DPS_METHOD}.get_jo_row`,
				args: { job_order_converting: values.job_order_converting },
				callback(r) {
					if (!r.message) return;
					Object.assign(frm.add_child("items"), r.message);
					frm.refresh_field("items");
					frappe.show_alert({ message: __("Job added"), indicator: "green" });
				},
			});
			d.hide();
		},
	});
	d.show();
}

// ---- Auto-fill display fields when a JO is picked manually (Add Row) ----

frappe.ui.form.on("Daily Production Schedule Item", {
	job_order_converting(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.job_order_converting) return;
		frappe.call({
			method: `${DPS_METHOD}.get_jo_row`,
			args: { job_order_converting: row.job_order_converting },
			callback(r) {
				if (!r.message) return;
				const v = r.message;
				frappe.model.set_value(cdt, cdn, {
					item_code: v.item_code,
					item_name: v.item_name,
					master_card: v.master_card,
					customer: v.customer,
					so_no: v.so_no,
					so_qty: v.so_qty,
					due_date: v.due_date,
					flute: v.flute,
					colours: v.colours,
				});
			},
		});
	},
});
