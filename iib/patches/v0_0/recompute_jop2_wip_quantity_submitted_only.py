# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt
"""Recompute custom_wip_quantity on Sales Order Item and Packed Item.

Previously this field counted ALL non-cancelled Job Order Converting allocations
(drafts + submitted). The semantics were tightened to submitted-only to
parallel JOP1's `custom_corrugator_qty`.

This patch zeroes the field on every row that has a non-zero value and
recomputes it from submitted Job Order Converting Sales Order Item rows.
"""

import frappe
from frappe.utils import flt


def execute():
	# Collect every SO-line reference that currently shows a non-zero allocation
	# on either parent doctype.
	affected_rows: dict = {}

	for doctype in ("Sales Order Item", "Packed Item"):
		if not frappe.db.has_column(doctype, "custom_wip_quantity"):
			continue
		rows = frappe.db.get_all(
			doctype,
			filters={"custom_wip_quantity": ["!=", 0]},
			pluck="name",
		)
		for name in rows:
			affected_rows.setdefault(doctype, []).append(name)

	# Also include any row referenced by a submitted JOP2 (even if its
	# current value is already 0 — the submitted-only sum may still differ).
	converting_refs = frappe.db.sql(
		"""
		SELECT DISTINCT josi.sales_order_item
		FROM `tabJob Order Converting Sales Order Item` josi
		JOIN `tabJob Order Converting` converting ON converting.name = josi.parent
		WHERE converting.docstatus = 1
		  AND josi.sales_order_item IS NOT NULL
		  AND josi.sales_order_item != ''
		""",
		as_dict=True,
	)
	pending_refs = [r.sales_order_item for r in converting_refs]

	# Classify each ref by its source doctype.
	for ref in pending_refs:
		if frappe.db.exists("Packed Item", ref):
			affected_rows.setdefault("Packed Item", []).append(ref)
		elif frappe.db.exists("Sales Order Item", ref):
			affected_rows.setdefault("Sales Order Item", []).append(ref)

	# Recompute each affected row's allocation from submitted JOP2s only.
	for doctype, names in affected_rows.items():
		for name in set(names):
			total = flt(
				frappe.db.sql(
					"""
					SELECT IFNULL(SUM(josi.qty), 0)
					FROM `tabJob Order Converting Sales Order Item` josi
					JOIN `tabJob Order Converting` converting ON converting.name = josi.parent
					WHERE josi.sales_order_item = %s
					  AND converting.docstatus = 1
					""",
					(name,),
				)[0][0]
			)
			frappe.db.set_value(
				doctype, name, "custom_wip_quantity", total, update_modified=False
			)

	frappe.db.commit()
