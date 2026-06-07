import frappe
from frappe import _
from frappe.utils import flt, getdate, nowtime

from erpnext.controllers.stock_controller import StockController


class FGTS(StockController):
	def autoname(self):
		from iib.iib.utils.naming import get_next_iib_number

		d = getdate(self.posting_date or frappe.utils.today())
		yymm = d.strftime("%y%m")
		seq = get_next_iib_number("fgts", period=yymm, digits=5)
		self.name = f"{yymm}{seq}"

	"""Finished Goods Tracking System.

	Two-phase stock movement:
	  Phase 1 (Submit → Waiting QC):  WIP Warehouse → Finished Goods Warehouse
	  Phase 2 (Approve QC → OK QC):   Finished Goods Warehouse → Stores

	Qty / BDL / Loose are header-level and shared across all component rows.
	Total Qty = Qty (BDL and Loose are informational only, not used in calculations).
	"""

	# -------------------------------------------------------------------------
	# Lifecycle
	# -------------------------------------------------------------------------

	def validate(self):
		self._set_defaults()
		self._resolve_job_order_converting()
		self._calculate_total_qty()
		if not self.status:
			self.status = "Draft"

	def before_submit(self):
		if not self.items:
			frappe.throw(_("At least one component is required"))
		if not self.source_warehouse:
			frappe.throw(_("Source Warehouse must be selected"))
		source_warehouse = self._resolve_source_warehouse()
		if not source_warehouse:
			frappe.throw(_("Source warehouse could not be resolved — check IIB Settings"))
		if not self.fg_warehouse:
			frappe.throw(_("FG Warehouse not resolved — save the document first"))
		if flt(self.total_qty) <= 0:
			frappe.throw(_("Qty must be greater than zero"))
		self._validate_stock(source_warehouse)

	def on_submit(self):
		"""Phase 1: Source Warehouse (RM or WIP) → Finished Goods."""
		source_warehouse = self._resolve_source_warehouse()
		self._move_stock(source_warehouse, self.fg_warehouse, "Source to FG")
		self.db_set("status", "Waiting QC")
		self.db_set("wip_to_fg_done", 1)
		self._update_jo_produced_qty()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Stock Ledger Entry")
		source_warehouse = self._resolve_source_warehouse()

		# Cancel SLEs in reverse phase order — ERPNext's make_sl_entries with
		# is_cancelled=1 calls set_as_cancel() to mark originals, then posts
		# proper reversal entries and reposts stock balances.
		# Collect all cancellation entries in one batch so set_as_cancel fires once.
		cancel_sl = []
		if self.fg_to_stores_done:
			cancel_sl.extend(
				self._build_sl_entries(self.fg_warehouse, self.stores_warehouse, cancel=True)
			)
		if self.wip_to_fg_done:
			cancel_sl.extend(
				self._build_sl_entries(source_warehouse, self.fg_warehouse, cancel=True)
			)
		if cancel_sl:
			self.make_sl_entries(cancel_sl)

		# Cancel GL entries using the standard AccountsController method
		self.make_gl_entries_on_cancel()

		self.db_set("status", "Cancelled")
		self._update_jo_produced_qty()

	# -------------------------------------------------------------------------
	# Defaults & helpers
	# -------------------------------------------------------------------------

	def _set_defaults(self):
		if not self.posting_time:
			self.posting_time = nowtime()
		if not self.company:
			self.company = frappe.defaults.get_global_default("company")
		if not self.stores_warehouse:
			self.stores_warehouse = "Stores - IIB"

		# Try to get warehouses from linked JO P2 first
		if self.job_order_converting and (not self.wip_warehouse or not self.fg_warehouse):
			jo_wh = frappe.db.get_value(
				"Job Order Converting",
				self.job_order_converting,
				["wip_warehouse", "fg_warehouse"],
				as_dict=True,
			)
			if jo_wh:
				self.wip_warehouse = self.wip_warehouse or jo_wh.wip_warehouse
				self.fg_warehouse = self.fg_warehouse or jo_wh.fg_warehouse

		# Fall back to IIB Settings defaults
		if not self.wip_warehouse:
			self.wip_warehouse = frappe.db.get_single_value("IIB Settings", "default_wip_warehouse")
		if not self.fg_warehouse:
			self.fg_warehouse = frappe.db.get_single_value("IIB Settings", "default_fg_warehouse")
		if not self.cost_center:
			self.cost_center = frappe.db.get_single_value(
				"IIB Settings", "default_cost_center"
			) or frappe.get_cached_value("Company", self.company, "cost_center")

	def _resolve_source_warehouse(self):
		"""Resolve source_warehouse text to actual warehouse link.

		"Work In Progress" → self.wip_warehouse
		"Raw Material" → Returns configured RM warehouse from IIB Settings
		"""
		if self.source_warehouse == "Raw Material":
			return frappe.db.get_single_value("IIB Settings", "default_raw_material_warehouse") or "Raw Material - IIB"
		else:
			# Default to Work In Progress warehouse
			return self.wip_warehouse

	def _resolve_job_order_converting(self):
		"""Link an active JO P2 if not already set.

		Bundle FGTS rows hold component / packed items that are not the JO's
		production_item, so matching on item_code alone misses them. We try
		production_item across all rows first, then fall back to the Sales
		Order allocated on the JO.
		"""
		if self.job_order_converting or not self.items:
			return

		active = ["in", ["In Process", "Completed"]]
		item_codes = [r.item_code for r in self.items if r.item_code]

		jo = None
		if item_codes:
			jo = frappe.db.get_value(
				"Job Order Converting",
				{
					"production_item": ["in", item_codes],
					"docstatus": 1,
					"status": active,
				},
				"name",
				order_by="posting_date asc",
			)

		if not jo and self.sales_order:
			jo_list = frappe.get_all(
				"Job Order Converting",
				filters=[
					["Job Order Converting Sales Order Item", "sales_order", "=", self.sales_order],
					["docstatus", "=", 1],
					["status", "in", ["In Process", "Completed"]],
				],
				pluck="name",
				order_by="posting_date asc",
				limit=1,
			)
			jo = jo_list[0] if jo_list else None

		self.job_order_converting = jo or ""

	def _calculate_total_qty(self):
		"""Total Qty = Qty directly. BDL and Loose are informational only."""
		self.total_qty = flt(self.qty)

	def _validate_stock(self, warehouse):
		"""Ensure each component row has at least total_qty available in `warehouse`."""
		from erpnext.stock.utils import get_stock_balance

		for row in self.items:
			available = get_stock_balance(row.item_code, warehouse, self.posting_date)
			if available < flt(self.total_qty):
				frappe.throw(
					_(
						"Insufficient stock in {0} warehouse for {1}. "
						"Available: {2}, Required: {3}"
					).format(warehouse, row.item_code, available, flt(self.total_qty))
				)

	def _stock_uom(self, item_code):
		return frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

	# -------------------------------------------------------------------------
	# Stock & GL movement
	# -------------------------------------------------------------------------

	def _move_stock(self, from_warehouse, to_warehouse, remarks_prefix="Transfer"):
		"""Create SL + GL entries for all component rows in one warehouse movement.

		Stock is transferred at the source warehouse's current valuation rate so
		value is preserved across the move (no zero-rated receipts).
		"""
		rates = self._row_valuation(from_warehouse)
		sl_entries = self._build_sl_entries(from_warehouse, to_warehouse, rates=rates)
		if sl_entries:
			self.make_sl_entries(sl_entries)
		total_amount = sum(flt(self.total_qty) * rates.get(r.item_code, 0) for r in self.items)
		self._make_gl_entries(from_warehouse, to_warehouse, total_amount, remarks_prefix)

	def _row_valuation(self, warehouse):
		"""Return {item_code: valuation_rate} at `warehouse` for all component rows."""
		from erpnext.stock.utils import get_stock_balance

		rates = {}
		for row in self.items:
			if not row.item_code or row.item_code in rates:
				continue
			_qty, rate = get_stock_balance(
				row.item_code, warehouse, self.posting_date, with_valuation_rate=True
			)
			rates[row.item_code] = flt(rate)
		return rates

	def _build_sl_entries(self, from_warehouse, to_warehouse, cancel=False, rates=None):
		"""Return a list of SL entry dicts for all component rows.

		The incoming side is rated at the source warehouse's valuation rate so
		stock value is preserved across the transfer.

		When cancel=True the entries carry is_cancelled=1, which causes
		make_sl_entries() to call set_as_cancel() (marks originals) and then
		post proper reversal SLEs with updated stock balances.
		"""
		if rates is None:
			rates = self._row_valuation(from_warehouse)

		sl_entries = []
		for row in self.items:
			d = frappe._dict(
				item_code=row.item_code,
				uom=self._stock_uom(row.item_code),
			)
			out_entry = self.get_sl_entries(
				d,
				{
					"actual_qty": -flt(self.total_qty),
					"warehouse": from_warehouse,
				},
			)
			in_entry = self.get_sl_entries(
				d,
				{
					"actual_qty": flt(self.total_qty),
					"incoming_rate": rates.get(row.item_code, 0),
					"warehouse": to_warehouse,
				},
			)
			if cancel:
				out_entry["is_cancelled"] = 1
				in_entry["is_cancelled"] = 1
			sl_entries.extend([out_entry, in_entry])
		return sl_entries

	def _make_gl_entries(self, from_warehouse, to_warehouse, total_amount, remarks_prefix="Transfer"):
		import erpnext
		from erpnext.accounts.general_ledger import process_gl_map

		total_amount = flt(total_amount)
		if total_amount <= 0:
			return
		if not erpnext.is_perpetual_inventory_enabled(self.company):
			return

		source_account = frappe.get_cached_value("Warehouse", from_warehouse, "account")
		target_account = frappe.get_cached_value("Warehouse", to_warehouse, "account")

		if not source_account or not target_account or source_account == target_account:
			return

		remarks = _("{0}: {1}").format(remarks_prefix, self.name)
		d = frappe._dict(item_code=self.items[0].item_code if self.items else "")

		gl_entries = [
			# Dr target (asset increases)
			self.get_gl_dict(
				{
					"account": target_account,
					"against": source_account,
					"cost_center": self.cost_center,
					"debit": total_amount,
					"debit_in_account_currency": total_amount,
					"remarks": remarks,
				},
				item=d,
			),
			# Cr source (asset decreases)
			self.get_gl_dict(
				{
					"account": source_account,
					"against": target_account,
					"cost_center": self.cost_center,
					"credit": total_amount,
					"credit_in_account_currency": total_amount,
					"remarks": remarks,
				},
				item=d,
			),
		]

		gl_map = process_gl_map(gl_entries)
		if gl_map:
			self.make_gl_entries(gl_map)

	def _update_jo_produced_qty(self):
		if not self.job_order_converting:
			return
		try:
			jo = frappe.get_doc("Job Order Converting", self.job_order_converting)
			jo.update_produced_qty()
		except Exception:
			frappe.log_error(
				title="FGTS: failed to update Job Order Converting produced qty",
				message=frappe.get_traceback(),
			)


# ---------------------------------------------------------------------------
# Whitelisted API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_fgts_details(sales_order):
	"""Return a list of component options for a Sales Order.

	Fetches directly from SO Items (and Packed Items for bundle products).
	The caller (JS) adds each selected entry as a row in the FGTS Items child table.
	"""
	frappe.has_permission("FGTS", "read", throw=True)
	customer = frappe.db.get_value("Sales Order", sales_order, "customer")
	settings = frappe.get_cached_doc("IIB Settings")
	wip_wh = settings.default_wip_warehouse or ""
	fg_wh = settings.default_fg_warehouse or ""

	results = []

	# --- Packed Items (components of bundle/product bundle items) ---
	packed_rows = frappe.db.get_all(
		"Packed Item",
		{"parent": sales_order, "parenttype": "Sales Order"},
		["item_code", "item_name", "parent_detail_docname"],
		order_by="idx asc",
	)
	if packed_rows:
		for p in packed_rows:
			results.append(_build_entry(
				customer=customer,
				item_code=p.item_code,
				item_name=p.item_name or "",
				sales_order_item=p.parent_detail_docname or "",
				wip_warehouse=wip_wh,
				fg_warehouse=fg_wh,
			))
	else:
		# --- Sales Order Items directly ---
		so_items = frappe.db.get_all(
			"Sales Order Item",
			{"parent": sales_order},
			["name", "item_code", "item_name"],
			order_by="idx asc",
		)
		for item in so_items:
			results.append(_build_entry(
				customer=customer,
				item_code=item.item_code,
				item_name=item.item_name or "",
				sales_order_item=item.name,
				wip_warehouse=wip_wh,
				fg_warehouse=fg_wh,
			))

	return results


def _build_entry(customer, item_code, item_name, sales_order_item, wip_warehouse, fg_warehouse):
	"""Build a single FGTS-fill dict for one component.

	`sales_order_item` is the Sales Order Item row name this component traces to
	(for packed/bundle items this is the parent SO line, not the packed row).
	"""
	mc_item = frappe.db.get_value(
		"Master Card Item", {"item_code": item_code}, ["parent", "component"], as_dict=True
	)
	master_card = (mc_item or {}).get("parent") or ""
	component = (mc_item or {}).get("component") or ""

	return {
		"customer": customer,
		"item_code": item_code,
		"item_name": item_name,
		"sales_order_item": sales_order_item,
		"master_card": master_card,
		"component": component,
		"wip_warehouse": wip_warehouse,
		"fg_warehouse": fg_warehouse,
		"stores_warehouse": "Stores - IIB",
	}


@frappe.whitelist()
def get_items_warehouse_quantities(item_codes, posting_date):
	"""Batched stock balances (RM/WIP/FG/Stores) for many items in one call.

	`item_codes` is a JSON list. Returns
	{item_code: {rm_qty, wip_qty, fg_qty, stores_qty}}.
	"""
	from erpnext.stock.utils import get_stock_balance

	frappe.has_permission("FGTS", "read", throw=True)
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)

	settings = frappe.get_cached_doc("IIB Settings")
	rm_warehouse = settings.default_raw_material_warehouse or "Raw Material - IIB"
	wip_warehouse = settings.default_wip_warehouse or ""
	fg_warehouse = settings.default_fg_warehouse or ""
	stores_warehouse = "Stores - IIB"

	out = {}
	for item_code in dict.fromkeys(item_codes or []):
		out[item_code] = {
			"rm_qty": flt(get_stock_balance(item_code, rm_warehouse, posting_date)),
			"wip_qty": flt(get_stock_balance(item_code, wip_warehouse, posting_date)) if wip_warehouse else 0,
			"fg_qty": flt(get_stock_balance(item_code, fg_warehouse, posting_date)) if fg_warehouse else 0,
			"stores_qty": flt(get_stock_balance(item_code, stores_warehouse, posting_date)),
		}
	return out


@frappe.whitelist()
def approve_qc(name):
	"""Phase 2: FG → Stores. Called from the Approve QC button."""
	frappe.has_permission("FGTS", "write", throw=True)
	doc = frappe.get_doc("FGTS", name)

	if doc.docstatus != 1:
		frappe.throw(_("FGTS must be submitted"))
	if doc.status != "Waiting QC":
		frappe.throw(_("FGTS status must be 'Waiting QC' to approve"))

	doc._validate_stock(doc.fg_warehouse)
	doc._move_stock(doc.fg_warehouse, doc.stores_warehouse, "FG to Stores")
	doc.db_set("status", "OK QC")
	doc.db_set("fg_to_stores_done", 1)
	return "OK QC"
