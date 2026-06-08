import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_timedelta, getdate


class ProductionProcess(Document):
	def autoname(self):
		from iib.iib.utils.naming import get_next_iib_number

		d = getdate(self.posting_date or frappe.utils.today())
		yymm = d.strftime("%y%m")
		seq = get_next_iib_number("pp", period=yymm, digits=4)
		self.name = f"{yymm}{seq}"

	def validate(self):
		self._block_duplicate()
		self._resolve_dps()
		self._validate_dps_section()
		self._validate_reject_uniqueness()
		self._validate_reject_totals()
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

	def _resolve_dps(self):
		"""Auto-fill the Daily Production Schedule link from (section, DPS Date). The link is
		read-only — the user picks a date and we resolve the unique DPS for that section+date."""
		if self.section and self.dps_date:
			self.daily_production_schedule = get_dps_for(self.section, self.dps_date) or ""
		else:
			self.daily_production_schedule = ""

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
		if not self.sn:
			return
		existing = frappe.db.get_value(
			"Production Process",
			{
				"posting_date": self.posting_date,
				"section": self.section,
				"sn": self.sn,
				"name": ["!=", self.name],
				"docstatus": ["!=", 2],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("A Production Process already exists for {0} SN {1} on {2}: {3}").format(
					self.section, self.sn, self.posting_date, existing
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

	def _validate_reject_totals(self):
		"""On submit, the Reject table (reason breakdown) must reconcile per Job Order to
		that JO's total reject = sum of item-row RMR + SR. Enforced only at submit so drafts
		can be saved mid-entry."""
		if self.docstatus != 1:
			return

		reject_total_by_jo = {}
		for row in self.items or []:
			if not row.job_order_converting:
				continue
			reject_total_by_jo[row.job_order_converting] = (
				reject_total_by_jo.get(row.job_order_converting, 0)
				+ flt(row.rmr)
				+ flt(row.sr)
			)

		reason_total_by_jo = {}
		for row in self.rejects or []:
			if not row.job_order_converting:
				continue
			reason_total_by_jo[row.job_order_converting] = (
				reason_total_by_jo.get(row.job_order_converting, 0) + flt(row.qty)
			)

		for jo in set(reject_total_by_jo) | set(reason_total_by_jo):
			expected = flt(reject_total_by_jo.get(jo, 0))
			entered = flt(reason_total_by_jo.get(jo, 0))
			if expected != entered:
				frappe.throw(
					_(
						"Job Order {0}: reject reasons total {1} must equal RMR + SR total {2}."
					).format(frappe.bold(jo), entered, expected)
				)

	def _resolve_operation_refs(self):
		if not self.section:
			return

		for row in self.items or []:
			if not row.job_order_converting:
				continue
			op_name = frappe.db.get_value(
				"Job Order Converting Operation",
				{
					"parent": row.job_order_converting,
					"parenttype": "Job Order Converting",
					"production_section": self.section,
				},
				"name",
			)
			if not op_name:
				frappe.throw(
					_(
						"Row {0}: Job Order {1} has no operation for section {2} — "
						"its production cannot be recorded here."
					).format(
						row.idx,
						frappe.bold(row.job_order_converting),
						frappe.bold(self.section),
					)
				)
			row.job_order_converting_operation = op_name

	@staticmethod
	def _time_diff_seconds(start, end):
		"""Seconds between two time-only values. Adds 24h when the end wraps past
		midnight (e.g. night shift 23:00 → 01:00) so the duration stays positive."""
		if not (start and end):
			return 0
		try:
			seconds = (get_timedelta(end) - get_timedelta(start)).total_seconds()
		except Exception:
			return 0
		if seconds < 0:
			seconds += 86400
		return seconds

	def _compute_time_totals(self):
		for row in self.items or []:
			row.tot_s = self._time_diff_seconds(row.t_start, row.t_sett)
			row.tot_p = self._time_diff_seconds(row.t_sett, row.t_stop)

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

		At on_update time this doc has docstatus=0/1 (included in the SUM); at on_cancel
		Frappe has already set docstatus=2, so it is excluded. ✓
		"""
		from iib.iib.utils.operation_qty import write_back_operation_qty

		# Collect unique (jo_name, op_name) pairs referenced in this PP's items.
		pairs = set()
		for row in self.items or []:
			if row.job_order_converting and row.job_order_converting_operation:
				pairs.add((row.job_order_converting, row.job_order_converting_operation))

		if not pairs:
			return

		jos_touched = set()
		for jo_name, op_name in pairs:
			jo_qty = frappe.db.get_value("Job Order Converting", jo_name, "qty")
			write_back_operation_qty(op_name, jo_qty)
			jos_touched.add(jo_name)

		# Reload each touched JO so its operations reflect the just-written statuses,
		# then recompute the header status.
		for jo_name in jos_touched:
			frappe.get_doc("Job Order Converting", jo_name)._refresh_header_status()


def get_dps_for(section, dps_date):
	"""The unique Daily Production Schedule for a section on a given date, or None.
	(DPS enforces one document per section + posting_date.)"""
	if not (section and dps_date):
		return None
	return frappe.db.get_value(
		"Daily Production Schedule",
		{"section": section, "posting_date": dps_date},
		"name",
		order_by="creation desc",
	)


@frappe.whitelist()
def resolve_dps(section, dps_date):
	"""Client helper: resolve the DPS name for (section, date) to auto-fill the link."""
	frappe.has_permission("Production Process", "read", throw=True)
	return get_dps_for(section, dps_date)


@frappe.whitelist()
def fetch_from_dps(daily_production_schedule=None, section=None, dps_date=None):
	frappe.has_permission("Production Process", "read", throw=True)
	if not daily_production_schedule and section and dps_date:
		daily_production_schedule = get_dps_for(section, dps_date)
	if not daily_production_schedule:
		return []
	dps = frappe.get_doc("Daily Production Schedule", daily_production_schedule)

	results = []
	for row in dps.items or []:
		op_name = frappe.db.get_value(
			"Job Order Converting Operation",
			{
				"parent": row.job_order_converting,
				"parenttype": "Job Order Converting",
				"production_section": dps.section,
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

	op_name = frappe.db.get_value(
		"Job Order Converting Operation",
		{"parent": job_order_converting, "parenttype": "Job Order Converting", "production_section": section},
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
	section = (filters or {}).get("section") or ""
	item_code = (filters or {}).get("item_code") or ""
	return frappe.db.sql(
		"""
		SELECT DISTINCT jo.name, jo.production_item
		FROM `tabJob Order Converting` jo
		JOIN `tabJob Order Converting Operation` op ON op.parent = jo.name
		WHERE jo.docstatus = 1
		  AND jo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
		  AND op.production_section = %(section)s
		  AND (%(item_code)s = '' OR jo.production_item = %(item_code)s)
		  AND (jo.name LIKE %(txt)s OR jo.production_item LIKE %(txt)s)
		ORDER BY jo.name
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"section": section,
			"item_code": item_code,
			"txt": f"%{txt}%",
			"start": start,
			"page_len": page_len,
		},
	)
