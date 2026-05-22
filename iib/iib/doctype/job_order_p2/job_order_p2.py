import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class JobOrderP2(Document):
	def before_validate(self):
		# Reset operations if production_item changed
		if not self.is_new() and self.has_value_changed("production_item"):
			self.operations = []

	def validate(self):
		self.fetch_item_metadata()
		self.resolve_master_card()
		self.set_warehouse_defaults()
		self.validate_so_items_match_production_item()
		self.resolve_operations_from_master_card()
		self.compute_rollup_fields()
		if self.docstatus == 0 and not self.status:
			self.status = "Draft"

	def before_submit(self):
		self.validate_operations_exist()
		self.validate_so_items_exist()

	def on_submit(self):
		self.db_set("status", "In Process")
		self.create_job_cards()
		self.create_and_submit_material_transfer_se()

	def before_cancel(self):
		self.guard_against_submitted_job_cards()
		self.guard_against_submitted_stock_entries()

	def on_cancel(self):
		self.delete_draft_job_cards()
		self.db_set("status", "Cancelled")
		self.db_set("created_job_cards", "")
		if self.production_plan_p2:
			plan = frappe.get_doc("Production Plan P2", self.production_plan_p2)
			plan.recompute_produced_qty()

	# ---- validation helpers ----

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

	def validate_so_items_exist(self):
		if not self.sales_order_items:
			frappe.throw(
				_("At least one Sales Order Item is required before submitting Job Order P2")
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
		if not self.master_card or not self.production_item:
			return
		mc = frappe.get_cached_doc("Master Card", self.master_card)
		component_letter = None
		for row in mc.items:
			if row.item_code == self.production_item:
				component_letter = (row.component or "").upper()
				break
		if not component_letter:
			return
		processes = sorted(
			[p for p in (mc.processes or []) if (p.component or "").upper() == component_letter],
			key=lambda p: p.sequence,
		)
		for p in processes:
			self.append(
				"operations",
				{
					"sequence": p.sequence,
					"section": p.section,
					"est_time_mins": p.est_time_mins,
					"description": p.description,
					"status": "Pending",
					"completed_qty": 0,
				},
			)

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
		so_item_names = [r.sales_order_item for r in self.sales_order_items if r.sales_order_item]
		if not so_item_names:
			return 0
		placeholders = ", ".join(["%s"] * len(so_item_names))
		total = frappe.db.sql(
			f"""
			SELECT IFNULL(SUM(dni.qty), 0) AS qty
			FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 1
			  AND dni.so_detail IN ({placeholders})
			""",
			tuple(so_item_names),
		)[0][0]
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

	# ---- Job Card auto-creation ----

	def create_job_cards(self):
		created = []
		for op in self.operations:
			jc = frappe.new_doc("Job Card P2")
			jc.company = self.company
			jc.posting_date = nowdate()
			jc.job_order_p2 = self.name
			jc.job_order_p2_operation = op.name
			jc.production_item = self.production_item
			jc.master_card = self.master_card
			jc.section = op.section
			jc.for_quantity = self.qty
			jc.status = "Open"
			jc.insert(ignore_permissions=True)
			created.append(jc.name)
		if created:
			self.db_set("created_job_cards", "\n".join(created))

	# ---- Auto-submitted Material Transfer Stock Entry ----

	def create_and_submit_material_transfer_se(self):
		"""On submit: move production_item from Raw Material warehouse -> WIP warehouse."""
		settings = frappe.get_cached_doc("IIB Settings")
		source = settings.default_raw_material_warehouse
		if not source:
			frappe.throw(
				_(
					"Set Raw Material Warehouse in IIB Settings before submitting Job Order P2"
				)
			)
		if not self.wip_warehouse:
			frappe.throw(_("WIP Warehouse not set"))
		if flt(self.qty) <= 0:
			frappe.throw(_("Qty to Convert must be greater than 0"))

		stock_uom = frappe.db.get_value("Item", self.production_item, "stock_uom")

		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Transfer"
		se.purpose = "Material Transfer"
		se.company = self.company
		se.posting_date = self.posting_date or nowdate()
		se.from_warehouse = source
		se.to_warehouse = self.wip_warehouse
		se.iib_job_order_p2 = self.name
		se.append(
			"items",
			{
				"item_code": self.production_item,
				"qty": flt(self.qty),
				"transfer_qty": flt(self.qty),
				"uom": stock_uom,
				"stock_uom": stock_uom,
				"conversion_factor": 1,
				"s_warehouse": source,
				"t_warehouse": self.wip_warehouse,
			},
		)
		se.insert(ignore_permissions=True)
		try:
			se.submit()
		except Exception as e:
			frappe.log_error(
				title="JO P2 Material Transfer auto-submit failed",
				message=f"JO: {self.name}, SE: {se.name}, Error: {e}",
			)
			frappe.throw(
				_("Failed to auto-submit Material Transfer Stock Entry {0}: {1}").format(
					se.name, str(e)
				)
			)
		self.db_set("transfer_stock_entry", se.name)

	# ---- cancel guards ----

	def guard_against_submitted_job_cards(self):
		submitted = frappe.db.sql(
			"""
			SELECT name FROM `tabJob Card P2`
			WHERE job_order_p2 = %s AND docstatus = 1
			""",
			(self.name,),
			as_dict=True,
		)
		if submitted:
			names = [r.name for r in submitted]
			frappe.throw(
				_("Cannot cancel: submitted Job Card P2 exist: {0}. Cancel them first.").format(
					", ".join(names)
				)
			)

	def guard_against_submitted_stock_entries(self):
		# Exclude the transfer SE attached to this JO — we will cancel it as part of cancel logic if needed
		submitted = frappe.db.get_all(
			"Stock Entry",
			filters={"iib_job_order_p2": self.name, "docstatus": 1},
			pluck="name",
		)
		# Allow cancel if the only submitted SE is the transfer SE — but require user to cancel manually first
		if submitted:
			frappe.throw(
				_(
					"Cannot cancel: submitted Stock Entries exist for this Job Order: {0}. "
					"Cancel them manually first."
				).format(", ".join(submitted))
			)

	def delete_draft_job_cards(self):
		drafts = frappe.db.sql(
			"""
			SELECT name FROM `tabJob Card P2`
			WHERE job_order_p2 = %s AND docstatus = 0
			""",
			(self.name,),
			as_dict=True,
		)
		for r in drafts:
			frappe.delete_doc("Job Card P2", r.name, ignore_permissions=True, force=True)

	# ---- Operation rollup (called from Job Card P2 submit/cancel) ----

	def update_operation_completed_qty(self, operation_row_name):
		"""Recompute completed_qty + status for one operation row from submitted Job Cards."""
		total = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(total_completed_qty), 0) AS qty
			FROM `tabJob Card P2`
			WHERE job_order_p2 = %s
			  AND job_order_p2_operation = %s
			  AND docstatus = 1
			""",
			(self.name, operation_row_name),
		)[0][0]
		for op in self.operations:
			if op.name == operation_row_name:
				op.db_set("completed_qty", flt(total), update_modified=False)
				if flt(total) <= 0:
					op.db_set("status", "Pending", update_modified=False)
				elif flt(total) < flt(self.qty):
					op.db_set("status", "In Progress", update_modified=False)
				else:
					op.db_set("status", "Completed", update_modified=False)
				break
		self._refresh_header_status()

	def _refresh_header_status(self):
		if self.docstatus != 1 or self.status in ("Cancelled", "Stopped", "Closed"):
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

	# ---- Stock Entry rollup (called from Stock Entry submit/cancel hook) ----

	def update_produced_qty(self):
		"""Recompute produced_qty from submitted Stock Entries (WIP -> FG only)."""
		total = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(sed.transfer_qty), 0) AS qty
			FROM `tabStock Entry Detail` sed
			JOIN `tabStock Entry` se ON se.name = sed.parent
			WHERE se.iib_job_order_p2 = %s
			  AND se.docstatus = 1
			  AND sed.item_code = %s
			  AND IFNULL(sed.t_warehouse, '') = %s
			""",
			(self.name, self.production_item, self.fg_warehouse or ""),
		)[0][0]
		self.db_set("produced_qty", flt(total), update_modified=False)
		# Update derived jo_qty_in_process
		jo_qty_in_process = max(flt(self.qty) - flt(total), 0)
		self.db_set("jo_qty_in_process", jo_qty_in_process, update_modified=False)
		if self.production_plan_p2:
			plan = frappe.get_doc("Production Plan P2", self.production_plan_p2)
			plan.recompute_produced_qty()


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def make_finish_stock_entry(source_name):
	"""Build a draft Stock Entry to transfer the FG item from WIP -> FG Warehouse."""
	jo = frappe.get_doc("Job Order P2", source_name)
	if jo.docstatus != 1:
		frappe.throw(_("Job Order P2 must be submitted before Set Finish"))
	if jo.status in ("Cancelled", "Stopped", "Closed"):
		frappe.throw(_("Job Order P2 is {0}; cannot Set Finish").format(jo.status))

	pending = flt(jo.qty) - flt(jo.produced_qty)
	if pending <= 0:
		frappe.throw(_("Nothing left to finish for this Job Order P2"))

	stock_uom = frappe.db.get_value("Item", jo.production_item, "stock_uom")

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = jo.company
	se.from_warehouse = jo.wip_warehouse
	se.to_warehouse = jo.fg_warehouse
	se.iib_job_order_p2 = jo.name
	se.append(
		"items",
		{
			"item_code": jo.production_item,
			"qty": pending,
			"transfer_qty": pending,
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": 1,
			"s_warehouse": jo.wip_warehouse,
			"t_warehouse": jo.fg_warehouse,
		},
	)
	return se.as_dict()


@frappe.whitelist()
def make_return_components(source_name):
	"""Build a draft Stock Entry to return un-consumed material from WIP -> Raw Material warehouse."""
	jo = frappe.get_doc("Job Order P2", source_name)
	if jo.docstatus != 1:
		frappe.throw(_("Job Order P2 must be submitted before Return Components"))

	in_process = flt(jo.qty) - flt(jo.produced_qty)
	if in_process <= 0:
		frappe.throw(_("No quantity in WIP to return"))

	settings = frappe.get_cached_doc("IIB Settings")
	target = settings.default_raw_material_warehouse
	if not target:
		frappe.throw(_("Set Raw Material Warehouse in IIB Settings"))

	stock_uom = frappe.db.get_value("Item", jo.production_item, "stock_uom")

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = jo.company
	se.from_warehouse = jo.wip_warehouse
	se.to_warehouse = target
	se.iib_job_order_p2 = jo.name
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
	"""Stop / Re-open / Close a submitted Job Order P2."""
	frappe.has_permission("Job Order P2", "submit", doc=name, throw=True)
	if status not in ("Stopped", "In Process", "Completed", "Closed"):
		frappe.throw(_("Invalid status transition: {0}").format(status))
	jo = frappe.get_doc("Job Order P2", name)
	if jo.docstatus != 1:
		frappe.throw(_("Only submitted Job Order P2 can transition status"))
	jo.db_set("status", status)
	return jo.status


@frappe.whitelist()
def get_sales_orders_for_jo(production_item, customer=None, from_date=None, to_date=None):
	"""Return open Sales Order Items matching a given MC Component."""
	if not production_item:
		frappe.throw(_("MC Component is required"))
	filters = ["so.docstatus = 1", "so.status NOT IN ('Stopped','Closed','Cancelled')"]
	values = []
	filters.append("soi.item_code = %s")
	values.append(production_item)
	filters.append("(soi.qty - IFNULL(soi.delivered_qty, 0)) > 0")
	if customer:
		filters.append("so.customer = %s")
		values.append(customer)
	if from_date:
		filters.append("so.transaction_date >= %s")
		values.append(from_date)
	if to_date:
		filters.append("so.transaction_date <= %s")
		values.append(to_date)
	where = " AND ".join(filters)
	rows = frappe.db.sql(
		f"""
		SELECT
		    so.name AS sales_order,
		    soi.name AS sales_order_item,
		    soi.item_code,
		    (soi.qty - IFNULL(soi.delivered_qty, 0)) AS open_qty,
		    soi.delivery_date,
		    so.customer,
		    so.status AS so_status,
		    so.transaction_date
		FROM `tabSales Order Item` soi
		JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE {where}
		ORDER BY soi.delivery_date ASC, so.name ASC
		""",
		tuple(values),
		as_dict=True,
	)
	return rows
