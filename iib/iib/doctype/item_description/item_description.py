import frappe
from frappe import _
from frappe.model.document import Document


class ItemDescription(Document):
	def autoname(self):
		if not self.id:
			self.id = self._generate_id()
		self.name = self.id

	def _generate_id(self):
		description = (self.item_description or "").strip()
		if not description:
			frappe.throw(_("Item Description is required to generate ID"))
		prefix = description[0].upper()
		last = frappe.db.sql(
			"""select id from `tabItem Description`
			   where id like %s order by id desc limit 1""",
			(f"{prefix}%",),
		)
		next_number = 1
		if last and last[0][0][1:].isdigit():
			next_number = int(last[0][0][1:]) + 1
		return f"{prefix}{next_number:04d}"
