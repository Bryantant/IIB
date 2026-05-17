import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.stock.doctype.item.test_item import make_item
from iib.overrides.bom_creator import add_sub_assembly


class TestBOMCreatorBranch(FrappeTestCase):
	def test_branch_raw_materials_create_matching_subassembly_and_fg_boms(self):
		suffix = frappe.generate_hash(length=8)
		fg = self.make_test_item(f"IIB-FG-{suffix}")
		sa = self.make_test_item(f"IIB-SA-{suffix}")
		rm_a = self.make_test_item(f"IIB-RM-A-{suffix}", valuation_rate=10)
		rm_b = self.make_test_item(f"IIB-RM-B-{suffix}", valuation_rate=20)
		rm_common = self.make_test_item(f"IIB-RM-COMMON-{suffix}", valuation_rate=5)

		doc = self.make_bom_creator(fg)
		add_sub_assembly(
			parent=doc.name,
			fg_item=fg,
			fg_reference_id=doc.name,
			allow_alternative_item=1,
			bom_item={
				"item_code": sa,
				"qty": 1,
				"items": [
					{"item_code": rm_a, "qty": 1, "custom_iib_branch": " A "},
					{"item_code": rm_b, "qty": 1, "custom_iib_branch": "B"},
					{"item_code": rm_common, "qty": 1},
				],
			},
		)

		doc.reload()
		doc.submit()
		doc.create_boms()

		branch_a_sa = self.get_bom(doc.name, sa, "A")
		branch_b_sa = self.get_bom(doc.name, sa, "B")
		branch_a_fg = self.get_bom(doc.name, fg, "A")
		branch_b_fg = self.get_bom(doc.name, fg, "B")

		self.assert_bom_items(branch_a_sa.name, includes={rm_a, rm_common}, excludes={rm_b})
		self.assert_bom_items(branch_b_sa.name, includes={rm_b, rm_common}, excludes={rm_a})

		self.assert_parent_links_to_branch_bom(branch_a_fg.name, sa, branch_a_sa.name)
		self.assert_parent_links_to_branch_bom(branch_b_fg.name, sa, branch_b_sa.name)

		self.assertEqual(
			frappe.db.count("BOM", {"bom_creator": doc.name, "docstatus": 1}),
			4,
		)

	def test_non_branch_bom_creator_keeps_existing_single_variant_behavior(self):
		suffix = frappe.generate_hash(length=8)
		fg = self.make_test_item(f"IIB-FG-LEGACY-{suffix}")
		sa = self.make_test_item(f"IIB-SA-LEGACY-{suffix}")
		rm = self.make_test_item(f"IIB-RM-LEGACY-{suffix}", valuation_rate=10)

		doc = self.make_bom_creator(fg)
		add_sub_assembly(
			parent=doc.name,
			fg_item=fg,
			fg_reference_id=doc.name,
			allow_alternative_item=1,
			bom_item={
				"item_code": sa,
				"qty": 1,
				"items": [{"item_code": rm, "qty": 1}],
			},
		)

		doc.reload()
		doc.submit()
		doc.create_boms()

		self.assertIsNotNone(self.get_bom(doc.name, sa, ""))
		self.assertIsNotNone(self.get_bom(doc.name, fg, ""))
		self.assertEqual(
			frappe.db.count("BOM", {"bom_creator": doc.name, "docstatus": 1}),
			2,
		)

		doc.create_boms()
		self.assertEqual(
			frappe.db.count("BOM", {"bom_creator": doc.name, "docstatus": 1}),
			2,
		)

	def make_test_item(self, item_code, valuation_rate=0):
		return make_item(
			item_code,
			{
				"item_group": "Raw Material",
				"stock_uom": "Nos",
				"valuation_rate": valuation_rate,
			},
		).name

	def make_bom_creator(self, item_code):
		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		currency = frappe.get_cached_value("Company", company, "default_currency")

		doc = frappe.new_doc("BOM Creator")
		doc.update(
			{
				"company": company,
				"item_code": item_code,
				"qty": 1,
				"rm_cost_as_per": "Valuation Rate",
				"currency": currency,
				"plc_conversion_rate": 1,
				"conversion_rate": 1,
			}
		)
		doc.save()
		return doc

	def get_bom(self, bom_creator, item, branch):
		filters = {
			"bom_creator": bom_creator,
			"item": item,
			"docstatus": 1,
		}
		if branch:
			filters["custom_iib_branch"] = branch
		else:
			filters["custom_iib_branch"] = ("in", ["", None])

		return frappe.get_all(
			"BOM",
			filters=filters,
			fields=["name", "item", "custom_iib_branch"],
			limit=1,
		)[0]

	def assert_bom_items(self, bom, includes, excludes):
		items = {
			row.item_code
			for row in frappe.get_all(
				"BOM Item",
				filters={"parent": bom},
				fields=["item_code"],
			)
		}
		self.assertTrue(includes.issubset(items))
		self.assertFalse(excludes.intersection(items))

	def assert_parent_links_to_branch_bom(self, parent_bom, item_code, child_bom):
		row = frappe.get_all(
			"BOM Item",
			filters={"parent": parent_bom, "item_code": item_code},
			fields=["bom_no"],
			limit=1,
		)[0]
		self.assertEqual(row.bom_no, child_bom)
