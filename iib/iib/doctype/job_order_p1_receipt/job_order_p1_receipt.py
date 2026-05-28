# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import flt, nowtime

from iib.iib.doctype.job_order_p1.job_order_p1 import JOP1_TARGET_WAREHOUSE
from iib.iib.utils.tolerance import lookup_tolerance

from erpnext.controllers.stock_controller import StockController


class JobOrderP1Receipt(StockController):
	def validate(self):
		self.set_defaults()
		self.validate_expense_account()
		self.validate_items()
		self.validate_receipt_qty_vs_jop1()
		self.compute_totals()
		if self.docstatus == 0 and not self.status:
			self.status = "Draft"

	def set_defaults(self):
		if not self.posting_time:
			self.posting_time = nowtime()
		# Header GL defaults — sourced from IIB Settings
		if not self.cost_center:
			self.cost_center = frappe.db.get_single_value(
				"IIB Settings", "default_cost_center"
			) or frappe.get_cached_value("Company", self.company, "cost_center")
		if not self.expense_account:
			self.expense_account = frappe.db.get_single_value(
				"IIB Settings", "default_expense_account"
			)
		for row in self.items:
			row.target_warehouse = JOP1_TARGET_WAREHOUSE

	def validate_expense_account(self):
		if not self.expense_account:
			return

		account = frappe.db.get_value(
			"Account", self.expense_account, ["is_group", "company"], as_dict=True
		)
		if not account:
			frappe.throw(
				_("Expense Account {0} does not exist").format(
					frappe.bold(self.expense_account)
				)
			)
		if account.is_group:
			frappe.throw(
				_("Expense Account {0} must be a leaf account, not a group account.").format(
					frappe.bold(self.expense_account)
				)
			)
		if self.company and account.company and account.company != self.company:
			frappe.throw(
				_("Expense Account {0} does not belong to company {1}.").format(
					frappe.bold(self.expense_account), frappe.bold(self.company)
				)
			)

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Items table is empty"))
		for row in self.items:
			self.validate_stock_item_and_uom(row)
			self.validate_linked_jop1_item(row)
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be positive").format(row.idx))
			if not row.target_warehouse:
				frappe.throw(_("Row {0}: Target Warehouse is required").format(row.idx))
			if flt(row.basic_rate) <= 0:
				frappe.throw(_("Row {0}: Basic Rate is required").format(row.idx))
			# Ensure linked JOP1 is submitted
			if row.job_order_p1:
				docstatus = frappe.db.get_value("Job Order P1", row.job_order_p1, "docstatus")
				if docstatus != 1:
					frappe.throw(
						_("Row {0}: Job Order P1 {1} is not submitted").format(row.idx, row.job_order_p1)
					)
			row.amount = flt(row.qty) * flt(row.basic_rate)

	def validate_stock_item_and_uom(self, row):
		if not row.item_code:
			frappe.throw(_("Row {0}: Item Code is required").format(row.idx))

		item_details = frappe.db.get_value(
			"Item", row.item_code, ["is_stock_item", "stock_uom"], as_dict=True
		)
		if not item_details:
			frappe.throw(_("Row {0}: Item {1} not found").format(row.idx, row.item_code))
		if not item_details.is_stock_item:
			frappe.throw(
				_("Row {0}: Item {1} must be a stock item for Job Order P1 Receipt").format(
					row.idx, frappe.bold(row.item_code)
				)
			)
		if not item_details.stock_uom:
			frappe.throw(_("Row {0}: Item {1} has no Stock UOM").format(row.idx, row.item_code))
		if row.uom and row.uom != item_details.stock_uom:
			frappe.throw(
				_(
					"Row {0}: Item {1} must use stock UOM {2}; current UOM is {3}. "
					"Job Order P1 Receipt does not support UOM conversion."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(item_details.stock_uom),
					frappe.bold(row.uom),
				)
			)
		row.uom = item_details.stock_uom

	def validate_linked_jop1_item(self, row):
		if not row.job_order_p1_item:
			return

		linked_row = frappe.db.get_value(
			"Job Order P1 Item",
			row.job_order_p1_item,
			["parent", "item_code", "uom"],
			as_dict=True,
		)
		if not linked_row:
			frappe.throw(
				_("Row {0}: Job Order P1 Item {1} not found").format(
					row.idx, row.job_order_p1_item
				)
			)
		if row.job_order_p1 and linked_row.parent != row.job_order_p1:
			frappe.throw(
				_("Row {0}: Job Order P1 Item {1} does not belong to {2}").format(
					row.idx, row.job_order_p1_item, row.job_order_p1
				)
			)
		if linked_row.item_code != row.item_code:
			frappe.throw(
				_("Row {0}: Item Code must match linked Job Order P1 Item {1}").format(
					row.idx, row.job_order_p1_item
				)
			)
		if linked_row.uom != row.uom:
			frappe.throw(
				_("Row {0}: UOM must match linked Job Order P1 Item {1}").format(
					row.idx, row.job_order_p1_item
				)
			)

	def validate_receipt_qty_vs_jop1(self):
		"""Points 1 & 3 — guard against over-receiving beyond JO P1 ordered qty + tolerance.

		Aggregates all rows in *this* receipt by ``job_order_p1_item`` (handles the
		edge-case where the same JO P1 Item row appears more than once), then checks:

			already_received (submitted receipts) + this_receipt_qty
			    ≤ jop1_item.qty + tolerance_tier

		``jop1_item.received_qty`` is kept in sync only with *submitted* receipts, so a
		draft being saved/submitted never double-counts itself.

		The tolerance tiers are reused from the IIB Settings JOP1 Tolerance table — the
		same tiers that govern how much over the SO qty a JO P1 may order.

		DB calls are isolated in ``_get_jop1_tolerance_rows`` and ``_get_jop1_item_data``
		so unit tests can override them without needing a live Frappe context.
		"""
		# --- aggregate this receipt's qty per JO P1 Item row ---
		receipt_qty_by_item: dict[str, float] = {}
		for row in self.items:
			if not row.job_order_p1_item:
				continue
			receipt_qty_by_item[row.job_order_p1_item] = (
				flt(receipt_qty_by_item.get(row.job_order_p1_item, 0)) + flt(row.qty)
			)

		if not receipt_qty_by_item:
			return

		tolerance_rows = self._get_jop1_tolerance_rows()

		for jop1_item_name, this_qty in receipt_qty_by_item.items():
			jop1_item = self._get_jop1_item_data(jop1_item_name)
			if not jop1_item:
				continue

			ordered_qty = flt(jop1_item["qty"])
			already_received = flt(jop1_item["received_qty"])  # submitted receipts only
			would_receive = already_received + this_qty
			tolerance = lookup_tolerance(tolerance_rows, ordered_qty, "jop1_qty", "jop1_toleransi")

			if would_receive > ordered_qty + tolerance:
				max_receivable = max(ordered_qty + tolerance - already_received, 0)
				frappe.throw(
					_(
						"JO P1 {0} — Item {1}: receipt qty {2} would bring total received"
						" to {3}, exceeding ordered qty {4} + tolerance {5} = {6}."
						" Maximum receivable now: {7}."
					).format(
						frappe.bold(jop1_item["parent"]),
						frappe.bold(jop1_item["item_code"]),
						frappe.bold(flt(this_qty, 3)),
						frappe.bold(flt(would_receive, 3)),
						ordered_qty,
						tolerance,
						frappe.bold(flt(ordered_qty + tolerance, 3)),
						frappe.bold(flt(max_receivable, 3)),
					)
				)

	# -- DB helpers (extracted for unit-test overrideability) --

	def _get_jop1_tolerance_rows(self):
		"""Return JO P1 tolerance tiers from IIB Settings, sorted asc by qty."""
		return frappe.get_all(
			"IIB Settings JOP1 Tolerance",
			filters={"parent": "IIB Settings", "parenttype": "IIB Settings"},
			fields=["jop1_qty", "jop1_toleransi"],
			order_by="jop1_qty asc",
		)

	def _get_jop1_item_data(self, jop1_item_name):
		"""Return qty/received_qty/item_code/parent for one JO P1 Item row."""
		return frappe.db.get_value(
			"Job Order P1 Item",
			jop1_item_name,
			["qty", "received_qty", "item_code", "parent"],
			as_dict=True,
		)

	def compute_totals(self):
		self.total_qty = sum(flt(r.qty) for r in self.items)
		self.total_amount = sum(flt(r.amount) for r in self.items)

	# -------------------------------------------------------------------------
	# Lifecycle
	# -------------------------------------------------------------------------

	def on_submit(self):
		self.update_stock_ledger()
		self.make_gl_entries()
		self.update_jop1_received_qty()
		self.db_set("status", "Submitted")

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Stock Ledger Entry")
		self.update_stock_ledger()
		self.make_gl_entries_on_cancel()
		self.update_jop1_received_qty()
		self.db_set("status", "Cancelled")

	# -------------------------------------------------------------------------
	# Stock Ledger
	# -------------------------------------------------------------------------

	def update_stock_ledger(self):
		sl_entries = []
		for d in self.get("items"):
			if not d.target_warehouse:
				continue
			sl_entries.append(
				self.get_sl_entries(
					d,
					{
						"actual_qty": flt(d.qty) * (1 if self.docstatus == 1 else -1),
						"incoming_rate": flt(d.basic_rate),
						"warehouse": d.target_warehouse,
					},
				)
			)
		if sl_entries:
			self.make_sl_entries(sl_entries)

	# -------------------------------------------------------------------------
	# GL Entries (header-level expense_account, header-level cost_center)
	# -------------------------------------------------------------------------

	def get_gl_entries(self, warehouse_account=None, default_expense_account=None,
	                   default_cost_center=None):
		from erpnext.accounts.general_ledger import process_gl_map

		gl_entries = []
		for d in self.get("items"):
			amount = flt(d.qty) * flt(d.basic_rate)
			if not amount or not d.target_warehouse:
				continue

			if warehouse_account:
				stock_account = (warehouse_account.get(d.target_warehouse) or {}).get("account")
			else:
				stock_account = frappe.get_cached_value("Warehouse", d.target_warehouse, "account")

			if not stock_account:
				frappe.throw(
					_("Row {0}: Target Warehouse {1} has no linked Account").format(
						d.idx, d.target_warehouse
					)
				)

			# Dr  Stock account
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": stock_account,
						"against": self.expense_account,
						"cost_center": self.cost_center,
						"debit": amount,
						"debit_in_account_currency": amount,
						"remarks": self.notes or _("Job Order P1 Receipt"),
					},
					item=d,
				)
			)
			# Cr  Expense account
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": self.expense_account,
						"against": stock_account,
						"cost_center": self.cost_center,
						"credit": amount,
						"credit_in_account_currency": amount,
						"remarks": self.notes or _("Job Order P1 Receipt"),
					},
					item=d,
				)
			)
		return process_gl_map(gl_entries)

	# -------------------------------------------------------------------------
	# JOP1 received_qty propagation
	# -------------------------------------------------------------------------

	def update_jop1_received_qty(self):
		jop1_names = {r.job_order_p1 for r in self.items if r.job_order_p1}
		for name in jop1_names:
			jop1 = frappe.get_doc("Job Order P1", name)
			jop1.recompute_received_qty()
			existing = [
				n for n in (jop1.created_receipts or "").split(", ") if n
			]
			if self.docstatus == 1 and self.name not in existing:
				existing.append(self.name)
			elif self.docstatus == 2 and self.name in existing:
				existing.remove(self.name)
			jop1.db_set("created_receipts", ", ".join(existing))


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def get_jop1_items_for_receipt_dialog(job_order_p1s, filtered_children=None):
	"""Return pending JO P1 Item rows for the custom two-step selection dialog.

	filtered_children: list of Job Order P1 Item names selected via the
	allow_child_item_selection checkbox in the Step-1 dialog.  When provided
	only those specific rows are returned (still subject to pending > 0).
	When empty / omitted all pending rows for the given JO P1s are returned.
	"""
	if isinstance(job_order_p1s, str):
		job_order_p1s = json.loads(job_order_p1s)
	if isinstance(filtered_children, str):
		filtered_children = json.loads(filtered_children)
	if not job_order_p1s:
		return []

	filters = {"parent": ("in", job_order_p1s)}
	if filtered_children:
		filters["name"] = ("in", filtered_children)

	rows = frappe.get_all(
		"Job Order P1 Item",
		filters=filters,
		fields=[
			"name as job_order_p1_item",
			"parent as job_order_p1",
			"item_code",
			"item_name",
			"description",
			"sales_order",
			"uom",
			"qty",
			"received_qty",
		],
		order_by="parent, idx",
	)

	output = []
	for r in rows:
		qty = flt(r.pop("qty"))
		received_qty = flt(r.pop("received_qty"))
		pending = qty - received_qty
		if pending <= 0:
			continue
		r["pending_qty"] = pending        # used as row.qty when added to receipt
		r["received_qty"] = received_qty  # shown in "JO P1 Receipt" column
		r["basic_rate"] = (
			frappe.db.get_value("Item", r["item_code"], "custom_basic_rate") or 0
		)
		r["target_warehouse"] = JOP1_TARGET_WAREHOUSE
		output.append(r)
	return output


@frappe.whitelist()
def get_jop1_items(job_order_p1s):
	"""Fetch pending JOP1 Item rows for the Get Items From → Job Order P1 picker."""
	if isinstance(job_order_p1s, str):
		job_order_p1s = json.loads(job_order_p1s)
	if not job_order_p1s:
		return []

	rows = frappe.get_all(
		"Job Order P1 Item",
		filters={"parent": ("in", job_order_p1s)},
		fields=[
			"name as job_order_p1_item",
			"parent as job_order_p1",
			"item_code",
			"description",
			"sales_order",
			"uom",
			"qty",
			"received_qty",
		],
		order_by="parent, idx",
	)

	output = []
	for r in rows:
		pending = flt(r.pop("qty")) - flt(r.pop("received_qty"))
		if pending <= 0:
			continue
		r["qty"] = pending
		r["basic_rate"] = (
			frappe.db.get_value("Item", r["item_code"], "custom_basic_rate") or 0
		)
		r["target_warehouse"] = JOP1_TARGET_WAREHOUSE
		output.append(r)
	return output
