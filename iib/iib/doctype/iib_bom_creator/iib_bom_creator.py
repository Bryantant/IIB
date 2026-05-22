# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

BOM_FIELDS = [
	"company",
	"rm_cost_as_per",
	"currency",
]

ITEM_SPEC_FIELDS = [
	"custom_part_no",
	"custom_printing",
	"custom_colour_1",
	"custom_colour_2",
	"custom_colour_3",
	"custom_colour_4",
	"custom_colour_5",
	"custom_inside_measure_l",
	"custom_inside_measure_w",
	"custom_inside_measure_h",
	"custom_width",
	"custom_length",
	"custom_dc",
	"custom_board_quality",
	"custom_flute",
	"custom_remarks",
	"custom_weight",
]


class IIBBOMCreator(Document):
	def autoname(self):
		settings = frappe.get_single("IIB Settings")
		next_number = int(settings.master_card_next_number or 1)

		frappe.db.sql(
			"select value from `tabSingles` where doctype=%s for update",
			("IIB Settings",),
		)

		while frappe.db.exists("IIB BOM Creator", str(next_number)):
			next_number += 1

		frappe.db.set_single_value(
			"IIB Settings", "master_card_next_number", next_number + 1
		)
		self.name = str(next_number)

	def before_save(self):
		self._populate_defaults()
		self._ensure_fg_item()
		self._sync_sub_assembly_items()
		self._sync_rm_items()

	def validate(self):
		self._validate_components()

	def on_submit(self):
		self.enqueue_create_boms()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	# ------------------------------------------------------------------
	# Defaults
	# ------------------------------------------------------------------

	def _populate_defaults(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)

		if self.company and not self.currency:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")

		if not self.rm_cost_as_per:
			self.rm_cost_as_per = "Valuation Rate"

		settings = frappe.get_single("IIB Settings")

		if not self.fg_item_group:
			self.fg_item_group = getattr(settings, "fg_item_group", None) or "Master Card"

		if not self.sub_assembly_item_group:
			self.sub_assembly_item_group = (
				getattr(settings, "sub_assembly_item_group", None) or "Sub Assemblies"
			)

		if not self.default_uom:
			self.default_uom = getattr(settings, "default_uom", None) or "Nos"

	# ------------------------------------------------------------------
	# FG item
	# ------------------------------------------------------------------

	def _ensure_fg_item(self):
		if frappe.db.exists("Item", self.name):
			# Update description/customer if changed
			updates = {}
			if self.description:
				updates["item_name"] = self.description
			if self.customer:
				updates["linked_customer"] = self.customer
			if updates:
				frappe.db.set_value("Item", self.name, updates)
			self.item_code = self.name
			return

		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": self.name,
				"item_name": self.description or self.name,
				"item_group": self.fg_item_group,
				"stock_uom": self.default_uom or "Nos",
				"is_stock_item": 1,
				"include_item_in_manufacturing": 1,
				"linked_customer": self.customer or None,
			}
		)
		item.insert(ignore_permissions=True)
		self.item_code = self.name

	# ------------------------------------------------------------------
	# Sub-assembly items
	# ------------------------------------------------------------------

	def _validate_components(self):
		seen = set()
		for row in self.items:
			if not row.component:
				continue
			if len(row.component) != 1 or not row.component.isalpha():
				frappe.throw(
					_("Row {0}: Component must be a single letter A–Z.").format(row.idx)
				)
			letter = row.component.upper()
			if letter in seen:
				frappe.throw(
					_("Row {0}: Duplicate component letter '{1}'.").format(row.idx, letter)
				)
			seen.add(letter)

	def _sync_sub_assembly_items(self):
		customer = self.customer or None

		for row in self.items:
			if not row.component:
				frappe.throw(_("Row {0}: Component letter is required.").format(row.idx))

			letter = row.component.upper()
			row.component = letter
			row.item_code = self.name + letter
			row.item_name = row.item_code
			row.is_expandable = 1
			row.fg_reference_id = self.name

			spec = {f: row.get(f) for f in ITEM_SPEC_FIELDS}

			if frappe.db.exists("Item", row.item_code):
				# Update spec fields on existing item
				if any(v for v in spec.values()):
					frappe.db.set_value("Item", row.item_code, spec)
			else:
				item_doc = frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": row.item_code,
						"item_name": row.item_code,
						"item_group": self.sub_assembly_item_group,
						"stock_uom": row.uom or self.default_uom or "Nos",
						"is_stock_item": 1,
						"include_item_in_manufacturing": 1,
						"linked_customer": customer,
					}
				)
				for field, value in spec.items():
					if value:
						item_doc.set(field, value)
				item_doc.insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	# Raw material items
	# ------------------------------------------------------------------

	def _component_item_group(self):
		settings = frappe.get_single("IIB Settings")
		return getattr(settings, "component_item_group", None) or "Component"

	def _sync_rm_items(self):
		customer = self.customer or None
		existing_warnings = []

		for row in self.rm_items:
			if not row.item_code:
				frappe.throw(_("Row {0}: RM Item Code is required.").format(row.idx))

			if frappe.db.exists("Item", row.item_code):
				existing_warnings.append(row.item_code)
				# Fetch item_name if not set
				row.item_name = frappe.db.get_value("Item", row.item_code, "item_name") or row.item_name
			else:
				item_doc = frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": row.item_code,
						"item_name": row.item_name or row.item_code,
						"item_group": self._component_item_group(),
						"stock_uom": "Nos",
						"is_stock_item": 1,
						"include_item_in_manufacturing": 1,
						"default_material_request_type": row.default_material_request_type or "Purchase",
						"linked_customer": customer,
					}
				)
				item_doc.insert(ignore_permissions=True)
				row.item_name = item_doc.item_name

		if existing_warnings:
			frappe.msgprint(
				_("Items already exist — creation skipped: {0}").format(
					", ".join(existing_warnings)
				),
				title=_("Skipped Existing Items"),
				indicator="orange",
			)

	# ------------------------------------------------------------------
	# BOM creation
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def enqueue_create_boms(self):
		frappe.enqueue(
			self.create_boms,
			queue="short",
			timeout=600,
			is_async=True,
		)
		frappe.msgprint(
			_("BOMs creation has been enqueued, kindly check the status after some time"),
			alert=True,
		)

	def create_boms(self):
		self.db_set("status", "In Progress")

		try:
			# Build sub-assembly BOMs first (leaves), then FG BOM (root)
			for row in self.items:
				self._create_sub_assembly_bom(row)

			self._create_fg_bom()

			self.db_set("status", "Completed")
			frappe.msgprint(_("BOMs created successfully"))

		except Exception:
			traceback = frappe.get_traceback(with_context=True)
			self.db_set("status", "Failed")
			self.db_set("error_log", traceback)
			frappe.msgprint(_("BOMs creation failed"))

	def _create_sub_assembly_bom(self, row):
		if frappe.db.exists(
			"BOM",
			{"bom_creator": self.name, "item": row.item_code, "docstatus": 1},
		):
			return

		bom = frappe.new_doc("BOM")
		bom.update(
			{
				"item": row.item_code,
				"bom_type": "Production",
				"quantity": row.qty or 1,
				"bom_creator": self.name,
			}
		)

		for field in BOM_FIELDS:
			if self.get(field):
				bom.set(field, self.get(field))

		rm_rows = [r for r in self.rm_items if r.parent_sub_assembly == row.item_code]
		for rm in rm_rows:
			bom.append(
				"items",
				{
					"item_code": rm.item_code,
					"qty": rm.qty,
					"uom": "Nos",
					"stock_uom": "Nos",
					"do_not_explode": 1,
					"allow_scrap_items": 1,
					"include_item_in_manufacturing": 1,
				},
			)

		bom.save(ignore_permissions=True)
		bom.submit()

		frappe.db.set_value("IIB BOM Creator Item", row.name, "bom_no", bom.name)
		frappe.db.set_value("IIB BOM Creator Item", row.name, "bom_created", 1)

	def _create_fg_bom(self):
		if frappe.db.exists(
			"BOM",
			{"bom_creator": self.name, "item": self.item_code, "docstatus": 1},
		):
			return

		bom = frappe.new_doc("BOM")
		bom.update(
			{
				"item": self.item_code,
				"bom_type": "Production",
				"quantity": 1,
				"bom_creator": self.name,
			}
		)

		for field in BOM_FIELDS:
			if self.get(field):
				bom.set(field, self.get(field))

		for row in self.items:
			child_bom = frappe.db.get_value(
				"BOM",
				{"bom_creator": self.name, "item": row.item_code, "docstatus": 1},
				"name",
			)
			bom.append(
				"items",
				{
					"item_code": row.item_code,
					"qty": row.qty or 1,
					"uom": row.uom or self.default_uom or "Nos",
					"stock_uom": row.uom or self.default_uom or "Nos",
					"bom_no": child_bom or "",
					"do_not_explode": 0 if child_bom else 1,
					"allow_scrap_items": 1,
					"include_item_in_manufacturing": 1,
				},
			)

		bom.save(ignore_permissions=True)
		bom.submit()
