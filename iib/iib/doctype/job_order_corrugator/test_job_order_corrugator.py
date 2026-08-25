import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from iib.iib.doctype.job_order_corrugator.job_order_corrugator import (
	JobOrderCorrugator,
	compute_available_qty,
	get_so_items_for_corrugator_dialog,
)


class TestJobOrderCorrugator(FrappeTestCase):
	def test_status_transitions_with_partial_receipt(self):
		"""Submit JOP1 -> partial SE -> Partially Received; full SE -> Completed."""
		self.skipTest("TODO: seed SO + items, exercise full flow")

	def test_cancel_blocked_by_submitted_stock_entry(self):
		"""before_cancel must throw when a submitted Stock Entry links back."""
		self.skipTest("TODO: seed SE submit, attempt JOP1 cancel, assert throw")

	def test_make_stock_entry_skips_fully_received_rows(self):
		"""get_mapped_doc condition should exclude rows where pending_qty <= 0."""
		self.skipTest("TODO: stage row with received_qty == qty, call make_stock_entry, assert excluded")

	def test_validate_rejects_duplicate_so_line(self):
		"""Two rows referencing same Sales Order Item must error on validate."""
		self.skipTest("TODO: insert duplicate sales_order_item rows, expect frappe.ValidationError")


class TestJobOrderCorrugatorFCAvailability(FrappeTestCase):
	"""Qty Avail = Qty - Qty FC Matched: FC rows shrink as General POs claim
	them, General rows always stay at their raw ordered qty (see the SO Batch
	Jenis PO feature in so_batch.py for where custom_fc_matched_qty /
	custom_fc_coverage_note come from). The picker exposes ``closed_qty``
	(= custom_fc_matched_qty, display only) alongside ``available_qty`` (the
	value actually used for row exclusion and copied into the JO P1 on
	selection).

	Note: the top-level Sales Order/JobOrderCorrugator stand-ins use
	SimpleNamespace, not frappe._dict, because both real objects expose an
	``items`` child-table attribute -- and frappe._dict is a plain dict
	subclass, so ``.items`` on a frappe._dict resolves to dict's own builtin
	``items()`` method instead of our child-row list. Leaf rows (SO Item /
	Packed Item stand-ins) stay as frappe._dict since the code under test
	calls ``.get(...)`` on them, which frappe._dict supports natively.
	"""

	def test_compute_available_qty(self):
		self.assertEqual(compute_available_qty(70800, 60800), 10000)
		self.assertEqual(compute_available_qty(70800, 70800), 0)
		self.assertEqual(compute_available_qty(70800, 0), 70800)
		self.assertEqual(compute_available_qty(70800, None), 70800)
		self.assertEqual(compute_available_qty(100, 150), 0)

	def test_dialog_excludes_fully_matched_fc_row(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-24",
			po_no="FC",
			items=[
				frappe._dict(
					{
						"name": "SOI-FC-1",
						"item_code": "ITEM-A",
						"item_name": "Item A",
						"description": "",
						"uom": "Pcs",
						"qty": 70800,
						"delivery_date": "2026-08-30",
						"custom_fc_matched_qty": 70800,
						"custom_corrugator_qty": 0,
						"custom_fc_coverage_note": None,
					}
				)
			],
		)
		with patch("frappe.get_doc", return_value=so), patch("frappe.get_all", return_value=[]):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-FC-1"]))
		self.assertEqual(rows, [])

	def test_dialog_reduces_partially_matched_fc_row(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-24",
			po_no="FC",
			items=[
				frappe._dict(
					{
						"name": "SOI-FC-1",
						"item_code": "ITEM-A",
						"item_name": "Item A",
						"description": "",
						"uom": "Pcs",
						"qty": 70800,
						"delivery_date": "2026-08-30",
						"custom_fc_matched_qty": 60800,
						"custom_corrugator_qty": 0,
						"custom_fc_coverage_note": None,
					}
				)
			],
		)
		with patch("frappe.get_doc", return_value=so), patch("frappe.get_all", return_value=[]):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-FC-1"]))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["po_no"], "FC")
		self.assertEqual(rows[0]["qty"], 70800)
		self.assertEqual(rows[0]["closed_qty"], 60800)
		self.assertEqual(rows[0]["available_qty"], 10000)
		self.assertEqual(rows[0]["remark"], "")
		self.assertEqual(rows[0]["item_name"], "Item A")

	def test_dialog_keeps_fully_covered_general_row_at_full_qty(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-25",
			po_no="ZZTEST-PO-1",
			items=[
				frappe._dict(
					{
						"name": "SOI-GEN-1",
						"item_code": "ITEM-A",
						"item_name": "Item A",
						"description": "",
						"uom": "Pcs",
						"qty": 60800,
						"delivery_date": "2026-08-31",
						"custom_fc_matched_qty": None,
						"custom_corrugator_qty": 0,
						"custom_fc_coverage_note": "Clear",
					}
				)
			],
		)
		with patch("frappe.get_doc", return_value=so), patch("frappe.get_all", return_value=[]):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-GEN-1"]))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["po_no"], "ZZTEST-PO-1")
		self.assertEqual(rows[0]["qty"], 60800)
		self.assertEqual(rows[0]["closed_qty"], 0)
		self.assertEqual(rows[0]["available_qty"], 60800)
		self.assertEqual(rows[0]["remark"], "Clear")

	def test_dialog_keeps_partially_covered_general_row_at_full_qty(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-25",
			po_no="ZZTEST-PO-2",
			items=[
				frappe._dict(
					{
						"name": "SOI-GEN-2",
						"item_code": "ITEM-A",
						"item_name": "Item A",
						"description": "",
						"uom": "Pcs",
						"qty": 90000,
						"delivery_date": "2026-08-31",
						"custom_fc_matched_qty": None,
						"custom_corrugator_qty": 0,
						"custom_fc_coverage_note": "Ord. 19,200",
					}
				)
			],
		)
		with patch("frappe.get_doc", return_value=so), patch("frappe.get_all", return_value=[]):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-GEN-2"]))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["po_no"], "ZZTEST-PO-2")
		self.assertEqual(rows[0]["qty"], 90000)
		self.assertEqual(rows[0]["closed_qty"], 0)
		self.assertEqual(rows[0]["available_qty"], 90000)
		self.assertEqual(rows[0]["remark"], "Ord. 19,200")

	def test_dialog_bundle_fc_row_excluded_when_fully_matched(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-24",
			po_no="FC",
			items=[
				frappe._dict(
					{
						"name": "SOI-FC-SET",
						"item_code": "SET-A",
						"qty": 100,
						"delivery_date": "2026-08-30",
					}
				)
			],
		)
		packed_items = [{"item_code": "COMP-A", "description": "", "qty_per_bundle": 2}]
		packed_row = frappe._dict(
			{
				"qty": 200,
				"custom_corrugator_qty": 0,
				"custom_fc_matched_qty": 200,
				"custom_fc_coverage_note": None,
			}
		)
		with patch("frappe.get_doc", return_value=so), patch(
			"frappe.get_all", return_value=packed_items
		), patch(
			"frappe.db.get_value",
			return_value={"item_name": "Comp A", "stock_uom": "Pcs"},
		), patch(
			"iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_packed_item_fc_row",
			return_value=packed_row,
		):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-FC-SET"]))
		self.assertEqual(rows, [])

	def test_dialog_bundle_general_row_unaffected(self):
		so = SimpleNamespace(
			docstatus=1,
			customer="CUST-1",
			transaction_date="2026-08-25",
			po_no="ZZTEST-PO-3",
			items=[
				frappe._dict(
					{
						"name": "SOI-GEN-SET",
						"item_code": "SET-A",
						"qty": 100,
						"delivery_date": "2026-08-31",
					}
				)
			],
		)
		packed_items = [{"item_code": "COMP-A", "description": "", "qty_per_bundle": 2}]
		packed_row = frappe._dict(
			{
				"qty": 200,
				"custom_corrugator_qty": 0,
				"custom_fc_matched_qty": None,
				"custom_fc_coverage_note": "Clear",
			}
		)
		with patch("frappe.get_doc", return_value=so), patch(
			"frappe.get_all", return_value=packed_items
		), patch(
			"frappe.db.get_value",
			return_value={"item_name": "Comp A", "stock_uom": "Pcs"},
		), patch(
			"iib.iib.doctype.job_order_corrugator.job_order_corrugator.get_packed_item_fc_row",
			return_value=packed_row,
		):
			rows = get_so_items_for_corrugator_dialog(json.dumps(["SO-GEN-SET"]))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["po_no"], "ZZTEST-PO-3")
		self.assertEqual(rows[0]["qty"], 200)
		self.assertEqual(rows[0]["closed_qty"], 0)
		self.assertEqual(rows[0]["available_qty"], 200)
		self.assertEqual(rows[0]["remark"], "Clear")

	def test_validate_corrugator_tolerance_fc_row_blocked_beyond_available_qty(self):
		fake_self = SimpleNamespace(
			name="IIB26TEST1",
			items=[
				frappe._dict({"sales_order_item": "SOI-FC-1", "item_code": "ITEM-A", "qty": 15000}),
			],
		)
		tolerance_rows = [{"corrugator_qty": 100000, "corrugator_toleransi": 500}]
		so_data = frappe._dict(
			{
				"parent": "SO-FC-1",
				"qty": 70800,
				"item_code": "ITEM-A",
				"custom_corrugator_qty": 0,
				"custom_fc_matched_qty": 60800,
			}
		)
		with patch("frappe.get_all", return_value=tolerance_rows), patch(
			"frappe.db.get_value", return_value=so_data
		), patch("frappe.db.exists", return_value=False):
			self.assertRaises(
				frappe.ValidationError, JobOrderCorrugator.validate_corrugator_tolerance, fake_self
			)

	def test_validate_corrugator_tolerance_fc_row_passes_within_available_qty(self):
		fake_self = SimpleNamespace(
			name="IIB26TEST2",
			items=[
				frappe._dict({"sales_order_item": "SOI-FC-1", "item_code": "ITEM-A", "qty": 9000}),
			],
		)
		tolerance_rows = [{"corrugator_qty": 100000, "corrugator_toleransi": 500}]
		so_data = frappe._dict(
			{
				"parent": "SO-FC-1",
				"qty": 70800,
				"item_code": "ITEM-A",
				"custom_corrugator_qty": 0,
				"custom_fc_matched_qty": 60800,
			}
		)
		with patch("frappe.get_all", return_value=tolerance_rows), patch(
			"frappe.db.get_value", return_value=so_data
		), patch("frappe.db.exists", return_value=False):
			JobOrderCorrugator.validate_corrugator_tolerance(fake_self)

	def test_validate_corrugator_tolerance_general_row_unaffected(self):
		fake_self = SimpleNamespace(
			name="IIB26TEST3",
			items=[
				frappe._dict({"sales_order_item": "SOI-GEN-1", "item_code": "ITEM-A", "qty": 62000}),
			],
		)
		tolerance_rows = [{"corrugator_qty": 100000, "corrugator_toleransi": 500}]
		so_data = frappe._dict(
			{
				"parent": "SO-GEN-1",
				"qty": 60800,
				"item_code": "ITEM-A",
				"custom_corrugator_qty": 0,
				"custom_fc_matched_qty": None,
			}
		)
		with patch("frappe.get_all", return_value=tolerance_rows), patch(
			"frappe.db.get_value", return_value=so_data
		), patch("frappe.db.exists", return_value=False):
			self.assertRaises(
				frappe.ValidationError, JobOrderCorrugator.validate_corrugator_tolerance, fake_self
			)
