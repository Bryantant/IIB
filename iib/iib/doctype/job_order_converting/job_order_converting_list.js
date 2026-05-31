// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

// Submittable doctypes default to a docstatus-based list badge
// (Draft / Submitted / Cancelled). Override get_indicator so the list
// reflects the custom `status` field, matching the form indicator.
frappe.listview_settings["Job Order Converting"] = {
	get_indicator(doc) {
		const colors = {
			Draft: "red",
			"Not Started": "orange",
			"In Process": "yellow",
			Completed: "green",
			Stopped: "grey",
			Closed: "grey",
			Cancelled: "red",
		};
		const status = doc.status || "Draft";
		return [__(status), colors[status] || "blue", "status,=," + status];
	},
};
