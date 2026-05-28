frappe.ui.form.on("Daily Production Schedule", {
	setup(frm) {
		frm.set_query("section", () => ({ filters: { is_group: 0 } }));
	},

	refresh(frm) {
		set_status_indicator(frm);
		render_fetch_jobs_btn(frm);
	},
});

function render_fetch_jobs_btn(frm) {
	const $table = frm.fields_dict.items.$wrapper;
	$table.prev(".dps-fetch-wrapper").remove();
	if (frm.doc.docstatus !== 0) return;

	$(`<div class="dps-fetch-wrapper mb-2">
		<button class="btn btn-sm btn-default btn-dps-fetch">
			${__("Fetch Pending Jobs")}
		</button>
	</div>`)
		.insertBefore($table)
		.find(".btn-dps-fetch")
		.on("click", () => run_fetch_pending_jobs(frm));
}

function run_fetch_pending_jobs(frm) {
	if (!frm.doc.section) {
		frappe.show_alert({ message: __("Set Section first"), indicator: "orange" });
		return;
	}
	const existing_jos = (frm.doc.items || []).map((r) => r.job_order_p2).filter(Boolean);
	frappe.call({
		method: "iib.iib.doctype.daily_production_schedule.daily_production_schedule.get_pending_jobs",
		args: {
			section: frm.doc.section,
			posting_date: frm.doc.posting_date,
			existing_jos: JSON.stringify(existing_jos),
		},
		freeze: true,
		freeze_message: __("Fetching pending jobs..."),
		callback(r) {
			if (!r.message?.length) {
				frappe.show_alert({
					message: __("No pending jobs found for this section"),
					indicator: "orange",
				});
				return;
			}
			r.message.forEach((row) => {
				const child = frm.add_child("items");
				Object.assign(child, row);
			});
			frm.refresh_field("items");
			frappe.show_alert({
				message: __("{0} job(s) added", [r.message.length]),
				indicator: "green",
			});
		},
	});
}

function set_status_indicator(frm) {
	const colors = { Draft: "grey", Confirmed: "green", Cancelled: "red" };
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}
