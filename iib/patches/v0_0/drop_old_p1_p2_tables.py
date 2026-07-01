import frappe


def execute():
	"""Drop orphaned database tables left over from the P1/P2 → Corrugator/Converting rename.

	frappe.delete_doc removes the tabDocType metadata but leaves the physical table.
	These tables are safe to drop: no DocType records reference them and all data
	has been superseded by the renamed Corrugator/Converting tables.
	"""
	old_doctypes = [
		"Job Order P1 Receipt Item",
		"Job Order P1 Receipt",
		"Job Order P1 Item",
		"Job Order P1",
		"IIB Settings JOP1 Tolerance",
		"Job Order P2 Sales Order Item",
		"Job Order P2 RM to WIP Item",
		"Job Order P2 WIP to FG Item",
		"Job Order P2 RM to WIP",
		"Job Order P2 WIP to FG",
		"Job Order P2 Operation",
		"Job Order P2",
		"IIB Settings JOP2 Tolerance",
	]

	for doctype in old_doctypes:
		table = f"tab{doctype}"
		if frappe.db.table_exists(doctype):  # table_exists takes the doctype name, not tab-prefixed
			frappe.db.sql(f"DROP TABLE IF EXISTS `{table}`")

	frappe.db.commit()
