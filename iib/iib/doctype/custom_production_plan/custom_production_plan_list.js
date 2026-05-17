frappe.listview_settings["Custom Production Plan"] = {
	add_fields: ["status"],
	indicator(doc) {
		const map = {
			Draft: "red",
			Submitted: "blue",
			"In Process": "orange",
			Completed: "green",
			Cancelled: "red",
			Closed: "gray",
			"Material Requested": "purple",
		};
		return [__(doc.status), map[doc.status] || "gray", "status,=," + doc.status];
	},
};
