import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from iib.iib.utils.tolerance import lookup_tolerance


SO_ITEM_WIP_FIELD = "custom_wip_quantity"
SO_LINE_DOCTYPES = ("Packed Item", "Sales Order Item")


def has_wip_field(doctype):
	return frappe.db.has_column(doctype, SO_ITEM_WIP_FIELD)


def get_so_line_doctype(sales_order_item):
	if not sales_order_item:
		return None
	for doctype in SO_LINE_DOCTYPES:
		if frappe.db.exists(doctype, sales_order_item):
			return doctype
	return None


def get_so_line_details(sales_order_item):
	"""Return normalized Sales Order allocation details.

	`sales_order_item` may be either a Packed Item row (new P2 flow) or a
	Sales Order Item row (legacy/direct fallback).
	"""
	doctype = get_so_line_doctype(sales_order_item)
	if doctype == "Packed Item":
		rows = frappe.db.sql(
			"""
			SELECT
				pi.name,
				'Packed Item' AS doctype,
				pi.parent AS sales_order,
				pi.parent_detail_docname AS parent_sales_order_item,
				pi.item_code,
				pi.item_name,
				pi.description,
				pi.uom,
				pi.qty,
				IFNULL(pi.{wip_field}, 0) AS wip_quantity,
				soi.delivery_date,
				IFNULL(soi.qty, 0) AS parent_qty,
				IFNULL(soi.delivered_qty, 0) AS parent_delivered_qty,
				so.customer,
				so.status AS so_status,
				so.docstatus AS so_docstatus
			FROM `tabPacked Item` pi
			JOIN `tabSales Order Item` soi ON soi.name = pi.parent_detail_docname
			JOIN `tabSales Order` so ON so.name = pi.parent
			WHERE pi.name = %(sales_order_item)s
			""".format(wip_field=SO_ITEM_WIP_FIELD)
			if has_wip_field("Packed Item")
			else """
			SELECT
				pi.name,
				'Packed Item' AS doctype,
				pi.parent AS sales_order,
				pi.parent_detail_docname AS parent_sales_order_item,
				pi.item_code,
				pi.item_name,
				pi.description,
				pi.uom,
				pi.qty,
				0 AS wip_quantity,
				soi.delivery_date,
				IFNULL(soi.qty, 0) AS parent_qty,
				IFNULL(soi.delivered_qty, 0) AS parent_delivered_qty,
				so.customer,
				so.status AS so_status,
				so.docstatus AS so_docstatus
			FROM `tabPacked Item` pi
			JOIN `tabSales Order Item` soi ON soi.name = pi.parent_detail_docname
			JOIN `tabSales Order` so ON so.name = pi.parent
			WHERE pi.name = %(sales_order_item)s
			""",
			{"sales_order_item": sales_order_item},
			as_dict=True,
		)
		if not rows:
			return None
		row = rows[0]
		parent_qty = flt(row.parent_qty)
		parent_delivered = flt(row.parent_delivered_qty)
		row.delivered_qty = flt(row.qty) * (parent_delivered / parent_qty) if parent_qty else 0
		return row

	rows = frappe.db.sql(
		"""
		SELECT
			soi.name,
			'Sales Order Item' AS doctype,
			soi.parent AS sales_order,
			soi.name AS parent_sales_order_item,
			soi.item_code,
			soi.item_name,
			soi.description,
			soi.uom,
			soi.qty,
			IFNULL(soi.delivered_qty, 0) AS delivered_qty,
			{wip_expr} AS wip_quantity,
			soi.delivery_date,
			so.customer,
			so.status AS so_status,
			so.docstatus AS so_docstatus
		FROM `tabSales Order Item` soi
		JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE soi.name = %(sales_order_item)s
		""".format(
			wip_expr=f"IFNULL(soi.{SO_ITEM_WIP_FIELD}, 0)"
			if has_wip_field("Sales Order Item")
			else "0"
		),
		{"sales_order_item": sales_order_item},
		as_dict=True,
	)
	return rows[0] if rows else None


def get_live_so_item_wip_qty(sales_order_item, exclude_job_order=None):
	if not sales_order_item:
		return 0

	conditions = [
		"josi.parenttype = 'Job Order Converting'",
		"josi.sales_order_item = %(sales_order_item)s",
		"converting.docstatus = 1",
	]
	values = {"sales_order_item": sales_order_item}
	if exclude_job_order:
		conditions.append("converting.name != %(exclude_job_order)s")
		values["exclude_job_order"] = exclude_job_order

	return flt(
		frappe.db.sql(
			f"""
			SELECT IFNULL(SUM(josi.qty), 0)
			FROM `tabJob Order Converting Sales Order Item` josi
			JOIN `tabJob Order Converting` converting ON converting.name = josi.parent
			WHERE {" AND ".join(conditions)}
			""",
			values,
		)[0][0]
	)


def get_job_order_so_item_qty(job_order, sales_order_item):
	if not job_order or not sales_order_item:
		return 0
	return flt(
		frappe.db.sql(
			"""
			SELECT IFNULL(SUM(qty), 0)
			FROM `tabJob Order Converting Sales Order Item`
			WHERE parenttype = 'Job Order Converting'
			  AND parent = %(job_order)s
			  AND sales_order_item = %(sales_order_item)s
			""",
			{"job_order": job_order, "sales_order_item": sales_order_item},
		)[0][0]
	)


def get_so_item_wip_qty(sales_order_item, exclude_job_order=None):
	if not sales_order_item:
		return 0
	doctype = get_so_line_doctype(sales_order_item)
	if not doctype or not has_wip_field(doctype):
		return get_live_so_item_wip_qty(sales_order_item, exclude_job_order)

	wip_qty = flt(
		frappe.db.get_value(doctype, sales_order_item, SO_ITEM_WIP_FIELD)
	)
	if exclude_job_order:
		wip_qty -= get_job_order_so_item_qty(exclude_job_order, sales_order_item)
	return max(wip_qty, 0)


def get_so_item_available_qty(sales_order_item, exclude_job_order=None):
	so_item = get_so_line_details(sales_order_item)
	if not so_item:
		return 0
	return max(
		flt(so_item.qty)
		- flt(so_item.delivered_qty)
		- get_so_item_wip_qty(sales_order_item, exclude_job_order),
		0,
	)


def sync_so_item_wip_quantities(sales_order_items, exclude_job_order=None):
	for sales_order_item in sorted({d for d in sales_order_items if d}):
		doctype = get_so_line_doctype(sales_order_item)
		if not doctype or not has_wip_field(doctype):
			continue
		frappe.db.set_value(
			doctype,
			sales_order_item,
			SO_ITEM_WIP_FIELD,
			get_live_so_item_wip_qty(sales_order_item, exclude_job_order),
			update_modified=False,
		)


def is_blank_so_item_row(row):
	return not any(
		[
			row.sales_order,
			row.sales_order_item,
			row.item_code,
			row.delivery_date,
			row.customer,
			row.so_status,
			flt(row.qty),
		]
	)


def get_master_card_operations_for_item(production_item, master_card=None):
	if not production_item:
		return {"master_card": master_card or "", "operations": []}

	master_card = master_card or frappe.db.get_value(
		"Master Card Item", {"item_code": production_item}, "parent"
	)
	if not master_card:
		return {"master_card": "", "operations": []}

	mc = frappe.get_cached_doc("Master Card", master_card)
	component_letter = None
	for row in mc.items:
		if row.item_code == production_item:
			component_letter = (row.component or "").upper()
			break
	if not component_letter:
		return {"master_card": master_card, "operations": []}

	processes = sorted(
		[p for p in (mc.processes or []) if (p.component or "").upper() == component_letter],
		key=lambda p: p.sequence,
	)
	return {
		"master_card": master_card,
		"operations": [
			{
				"sequence": p.sequence,
				"section": p.section,
				"production_section": "",
				"est_time_mins": p.est_time_mins,
				"description": p.description,
				"status": "Pending",
				"completed_qty": 0,
			}
			for p in processes
		],
	}


class JobOrderConverting(Document):
	def autoname(self):
		from iib.iib.utils.naming import get_next_iib_number

		seq = get_next_iib_number("jop2", period=None, digits=4)
		self.name = f"JO{seq}"

	def before_validate(self):
		self.set(
			"sales_order_items",
			[row for row in (self.sales_order_items or []) if not is_blank_so_item_row(row)],
		)
		# Reset operations if production_item changed
		if not self.is_new() and self.has_value_changed("production_item"):
			self.operations = []

	def validate(self):
		self.fetch_item_metadata()
		self.resolve_master_card()
		self.set_warehouse_defaults()
		self.validate_so_items_match_production_item()
		self.validate_so_item_quantities()
		self.resolve_operations_from_master_card()
		self.validate_operation_section_groups()
		self.validate_operation_production_sections(require_section=False)
		self.compute_rollup_fields()
		if self.docstatus == 0 and not self.status:
			self.status = "Draft"

	def before_save(self):
		self.flags.previous_so_item_refs = self.get_previous_so_item_refs()

	def before_submit(self):
		# NOTE: operations are optional — no validate_operations_exist() call
		# NOTE: production_section is intentionally NOT required here — it is filled
		#       later by the Production Process doctype when work is assigned.
		self.validate_so_items_exist()
		self.validate_operation_production_sections(require_section=False)
		self.validate_converting_tolerance()

	def on_submit(self):
		self.db_set("status", "Not Started")
		self.sync_current_so_item_wip_quantities()

	def before_cancel(self):
		self.guard_against_submitted_movement_docs()

	def on_cancel(self):
		self.cancel_draft_rm_to_wip()
		self.db_set("status", "Cancelled")
		self.sync_current_so_item_wip_quantities(exclude_self=True)

	def on_trash(self):
		self.sync_current_so_item_wip_quantities(exclude_self=True)

	# ---- validation helpers ----

	def get_current_so_item_refs(self):
		return {
			row.sales_order_item
			for row in (self.sales_order_items or [])
			if row.sales_order_item
		}

	def get_previous_so_item_refs(self):
		if self.is_new():
			return set()
		previous = self.get_doc_before_save()
		if not previous:
			return set()
		return {
			row.sales_order_item
			for row in (previous.sales_order_items or [])
			if row.sales_order_item
		}

	def sync_current_so_item_wip_quantities(self, exclude_self=False):
		refs = set(self.get_current_so_item_refs())
		refs.update(getattr(self.flags, "previous_so_item_refs", set()) or set())
		sync_so_item_wip_quantities(
			refs,
			exclude_job_order=self.name if exclude_self else None,
		)

	def fetch_item_metadata(self):
		if not self.production_item:
			return
		item = frappe.db.get_value(
			"Item", self.production_item, ["item_name", "description"], as_dict=True
		)
		if item:
			self.item_name = item.item_name
			if not self.description:
				self.description = item.description

	def resolve_master_card(self):
		"""Auto-resolve master_card from production_item via Master Card Item."""
		if not self.production_item:
			return
		parent = frappe.db.get_value(
			"Master Card Item", {"item_code": self.production_item}, "parent"
		)
		if parent:
			self.master_card = parent

	def set_warehouse_defaults(self):
		"""Default WIP/FG warehouses from IIB Settings if not already set."""
		settings = frappe.get_cached_doc("IIB Settings")
		if not self.wip_warehouse:
			self.wip_warehouse = settings.default_wip_warehouse
		if not self.fg_warehouse:
			self.fg_warehouse = settings.default_fg_warehouse

	def validate_so_items_match_production_item(self):
		"""Every sales_order_items row must reference the same production_item."""
		if not self.production_item or not self.sales_order_items:
			return
		mismatched = [
			row.sales_order_item or row.sales_order
			for row in self.sales_order_items
			if row.item_code and row.item_code != self.production_item
		]
		if mismatched:
			frappe.throw(
				_("Sales Order Item rows reference different items than MC Component {0}: {1}").format(
					self.production_item, ", ".join(mismatched)
				)
			)

	def validate_so_item_quantities(self):
		if not self.sales_order_items:
			return

		requested_by_so_item = {}
		for row in self.sales_order_items:
			if not row.sales_order_item:
				frappe.throw(_("Sales Order Item is required in row {0}").format(row.idx))
			if flt(row.qty) <= 0:
				frappe.throw(_("Sales Order Item row {0}: Qty must be positive").format(row.idx))

			so_item = get_so_line_details(row.sales_order_item)
			if not so_item:
				frappe.throw(
					_("Sales Order Item {0} does not exist").format(row.sales_order_item)
				)
			if so_item.so_docstatus != 1 or so_item.so_status in (
				"Stopped",
				"Closed",
				"Cancelled",
			):
				frappe.throw(
					_("Sales Order {0} is not open for Job Order Converting allocation").format(
						so_item.sales_order
					)
				)
			if row.sales_order and row.sales_order != so_item.sales_order:
				frappe.throw(
					_("Row {0}: Sales Order does not match Sales Order Item {1}").format(
						row.idx, row.sales_order_item
					)
				)
			if self.production_item and so_item.item_code != self.production_item:
				frappe.throw(
					_("Row {0}: Sales Order Item {1} is for item {2}, not {3}").format(
						row.idx,
						row.sales_order_item,
						so_item.item_code,
						self.production_item,
					)
				)

			row.sales_order = so_item.sales_order
			row.item_code = so_item.item_code
			row.delivery_date = so_item.delivery_date
			row.customer = so_item.customer
			row.so_status = so_item.so_status

			requested_by_so_item[row.sales_order_item] = (
				requested_by_so_item.get(row.sales_order_item, 0) + flt(row.qty)
			)

		exclude_job_order = self.name if self.name and not self.is_new() else None
		for sales_order_item, requested_qty in requested_by_so_item.items():
			available_qty = get_so_item_available_qty(sales_order_item, exclude_job_order)
			if requested_qty > available_qty + 0.0001:
				frappe.throw(
					_(
						"Sales Order Item {0}: requested qty {1} exceeds remaining available qty {2}"
					).format(sales_order_item, requested_qty, available_qty)
				)

	def validate_so_items_exist(self):
		if not self.sales_order_items:
			frappe.throw(
				_("At least one Sales Order Item is required before submitting Job Order Converting")
			)

	def validate_converting_tolerance(self):
		"""Block submit if any SO Item / Packed Item row would be over-ordered.

		Mirrors JOP1's `validate_corrugator_tolerance` exactly — reads the tiered
		`IIB Settings Converting Tolerance` table and compares
		``prev_custom_wip_quantity + this_converting_qty`` against
		``so_qty + tolerance`` per Sales Order line.

		`custom_wip_quantity` already excludes drafts (submitted-only
		semantics) so the comparison correctly counts only past, locked-in
		allocations plus this draft's own qty.
		"""
		tolerance_rows = frappe.get_all(
			"IIB Settings Converting Tolerance",
			filters={"parent": "IIB Settings", "parenttype": "IIB Settings"},
			fields=["converting_qty", "converting_toleransi"],
			order_by="converting_qty asc",
		)
		if not tolerance_rows:
			return  # No table configured — allow any qty

		# Group current JO P2 qty per sales_order_item (Packed Item row name)
		current_qty_map: dict = {}
		for row in self.sales_order_items or []:
			if not row.sales_order_item:
				continue
			current_qty_map[row.sales_order_item] = (
				flt(current_qty_map.get(row.sales_order_item, 0)) + flt(row.qty)
			)

		for so_item_name, current_qty in current_qty_map.items():
			so_line = get_so_line_details(so_item_name)
			if not so_line:
				continue

			so_qty = flt(so_line.qty)
			# `custom_wip_quantity` is submitted-only post-refactor.
			prev_converting_qty = flt(get_so_item_wip_qty(so_item_name, exclude_job_order=self.name))
			total_qty = prev_converting_qty + current_qty

			tolerance = lookup_tolerance(
				tolerance_rows, so_qty, "converting_qty", "converting_toleransi"
			)

			if total_qty > so_qty + tolerance:
				frappe.throw(
					_(
						"SO Item {0} (item {1}): total JO P2 qty {2} exceeds SO qty {3} + tolerance {4} = {5}."
					).format(
						frappe.bold(so_item_name),
						frappe.bold(so_line.item_code),
						frappe.bold(flt(total_qty, 3)),
						so_qty,
						tolerance,
						frappe.bold(so_qty + tolerance),
					)
				)

	def validate_operation_section_groups(self):
		for row in self.operations or []:
			if not row.section:
				frappe.throw(_("Operation row {0}: Section Group is required").format(row.idx))
			section = frappe.db.get_value(
				"IIB Production Section",
				row.section,
				["is_group", "disabled"],
				as_dict=True,
			)
			if not section:
				frappe.throw(
					_("Operation row {0}: Section Group {1} does not exist").format(
						row.idx, row.section
					)
				)
			if section.disabled or not section.is_group:
				frappe.throw(
					_("Operation row {0}: Section Group must be an enabled group section").format(
						row.idx
					)
				)

	def validate_operation_production_sections(self, require_section=True):
		for row in self.operations or []:
			if not row.production_section:
				if require_section:
					frappe.throw(
						_(
							"Operation row {0}: Production Section is required before submitting Job Order Converting"
						).format(row.idx)
					)
				continue

			section = frappe.db.get_value(
				"IIB Production Section",
				row.production_section,
				["is_group", "disabled", "lft", "rgt"],
				as_dict=True,
			)
			if not section:
				frappe.throw(
					_("Operation row {0}: Production Section {1} does not exist").format(
						row.idx, row.production_section
					)
				)
			if section.disabled or section.is_group:
				frappe.throw(
					_("Operation row {0}: Production Section must be an enabled detail section").format(
						row.idx
					)
				)

			if not row.section:
				continue
			group = frappe.db.get_value(
				"IIB Production Section",
				row.section,
				["is_group", "disabled", "lft", "rgt"],
				as_dict=True,
			)
			if not group:
				frappe.throw(
					_("Operation row {0}: Section Group {1} does not exist").format(
						row.idx, row.section
					)
				)
			if group.disabled or not group.is_group:
				frappe.throw(
					_("Operation row {0}: Section Group must be an enabled group section").format(
						row.idx
					)
				)
			if not (section.lft > group.lft and section.rgt < group.rgt):
				frappe.throw(
					_("Operation row {0}: Production Section {1} must be under Section Group {2}").format(
						row.idx, row.production_section, row.section
					)
				)

	def validate_operations_exist(self):
		if not self.operations:
			frappe.throw(
				_(
					"No operations defined. Set Master Card with Processes for item {0}, "
					"or add operation rows manually."
				).format(self.production_item)
			)

	def resolve_operations_from_master_card(self):
		"""Seed operations table from Master Card Process rows for the production item."""
		if self.operations:
			return
		if not self.production_item:
			return
		data = get_master_card_operations_for_item(self.production_item, self.master_card)
		if data.get("master_card"):
			self.master_card = data["master_card"]
		for row in data.get("operations") or []:
			self.append("operations", row)

	# ---- Read-only rollup fields ----

	def compute_rollup_fields(self):
		self.total_so_qty = sum(flt(row.qty) for row in (self.sales_order_items or []))
		self.delivered_qty = self._compute_delivered_qty()
		self.closed_qty = self._compute_closed_qty()
		self.jo_qty_in_process = max(flt(self.qty) - flt(self.produced_qty), 0)
		self.oh_qty = self._compute_oh_qty()

	def _compute_delivered_qty(self):
		if not self.sales_order_items:
			return 0
		total = 0
		for row in self.sales_order_items:
			line = get_so_line_details(row.sales_order_item)
			if line:
				total += min(flt(row.qty), flt(line.delivered_qty))
		return flt(total)

	def _compute_closed_qty(self):
		if not self.sales_order_items:
			return 0
		total = 0
		for row in self.sales_order_items:
			if not row.sales_order:
				continue
			so_status = frappe.db.get_value("Sales Order", row.sales_order, "status")
			if so_status == "Closed":
				total += flt(row.qty)
		return total

	def _compute_oh_qty(self):
		if not self.production_item:
			return 0
		settings = frappe.get_cached_doc("IIB Settings")
		warehouse = settings.default_raw_material_warehouse
		if not warehouse:
			return 0
		qty = frappe.db.get_value(
			"Bin", {"item_code": self.production_item, "warehouse": warehouse}, "actual_qty"
		)
		return flt(qty)

	# ---- RM to WIP doc creation (on submit) ----

	def create_rm_to_wip_doc(self):
		"""On submit: create a draft Job Order Converting RM to WIP document for review."""
		settings = frappe.get_cached_doc("IIB Settings")
		source = settings.default_raw_material_warehouse
		if not source:
			frappe.throw(
				_("Set Raw Material Warehouse in IIB Settings before submitting Job Order Converting")
			)
		if not self.wip_warehouse:
			frappe.throw(_("WIP Warehouse not set"))
		if flt(self.qty) <= 0:
			frappe.throw(_("Qty to Convert must be greater than 0"))

		item_data = frappe.db.get_value(
			"Item", self.production_item, ["stock_uom", "valuation_rate"], as_dict=True
		) or {}
		stock_uom = item_data.get("stock_uom") or ""
		basic_rate = flt(item_data.get("valuation_rate") or 0)

		doc = frappe.new_doc("Job Order Converting RM to WIP")
		doc.company = self.company
		doc.posting_date = self.posting_date or nowdate()
		doc.job_order_converting = self.name
		doc.source_warehouse = source
		doc.target_warehouse = self.wip_warehouse
		doc.append(
			"items",
			{
				"item_code": self.production_item,
				"qty": flt(self.qty),
				"uom": stock_uom,
				"basic_rate": basic_rate,
			},
		)
		doc.insert(ignore_permissions=True)
		self.db_set("transfer_rm_doc", doc.name)

	# ---- cancel guards ----

	def guard_against_submitted_movement_docs(self):
		"""Block cancel if any submitted RM to WIP or WIP to FG docs exist."""
		rm_to_wip = frappe.db.get_value(
			"Job Order Converting RM to WIP",
			{"job_order_converting": self.name, "docstatus": 1},
			"name",
		)
		if rm_to_wip:
			frappe.throw(
				_(
					"Cannot cancel: submitted Job Order Converting RM to WIP {0} exists. "
					"Cancel it first."
				).format(frappe.bold(rm_to_wip))
			)
		wip_to_fg = frappe.db.get_all(
			"Job Order Converting WIP to FG",
			filters={"job_order_converting": self.name, "docstatus": 1},
			fields=["name"],
		)
		if wip_to_fg:
			names = [r.name for r in wip_to_fg]
			frappe.throw(
				_(
					"Cannot cancel: submitted Job Order Converting WIP to FG exist: {0}. "
					"Cancel them first."
				).format(", ".join(names))
			)

	def cancel_draft_rm_to_wip(self):
		"""Delete draft RM to WIP doc when cancelling JO P2 (submitted ones blocked by guard)."""
		if not self.transfer_rm_doc:
			return
		try:
			docstatus = frappe.db.get_value(
				"Job Order Converting RM to WIP", self.transfer_rm_doc, "docstatus"
			)
			if docstatus == 0:
				frappe.delete_doc(
					"Job Order Converting RM to WIP",
					self.transfer_rm_doc,
					ignore_permissions=True,
					force=True,
				)
		except Exception:
			pass

	def _refresh_header_status(self):
		if self.docstatus != 1 or self.status in ("Cancelled", "Stopped", "Closed"):
			return
		if not self.operations:
			# No operations — status is driven by produced_qty / movement docs, not ops
			return
		statuses = [op.status for op in self.operations]
		if all(s == "Completed" for s in statuses):
			new = "Completed"
		elif any(s in ("In Progress", "Completed") for s in statuses):
			new = "In Process"
		else:
			new = "Not Started"
		if new != self.status:
			self.db_set("status", new)

	def get_status(self):
		"""Compute status from produced_qty and movement docs. Does not override terminal states."""
		if self.status in ("Stopped", "Closed", "Cancelled"):
			return self.status
		if self.docstatus == 0:
			return "Draft"
		if self.docstatus == 2:
			return "Cancelled"
		# Submitted — check production progress
		if flt(self.qty) > 0 and flt(self.produced_qty) >= flt(self.qty):
			return "Completed"
		# In Process if RM has been transferred to WIP
		if frappe.db.exists(
			"Job Order Converting RM to WIP", {"job_order_converting": self.name, "docstatus": 1}
		):
			return "In Process"
		return "Not Started"

	def update_status(self):
		"""Recompute and persist status. Safe to call from sub-documents."""
		new = self.get_status()
		if new != self.status:
			self.db_set("status", new)
		return new

	# ---- Stock Entry rollup (called from Stock Entry submit/cancel hook) ----

	def update_produced_qty(self):
		"""Recompute produced_qty from submitted FGTS docs (primary) + legacy WIP to FG docs."""
		fgts_total = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(f.total_qty), 0)
			FROM `tabFGTS Item` fi
			JOIN `tabFGTS` f ON f.name = fi.parent
			WHERE f.job_order_converting = %s
			  AND f.docstatus = 1
			  AND fi.item_code = %s
			""",
			(self.name, self.production_item),
		)[0][0]
		legacy_total = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(i.qty), 0)
			FROM `tabJob Order Converting WIP to FG Item` i
			JOIN `tabJob Order Converting WIP to FG` p ON p.name = i.parent
			WHERE p.job_order_converting = %s
			  AND p.docstatus = 1
			  AND i.item_code = %s
			""",
			(self.name, self.production_item),
		)[0][0]
		total = flt(fgts_total) + flt(legacy_total)
		self.db_set("produced_qty", flt(total), update_modified=False)
		jo_qty_in_process = max(flt(self.qty) - flt(total), 0)
		self.db_set("jo_qty_in_process", jo_qty_in_process, update_modified=False)
		# Update status (may flip to Completed)
		self.update_status()


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def start_job_order(name):
	"""Create and immediately submit a Job Order Converting RM to WIP (the 'Start' action).

	Idempotent: if a draft RM to WIP already exists it is submitted; if one is
	already submitted the call is a no-op and returns the existing doc name.
	"""
	jo = frappe.get_doc("Job Order Converting", name)
	frappe.has_permission("Job Order Converting", "write", doc=jo, throw=True)

	if jo.docstatus != 1:
		frappe.throw(_("Job Order Converting must be submitted before starting"))
	if jo.status in ("Cancelled", "Stopped", "Closed"):
		frappe.throw(_("Cannot start a {0} Job Order Converting").format(jo.status))

	# Already have a linked RM to WIP doc
	if jo.transfer_rm_doc:
		rm_doc = frappe.get_doc("Job Order Converting RM to WIP", jo.transfer_rm_doc)
		if rm_doc.docstatus == 1:
			# Already submitted — nothing to do
			return jo.transfer_rm_doc
		# Draft exists (e.g. legacy) — submit it and flip status
		rm_doc.submit()
		jo.db_set("status", "In Process")
		return rm_doc.name

	# Create fresh and submit in one step
	jo.create_rm_to_wip_doc()
	rm_doc_name = frappe.db.get_value("Job Order Converting", name, "transfer_rm_doc")
	rm_doc = frappe.get_doc("Job Order Converting RM to WIP", rm_doc_name)
	rm_doc.submit()
	# Flip JO status to In Process
	jo.db_set("status", "In Process")
	return rm_doc.name


@frappe.whitelist()
def make_return_components(source_name):
	"""Build a draft Stock Entry to return un-consumed material from WIP -> Raw Material warehouse."""
	jo = frappe.get_doc("Job Order Converting", source_name)
	jo.check_permission("read")
	frappe.has_permission("Stock Entry", "create", throw=True)
	if jo.docstatus != 1:
		frappe.throw(_("Job Order Converting must be submitted before Return Components"))

	in_process = flt(jo.qty) - flt(jo.produced_qty)
	if in_process <= 0:
		frappe.throw(_("No quantity in WIP to return"))

	settings = frappe.get_cached_doc("IIB Settings")
	target = settings.default_raw_material_warehouse
	if not target:
		frappe.throw(_("Set Raw Material Warehouse in IIB Settings"))

	stock_uom = frappe.db.get_value("Item", jo.production_item, "stock_uom")

	return_se_type = settings.converting_start_stock_entry_type or "Material Transfer"
	return_se_purpose = (
		frappe.db.get_value("Stock Entry Type", return_se_type, "purpose") or "Material Transfer"
	)

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = return_se_type
	se.purpose = return_se_purpose
	se.company = jo.company
	se.from_warehouse = jo.wip_warehouse
	se.to_warehouse = target
	se.iib_job_order_converting = jo.name
	se.append(
		"items",
		{
			"item_code": jo.production_item,
			"qty": in_process,
			"transfer_qty": in_process,
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": 1,
			"s_warehouse": jo.wip_warehouse,
			"t_warehouse": target,
		},
	)
	return se.as_dict()


@frappe.whitelist()
def stop_job_order(name, status):
	"""Stop / Re-open / Close a submitted Job Order Converting."""
	if status not in ("Stopped", "In Process", "Completed", "Closed"):
		frappe.throw(_("Invalid status transition: {0}").format(status))
	jo = frappe.get_doc("Job Order Converting", name)
	jo.check_permission("submit")
	if jo.docstatus != 1:
		frappe.throw(_("Only submitted Job Order Converting can transition status"))
	jo.db_set("status", status)
	return jo.status


@frappe.whitelist()
def get_operations_for_item(production_item):
	"""Return Master Card Process operations for a single MC Component."""
	frappe.has_permission("Job Order Converting", "read", throw=True)
	frappe.has_permission("Master Card", "read", throw=True)
	if not production_item:
		frappe.throw(_("MC Component is required"))
	return get_master_card_operations_for_item(production_item)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_so_query_for_production_item(doctype, txt, searchfield, start, page_len, filters):
	"""Link query: return submitted, active Sales Orders that have a Packed Item
	matching the given production_item. Used by the Get Items From picker when
	MC Component is already set so users only see relevant SOs."""
	# production_item may come from get_query_filters or from the mc_no setter value
	production_item = filters.get("production_item") or filters.get("mc_no") or ""
	customer = filters.get("customer") or ""

	# Build optional customer clause (parametrised — no injection risk)
	customer_clause = "AND so.customer = %(customer)s" if customer else ""

	return frappe.db.sql(
		f"""
		SELECT DISTINCT so.name, pi.item_code AS mc_no, so.customer, so.transaction_date
		FROM `tabSales Order` so
		JOIN `tabPacked Item` pi ON pi.parent = so.name
		WHERE so.docstatus = 1
		  AND so.status NOT IN ('Stopped', 'Closed', 'Cancelled')
		  AND pi.item_code = %(production_item)s
		  {customer_clause}
		  AND (so.name LIKE %(txt)s OR so.customer LIKE %(txt)s)
		ORDER BY so.transaction_date DESC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{
			"production_item": production_item,
			"customer": customer,
			"txt": f"%{txt}%",
			"page_len": page_len,
			"start": start,
		},
		as_dict=1,
	)


@frappe.whitelist()
def get_items_from_so_for_converting(source_name, target_doc=None, kwargs=None):
	"""Mapper for map_current_doc with allow_child_item_selection: true.

	Adds Packed Item rows from a Sales Order to the JO P2's sales_order_items table.
	Silently filters by production_item (skip non-matching rows). Respects
	allow_child_item_selection via kwargs.filtered_children.

	Args:
		source_name: the Sales Order name.
		target_doc: the JO P2 document (dict or Document object).
		kwargs: optional dict with filtered_children list (from allow_child_item_selection).

	Returns:
		The mutated target_doc.
	"""
	frappe.has_permission("Job Order Converting", "read", throw=True)
	frappe.has_permission("Sales Order", "read", throw=True)

	if kwargs is None:
		kwargs = {}

	if target_doc is None:
		target_doc = frappe.new_doc("Job Order Converting")
	elif isinstance(target_doc, str):
		# map_docs passes target_doc as a raw JSON string
		target_doc = frappe.get_doc(json.loads(target_doc))
	elif isinstance(target_doc, dict):
		target_doc = frappe.get_doc(target_doc)

	source = frappe.get_doc("Sales Order", source_name)
	if source.docstatus != 1:
		return target_doc

	# Extract production_item and exclude_job_order from target
	production_item = target_doc.get("production_item")
	exclude_job_order = (
		target_doc.get("name") if target_doc.get("docstatus") == 0 else None
	)

	# Get filtered_children if in child-selection mode (user selected specific Packed Items)
	filtered_children = kwargs.get("filtered_children") or []

	# Ensure sales_order_items exists
	if not target_doc.sales_order_items:
		target_doc.sales_order_items = []

	# Walk packed_items, applying filters
	rows_added = 0
	first_item_code = None
	for pi_row in source.packed_items or []:
		# Silent filter 1: production_item mismatch
		if production_item and pi_row.item_code != production_item:
			continue

		# Silent filter 2: child-selection mode and not in filtered list
		if filtered_children and pi_row.name not in filtered_children:
			continue

		# Calculate open quantity
		open_qty = flt(
			get_so_item_available_qty(
				pi_row.name, exclude_job_order=exclude_job_order
			)
		)
		if open_qty <= 0:
			continue

		# Check if already in target (avoid duplicates)
		existing = [
			r for r in target_doc.sales_order_items
			if r.sales_order == source_name
			and r.sales_order_item == pi_row.name
		]
		if existing:
			continue

		# Resolve delivery_date from parent Sales Order Item
		details = get_so_line_details(pi_row.name) or frappe._dict()

		# Add to target's sales_order_items
		target_doc.append("sales_order_items", {
			"sales_order": source_name,
			"sales_order_item": pi_row.name,
			"item_code": pi_row.item_code,
			"qty": open_qty,
			"delivery_date": details.get("delivery_date"),
			"customer": source.customer,
			"so_status": source.status,
		})
		if first_item_code is None:
			first_item_code = pi_row.item_code
		rows_added += 1

	# Auto-populate MC Component from the first added row's item_code when not already set
	if rows_added > 0 and first_item_code and not target_doc.get("production_item"):
		target_doc.production_item = first_item_code

	if rows_added == 0:
		item_label = production_item or _("any item")
		frappe.msgprint(
			_("No open Packed Items found for <b>{0}</b> in {1}. "
			  "Either the item is not in this Sales Order's packed items, "
			  "or the full quantity is already allocated.").format(item_label, source_name),
			title=_("No Items Added"),
			indicator="orange",
		)

	return target_doc
