import json
import os

import frappe


def execute():
	app_root = frappe.get_app_path("iib")

	# Force the new doctypes into existence now, before the standard doctype-sync
	# step converts Colour.colour_group from Select to Table MultiSelect and drops
	# the old VARCHAR column — we need somewhere to copy the old values into first.
	for folder, doctype_name in (
		("colour_group", "Colour Group"),
		("colour_colour_group", "Colour Colour Group"),
	):
		if frappe.db.table_exists(doctype_name):
			continue
		path = os.path.join(app_root, "iib", "doctype", folder, f"{folder}.json")
		with open(path) as f:
			data = json.load(f)
		doc = frappe.get_doc(data)
		doc.flags.ignore_version = True
		doc.flags.ignore_permissions = True
		doc.flags.in_patch = True
		doc.insert(ignore_if_duplicate=True)
		frappe.db.commit()

	for i in range(1, 6):
		name = f"Colour {i}"
		if not frappe.db.exists("Colour Group", name):
			frappe.get_doc({"doctype": "Colour Group", "colour_group": name}).insert(
				ignore_permissions=True
			)
	frappe.db.commit()

	if not frappe.db.has_column("Colour", "colour_group"):
		return

	rows = frappe.db.sql(
		"""
		SELECT `name`, `colour_group` FROM `tabColour`
		WHERE `colour_group` IS NOT NULL AND `colour_group` != ''
		""",
		as_dict=True,
	)
	for row in rows:
		if frappe.db.exists(
			"Colour Colour Group", {"parent": row.name, "colour_group": row.colour_group}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Colour Colour Group",
				"parent": row.name,
				"parenttype": "Colour",
				"parentfield": "colour_group",
				"colour_group": row.colour_group,
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()
