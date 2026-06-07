"""Shared completed-qty aggregation for Job Order Converting operations.

A JO operation's `completed_qty` is the sum of `c_qty` across every non-cancelled
Production Process Item that references it. Both the Production Process controller
(on save/cancel) and the JOP2 "refresh operations" action need this exact logic, so
it lives here to stay in one place.
"""

import frappe
from frappe.utils import flt


def aggregate_operation_completed_qty(op_name: str) -> float:
	"""Sum c_qty across all non-cancelled Production Process Items for one JO operation."""
	if not op_name:
		return 0.0
	return flt(
		frappe.db.sql(
			"""
			SELECT IFNULL(SUM(ppi.c_qty), 0)
			FROM `tabProduction Process Item` ppi
			JOIN `tabProduction Process` pp ON pp.name = ppi.parent
			WHERE ppi.job_order_converting_operation = %s
			  AND pp.docstatus != 2
			""",
			(op_name,),
		)[0][0]
	)


def operation_status_for_qty(total, jo_qty) -> str:
	"""Tier an operation's status from its completed total against the JO qty."""
	total = flt(total)
	if total <= 0:
		return "Pending"
	if total < flt(jo_qty):
		return "In Progress"
	return "Completed"


def write_back_operation_qty(op_name: str, jo_qty) -> float:
	"""Aggregate and persist completed_qty + status for one operation. Returns the total."""
	total = aggregate_operation_completed_qty(op_name)
	frappe.db.set_value(
		"Job Order Converting Operation",
		op_name,
		{"completed_qty": total, "status": operation_status_for_qty(total, jo_qty)},
		update_modified=False,
	)
	return total
