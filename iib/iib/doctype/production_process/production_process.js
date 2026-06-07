frappe.ui.form.on("Production Process", {
	setup(frm) {
		frm.set_query("section", () => ({ filters: { is_group: 0 } }));
		frm.set_query("daily_production_schedule", () => ({
			filters: frm.doc.section ? { section: frm.doc.section } : {},
		}));
		frm.set_query("job_order_converting", "items", () => ({
			query: "iib.iib.doctype.production_process.production_process.get_job_orders_for_section",
			filters: { section: frm.doc.section || "" },
		}));
		frm.set_query("job_order_converting", "rejects", () => {
			const jos = (frm.doc.items || []).map((r) => r.job_order_converting).filter(Boolean);
			return jos.length ? { filters: [["name", "in", jos]] } : {};
		});
		frm.set_query("reject_reason", "rejects", () => ({}));
	},

	refresh(frm) {
		set_status_indicator(frm);
		render_fetch_dps_btn(frm);
		// Hide the row-index "No." column from the items grid
		frm.fields_dict.items.$wrapper.find(".row-index").hide();
	},

	section(frm) {
		frm.set_value("daily_production_schedule", "");
	},
});

// ---- Status indicator ----

function set_status_indicator(frm) {
	const colors = {
		Draft: "grey",
		Submitted: "green",
		Cancelled: "red",
	};
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}

function render_fetch_dps_btn(frm) {
	const $table = frm.fields_dict.items.$wrapper;
	$table.prev(".pp-fetch-wrapper").remove();

	// Only show on unsaved drafts
	if (frm.doc.docstatus !== 0) return;

	const $wrap = $(`<div class="pp-fetch-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-pp-fetch mr-2">
			${__("Fetch from DPS")}
		</button>
		<button class="btn btn-sm btn-default btn-pp-add-item">
			${__("Add Job by Item")}
		</button>
	</div>`).insertBefore($table);

	$wrap.find(".btn-pp-fetch").on("click", () => run_fetch_from_dps(frm));
	$wrap.find(".btn-pp-add-item").on("click", () => add_job_by_item(frm));
}

// ---- Add Job by Item: filter by Item and/or pick a Job Order directly ----

const DPS_MODULE = "iib.iib.doctype.daily_production_schedule.daily_production_schedule";
const PP_MODULE = "iib.iib.doctype.production_process.production_process";

function add_job_by_item(frm) {
	if (!frm.doc.section) {
		frappe.show_alert({ message: __("Set Section first"), indicator: "orange" });
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __("Add Job by Item"),
		fields: [
			{
				fieldname: "item_code",
				fieldtype: "Link",
				options: "Item",
				label: __("Filter by Item"),
				get_query: () => ({
					query: `${DPS_MODULE}.get_jo_items_for_section`,
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
					query: `${PP_MODULE}.get_job_orders_for_section`,
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
					message: __("Already on this Production Process"),
					indicator: "orange",
				});
				return;
			}
			frappe.call({
				method: `${PP_MODULE}.get_jo_details`,
				args: { job_order_converting: values.job_order_converting, section: frm.doc.section },
				callback(r) {
					if (!r.message) return;
					const vals = r.message;
					if (!vals.p_qty && vals.so_qty) vals.p_qty = vals.so_qty;
					Object.assign(frm.add_child("items"), vals, {
						job_order_converting: values.job_order_converting,
					});
					frm.refresh_field("items");
					frappe.show_alert({ message: __("Job added"), indicator: "green" });
				},
			});
			d.hide();
		},
	});
	d.show();
}

function run_fetch_from_dps(frm) {
	if (!frm.doc.daily_production_schedule) {
		frappe.show_alert({
			message: __("Set Daily Production Schedule first"),
			indicator: "orange",
		});
		return;
	}
	frappe.call({
		method: "iib.iib.doctype.production_process.production_process.fetch_from_dps",
		args: { daily_production_schedule: frm.doc.daily_production_schedule },
		freeze: true,
		freeze_message: __("Loading from schedule..."),
		callback(r) {
			if (!r.message?.length) {
				frappe.show_alert({
					message: __("No jobs found in the schedule"),
					indicator: "orange",
				});
				return;
			}
			frm.clear_table("items");
			r.message.forEach((row) => Object.assign(frm.add_child("items"), row));
			frm.refresh_field("items");
			frappe.show_alert({
				message: __("{0} job(s) loaded", [r.message.length]),
				indicator: "green",
			});
		},
	});
}

// ---- Child table: auto-populate from Job Order when manually adding a row ----

frappe.ui.form.on("Production Process Item", {
	job_order_converting(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.job_order_converting) return;

		frappe.call({
			method: "iib.iib.doctype.production_process.production_process.get_jo_details",
			args: { job_order_converting: row.job_order_converting, section: frm.doc.section },
			callback(r) {
				if (!r.message) return;
				const values = r.message;
				// Default p_qty to JO qty when manually adding a row
				if (!row.p_qty && values.so_qty) {
					values.p_qty = values.so_qty;
				}
				frappe.model.set_value(cdt, cdn, values);
			},
		});
	},
});
