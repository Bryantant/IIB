import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime


class ProductionProcess(Document):
	def validate(self):
		self._block_duplicate()
		self._validate_dps_section()
		self._validate_reject_uniqueness()
		self._resolve_operation_refs()
		self._compute_time_totals()
		self._update_row_logs()
		if self.docstatus == 0 and not self.status:
			self.status = "Draft"

	def on_update(self):
		# Write back completed_qty on every save (draft or submitted amendment)
		self._write_back_completed_qty()

	def on_submit(self):
		self.db_set("status", "Submitted")

	def on_cancel(self):
		# Re-aggregate so the cancelled PP's c_qty is excluded from JO operation totals.
		# By this point Frappe has already set docstatus=2 in the DB, so the sum
		# query in _write_back_completed_qty will naturally exclude this doc.
		self._write_back_completed_qty()
		self.db_set("status", "Cancelled")

	def _validate_dps_section(self):
		"""Ensure the linked Daily Production Schedule is for the same section as this PP."""
		if not self.daily_production_schedule or not self.section:
			return
		dps_section = frappe.db.get_value(
			"Daily Production Schedule", self.daily_production_schedule, "section"
		)
		if dps_section and dps_section != self.section:
			frappe.throw(
				_(
					"Daily Production Schedule {0} belongs to section {1}, "
					"but this Production Process is for section {2}."
				).format(
					frappe.bold(self.daily_production_schedule),
					frappe.bold(dps_section),
					frappe.bold(self.section),
				)
			)

	def _block_duplicate(self):
		existing = frappe.db.get_value(
			"Production Process",
			{
				"posting_date": self.posting_date,
				"section": self.section,
				"shift": self.shift,
				"name": ["!=", self.name],
				"docstatus": ["!=", 2],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("A Production Process already exists for {0} ({1}) on {2}: {3}").format(
					self.section, self.shift, self.posting_date, existing
				)
			)

	def _validate_reject_uniqueness(self):
		seen = set()
		for row in self.rejects or []:
			key = (row.job_order_converting or "", (row.reject_reason or "").strip())
			if key in seen:
				frappe.throw(
					_("Row {0}: Reject reason '{1}' already entered for Job Order {2}").format(
						row.idx, row.reject_reason, row.job_order_converting
					)
				)
			seen.add(key)

	def _resolve_operation_refs(self):
		if not self.section:
			return

		# Resolve the parent section group once (e.g. "FLEXO 1" → "FLEXO").
		# JO P2 operations store the group in `section`; `production_section` (the
		# leaf) is empty until a PP assigns it, so we must look up by group.
		section_group = (
			frappe.db.get_value(
				"IIB Production Section",
				self.section,
				"parent_iib_production_section",
			)
			or self.section
		)

		for row in self.items or []:
			if not row.job_order_converting:
				continue
			op_name = frappe.db.get_value(
				"Job Order Converting Operation",
				{
					"parent": row.job_order_converting,
					"parenttype": "Job Order Converting",
					"section": section_group,
				},
				"name",
			)
			row.job_order_converting_operation = op_name or ""

			# Stamp the leaf section onto the JO P2 operation so the Operations
			# table in JO P2 shows which machine handled it.
			if op_name:
				frappe.db.set_value(
					"Job Order Converting Operation",
					op_name,
					"production_section",
					self.section,
					update_modified=False,
				)

	def _compute_time_totals(self):
		for row in self.items or []:
			try:
				row.tot_s = (
					(get_datetime(row.t_sett) - get_datetime(row.t_start)).total_seconds()
					if row.t_start and row.t_sett
					else 0
				)
			except Exception:
				row.tot_s = 0
			try:
				row.tot_p = (
					(get_datetime(row.t_stop) - get_datetime(row.t_sett)).total_seconds()
					if row.t_sett and row.t_stop
					else 0
				)
			except Exception:
				row.tot_p = 0

	def _update_row_logs(self):
		stamp = f"{frappe.session.user} {frappe.utils.now()}"
		for row in self.items or []:
			if not row.created_log:
				row.created_log = stamp
			row.last_update = stamp

	def _write_back_completed_qty(self):
		"""Aggregate completed_qty from ALL non-cancelled Production Process docs for each
		(job_order_converting, operation) pair touched by this PP, then write the total back.

		Using a DB-level SUM (rather than this doc's c_qty alone) means:
		  - Multiple PP docs for the same operation accumulate correctly.
		  - Cancelling a PP re-aggregates and removes its contribution.
		  - Saving the same PP multiple times is idempotent.
		"""
		# Collect unique (jo_name, op_name) pairs referenced in this PP's items.
		pairs = set()
		for row in self.items or []:
			if row.job_order_converting and row.job_order_converting_operation:
				pairs.add((row.job_order_converting, row.job_order_converting_operation))

		if not pairs:
			return

		for jo_name, op_name in pairs:
			# Sum c_qty from ALL non-cancelled Production Process docs for this operation.
			# At on_update time this doc has docstatus=0/1 (included).
			# At on_cancel time Frappe has already set docstatus=2 (excluded). ✓
			total = flt(
				frappe.db.sql(
					"""
					SELECT IFNULL(SUM(ppi.c_qty), 0)
					FROM `tabProduction Process Item` ppi
					JOIN `tabProduction Process` pp ON pp.name = ppi.parent
					WHERE ppi.job_order_converting_operation = %s
					  AND pp.docstatus != 2
					""",
					(op_name,),
				)[0][0]
			)

			jo = frappe.get_doc("Job Order Converting", jo_name)
			for op in jo.operations or []:
				if op.name == op_name:
					op.db_set("completed_qty", total, update_modified=False)
					if total <= 0:
						op.db_set("status", "Pending", update_modified=False)
					elif total < flt(jo.qty):
						op.db_set("status", "In Progress", update_modified=False)
					else:
						op.db_set("status", "Completed", update_modified=False)
					break
			jo._refresh_header_status()


@frappe.whitelist()
def fetch_from_dps(daily_production_schedule):
	frappe.has_permission("Production Process", "read", throw=True)
	dps = frappe.get_doc("Daily Production Schedule", daily_production_schedule)

	# Resolve the section group once so we can look up operations by group
	# (leaf section is stamped onto the operation when the PP is saved, not before).
	dps_section_group = (
		frappe.db.get_value(
			"IIB Production Section",
			dps.section,
			"parent_iib_production_section",
		)
		or dps.section
	)

	results = []
	for row in dps.items or []:
		op_name = frappe.db.get_value(
			"Job Order Converting Operation",
			{
				"parent": row.job_order_converting,
				"parenttype": "Job Order Converting",
				"section": dps_section_group,
			},
			"name",
		)
		# Get JO qty for p_qty default (planned qty for this session starts at full JO qty)
		jo_qty = frappe.db.get_value("Job Order Converting", row.job_order_converting, "qty") or 0
		results.append({
			"job_order_converting": row.job_order_converting,
			"job_order_converting_operation": op_name or "",
			"item_code": row.item_code,
			"item_name": row.item_name or "",
			"master_card": row.master_card or "",
			"customer": row.customer or "",
			"so_no": row.so_no or "",
			"so_qty": row.so_qty or 0,
			"due_date": row.due_date,
			"p_qty": flt(jo_qty),
		})
	return results


@frappe.whitelist()
def get_jo_details(job_order_converting, section):
	frappe.has_permission("Production Process", "read", throw=True)
	jo = frappe.db.get_value(
		"Job Order Converting",
		job_order_converting,
		["production_item", "item_name", "master_card", "qty", "due_date"],
		as_dict=True,
	)
	if not jo:
		return {}

	so_row = frappe.db.get_value(
		"Job Order Converting Sales Order Item",
		{"parent": job_order_converting, "parenttype": "Job Order Converting"},
		["sales_order", "customer", "delivery_date"],
		as_dict=True,
		order_by="idx asc",
	)

	# Look up the operation by section group (the leaf section hasn't been stamped
	# onto the operation yet at this point — that happens in _resolve_operation_refs).
	section_group = (
		frappe.db.get_value(
			"IIB Production Section",
			section,
			"parent_iib_production_section",
		)
		or section
	)
	op_name = frappe.db.get_value(
		"Job Order Converting Operation",
		{"parent": job_order_converting, "parenttype": "Job Order Converting", "section": section_group},
		"name",
	)

	return {
		"item_code": jo.production_item,
		"item_name": jo.item_name or "",
		"master_card": jo.master_card or "",
		"customer": (so_row or {}).get("customer") or "",
		"so_no": (so_row or {}).get("sales_order") or "",
		"so_qty": jo.qty or 0,
		"due_date": (so_row or {}).get("delivery_date") or jo.due_date,
		"job_order_converting_operation": op_name or "",
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_job_orders_for_section(doctype, txt, searchfield, start, page_len, filters):
	"""Return submitted JO P2s whose operations include the *group* that the given
	leaf section belongs to.

	Production Process stores a leaf section (e.g. "FLEXO 1") in its header.
	JO P2 operations store the parent group (e.g. "FLEXO") in the `section` column.
	We resolve the group via `parent_iib_production_section` so the filter matches
	operations even though `production_section` is not yet filled on the JO P2.
	"""
	section = (filters or {}).get("section") or ""
	return frappe.db.sql(
		"""
		SELECT DISTINCT jo.name, jo.production_item
		FROM `tabJob Order Converting` jo
		JOIN `tabJob Order Converting Operation` op ON op.parent = jo.name
		WHERE jo.docstatus = 1
		  AND op.section = (
		      SELECT parent_iib_production_section
		      FROM `tabIIB Production Section`
		      WHERE name = %(section)s
		  )
		  AND (jo.name LIKE %(txt)s OR jo.production_item LIKE %(txt)s)
		ORDER BY jo.name
		LIMIT %(start)s, %(page_len)s
		""",
		{"section": section, "txt": f"%{txt}%", "start": start, "page_len": page_len},
	)
