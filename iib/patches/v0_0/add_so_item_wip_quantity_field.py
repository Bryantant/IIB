import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt


def execute():
	create_custom_fields(
		{
			"Sales Order Item": [
				{
					"fieldname": "custom_wip_quantity",
					"label": "WIP Quantity",
					"fieldtype": "Float",
					"insert_after": "delivered_qty",
					"default": "0",
					"read_only": 1,
					"in_list_view": 1,
					"no_copy": 1,
					"module": "IIB",
				}
			]
		}
	)
	sync_existing_wip_quantities()
	frappe.clear_cache()


def sync_existing_wip_quantities():
	if not frappe.db.has_column("Sales Order Item", "custom_wip_quantity"):
		return

	so_items = {
		r.sales_order_item
		for r in frappe.db.sql(
			"""
			SELECT DISTINCT sales_order_item
			FROM `tabJob Order Converting Sales Order Item`
			WHERE IFNULL(sales_order_item, '') != ''
			""",
			as_dict=True,
		)
	}
	so_items.update(
		r.name
		for r in frappe.db.sql(
			"""
			SELECT name
			FROM `tabSales Order Item`
			WHERE IFNULL(custom_wip_quantity, 0) != 0
			""",
			as_dict=True,
		)
	)

	for so_item in so_items:
		qty = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(josi.qty), 0)
			FROM `tabJob Order Converting Sales Order Item` josi
			JOIN `tabJob Order Converting` converting ON converting.name = josi.parent
			WHERE josi.parenttype = 'Job Order Converting'
			  AND josi.sales_order_item = %(so_item)s
			  AND converting.docstatus < 2
			""",
			{"so_item": so_item},
		)[0][0]
		frappe.db.set_value(
			"Sales Order Item",
			so_item,
			"custom_wip_quantity",
			flt(qty),
			update_modified=False,
		)
