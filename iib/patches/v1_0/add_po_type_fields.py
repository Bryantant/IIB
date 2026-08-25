import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Sales Order": [
				{
					"fieldname": "po_type",
					"label": "Jenis PO",
					"fieldtype": "Select",
					"options": "General\nFC",
					"default": "General",
					"insert_after": "so_batch",
					"in_standard_filter": 1,
					"read_only": 1,
					"module": "IIB",
				}
			],
			"Sales Order Item": [
				{
					"fieldname": "custom_po_type",
					"label": "Jenis PO",
					"fieldtype": "Select",
					"options": "General\nFC",
					"default": "General",
					"insert_after": "qty",
					"read_only": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_master_card",
					"label": "FC Match Master Card",
					"fieldtype": "Link",
					"options": "Master Card",
					"insert_after": "custom_po_type",
					"read_only": 1,
					"hidden": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_component",
					"label": "FC Match Component",
					"fieldtype": "Data",
					"insert_after": "custom_master_card",
					"read_only": 1,
					"hidden": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_matched_qty",
					"label": "FC Matched Qty",
					"fieldtype": "Float",
					"default": "0",
					"insert_after": "custom_component",
					"read_only": 1,
					"in_list_view": 1,
					"no_copy": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_covered_qty",
					"label": "FC Covered Qty",
					"fieldtype": "Float",
					"default": "0",
					"insert_after": "custom_fc_matched_qty",
					"read_only": 1,
					"in_list_view": 1,
					"no_copy": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_coverage_note",
					"label": "Remark",
					"fieldtype": "Data",
					"insert_after": "custom_fc_covered_qty",
					"read_only": 1,
					"in_list_view": 1,
					"no_copy": 1,
					"module": "IIB",
				},
			],
			"Packed Item": [
				{
					"fieldname": "custom_po_type",
					"label": "Jenis PO",
					"fieldtype": "Select",
					"options": "General\nFC",
					"default": "General",
					"insert_after": "qty",
					"read_only": 1,
					"hidden": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_master_card",
					"label": "FC Match Master Card",
					"fieldtype": "Link",
					"options": "Master Card",
					"insert_after": "custom_po_type",
					"read_only": 1,
					"hidden": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_component",
					"label": "FC Match Component",
					"fieldtype": "Data",
					"insert_after": "custom_master_card",
					"read_only": 1,
					"hidden": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_matched_qty",
					"label": "FC Matched Qty",
					"fieldtype": "Float",
					"default": "0",
					"insert_after": "custom_component",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_covered_qty",
					"label": "FC Covered Qty",
					"fieldtype": "Float",
					"default": "0",
					"insert_after": "custom_fc_matched_qty",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"module": "IIB",
				},
				{
					"fieldname": "custom_fc_coverage_note",
					"label": "Remark",
					"fieldtype": "Data",
					"insert_after": "custom_fc_covered_qty",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
					"module": "IIB",
				},
			],
		}
	)

	frappe.db.sql(
		"UPDATE `tabSO Batch Item` SET po_type = 'General' WHERE IFNULL(po_type, '') = ''"
	)
	frappe.db.sql(
		"UPDATE `tabSales Order` SET po_type = 'General' WHERE IFNULL(po_type, '') = ''"
	)

	frappe.clear_cache()
