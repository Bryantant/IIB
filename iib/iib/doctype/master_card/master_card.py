# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

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
	"custom_basic_rate",
]


class MasterCard(Document):
	def autoname(self):
		settings = frappe.get_single("IIB Settings")
		next_number = int(settings.master_card_next_number or 1)

		# Lock the row for concurrency
		frappe.db.sql(
			"select value from `tabSingles` where doctype=%s for update",
			("IIB Settings",),
		)

		while frappe.db.exists("Master Card", str(next_number)):
			next_number += 1

		frappe.db.set_single_value(
			"IIB Settings", "master_card_next_number", next_number + 1
		)
		self.name = str(next_number)

	def before_save(self):
		self._populate_defaults()
		self._calculate_price_items()
		self._ensure_bundle_item()
		self._sync_fg_items()
		self._create_product_bundle()
		self._sync_disabled_to_item()

	def validate(self):
		self._validate_components()
		self._calculate_price_items()
		self._validate_price_items()
		self._validate_processes()

	# ------------------------------------------------------------------
	# Defaults
	# ------------------------------------------------------------------

	def _populate_defaults(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default(
				"Company"
			) or frappe.db.get_single_value("Global Defaults", "default_company")

		if not self.currency:
			self.currency = "SGD"

		if not self.rm_cost_as_per:
			self.rm_cost_as_per = "Valuation Rate"

		settings = frappe.get_single("IIB Settings")

		if not self.mc_bundle_item_group:
			self.mc_bundle_item_group = (
				getattr(settings, "mc_bundle_item_group", None) or "Master Card"
			)

		if not self.mc_fg_item_group:
			self.mc_fg_item_group = getattr(settings, "mc_fg_item_group", None) or "Sub Assemblies"

		if not self.component_item_group:
			self.component_item_group = (
				getattr(settings, "component_item_group", None) or "Component"
			)

		if not self.default_uom:
			self.default_uom = getattr(settings, "default_uom", None) or "Nos"

	# ------------------------------------------------------------------
	# Product Bundle parent item (non-stock)
	# ------------------------------------------------------------------

	def _ensure_bundle_item(self):
		if frappe.db.exists("Item", self.name):
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
				"item_group": self.mc_bundle_item_group,
				"stock_uom": self.default_uom or "Nos",
				"is_stock_item": 0,
				"is_sales_item": 1,
				"include_item_in_manufacturing": 0,
				"linked_customer": self.customer or None,
			}
		)
		item.insert(ignore_permissions=True)
		self.item_code = self.name

	# ------------------------------------------------------------------
	# Finish Good items
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

	def _validate_processes(self):
		valid_components = {row.component.upper() for row in self.items if row.component}
		seen = set()
		for row in self.processes or []:
			if not row.component:
				frappe.throw(_("Process row {0}: Component is required.").format(row.idx))
			letter = row.component.upper()
			if letter not in valid_components:
				frappe.throw(
					_("Process row {0}: Component '{1}' does not exist in Finish Goods.").format(
						row.idx, letter
					)
				)
			row.component = letter
			if not row.sequence or row.sequence <= 0:
				frappe.throw(_("Process row {0}: Sequence must be a positive integer.").format(row.idx))
			self._validate_process_section_group(row)
			key = (letter, row.sequence)
			if key in seen:
				frappe.throw(
					_("Process row {0}: Duplicate sequence {1} for component '{2}'.").format(
						row.idx, row.sequence, letter
					)
				)
			seen.add(key)

	def _calculate_price_items(self):
		for row in self.price_items or []:
			row.component = (row.component or "").upper().strip()
			row.total = (
				flt(row.material)
				+ flt(row.labour)
				+ flt(row.profit)
				+ flt(row.ext_profit)
			)

	def _validate_price_items(self):
		valid_components = {row.component.upper() for row in self.items if row.component}
		seen = set()
		for row in self.price_items or []:
			if not row.component:
				frappe.throw(_("Price row {0}: Component is required.").format(row.idx))

			component = row.component.upper().strip()
			row.component = component
			if component not in valid_components:
				frappe.throw(
					_("Price row {0}: Component '{1}' does not exist in Finish Goods.").format(
						row.idx, component
					)
				)

			key = (row.moq_idx, component)
			if key in seen:
				frappe.throw(
					_("Price row {0}: Duplicate component '{1}' in the same MOQ level.").format(
						row.idx, component
					)
				)
			seen.add(key)

	def _validate_process_section_group(self, row):
		if not row.section:
			frappe.throw(_("Process row {0}: Section Group is required.").format(row.idx))

		section = frappe.db.get_value(
			"IIB Production Section",
			row.section,
			["is_group", "disabled"],
			as_dict=True,
		)
		if not section:
			frappe.throw(_("Process row {0}: Section Group {1} does not exist.").format(row.idx, row.section))
		if section.disabled or not section.is_group:
			frappe.throw(
				_("Process row {0}: Section Group must be an enabled group section.").format(
					row.idx
				)
			)

	def _sync_fg_items(self):
		customer = self.customer or None

		for row in self.items:
			if not row.component:
				frappe.throw(_("Row {0}: Component letter is required.").format(row.idx))

			letter = row.component.upper()
			row.component = letter
			row.item_code = self.name + letter
			row.item_name = row.item_description or row.item_code

			spec = {f: row.get(f) for f in ITEM_SPEC_FIELDS}

			if frappe.db.exists("Item", row.item_code):
				updates = {f: v for f, v in spec.items() if v}
				if row.item_description:
					updates["item_name"] = row.item_description
				if row.uom:
					updates["stock_uom"] = row.uom
					self._ensure_item_uom(row.item_code, row.uom)
				if updates:
					frappe.db.set_value("Item", row.item_code, updates)
			else:
				item_doc = frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": row.item_code,
						"item_name": row.item_description or row.item_code,
						"item_group": self.mc_fg_item_group,
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

	def _ensure_item_uom(self, item_code, uom):
		"""Insert a UOM Conversion Detail row for this UOM if one doesn't already exist."""
		if frappe.db.exists("UOM Conversion Detail", {"parent": item_code, "uom": uom}):
			return
		next_idx = (
			frappe.db.count("UOM Conversion Detail", {"parent": item_code}) or 0
		) + 1
		uom_row = frappe.new_doc("UOM Conversion Detail")
		uom_row.parent = item_code
		uom_row.parenttype = "Item"
		uom_row.parentfield = "uoms"
		uom_row.uom = uom
		uom_row.conversion_factor = 1.0
		uom_row.idx = next_idx
		uom_row.db_insert()

	# ------------------------------------------------------------------
	# Product Bundle
	# ------------------------------------------------------------------

	def _create_product_bundle(self):
		if not self.item_code:
			return

		if frappe.db.exists("Product Bundle", self.item_code):
			pb = frappe.get_doc("Product Bundle", self.item_code)
			pb.items = []
		else:
			pb = frappe.new_doc("Product Bundle")
			pb.new_item_code = self.item_code
			pb.description = self.description or ""

		for row in self.items:
			if row.item_code:
				pb.append(
					"items",
					{
						"item_code": row.item_code,
						"qty": row.qty or 1,
						"description": row.item_description or "",
						"uom": row.uom or self.default_uom or "Nos",
					},
				)

		pb.save(ignore_permissions=True)

	# ------------------------------------------------------------------
	# Disabled sync
	# ------------------------------------------------------------------

	def _sync_disabled_to_item(self):
		disabled_val = int(self.disabled or 0)
		# Disable/enable the bundle item (non-stock parent)
		if self.item_code and frappe.db.exists("Item", self.item_code):
			frappe.db.set_value("Item", self.item_code, "disabled", disabled_val)
		# Disable/enable the Product Bundle record itself
		if self.item_code and frappe.db.exists("Product Bundle", self.item_code):
			frappe.db.set_value("Product Bundle", self.item_code, "disabled", disabled_val)
		# Disable/enable all FG items
		for row in self.items:
			if row.item_code and frappe.db.exists("Item", row.item_code):
				frappe.db.set_value("Item", row.item_code, "disabled", disabled_val)

	# ------------------------------------------------------------------
	# New Version
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def create_new_version(self):
		new_doc = frappe.copy_doc(self)
		new_doc.insert(ignore_permissions=True)
		return new_doc.name
