# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import re
from collections import OrderedDict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries

BOM_FIELDS = [
	"company",
	"rm_cost_as_per",
	"currency",
]

BOM_ITEM_FIELDS = [
	"item_code",
	"qty",
	"uom",
	"stock_uom",
	"bom_no",
]


class IIBBOMCreator(Document):
	def before_save(self):
		if not self.item_code:
			self._create_fg_item()

	def validate(self):
		self._validate_items()

	def _validate_items(self):
		for row in self.items:
			if row.level == 1 and row.fg_reference_id != self.name:
				frappe.throw(
					_("Row {0}: Level-1 item must reference the BOM Creator document").format(row.idx)
				)

	def _create_fg_item(self):
		code = getseries("IIB-FG", 4)
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": self.fg_item_group,
				"stock_uom": self.default_uom or "Nos",
				"is_stock_item": 1,
			}
		)
		item.insert(ignore_permissions=True)
		self.item_code = code
		self.item_name = code

	def on_submit(self):
		self.enqueue_create_boms()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def enqueue_create_boms(self):
		frappe.enqueue(
			self.create_boms,
			queue="short",
			timeout=600,
			is_async=True,
		)
		frappe.msgprint(
			_("BOMs creation has been enqueued, kindly check the status after some time"), alert=True
		)

	def create_boms(self):
		self.db_set("status", "In Progress")

		production_item_wise_rm = OrderedDict()
		production_item_wise_rm[(self.item_code, self.name)] = frappe._dict(
			{"items": [], "bom_no": "", "fg_item_data": self}
		)

		for row in self.items:
			if row.is_expandable:
				key = (row.item_code, row.name)
				if key not in production_item_wise_rm:
					production_item_wise_rm[key] = frappe._dict(
						{"items": [], "bom_no": "", "fg_item_data": row}
					)

			parent_code = self.item_code if row.fg_reference_id == self.name else None
			if parent_code is None:
				parent_row = next(
					(r for r in self.items if r.name == row.fg_reference_id), None
				)
				parent_code = parent_row.item_code if parent_row else None

			if parent_code:
				key = (parent_code, row.fg_reference_id)
				if key not in production_item_wise_rm:
					production_item_wise_rm[key] = frappe._dict(
						{"items": [], "bom_no": "", "fg_item_data": row}
					)
				production_item_wise_rm[key]["items"].append(row)

		reverse_tree = OrderedDict(reversed(list(production_item_wise_rm.items())))

		try:
			for key in reverse_tree:
				fg_item_data = production_item_wise_rm[key].fg_item_data
				self._create_bom(fg_item_data, production_item_wise_rm)

			self.db_set("status", "Completed")
			frappe.msgprint(_("BOMs created successfully"))
		except Exception:
			traceback = frappe.get_traceback(with_context=True)
			self.db_set("status", "Failed")
			self.db_set("error_log", traceback)
			frappe.msgprint(_("BOMs creation failed"))

	def _create_bom(self, row, production_item_wise_rm):
		bom_creator_item = row.name if hasattr(row, "name") and row.name != self.name else ""

		item_code = row.item_code if hasattr(row, "item_code") else self.item_code
		qty = row.qty if hasattr(row, "qty") else self.qty

		if frappe.db.exists(
			"BOM",
			{
				"bom_creator": self.name,
				"item": item_code,
				"docstatus": 1,
			},
		):
			return

		bom = frappe.new_doc("BOM")
		bom.update(
			{
				"item": item_code,
				"bom_type": "Production",
				"quantity": qty,
				"bom_creator": self.name,
			}
		)

		for field in BOM_FIELDS:
			if self.get(field):
				bom.set(field, self.get(field))

		ref_id = row.name if hasattr(row, "name") and row.name != self.name else self.name
		children = production_item_wise_rm.get((item_code, ref_id), frappe._dict({"items": []}))

		for child in children.get("items", []):
			child_bom_no = ""
			if child.is_expandable:
				child_key = (child.item_code, child.name)
				if child_key in production_item_wise_rm:
					child_bom_no = production_item_wise_rm[child_key].bom_no

			bom.append(
				"items",
				{
					"item_code": child.item_code,
					"qty": child.qty,
					"uom": child.uom or self.default_uom or "Nos",
					"stock_uom": child.uom or self.default_uom or "Nos",
					"bom_no": child_bom_no,
					"do_not_explode": 1 if not child_bom_no else 0,
					"allow_scrap_items": 1,
					"include_item_in_manufacturing": 1,
				},
			)

		bom.save(ignore_permissions=True)
		bom.submit()

		if hasattr(row, "name") and row.name != self.name:
			frappe.db.set_value("IIB BOM Creator Item", row.name, "bom_no", bom.name)
			frappe.db.set_value("IIB BOM Creator Item", row.name, "bom_created", 1)

		key = (item_code, ref_id)
		if key in production_item_wise_rm:
			production_item_wise_rm[key].bom_no = bom.name


@frappe.whitelist()
def add_level1_item(parent, letter, qty):
	if not re.match(r"^[A-Za-z]$", letter):
		frappe.throw(_("Sub-assembly letter must be a single alphabet character (A–Z)."))

	doc = frappe.get_doc("IIB BOM Creator", parent)

	if not doc.item_code:
		frappe.throw(_("Save the BOM Creator first to generate the FG item code."))

	item_code = doc.item_code + letter.upper()

	if frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} already exists. Choose a different letter.").format(item_code))

	_create_item(item_code, doc.sub_assembly_item_group, doc.default_uom or "Nos")

	doc.append(
		"items",
		{
			"item_code": item_code,
			"item_name": item_code,
			"level": 1,
			"parent_item_code": doc.item_code,
			"fg_reference_id": doc.name,
			"is_expandable": 1,
			"qty": qty,
			"uom": doc.default_uom or "Nos",
		},
	)

	doc.save(ignore_permissions=True)
	return doc


@frappe.whitelist()
def add_level2_item(parent, parent_ref_id, qty):
	doc = frappe.get_doc("IIB BOM Creator", parent)

	parent_row = next((r for r in doc.items if r.name == parent_ref_id), None)
	if not parent_row:
		frappe.throw(_("Parent sub-assembly row not found."))

	existing_children = [r for r in doc.items if r.fg_reference_id == parent_ref_id]
	counter = len(existing_children) + 1
	item_code = f"{parent_row.item_code}-{counter}"

	if frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} already exists.").format(item_code))

	_create_item(item_code, doc.component_item_group, doc.default_uom or "Nos")

	doc.append(
		"items",
		{
			"item_code": item_code,
			"item_name": item_code,
			"level": 2,
			"parent_item_code": parent_row.item_code,
			"fg_reference_id": parent_ref_id,
			"is_expandable": 0,
			"qty": qty,
			"uom": doc.default_uom or "Nos",
		},
	)

	doc.save(ignore_permissions=True)
	return doc


@frappe.whitelist()
def remove_item(parent, row_name):
	doc = frappe.get_doc("IIB BOM Creator", parent)

	row = next((r for r in doc.items if r.name == row_name), None)
	if not row:
		frappe.throw(_("Row not found."))

	if row.is_expandable:
		children = [r for r in doc.items if r.fg_reference_id == row_name]
		for child in children:
			doc.items.remove(child)

	doc.items.remove(row)
	doc.save(ignore_permissions=True)
	return doc


def _create_item(item_code, item_group, uom):
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": uom,
			"is_stock_item": 1,
		}
	).insert(ignore_permissions=True)
