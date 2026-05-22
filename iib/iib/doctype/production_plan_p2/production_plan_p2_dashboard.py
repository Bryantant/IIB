from frappe import _


def get_data():
	return {
		"fieldname": "production_plan_p2",
		"transactions": [
			{"label": _("Manufacturing"), "items": ["Job Order P2"]},
		],
	}
