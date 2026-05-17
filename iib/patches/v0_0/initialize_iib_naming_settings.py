import frappe


def execute():
	if not frappe.db.exists("DocType", "IIB Naming Settings"):
		return

	current = frappe.db.get_single_value("IIB Naming Settings", "master_card_next_number")
	if current:
		return

	max_code = frappe.db.sql(
		"""
		select max(cast(name as unsigned))
		from `tabItem`
		where item_group = 'Master Card'
			and name regexp '^[0-9]+$'
		"""
	)[0][0]

	next_number = int(max_code or 0) + 1
	frappe.db.set_single_value("IIB Naming Settings", "master_card_next_number", next_number)
