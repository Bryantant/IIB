# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, nowtime

from erpnext.controllers.stock_controller import StockController


class JobOrderConvertingWIPtoFG(StockController):
	"""WIP → Finished Goods transfer for Job Order Converting.

	Inherits StockController so that SL entries carry
	voucher_type = "Job Order Converting WIP to FG" instead of "Stock Entry".
	"""

	def validate(self):
		self.set_defaults()
		self.validate_items()
		if not self.status:
			self.status = "Draft"

	def set_defaults(self):
		if not self.posting_time:
			self.posting_time = nowtime()
		if not self.company:
			self.company = frappe.defaults.get_global_default("company")
		# Warehouses come from the linked Job Order Converting
		if self.job_order_converting and (not self.source_warehouse or not self.target_warehouse):
			jo_wh = frappe.db.get_value(
				"Job Order Converting",
				self.job_order_converting,
				["wip_warehouse", "fg_warehouse"],
				as_dict=True,
			)
			if jo_wh:
				if not self.source_warehouse:
					self.source_warehouse = jo_wh.wip_warehouse
				if not self.target_warehouse:
					self.target_warehouse = jo_wh.fg_warehouse
		if not self.cost_center:
			self.cost_center = (
				frappe.db.get_single_value("IIB Settings", "default_cost_center")
				or frappe.get_cached_value("Company", self.company, "cost_center")
			)

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Items table is empty"))
		for row in self.items:
			if not row.item_code:
				frappe.throw(_("Row {0}: Item Code is required").format(row.idx))
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Quantity must be positive").format(row.idx))
			if flt(row.basic_rate) <= 0:
				frappe.throw(_("Row {0}: Basic Rate must be positive").format(row.idx))
			item = frappe.db.get_value(
				"Item", row.item_code, ["item_name", "stock_uom"], as_dict=True
			)
			if item:
				row.item_name = item.item_name
				if not row.uom:
					row.uom = item.stock_uom

	# -------------------------------------------------------------------------
	# Lifecycle
	# -------------------------------------------------------------------------

	def on_submit(self):
		self.update_stock_ledger()
		self.make_gl_entries()
		self.db_set("status", "Submitted")
		self._cascade_to_job_order()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Stock Ledger Entry")
		self.update_stock_ledger()
		self.make_gl_entries_on_cancel()
		self.db_set("status", "Cancelled")
		self._cascade_to_job_order()

	def _cascade_to_job_order(self):
		"""Recompute produced_qty and status on the linked Job Order Converting."""
		if not self.job_order_converting:
			return
		try:
			jo = frappe.get_doc("Job Order Converting", self.job_order_converting)
			jo.update_produced_qty()
		except Exception:
			pass

	# -------------------------------------------------------------------------
	# Stock Ledger
	# -------------------------------------------------------------------------

	def update_stock_ledger(self):
		"""Create paired SL entries: WIP OUT, FG IN."""
		sl_entries = []
		for d in self.get("items"):
			if not d.item_code:
				continue
			# Deduct from WIP
			sl_entries.append(
				self.get_sl_entries(
					d,
					{
						"actual_qty": -flt(d.qty),
						"warehouse": self.source_warehouse,
					},
				)
			)
			# Add to Finished Goods
			sl_entries.append(
				self.get_sl_entries(
					d,
					{
						"actual_qty": flt(d.qty),
						"incoming_rate": flt(d.basic_rate),
						"warehouse": self.target_warehouse,
					},
				)
			)
		if sl_entries:
			self.make_sl_entries(sl_entries)

	# -------------------------------------------------------------------------
	# GL Entries (Dr FG warehouse account, Cr WIP warehouse account)
	# -------------------------------------------------------------------------

	def get_gl_entries(
		self, warehouse_account=None, default_expense_account=None, default_cost_center=None
	):
		from erpnext.accounts.general_ledger import process_gl_map

		gl_entries = []
		for d in self.get("items"):
			amount = flt(d.qty) * flt(d.basic_rate)
			if not amount:
				continue

			source_account = frappe.get_cached_value(
				"Warehouse", self.source_warehouse, "account"
			)
			target_account = frappe.get_cached_value(
				"Warehouse", self.target_warehouse, "account"
			)

			if not source_account or not target_account:
				continue
			if source_account == target_account:
				continue

			remarks = _("WIP to FG Transfer: {0}").format(self.name)

			# Dr FG (target) — FG asset increases
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": target_account,
						"against": source_account,
						"cost_center": self.cost_center,
						"debit": amount,
						"debit_in_account_currency": amount,
						"remarks": remarks,
					},
					item=d,
				)
			)
			# Cr WIP (source) — WIP asset decreases
			gl_entries.append(
				self.get_gl_dict(
					{
						"account": source_account,
						"against": target_account,
						"cost_center": self.cost_center,
						"credit": amount,
						"credit_in_account_currency": amount,
						"remarks": remarks,
					},
					item=d,
				)
			)

		return process_gl_map(gl_entries)
