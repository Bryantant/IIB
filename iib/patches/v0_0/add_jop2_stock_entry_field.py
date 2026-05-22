import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Stock Entry": [
				{
					"fieldname": "iib_job_order_p2",
					"label": "Job Order P2",
					"fieldtype": "Link",
					"options": "Job Order P2",
					"insert_after": "work_order",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"in_standard_filter": 1,
					"module": "IIB",
				}
			]
		}
	)
	frappe.clear_cache()
