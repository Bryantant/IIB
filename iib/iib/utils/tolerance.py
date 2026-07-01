# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt
"""Shared tolerance-lookup helper for Job Order Corrugator and P2 tiered tolerance tables.

The tolerance tables in IIB Settings are simple tiered lookups:

	corrugator_qty / converting_qty  →  corrugator_toleransi / converting_toleransi

The first tier whose Max-Qty is >= so_qty applies. If so_qty exceeds every
tier's Max, the last (highest) tier's tolerance is used.
"""

from __future__ import annotations

from frappe.utils import flt


def lookup_tolerance(tolerance_rows, so_qty, qty_field: str, tolerance_field: str) -> float:
	"""Return the tolerance amount for ``so_qty`` from a tiered tolerance table.

	``tolerance_rows`` must be pre-sorted ascending by ``qty_field``.

	- First tier where ``so_qty <= row[qty_field]`` → use that tier's
	  ``row[tolerance_field]``.
	- If ``so_qty`` exceeds every tier → use the last tier's
	  ``row[tolerance_field]``.
	- Empty input → ``0``.
	"""
	if not tolerance_rows:
		return 0.0
	for row in tolerance_rows:
		if flt(so_qty) <= flt(row.get(qty_field)):
			return flt(row.get(tolerance_field))
	return flt(tolerance_rows[-1].get(tolerance_field))
