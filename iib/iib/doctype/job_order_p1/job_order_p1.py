import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt


class JobOrderP1(Document):
	def validate(self):
		self.set_department_marker()
		self.fetch_item_metadata()
		self.validate_items()
		self.compute_totals()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		self.validate_no_double_booking()

	def on_submit(self):
		self.db_set("status", "To Receive")

	def before_cancel(self):
		self.guard_against_submitted_receipts()

	def on_cancel(self):
		self.delete_draft_receipts()
		self.db_set("status", "Cancelled")
		self.db_set("created_receipts", "")

	# ---- validate helpers ----

	def set_department_marker(self):
		if not self.department:
			self.department = "Production 1"

	def fetch_item_metadata(self):
		for row in self.items:
			if not row.sales_order or not row.sales_order_item:
				continue
			so_item = frappe.db.get_value(
				"Sales Order Item",
				row.sales_order_item,
				["item_code", "item_name", "description", "uom", "rate", "delivery_date", "parent"],
				as_dict=True,
			)
			if not so_item:
				frappe.throw(
					_("Row {0}: Sales Order Item {1} not found").format(row.idx, row.sales_order_item)
				)
			if so_item.parent != row.sales_order:
				frappe.throw(
					_("Row {0}: Sales Order Item {1} does not belong to {2}").format(
						row.idx, row.sales_order_item, row.sales_order
					)
				)
			item_details = self.get_stock_item_details(so_item.item_code, row.idx)
			self.validate_sales_order_stock_uom(
				row, so_item.item_code, so_item.uom, item_details.stock_uom
			)
			row.item_code = so_item.item_code
			row.item_name = so_item.item_name
			row.description = so_item.description
			row.uom = item_details.stock_uom
			row.rate = so_item.rate
			if not row.delivery_date:
				row.delivery_date = so_item.delivery_date
			row.customer = frappe.db.get_value("Sales Order", row.sales_order, "customer")

	def get_stock_item_details(self, item_code, row_idx):
		item_details = frappe.db.get_value(
			"Item", item_code, ["is_stock_item", "stock_uom"], as_dict=True
		)
		if not item_details:
			frappe.throw(_("Row {0}: Item {1} not found").format(row_idx, item_code))
		if not item_details.is_stock_item:
			frappe.throw(
				_("Row {0}: Item {1} must be a stock item for Job Order P1").format(
					row_idx, frappe.bold(item_code)
				)
			)
		if not item_details.stock_uom:
			frappe.throw(_("Row {0}: Item {1} has no Stock UOM").format(row_idx, item_code))
		return item_details

	def validate_sales_order_stock_uom(self, row, item_code, sales_order_uom, stock_uom):
		if sales_order_uom and sales_order_uom != stock_uom:
			frappe.throw(
				_(
					"Row {0}: Sales Order Item {1} uses UOM {2}, but Item {3} stock UOM is {4}. "
					"Job Order P1 only supports stock UOM lines."
				).format(
					row.idx,
					row.sales_order_item,
					frappe.bold(sales_order_uom),
					frappe.bold(item_code),
					frappe.bold(stock_uom),
				)
			)

	def validate_row_stock_uom(self, row, stock_uom):
		if row.uom and row.uom != stock_uom:
			frappe.throw(
				_(
					"Row {0}: Item {1} must use stock UOM {2}; current UOM is {3}. "
					"Job Order P1 does not support UOM conversion."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(stock_uom),
					frappe.bold(row.uom),
				)
			)
		row.uom = stock_uom

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Items table is empty"))

		seen = set()
		customers = set()
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be positive").format(row.idx))
			key = (row.sales_order, row.sales_order_item)
			if key in seen:
				frappe.throw(_("Row {0}: Duplicate Sales Order line {1}").format(row.idx, row.sales_order_item))
			seen.add(key)
			if row.item_code:
				item_details = self.get_stock_item_details(row.item_code, row.idx)
				self.validate_row_stock_uom(row, item_details.stock_uom)
			if row.customer:
				customers.add(row.customer)

		self.customer = list(customers)[0] if len(customers) == 1 else None

	def compute_totals(self):
		total_qty = sum(flt(r.qty) for r in self.items)
		total_received = sum(flt(r.received_qty) for r in self.items)
		self.total_qty = total_qty
		self.total_received_qty = total_received
		self.per_received = (total_received / total_qty * 100) if total_qty else 0
		for row in self.items:
			row.pending_qty = max(flt(row.qty) - flt(row.received_qty), 0)

	# ---- submit / cancel guards ----

	def validate_no_double_booking(self):
		so_item_names = [r.sales_order_item for r in self.items if r.sales_order_item]
		if not so_item_names:
			return

		clashes = frappe.db.sql(
			"""
			SELECT i.parent, i.sales_order_item
			FROM `tabJob Order P1 Item` i
			JOIN `tabJob Order P1` p ON p.name = i.parent
			WHERE i.sales_order_item IN %(items)s
			  AND p.name != %(self)s
			  AND p.docstatus = 1
			  AND p.status NOT IN ('Completed', 'Closed', 'Cancelled')
			""",
			{"items": tuple(so_item_names), "self": self.name or ""},
			as_dict=True,
		)
		if clashes:
			parents = sorted({c.parent for c in clashes})
			frappe.throw(
				_("Sales Order line already on open Job Order P1: {0}").format(", ".join(parents))
			)

	def guard_against_submitted_receipts(self):
		submitted = frappe.db.sql(
			"""
			SELECT DISTINCT r.name
			FROM `tabJob Order P1 Receipt` r
			JOIN `tabJob Order P1 Receipt Item` ri ON ri.parent = r.name
			WHERE ri.job_order_p1 = %s
			  AND r.docstatus = 1
			""",
			(self.name,),
			as_dict=True,
		)
		names = [r.name for r in submitted]
		if names:
			frappe.throw(
				_(
					"Cannot cancel: submitted Job Order P1 Receipts exist for this Job Order P1: {0}. Cancel them first."
				).format(", ".join(names))
			)

	def delete_draft_receipts(self):
		drafts = frappe.db.sql(
			"""
			SELECT DISTINCT r.name
			FROM `tabJob Order P1 Receipt` r
			JOIN `tabJob Order P1 Receipt Item` ri ON ri.parent = r.name
			WHERE ri.job_order_p1 = %s
			  AND r.docstatus = 0
			""",
			(self.name,),
			as_dict=True,
		)
		for r in drafts:
			frappe.delete_doc("Job Order P1 Receipt", r.name, ignore_permissions=True, force=True)

	# ---- post-receipt recompute ----

	def recompute_received_qty(self):
		"""Aggregate received_qty from submitted Job Order P1 Receipt rows and refresh status."""
		received_by_row = {}
		receipt_rows = frappe.db.sql(
			"""
			SELECT ri.job_order_p1_item AS row_name, SUM(ri.qty) AS qty
			FROM `tabJob Order P1 Receipt Item` ri
			JOIN `tabJob Order P1 Receipt` r ON r.name = ri.parent
			WHERE ri.job_order_p1 = %(name)s
			  AND ri.job_order_p1_item IS NOT NULL
			  AND ri.job_order_p1_item != ''
			  AND r.docstatus = 1
			GROUP BY ri.job_order_p1_item
			""",
			{"name": self.name},
			as_dict=True,
		)
		for d in receipt_rows:
			received_by_row[str(d.row_name)] = flt(d.qty)

		total_received = 0.0
		total_qty = 0.0
		for row in self.items:
			received = flt(received_by_row.get(str(row.name), 0))
			pending = max(flt(row.qty) - received, 0)
			row.db_set("received_qty", received, update_modified=False)
			row.db_set("pending_qty", pending, update_modified=False)
			total_received += received
			total_qty += flt(row.qty)

		self.db_set("total_received_qty", total_received, update_modified=False)
		self.db_set(
			"per_received",
			(total_received / total_qty * 100) if total_qty else 0,
			update_modified=False,
		)
		self._update_status_from_received_qty(total_qty, total_received)

	def _update_status_from_received_qty(self, total_qty, total_received):
		if self.status in ("Closed", "Cancelled"):
			return
		if self.docstatus != 1:
			return
		if total_received <= 0:
			new_status = "To Receive"
		elif total_received < total_qty:
			new_status = "Partially Received"
		else:
			new_status = "Completed"
		if new_status != self.status:
			self.db_set("status", new_status)


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def make_jop1_receipt(source_name, target_doc=None):
	"""Build a draft Job Order P1 Receipt from a submitted Job Order P1."""

	def update_header(source, target, source_parent=None):
		target.company = source.company
		target.naming_series = "JOP1R-.YY.-.#####"
		target.status = "Draft"  # prevent JOP1 status ("To Receive" etc.) from leaking in
		# Auto-fetch GL defaults from IIB Settings
		default_cc = frappe.db.get_single_value(
			"IIB Settings", "default_cost_center"
		) or frappe.get_cached_value("Company", source.company, "cost_center")
		if default_cc:
			target.cost_center = default_cc
		default_exp = frappe.db.get_single_value("IIB Settings", "default_expense_account")
		if default_exp:
			target.expense_account = default_exp

	def update_row(source_row, target_row, source_parent):
		pending = flt(source_row.qty) - flt(source_row.received_qty)
		target_row.qty = pending
		target_row.job_order_p1 = source_parent.name
		target_row.job_order_p1_item = source_row.name
		target_row.target_warehouse = source_row.target_warehouse or source_parent.target_warehouse
		target_row.basic_rate = (
			frappe.db.get_value("Item", source_row.item_code, "custom_basic_rate") or 0
		)

	doc = get_mapped_doc(
		"Job Order P1",
		source_name,
		{
			"Job Order P1": {
				"doctype": "Job Order P1 Receipt",
				"validation": {"docstatus": ["=", 1]},
				"postprocess": update_header,
			},
			"Job Order P1 Item": {
				"doctype": "Job Order P1 Receipt Item",
				"field_map": {
					"item_code": "item_code",
					"description": "description",
					"sales_order": "sales_order",
					"uom": "uom",
				},
				"postprocess": update_row,
				"condition": lambda d: flt(d.qty) - flt(d.received_qty) > 0,
			},
		},
		target_doc,
	)
	return doc


@frappe.whitelist()
def update_status(status, name):
	"""Close / Re-open a submitted Job Order P1."""
	frappe.has_permission("Job Order P1", "submit", doc=name, throw=True)
	if status not in ("Closed", "To Receive"):
		frappe.throw(_("Invalid status transition: {0}").format(status))
	jop1 = frappe.get_doc("Job Order P1", name)
	if jop1.docstatus != 1:
		frappe.throw(_("Only submitted Job Order P1 can be closed or re-opened"))
	if status == "Closed":
		jop1.db_set("status", "Closed")
	else:
		jop1.recompute_received_qty()
	return frappe.db.get_value("Job Order P1", name, "status")


@frappe.whitelist()
def get_so_items_for_jop1(sales_orders):
	"""Fetch submitted Sales Order Item rows for the picker."""
	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)
	if not sales_orders:
		return []
	rows = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ("in", sales_orders)},
		fields=[
			"name as sales_order_item",
			"parent as sales_order",
			"item_code",
			"item_name",
			"description",
			"uom",
			"qty",
			"rate",
			"delivery_date",
		],
		order_by="parent, idx",
	)
	for row in rows:
		row["customer"] = frappe.db.get_value("Sales Order", row["sales_order"], "customer")
	return rows
