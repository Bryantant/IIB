from frappe import _


def get_data():
	return {
		"fieldname": "job_order_p2",
		"transactions": [
			{
				"label": _("Material Movement"),
				"items": ["Job Order P2 RM to WIP", "Job Order P2 WIP to FG"],
			},
		],
	}
