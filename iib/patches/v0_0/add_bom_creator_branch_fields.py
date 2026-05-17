import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"BOM Creator Item": [
				{
					"fieldname": "custom_iib_branch",
					"label": "Branch",
					"fieldtype": "Data",
					"insert_after": "qty",
					"in_list_view": 1,
					"columns": 1,
					"module": "IIB",
				}
			],
			"BOM": [
				{
					"fieldname": "custom_iib_branch",
					"label": "Branch",
					"fieldtype": "Data",
					"insert_after": "bom_creator_item",
					"read_only": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
					"module": "IIB",
				}
			],
		}
	)
	frappe.clear_cache()
