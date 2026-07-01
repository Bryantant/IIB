frappe.listview_settings["FGTS"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = {
			Draft: "grey",
			"Waiting QC": "orange",
			"OK QC": "green",
			Cancelled: "red",
		};
		return [__(doc.status), colors[doc.status] || "blue", "status,=," + doc.status];
	},
};
