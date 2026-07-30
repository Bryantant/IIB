# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt
"""Backfill FG Item.item_name and Product Bundle Item.description with the
real Item Description text.

Master Card Item's `item_description` field is a Link to Item Description,
so its stored value is the linked docname (e.g. "D0001"), not the
human-readable text (e.g. "PLAIN D/C BOX"). Before this fix, Master Card's
`_sync_fg_items()`/`_create_product_bundle()` copied that raw docname
straight into Item.item_name and Product Bundle Item.description.

This patch only touches rows that currently hold the raw docname verbatim,
so any item_name/description a user has since customized by hand is left
alone.
"""

import frappe


def execute():
	fg_item_rows = frappe.db.sql(
		"""
		SELECT item.name AS item_code, idesc.item_description AS desc_text
		FROM `tabMaster Card Item` mci
		INNER JOIN `tabMaster Card` mc ON mc.name = mci.parent
		INNER JOIN `tabItem Description` idesc ON idesc.name = mci.item_description
		INNER JOIN `tabItem` item ON item.name = CONCAT(mc.name, UPPER(mci.component))
		WHERE mci.item_description IS NOT NULL
		  AND mci.item_description != ''
		  AND item.item_name = mci.item_description
		  AND item.item_name != idesc.item_description
		""",
		as_dict=True,
	)
	for row in fg_item_rows:
		frappe.db.set_value("Item", row.item_code, "item_name", row.desc_text, update_modified=False)

	bundle_item_rows = frappe.db.sql(
		"""
		SELECT pbi.name AS pbi_name, idesc.item_description AS desc_text
		FROM `tabProduct Bundle Item` pbi
		INNER JOIN `tabMaster Card` mc ON mc.item_code = pbi.parent
		INNER JOIN `tabMaster Card Item` mci
			ON mci.parent = mc.name AND CONCAT(mc.name, UPPER(mci.component)) = pbi.item_code
		INNER JOIN `tabItem Description` idesc ON idesc.name = mci.item_description
		WHERE mci.item_description IS NOT NULL
		  AND mci.item_description != ''
		  AND pbi.description = mci.item_description
		  AND pbi.description != idesc.item_description
		""",
		as_dict=True,
	)
	for row in bundle_item_rows:
		frappe.db.set_value(
			"Product Bundle Item", row.pbi_name, "description", row.desc_text, update_modified=False
		)

	frappe.db.commit()
