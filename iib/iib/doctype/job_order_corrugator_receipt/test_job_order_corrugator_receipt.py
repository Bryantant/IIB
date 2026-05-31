# Copyright (c) 2026, Hicom System and contributors
# For license information, please see license.txt

import types
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_receipt(rows):
	"""Return a minimal JobOrderCorrugatorReceipt instance with stubbed DB helpers."""
	from iib.iib.doctype.job_order_corrugator_receipt.job_order_corrugator_receipt import JobOrderCorrugatorReceipt

	doc = JobOrderCorrugatorReceipt.__new__(JobOrderCorrugatorReceipt)
	doc.name = "JOP1R-TEST-001"
	doc.docstatus = 0
	doc.items = [_make_row(**r) for r in rows]
	return doc


def _make_row(job_order_corrugator_item=None, qty=0):
	row = MagicMock()
	row.job_order_corrugator_item = job_order_corrugator_item
	row.qty = qty
	return row


def _corrugator_item(qty, received_qty, item_code="ITEM-A", parent="JOP1-001"):
	"""Return a plain dict matching the shape returned by _get_corrugator_item_data."""
	return {"qty": qty, "received_qty": received_qty, "item_code": item_code, "parent": parent}


def _stub(doc, tolerance_rows, item_data_map):
	"""Inject stub DB helpers onto *doc* so no Frappe context is needed.

	item_data_map: {corrugator_item_name: dict} or a single dict used for all names.
	"""
	doc._get_corrugator_tolerance_rows = lambda: tolerance_rows

	if isinstance(item_data_map, dict) and not any(
		isinstance(v, dict) for v in item_data_map.values()
	):
		# single flat dict → use for every name
		_data = item_data_map
		doc._get_corrugator_item_data = lambda name: _data
	else:
		doc._get_corrugator_item_data = lambda name: item_data_map.get(name)


# Shared tolerance presets
_NO_TOLERANCE = []
_TOLERANCE_5 = [{"corrugator_qty": 100, "corrugator_toleransi": 5}]


# ---------------------------------------------------------------------------
# Tests: validate_receipt_qty_vs_corrugator
# ---------------------------------------------------------------------------

class TestValidateReceiptQtyVsJop1(unittest.TestCase):
	"""Unit tests for the over-receipt guard (Points 1 & 3).

	All DB interactions are stubbed via instance-level helper overrides.
	``setUpClass`` binds ``frappe.local`` (reads site_config.json only;
	no DB connection is opened) so that ``frappe.throw()`` / ``frappe.bold()``
	work correctly in the blocked-scenario assertions.
	"""

	@classmethod
	def setUpClass(cls):
		import frappe
		frappe.init(
			site="iib.localhost",
			sites_path="/Users/bryantantonio/Dev/benchv15/sites",
		)

	@classmethod
	def tearDownClass(cls):
		import frappe
		frappe.destroy()

	# ------------------------------------------------------------------ #
	#  Basic pass / fail with no tolerance                                 #
	# ------------------------------------------------------------------ #

	def test_exact_qty_passes(self):
		"""Receiving exactly the ordered qty is allowed."""
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 10}])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=0))
		doc.validate_receipt_qty_vs_corrugator()  # must not raise

	def test_under_qty_passes(self):
		"""Receiving less than the pending qty is allowed."""
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 5}])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=3))
		doc.validate_receipt_qty_vs_corrugator()  # must not raise

	def test_over_qty_blocked_no_tolerance(self):
		"""Receiving 1 unit over the ordered qty is blocked when no tolerance is set."""
		import frappe
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 11}])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=0))
		self.assertRaises(frappe.ValidationError, doc.validate_receipt_qty_vs_corrugator)

	def test_partial_already_received_blocks_over_receipt(self):
		"""Already received 8 of 10 ordered; trying to receive 3 more is blocked."""
		import frappe
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 3}])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=8))
		self.assertRaises(frappe.ValidationError, doc.validate_receipt_qty_vs_corrugator)

	def test_partial_already_received_exact_remaining_passes(self):
		"""Already received 8 of 10 ordered; receiving exactly 2 more is allowed."""
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 2}])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=8))
		doc.validate_receipt_qty_vs_corrugator()  # must not raise

	# ------------------------------------------------------------------ #
	#  Tolerance in play                                                   #
	# ------------------------------------------------------------------ #

	def test_within_tolerance_passes(self):
		"""qty = ordered + tolerance (exactly at the ceiling) is allowed."""
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 15}])  # 10 + 5
		_stub(doc, _TOLERANCE_5, _corrugator_item(qty=10, received_qty=0))
		doc.validate_receipt_qty_vs_corrugator()  # must not raise

	def test_beyond_tolerance_blocked(self):
		"""qty = ordered + tolerance + 1 is blocked."""
		import frappe
		doc = _make_receipt([{"job_order_corrugator_item": "ROW-1", "qty": 16}])  # 10 + 5 + 1
		_stub(doc, _TOLERANCE_5, _corrugator_item(qty=10, received_qty=0))
		self.assertRaises(frappe.ValidationError, doc.validate_receipt_qty_vs_corrugator)

	# ------------------------------------------------------------------ #
	#  Multi-row aggregation                                               #
	# ------------------------------------------------------------------ #

	def test_two_rows_same_corrugator_item_aggregated_and_blocked(self):
		"""Two receipt rows for the same JO P1 Item are summed before checking.

		Each row (qty=6) would pass individually (ordered=10), but together (12)
		they exceed the ordered qty — must be blocked.
		"""
		import frappe
		doc = _make_receipt([
			{"job_order_corrugator_item": "ROW-1", "qty": 6},
			{"job_order_corrugator_item": "ROW-1", "qty": 6},
		])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=0))
		self.assertRaises(frappe.ValidationError, doc.validate_receipt_qty_vs_corrugator)

	def test_two_rows_same_corrugator_item_aggregated_and_passes(self):
		"""Two rows for the same JO P1 Item that sum to ≤ ordered qty pass."""
		doc = _make_receipt([
			{"job_order_corrugator_item": "ROW-1", "qty": 4},
			{"job_order_corrugator_item": "ROW-1", "qty": 6},
		])
		_stub(doc, _NO_TOLERANCE, _corrugator_item(qty=10, received_qty=0))
		doc.validate_receipt_qty_vs_corrugator()  # must not raise

	def test_two_different_corrugator_items_checked_independently(self):
		"""Rows for different JO P1 Items are checked independently.

		ROW-1: ordered 10, receive 10 → OK
		ROW-2: ordered 5,  receive 6  → blocked
		"""
		import frappe
		doc = _make_receipt([
			{"job_order_corrugator_item": "ROW-1", "qty": 10},
			{"job_order_corrugator_item": "ROW-2", "qty": 6},
		])
		item_map = {
			"ROW-1": _corrugator_item(qty=10, received_qty=0, item_code="ITEM-A"),
			"ROW-2": _corrugator_item(qty=5,  received_qty=0, item_code="ITEM-B"),
		}
		_stub(doc, _NO_TOLERANCE, item_map)
		self.assertRaises(frappe.ValidationError, doc.validate_receipt_qty_vs_corrugator)

	# ------------------------------------------------------------------ #
	#  Edge cases                                                          #
	# ------------------------------------------------------------------ #

	def test_rows_without_corrugator_item_are_skipped(self):
		"""A row with no job_order_corrugator_item must be silently ignored."""
		call_log = []
		doc = _make_receipt([{"job_order_corrugator_item": None, "qty": 999}])
		doc._get_corrugator_tolerance_rows = lambda: _NO_TOLERANCE
		doc._get_corrugator_item_data = lambda name: call_log.append(name) or {}
		doc.validate_receipt_qty_vs_corrugator()
		self.assertEqual(call_log, [], "_get_corrugator_item_data must not be called for unlinked rows")

	def test_missing_corrugator_item_record_is_skipped(self):
		"""If _get_corrugator_item_data returns None (deleted row), the check is skipped gracefully."""
		doc = _make_receipt([{"job_order_corrugator_item": "GHOST-ROW", "qty": 999}])
		doc._get_corrugator_tolerance_rows = lambda: _NO_TOLERANCE
		doc._get_corrugator_item_data = lambda name: None
		doc.validate_receipt_qty_vs_corrugator()  # must not raise


# ---------------------------------------------------------------------------
# Existing stubs (kept for future integration-test implementation)
# ---------------------------------------------------------------------------

class TestJobOrderCorrugatorReceipt(unittest.TestCase):
	def test_submit_creates_sle_at_basic_rate(self):
		pass

	def test_submit_creates_gl_entries_balanced(self):
		pass

	def test_cancel_reverses_sle_and_gl(self):
		pass

	def test_received_qty_propagates_to_corrugator(self):
		pass

	def test_get_corrugator_items_skips_fully_received(self):
		pass

	def test_validate_rejects_missing_expense_account(self):
		pass
