# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMasterCard(FrappeTestCase):
	def test_price_item_total_is_calculated(self):
		doc = frappe.get_doc(
			{
				"doctype": "Master Card",
				"customer": "TEST-CUSTOMER",
				"description": "Test Master Card",
				"items": [{"component": "A"}],
				"price_items": [
					{
						"moq_qty": 50,
						"component": "A",
						"material": 0.455,
						"labour": 0.535,
						"profit": 0.148,
						"ext_profit": 0,
					}
				],
			}
		)

		doc.validate()

		self.assertEqual(doc.price_items[0].total, 1.138)

	def test_price_item_component_must_exist_in_finish_goods(self):
		doc = frappe.get_doc(
			{
				"doctype": "Master Card",
				"customer": "TEST-CUSTOMER",
				"description": "Test Master Card",
				"items": [{"component": "A"}],
				"price_items": [{"moq_qty": 50, "component": "B", "material": 1}],
			}
		)

		self.assertRaises(frappe.ValidationError, doc.validate)
