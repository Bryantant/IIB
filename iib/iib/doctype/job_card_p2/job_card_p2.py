import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, time_diff_in_seconds


class JobCardP2(Document):
	def validate(self):
		self.compute_time_log_totals()
		self.validate_completed_vs_for_quantity()

	def before_submit(self):
		self.validate_unique_per_machine_day()
		if not self.time_logs:
			frappe.throw(_("Add at least one Time Log row before submitting"))
		self.status = "Completed"

	def on_submit(self):
		self.db_set("status", "Submitted")
		self._notify_job_order("submit")

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		self._notify_job_order("cancel")

	# ---- compute helpers ----

	def compute_time_log_totals(self):
		total_mins = 0.0
		total_qty = 0.0
		for row in self.time_logs:
			if row.from_time and row.to_time:
				secs = time_diff_in_seconds(row.to_time, row.from_time)
				if secs < 0:
					frappe.throw(
						_("Time Log row {0}: To Time must be after From Time").format(row.idx)
					)
				row.time_in_mins = round(secs / 60.0, 2)
			else:
				row.time_in_mins = 0
			total_mins += flt(row.time_in_mins)
			total_qty += flt(row.completed_qty)
		self.total_time_in_mins = round(total_mins, 2)
		self.total_completed_qty = total_qty

	def validate_completed_vs_for_quantity(self):
		reject_qty = sum(flt(r.reject_qty) for r in (self.rejects or []))
		max_allowed = flt(self.for_quantity) + reject_qty
		if flt(self.total_completed_qty) > max_allowed and self.for_quantity:
			frappe.throw(
				_(
					"Total completed qty ({0}) exceeds For Quantity ({1}) plus rejects ({2})"
				).format(self.total_completed_qty, self.for_quantity, reject_qty)
			)

	def validate_unique_per_machine_day(self):
		clash = frappe.db.sql(
			"""
			SELECT name FROM `tabJob Card P2`
			WHERE posting_date = %(d)s
			  AND section = %(s)s
			  AND machine_no = %(m)s
			  AND docstatus = 1
			  AND name != %(self)s
			LIMIT 1
			""",
			{
				"d": self.posting_date,
				"s": self.section,
				"m": self.machine_no,
				"self": self.name or "",
			},
			as_dict=True,
		)
		if clash:
			frappe.throw(
				_("Another Job Card P2 already exists for {0} on {1} machine {2}: {3}").format(
					self.section, self.posting_date, self.machine_no, clash[0].name
				)
			)

	# ---- Job Order P2 rollup ----

	def _notify_job_order(self, action):
		if not self.job_order_p2 or not self.job_order_p2_operation:
			return
		jo = frappe.get_doc("Job Order P2", self.job_order_p2)
		jo.update_operation_completed_qty(self.job_order_p2_operation)
