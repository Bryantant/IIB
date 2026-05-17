import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Work Order": [
				{
					"fieldname": "custom_production_plan",
					"label": "Custom Production Plan",
					"fieldtype": "Link",
					"options": "Custom Production Plan",
					"insert_after": "production_plan",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"search_index": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_production_plan_item",
					"label": "Custom Production Plan Item",
					"fieldtype": "Data",
					"insert_after": "custom_production_plan",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"module": "IIB",
				},
			],
			"Material Request Item": [
				{
					"fieldname": "custom_production_plan",
					"label": "Custom Production Plan",
					"fieldtype": "Link",
					"options": "Custom Production Plan",
					"insert_after": "production_plan",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_production_plan_item",
					"label": "Custom Production Plan Item",
					"fieldtype": "Data",
					"insert_after": "custom_production_plan",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"module": "IIB",
				},
			],
			"Purchase Order Item": [
				{
					"fieldname": "custom_production_plan",
					"label": "Custom Production Plan",
					"fieldtype": "Link",
					"options": "Custom Production Plan",
					"insert_after": "production_plan",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_production_plan_item",
					"label": "Custom Production Plan Item",
					"fieldtype": "Data",
					"insert_after": "custom_production_plan",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"print_hide": 1,
					"module": "IIB",
				},
			],
		}
	)
	frappe.clear_cache()
