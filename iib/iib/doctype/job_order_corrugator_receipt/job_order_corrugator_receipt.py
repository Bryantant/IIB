# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import flt, nowtime

from iib.iib.doctype.job_order_corrugator.job_order_corrugator import JOP1_TARGET_WAREHOUSE
from iib.iib.utils.tolerance import lookup_tolerance

from erpnext.controllers.stock_controller import StockController


class JobOrderCorrugatorReceipt(StockController):
	def validate(self):
		self.set_defaults()
		self.validate_expense_account()
		self.validate_items()
		self.validate_receipt_qty_vs_corrugator()
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
			self.validate_linked_corrugator_item(row)
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be positive").format(row.idx))
			if not row.target_warehouse:
				frappe.throw(_("Row {0}: Target Warehouse is required").format(row.idx))
			if flt(row.basic_rate) <= 0:
				frappe.throw(_("Row {0}: Basic Rate is required").format(row.idx))
			# Ensure linked JOP1 is submitted
			if row.job_order_corrugator:
				docstatus = frappe.db.get_value("Job Order Corrugator", row.job_order_corrugator, "docstatus")
				if docstatus != 1:
					frappe.throw(
						_("Row {0}: Job Order Corrugator {1} is not submitted").format(row.idx, row.job_order_corrugator)
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
				_("Row {0}: Item {1} must be a stock item for Job Order Corrugator Receipt").format(
					row.idx, frappe.bold(row.item_code)
				)
			)
		if not item_details.stock_uom:
			frappe.throw(_("Row {0}: Item {1} has no Stock UOM").format(row.idx, row.item_code))
		if row.uom and row.uom != item_details.stock_uom:
			frappe.throw(
				_(
					"Row {0}: Item {1} must use stock UOM {2}; current UOM is {3}. "
					"Job Order Corrugator Receipt does not support UOM conversion."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(item_details.stock_uom),
					frappe.bold(row.uom),
				)
			)
		row.uom = item_details.stock_uom

	def validate_linked_corrugator_item(self, row):
		if not row.job_order_corrugator_item:
			return

		linked_row = frappe.db.get_value(
			"Job Order Corrugator Item",
			row.job_order_corrugator_item,
			["parent", "item_code", "uom"],
			as_dict=True,
		)
		if not linked_row:
			frappe.throw(
				_("Row {0}: Job Order Corrugator Item {1} not found").format(
					row.idx, row.job_order_corrugator_item
				)
			)
		if row.job_order_corrugator and linked_row.parent != row.job_order_corrugator:
			frappe.throw(
				_("Row {0}: Job Order Corrugator Item {1} does not belong to {2}").format(
					row.idx, row.job_order_corrugator_item, row.job_order_corrugator
				)
			)
		if linked_row.item_code != row.item_code:
			frappe.throw(
				_("Row {0}: Item Code must match linked Job Order Corrugator Item {1}").format(
					row.idx, row.job_order_corrugator_item
				)
			)
		if linked_row.uom != row.uom:
			frappe.throw(
				_("Row {0}: UOM must match linked Job Order Corrugator Item {1}").format(
					row.idx, row.job_order_corrugator_item
				)
			)

	def validate_receipt_qty_vs_corrugator(self):
		"""Points 1 & 3 — guard against over-receiving beyond JO P1 ordered qty + tolerance.

		Aggregates all rows in *this* receipt by ``job_order_corrugator_item`` (handles the
		edge-case where the same JO P1 Item row appears more than once), then checks:

			already_received (submitted receipts) + this_receipt_qty
			    ≤ corrugator_item.qty + tolerance_tier

		``corrugator_item.received_qty`` is kept in sync only with *submitted* receipts, so a
		draft being saved/submitted never double-counts itself.

		The tolerance tiers are reused from the IIB Settings Corrugator Tolerance table — the
		same tiers that govern how much over the SO qty a JO P1 may order.

		DB calls are isolated in ``_get_corrugator_tolerance_rows`` and ``_get_corrugator_item_data``
		so unit tests can override them without needing a live Frappe context.
		"""
		# --- aggregate this receipt's qty per JO P1 Item row ---
		receipt_qty_by_item: dict[str, float] = {}
		for row in self.items:
			if not row.job_order_corrugator_item:
				continue
			receipt_qty_by_item[row.job_order_corrugator_item] = (
				flt(receipt_qty_by_item.get(row.job_order_corrugator_item, 0)) + flt(row.qty)
			)

		if not receipt_qty_by_item:
			return

		tolerance_rows = self._get_corrugator_tolerance_rows()

		for corrugator_item_name, this_qty in receipt_qty_by_item.items():
			corrugator_item = self._get_corrugator_item_data(corrugator_item_name)
			if not corrugator_item:
				continue

			ordered_qty = flt(corrugator_item["qty"])
			already_received = flt(corrugator_item["received_qty"])  # submitted receipts only
			would_receive = already_received + this_qty
			tolerance = lookup_tolerance(tolerance_rows, ordered_qty, "corrugator_qty", "corrugator_toleransi")

			if would_receive > ordered_qty + tolerance:
				max_receivable = max(ordered_qty + tolerance - already_received, 0)
				frappe.throw(
					_(
						"JO P1 {0} — Item {1}: receipt qty {2} would bring total received"
						" to {3}, exceeding ordered qty {4} + tolerance {5} = {6}."
						" Maximum receivable now: {7}."
					).format(
						frappe.bold(corrugator_item["parent"]),
						frappe.bold(corrugator_item["item_code"]),
						frappe.bold(flt(this_qty, 3)),
						frappe.bold(flt(would_receive, 3)),
						ordered_qty,
						tolerance,
						frappe.bold(flt(ordered_qty + tolerance, 3)),
						frappe.bold(flt(max_receivable, 3)),
					)
				)

	# -- DB helpers (extracted for unit-test overrideability) --

	def _get_corrugator_tolerance_rows(self):
		"""Return JO P1 tolerance tiers from IIB Settings, sorted asc by qty."""
		return frappe.get_all(
			"IIB Settings Corrugator Tolerance",
			filters={"parent": "IIB Settings", "parenttype": "IIB Settings"},
			fields=["corrugator_qty", "corrugator_toleransi"],
			order_by="corrugator_qty asc",
		)

	def _get_corrugator_item_data(self, corrugator_item_name):
		"""Return qty/received_qty/item_code/parent for one JO P1 Item row."""
		return frappe.db.get_value(
			"Job Order Corrugator Item",
			corrugator_item_name,
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
		self.update_corrugator_received_qty()
		self.db_set("status", "Submitted")

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Stock Ledger Entry")
		self.update_stock_ledger()
		self.make_gl_entries_on_cancel()
		self.update_corrugator_received_qty()
		self.db_set("status", "Cancelled")

	# -------------------------------------------------------------------------
	# Stock Ledger
	# -------------------------------------------------------------------------

	def make_sl_entries(self, sl_entries, allow_negative_stock=False, via_landed_cost_voucher=False):
		# Skip update_batch_qty — our items child table has no serial_and_batch_bundle column
		from erpnext.stock.stock_ledger import make_sl_entries as _make_sl_entries

		_make_sl_entries(sl_entries, allow_negative_stock, via_landed_cost_voucher)

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
						"remarks": self.notes or _("Job Order Corrugator Receipt"),
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
						"remarks": self.notes or _("Job Order Corrugator Receipt"),
					},
					item=d,
				)
			)
		return process_gl_map(gl_entries)

	# -------------------------------------------------------------------------
	# JOP1 received_qty propagation
	# -------------------------------------------------------------------------

	def update_corrugator_received_qty(self):
		corrugator_names = {r.job_order_corrugator for r in self.items if r.job_order_corrugator}
		for name in corrugator_names:
			corrugator = frappe.get_doc("Job Order Corrugator", name)
			corrugator.recompute_received_qty()
			existing = [
				n for n in (corrugator.created_receipts or "").split(", ") if n
			]
			if self.docstatus == 1 and self.name not in existing:
				existing.append(self.name)
			elif self.docstatus == 2 and self.name in existing:
				existing.remove(self.name)
			corrugator.db_set("created_receipts", ", ".join(existing))


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def get_corrugator_items_for_receipt_dialog(job_order_corrugators, filtered_children=None):
	"""Return pending JO P1 Item rows for the custom two-step selection dialog.

	filtered_children: list of Job Order Corrugator Item names selected via the
	allow_child_item_selection checkbox in the Step-1 dialog.  When provided
	only those specific rows are returned (still subject to pending > 0).
	When empty / omitted all pending rows for the given JO P1s are returned.
	"""
	if isinstance(job_order_corrugators, str):
		job_order_corrugators = json.loads(job_order_corrugators)
	if isinstance(filtered_children, str):
		filtered_children = json.loads(filtered_children)
	if not job_order_corrugators:
		return []

	filters = {"parent": ("in", job_order_corrugators)}
	if filtered_children:
		filters["name"] = ("in", filtered_children)

	rows = frappe.get_all(
		"Job Order Corrugator Item",
		filters=filters,
		fields=[
			"name as job_order_corrugator_item",
			"parent as job_order_corrugator",
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
def get_corrugator_items(job_order_corrugators):
	"""Fetch pending JOP1 Item rows for the Get Items From → Job Order Corrugator picker."""
	if isinstance(job_order_corrugators, str):
		job_order_corrugators = json.loads(job_order_corrugators)
	if not job_order_corrugators:
		return []

	rows = frappe.get_all(
		"Job Order Corrugator Item",
		filters={"parent": ("in", job_order_corrugators)},
		fields=[
			"name as job_order_corrugator_item",
			"parent as job_order_corrugator",
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
