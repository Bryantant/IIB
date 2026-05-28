frappe.ui.form.on("Production Process", {
	setup(frm) {
		frm.set_query("section", () => ({ filters: { is_group: 0 } }));
		frm.set_query("daily_production_schedule", () => ({
			filters: frm.doc.section ? { section: frm.doc.section, docstatus: 1 } : { docstatus: 1 },
		}));
		frm.set_query("job_order_p2", "items", () => ({
			query: "iib.iib.doctype.production_process.production_process.get_job_orders_for_section",
			filters: { section: frm.doc.section || "" },
		}));
		frm.set_query("job_order_p2", "rejects", () => {
			const jos = (frm.doc.items || []).map((r) => r.job_order_p2).filter(Boolean);
			return jos.length ? { filters: [["name", "in", jos]] } : {};
		});
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

	$(`<div class="pp-fetch-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-pp-fetch">
			${__("Fetch from DPS")}
		</button>
	</div>`)
		.insertBefore($table)
		.find(".btn-pp-fetch")
		.on("click", () => run_fetch_from_dps(frm));
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
	job_order_p2(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.job_order_p2) return;

		frappe.call({
			method: "iib.iib.doctype.production_process.production_process.get_jo_details",
			args: { job_order_p2: row.job_order_p2, section: frm.doc.section },
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
