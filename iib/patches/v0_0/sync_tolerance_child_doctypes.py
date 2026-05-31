import json
import os

import frappe


def execute():
	app_root = frappe.get_app_path("iib")  # …/apps/iib/iib/

	doctypes = [
		("iib_settings_corrugator_tolerance", "IIB Settings Corrugator Tolerance"),
		("iib_settings_converting_tolerance", "IIB Settings Converting Tolerance"),
	]

	for module_name, doctype_name in doctypes:
		path = os.path.join(
			app_root,
			"iib",
			"doctype",
			module_name,
			f"{module_name}.json",
		)

		# Check the actual DB record, bypassing any in-memory cache.
		exists_in_db = bool(
			frappe.db.sql("SELECT 1 FROM `tabDocType` WHERE name = %s", (doctype_name,))
		)

		if not exists_in_db:
			with open(path) as f:
				data = json.load(f)

			doc = frappe.get_doc(data)
			doc.flags.ignore_version = True
			doc.flags.ignore_permissions = True
			doc.flags.in_patch = True
			doc.insert(ignore_if_duplicate=True)
			frappe.db.commit()

	# Drop orphaned old-name tables (note: table_exists takes the DocType name, not the tab-prefixed name)
	for old_doctype in ("IIB Settings JOP1 Tolerance", "IIB Settings JOP2 Tolerance"):
		if frappe.db.table_exists(old_doctype):
			frappe.db.sql(f"DROP TABLE IF EXISTS `tab{old_doctype}`")
			frappe.db.commit()
