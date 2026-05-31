import json

import frappe
from frappe import _
from frappe.model.document import Document


class DailyProductionSchedule(Document):
	def validate(self):
		self._block_duplicate()
		self._update_last_update()
		if self.docstatus == 0:
			self.status = "Draft"

	def on_submit(self):
		self.db_set("status", "Confirmed")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def _block_duplicate(self):
		existing = frappe.db.get_value(
			"Daily Production Schedule",
			{
				"posting_date": self.posting_date,
				"section": self.section,
				"name": ["!=", self.name],
				"docstatus": ["!=", 2],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("A Daily Production Schedule already exists for {0} on {1}: {2}").format(
					self.section, self.posting_date, existing
				)
			)

	def _update_last_update(self):
		stamp = f"{frappe.session.user} {frappe.utils.now()}"
		for row in self.items or []:
			row.last_update = stamp


@frappe.whitelist()
def get_pending_jobs(section, posting_date, existing_jos=None):
	frappe.has_permission("Daily Production Schedule", "read", throw=True)
	exclude = json.loads(existing_jos) if existing_jos else []

	conditions = """
		jo.docstatus = 1
		AND jo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
		AND op.production_section = %(section)s
		AND op.status != 'Completed'
	"""
	params = {"section": section}
	if exclude:
		conditions += " AND jo.name NOT IN %(exclude)s"
		params["exclude"] = tuple(exclude)

	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT
			jo.name AS job_order_converting,
			jo.production_item AS item_code,
			jo.item_name,
			jo.master_card,
			jo.qty AS so_qty,
			jo.due_date
		FROM `tabJob Order Converting` jo
		JOIN `tabJob Order Converting Operation` op ON op.parent = jo.name
		WHERE {conditions}
		ORDER BY jo.due_date, jo.name
	""",
		params,
		as_dict=True,
	)

	results = []
	for jo in rows:
		so_row = frappe.db.get_value(
			"Job Order Converting Sales Order Item",
			{"parent": jo.job_order_converting, "parenttype": "Job Order Converting"},
			["sales_order", "customer", "delivery_date"],
			as_dict=True,
			order_by="idx asc",
		)

		mc_item = frappe.db.get_value(
			"Master Card Item",
			{"parent": jo.master_card, "item_code": jo.item_code},
			["custom_flute", "custom_colour_1", "custom_colour_2", "custom_colour_3",
			 "custom_colour_4", "custom_colour_5"],
			as_dict=True,
		) if jo.master_card and jo.item_code else {}

		colours = ""
		if mc_item:
			colour_parts = [
				mc_item.get(f"custom_colour_{i}") for i in range(1, 6)
				if mc_item.get(f"custom_colour_{i}")
			]
			colours = ", ".join(colour_parts)

		results.append({
			"job_order_converting": jo.job_order_converting,
			"item_code": jo.item_code,
			"item_name": jo.item_name or "",
			"master_card": jo.master_card or "",
			"customer": (so_row or {}).get("customer") or "",
			"so_no": (so_row or {}).get("sales_order") or "",
			"so_qty": jo.so_qty or 0,
			"due_date": (so_row or {}).get("delivery_date") or jo.due_date,
			"flute": (mc_item or {}).get("custom_flute") or "",
			"colours": colours,
		})
	return results
