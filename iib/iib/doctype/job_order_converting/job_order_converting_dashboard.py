from frappe import _


def get_data():
	return {
		"fieldname": "job_order_converting",
		"transactions": [
			{
				"label": _("Material Movement"),
				"items": ["Job Order Converting RM to WIP", "Job Order Converting WIP to FG"],
			},
		],
	}
