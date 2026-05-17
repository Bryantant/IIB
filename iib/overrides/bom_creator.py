from collections import OrderedDict

import frappe
from frappe import _
from erpnext.manufacturing.doctype.bom_creator.bom_creator import (
	BOM_FIELDS,
	BOM_ITEM_FIELDS,
	BOMCreator,
	get_item_details,
	get_parent_row_no,
)

BRANCH_FIELD = "custom_iib_branch"


def get_branch(value):
	return (value or "").strip()


def has_branch_field(doctype):
	return frappe.get_meta(doctype).has_field(BRANCH_FIELD)


class BOMCreatorExtended(BOMCreator):
	def create_boms(self):
		self.db_set("status", "In Progress")

		branches = self.get_branch_variants()
		production_item_wise_rm = OrderedDict()

		for branch in branches:
			production_item_wise_rm.setdefault(
				(self.item_code, self.name, branch),
				frappe._dict({"items": [], "bom_no": "", "fg_item_data": self}),
			)

		for row in self.items:
			if not row.fg_reference_id and production_item_wise_rm.get((row.fg_item, row.fg_reference_id, "")):
				frappe.throw(_("Please set Parent Row No for item {0}").format(row.fg_item))

			row_branches = self.get_row_branches(row, branches)

			if row.is_expandable:
				for branch in row_branches:
					production_item_wise_rm.setdefault(
						(row.item_code, row.name, branch),
						frappe._dict({"items": [], "bom_no": "", "fg_item_data": row}),
					)

			for branch in row_branches:
				key = (row.fg_item, row.fg_reference_id, branch)
				production_item_wise_rm.setdefault(
					key,
					frappe._dict({"items": [], "bom_no": "", "fg_item_data": row}),
				)
				production_item_wise_rm[key]["items"].append(row)

		reverse_tree = OrderedDict(reversed(list(production_item_wise_rm.items())))

		try:
			for key in reverse_tree:
				fg_item_data = production_item_wise_rm.get(key).fg_item_data
				self.create_bom(fg_item_data, production_item_wise_rm, key[2])

			frappe.msgprint(_("BOMs created successfully"))
		except Exception:
			traceback = frappe.get_traceback(with_context=True)
			self.db_set(
				{
					"status": "Failed",
					"error_log": traceback,
				}
			)

			frappe.msgprint(_("BOMs creation failed"))

	def get_branch_variants(self):
		branches = sorted(
			{
				get_branch(row.get(BRANCH_FIELD))
				for row in self.items
				if get_branch(row.get(BRANCH_FIELD))
			}
		)
		return branches or [""]

	def get_row_branches(self, row, branches):
		branch = get_branch(row.get(BRANCH_FIELD))
		return [branch] if branch else branches

	def get_existing_bom(self, row, branch):
		# row = self (BOM Creator doc) for the root item
		# row = BOM Creator Item child row for sub-assemblies
		bom_creator_item = row.name if row.name != self.name else ""

		filters = {
			"bom_creator": self.name,
			"item": row.item_code,
			"bom_creator_item": bom_creator_item,
			"docstatus": 1,
		}

		if has_branch_field("BOM"):
			filters[BRANCH_FIELD] = branch if branch else ("in", ["", None])

		return frappe.db.exists("BOM", filters)

	def create_bom(self, row, production_item_wise_rm, branch=""):
		# row = self (BOM Creator doc) for the root item
		# row = BOM Creator Item child row for sub-assemblies
		bom_creator_item = row.name if row.name != self.name else ""
		key = (row.item_code, row.name, branch)

		existing_bom = self.get_existing_bom(row, branch)
		if existing_bom:
			production_item_wise_rm[key].bom_no = existing_bom
			return

		bom = frappe.new_doc("BOM")
		bom.update(
			{
				"item": row.item_code,
				"bom_type": "Production",
				"quantity": row.qty,
				"bom_creator": self.name,
				"bom_creator_item": bom_creator_item,
			}
		)

		if has_branch_field("BOM"):
			bom.set(BRANCH_FIELD, branch)

		for field in BOM_FIELDS:
			if self.get(field):
				bom.set(field, self.get(field))

		# Per-item routing injection — set before bom.save() so that
		# bom.validate() → set_routing_operations() → get_routing()
		# auto-populates the operations table from the Routing master.
		routing = row.get("routing")
		if routing:
			bom.with_operations = 1
			bom.routing = routing

		for item in production_item_wise_rm[key]["items"]:
			bom_no = ""
			item.do_not_explode = 1
			item_key = (item.item_code, item.name, branch)
			if item_key in production_item_wise_rm:
				bom_no = production_item_wise_rm.get(item_key).bom_no
				item.do_not_explode = 0

			item_args = {}
			for field in BOM_ITEM_FIELDS:
				item_args[field] = item.get(field)

			item_args.update(
				{
					"bom_no": bom_no,
					"allow_scrap_items": 1,
					"include_item_in_manufacturing": 1,
				}
			)
			bom.append("items", item_args)

		bom.save(ignore_permissions=True)
		bom.submit()
		production_item_wise_rm[key].bom_no = bom.name


@frappe.whitelist()
def add_sub_assembly(**kwargs):
	if isinstance(kwargs, str):
		kwargs = frappe.parse_json(kwargs)

	if isinstance(kwargs, dict):
		kwargs = frappe._dict(kwargs)

	doc = frappe.get_doc("BOM Creator", kwargs.parent)
	bom_item = frappe.parse_json(kwargs.bom_item)

	name = kwargs.fg_reference_id
	parent_row_no = ""
	if not kwargs.convert_to_sub_assembly:
		item_info = get_item_details(bom_item.item_code)
		parent_row_no = get_parent_row_no(doc, kwargs.fg_reference_id)

		item_row = doc.append(
			"items",
			{
				"item_code": bom_item.item_code,
				"qty": bom_item.qty,
				"uom": item_info.stock_uom,
				"fg_item": kwargs.fg_item,
				"conversion_factor": 1,
				"parent_row_no": parent_row_no,
				"fg_reference_id": name,
				"stock_qty": bom_item.qty,
				"do_not_explode": 1,
				"is_expandable": 1,
				"stock_uom": item_info.stock_uom,
				"allow_alternative_item": kwargs.allow_alternative_item,
				BRANCH_FIELD: get_branch(bom_item.get(BRANCH_FIELD)),
			},
		)

		parent_row_no = item_row.idx
		name = ""
	else:
		parent_row_no = get_parent_row_no(doc, kwargs.fg_reference_id)

	for row in bom_item.get("items"):
		row = frappe._dict(row)
		if row.get("default_material_request_type"):
			frappe.db.set_value(
				"Item",
				row.item_code,
				"default_material_request_type",
				row.default_material_request_type,
			)

		item_info = get_item_details(row.item_code)
		doc.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": row.qty,
				"fg_item": bom_item.item_code,
				"uom": item_info.stock_uom,
				"fg_reference_id": name,
				"parent_row_no": parent_row_no,
				"conversion_factor": 1,
				"do_not_explode": 1,
				"stock_qty": row.qty,
				"stock_uom": item_info.stock_uom,
				"allow_alternative_item": row.get("allow_alternative_item", 1),
				BRANCH_FIELD: get_branch(row.get(BRANCH_FIELD)),
			},
		)

	doc.save()

	return doc


@frappe.whitelist()
def create_master_card_bom_creator(customer, item_name):
	customer = (customer or "").strip()
	item_name = (item_name or "").strip()

	if not customer:
		frappe.throw(_("Customer is required."))

	if not item_name:
		frappe.throw(_("Item Name is required."))

	settings = frappe.get_single("IIB Naming Settings")
	next_number = settings.master_card_next_number

	if not next_number or next_number < 1:
		frappe.throw(_("Set Master Card Next Number in IIB Naming Settings."))

	frappe.db.sql("select value from `tabSingles` where doctype=%s for update", (settings.doctype,))

	item_number = int(next_number)
	while frappe.db.exists("Item", str(item_number)):
		item_number += 1

	item_code = str(item_number)
	frappe.db.set_single_value("IIB Naming Settings", "master_card_next_number", item_number + 1)

	try:
		item_doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_name,
				"item_group": "Master Card",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"include_item_in_manufacturing": 1,
				"linked_customer": customer,
			}
		)
		item_doc.insert(ignore_permissions=True)

		bom_creator = frappe.get_doc(
			{
				"doctype": "BOM Creator",
				"item_code": item_doc.name,
				"company": frappe.defaults.get_user_default("Company"),
				"qty": 1.0,
				"currency": frappe.defaults.get_global_default("currency"),
				"conversion_rate": 1.0,
			}
		)
		bom_creator.insert(ignore_permissions=True)
	except Exception:
		frappe.db.set_single_value("IIB Naming Settings", "master_card_next_number", next_number)
		raise

	return {"item": item_doc.name, "bom_creator": bom_creator.name}
