import frappe


def execute():
	"""Drop obsolete columns removed from Production Process Item and Daily Production Schedule Item.

	Removed fields:
	  - Production Process Item: rmr, sr  (undefined float fields, never used)
	  - Daily Production Schedule Item: proc_qty, run_qty, waktu  (planning stubs, never implemented)
	"""
	_drop_column_if_exists("Production Process Item", "rmr")
	_drop_column_if_exists("Production Process Item", "sr")
	_drop_column_if_exists("Daily Production Schedule Item", "proc_qty")
	_drop_column_if_exists("Daily Production Schedule Item", "run_qty")
	_drop_column_if_exists("Daily Production Schedule Item", "waktu")

	for doctype in ("Production Process Item", "Daily Production Schedule Item"):
		frappe.clear_cache(doctype=doctype)


def _drop_column_if_exists(doctype, fieldname):
	table = f"tab{doctype}"
	if frappe.db.has_column(doctype, fieldname):
		frappe.db.sql(f"ALTER TABLE `{table}` DROP COLUMN `{fieldname}`")  # nosec
