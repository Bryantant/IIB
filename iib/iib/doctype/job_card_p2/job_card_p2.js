frappe.ui.form.on("Job Card P2", {
	setup(frm) {
		frm.set_query("section", () => ({
			query:
				"iib.iib.doctype.iib_production_section.iib_production_section.get_section_leaf_query",
			filters: {
				section_group: frm.doc.section_group || null,
			},
		}));
	},

	refresh(frm) {
		set_status_indicator(frm);
	},
});

frappe.ui.form.on("Job Card P2 Time Log", {
	from_time: compute_row_time,
	to_time: compute_row_time,
});

function compute_row_time(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (row.from_time && row.to_time) {
		const diff_ms =
			frappe.datetime.str_to_obj(row.to_time) -
			frappe.datetime.str_to_obj(row.from_time);
		row.time_in_mins = diff_ms > 0 ? Math.round((diff_ms / 60000) * 100) / 100 : 0;
		frm.refresh_field("time_logs");
	}
}

function set_status_indicator(frm) {
	const colors = {
		Open: "orange",
		"Work In Progress": "yellow",
		"On Hold": "grey",
		Completed: "blue",
		Submitted: "green",
		Cancelled: "red",
	};
	if (frm.doc.status) {
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "blue");
	}
}
