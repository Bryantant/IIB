import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, time_diff_in_seconds


class JobCardP2(Document):
	def validate(self):
		self.set_sections_from_job_order_operation()
		self.compute_time_log_totals()
		self.validate_completed_vs_for_quantity()
		self.validate_section_group()
		self.validate_leaf_section(require_section=False)

	def before_submit(self):
		self.validate_leaf_section(require_section=True)
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

	def validate_section_group(self):
		if not self.section_group:
			return
		group = frappe.db.get_value(
			"IIB Production Section",
			self.section_group,
			["is_group", "disabled"],
			as_dict=True,
		)
		if not group:
			frappe.throw(_("Section Group {0} does not exist").format(self.section_group))
		if group.disabled or not group.is_group:
			frappe.throw(_("Section Group must be an enabled group section"))

	def validate_leaf_section(self, require_section=True):
		if not self.section:
			if require_section:
				frappe.throw(
					_(
						"Set Production Section on the linked Job Order P2 Operation before submitting Job Card P2"
					)
				)
			return

		section = frappe.db.get_value(
			"IIB Production Section",
			self.section,
			["is_group", "disabled", "lft", "rgt"],
			as_dict=True,
		)
		if not section:
			frappe.throw(_("Production Section {0} does not exist").format(self.section))
		if section.disabled or section.is_group:
			frappe.throw(_("Production Section must be an enabled detail section"))

		if not self.section_group:
			return

		group = frappe.db.get_value(
			"IIB Production Section",
			self.section_group,
			["is_group", "disabled", "lft", "rgt"],
			as_dict=True,
		)
		if not group:
			frappe.throw(_("Section Group {0} does not exist").format(self.section_group))
		if group.disabled or not group.is_group:
			frappe.throw(_("Section Group must be an enabled group section"))
		if not (section.lft > group.lft and section.rgt < group.rgt):
			frappe.throw(
				_("Production Section {0} must be under Section Group {1}").format(
					self.section, self.section_group
				)
			)

	def set_sections_from_job_order_operation(self):
		if not self.job_order_p2 or not self.job_order_p2_operation:
			return

		operation = frappe.db.get_value(
			"Job Order P2 Operation",
			{"name": self.job_order_p2_operation, "parent": self.job_order_p2},
			["section", "production_section"],
			as_dict=True,
		)
		if not operation:
			return

		if operation.section:
			self.section_group = operation.section
		if operation.production_section:
			self.section = operation.production_section

	# ---- Job Order P2 rollup ----

	def _notify_job_order(self, action):
		if not self.job_order_p2 or not self.job_order_p2_operation:
			return
		jo = frappe.get_doc("Job Order P2", self.job_order_p2)
		jo.update_operation_completed_qty(self.job_order_p2_operation)
