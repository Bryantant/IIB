from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from iib.iib.doctype.so_batch.so_batch import (
    SOBatch,
    assert_sales_order_has_no_downstream_documents,
    close_fc_sales_order_if_fully_covered,
    consume_fc_for_row,
    format_remark_qty,
    get_expected_set_rate,
    get_master_card_price_map,
    get_outstanding_fc_rows,
    is_so_item_fully_covered,
    reopen_fc_sales_order_if_no_longer_covered,
    resolve_match_info,
)


class TestSOBatch(FrappeTestCase):
    def test_blank_rate_is_filled_from_expected_rate(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "so_batch_items": [{"qty": 10, "rate": 0, "part_no": "TEST-PART"}],
            }
        )

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_expected_rate_for_so_batch_row",
            return_value=(1.2345, {}),
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_rate_precision",
            return_value=4,
        ):
            SOBatch.set_validated_rates(doc)

        self.assertEqual(doc.so_batch_items[0].rate, 1.2345)

    def test_positive_mismatched_rate_is_blocked(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "so_batch_items": [{"qty": 10, "rate": 1.2344, "part_no": "TEST-PART"}],
            }
        )

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_expected_rate_for_so_batch_row",
            return_value=(1.2345, {}),
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_rate_precision",
            return_value=4,
        ):
            self.assertRaises(frappe.ValidationError, SOBatch.set_validated_rates, doc)

    def test_positive_matching_rate_is_normalized_to_currency_precision(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "so_batch_items": [{"qty": 10, "rate": 1.2345, "part_no": "TEST-PART"}],
            }
        )

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_expected_rate_for_so_batch_row",
            return_value=(1.2345, {}),
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_rate_precision",
            return_value=4,
        ):
            SOBatch.set_validated_rates(doc)

        self.assertEqual(doc.so_batch_items[0].rate, 1.2345)

    def test_price_map_uses_highest_moq_not_exceeding_qty(self):
        moq_rows = [
            frappe._dict({"idx": 1, "moq_qty": 100}),
            frappe._dict({"idx": 2, "moq_qty": 50}),
            frappe._dict({"idx": 3, "moq_qty": 1}),
        ]
        price_item_rows = [
            frappe._dict({"moq_idx": 1, "component": "A", "total": 9.9999}),
            frappe._dict({"moq_idx": 2, "component": "A", "total": 1.2345}),
            frappe._dict({"moq_idx": 3, "component": "A", "total": 2.3456}),
        ]

        with patch("frappe.get_all", side_effect=[moq_rows, price_item_rows]):
            price_map, moq_qty = get_master_card_price_map("MC-TEST", 75, 1)

        self.assertEqual(moq_qty, 50)
        self.assertEqual(price_map, {"A": 1.2345})

    def test_set_rate_sums_component_prices_using_bundle_qty(self):
        bundle_items = [
            frappe._dict({"item_code": "MC-TEST-A", "qty": 2}),
            frappe._dict({"item_code": "MC-TEST-B", "qty": 3}),
        ]

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_for_set_item",
            return_value="MC-TEST",
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_price_map",
            return_value=({"A": 1.1111, "B": 2.2222}, 50),
        ), patch(
            "frappe.get_all",
            return_value=bundle_items,
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_components_by_item",
            return_value={"MC-TEST-A": "A", "MC-TEST-B": "B"},
        ):
            expected_rate, component_rates = get_expected_set_rate("MC-TEST", 75, 1)

        self.assertEqual(expected_rate, 8.8888)
        self.assertEqual(component_rates, {"MC-TEST-A": 1.1111, "MC-TEST-B": 2.2222})

    def test_fc_row_forces_po_no_and_po_date(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "transaction_date": "2026-06-01",
                "so_batch_items": [
                    {
                        "po_type": "FC",
                        "po_no": "whatever",
                        "po_date": "2026-05-01",
                        "line_no": "1",
                    }
                ],
            }
        )

        SOBatch.validate_po_types(doc)

        self.assertEqual(doc.so_batch_items[0].po_no, "FC")
        self.assertEqual(getdate(doc.so_batch_items[0].po_date), getdate("2026-06-01"))

    def test_general_row_rejects_reserved_po_no(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "transaction_date": "2026-06-01",
                "so_batch_items": [
                    {
                        "po_type": "General",
                        "po_no": "fc",
                        "po_date": "2026-06-01",
                        "line_no": "1",
                    }
                ],
            }
        )

        self.assertRaises(frappe.ValidationError, SOBatch.validate_po_types, doc)

    def test_general_po_no_is_untouched_when_not_reserved(self):
        doc = frappe.get_doc(
            {
                "doctype": "SO Batch",
                "transaction_date": "2026-06-01",
                "so_batch_items": [
                    {
                        "po_type": "General",
                        "po_no": "PO-12345",
                        "po_date": "2026-06-01",
                        "line_no": "1",
                    }
                ],
            }
        )

        SOBatch.validate_po_types(doc)

        self.assertEqual(doc.so_batch_items[0].po_no, "PO-12345")

    def test_resolve_match_info_for_pcs_row(self):
        row = frappe._dict({"set_or_pcs": "Pcs", "resolved_item_code": "ITEM-A", "idx": 1})

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_component_for_item",
            return_value=("MC-TEST", "A"),
        ):
            master_card, components = resolve_match_info(row)

        self.assertEqual(master_card, "MC-TEST")
        self.assertEqual(components, {"ITEM-A": "A"})

    def test_resolve_match_info_for_set_row_only_includes_bundle_items(self):
        row = frappe._dict({"set_or_pcs": "Set", "resolved_set_item_code": "SET-A", "idx": 1})

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_for_set_item",
            return_value="MC-TEST",
        ), patch(
            "iib.iib.doctype.so_batch.so_batch.get_master_card_components_by_item",
            return_value={"ITEM-A": "A", "ITEM-B": "B", "ITEM-UNRELATED": "C"},
        ), patch(
            "frappe.get_all",
            return_value=["ITEM-A", "ITEM-B"],
        ):
            master_card, components = resolve_match_info(row)

        self.assertEqual(master_card, "MC-TEST")
        self.assertEqual(components, {"ITEM-A": "A", "ITEM-B": "B"})

    def test_consume_fc_for_row_covers_partially_across_two_fc_rows(self):
        fc_rows = [
            {
                "doctype": "Sales Order Item",
                "name": "SOI-OLD",
                "sales_order": "SO-FC-1",
                "qty": 10,
                "delivered_qty": 0,
                "matched_qty": 0,
            },
            {
                "doctype": "Packed Item",
                "name": "PI-NEW",
                "sales_order": "SO-FC-2",
                "qty": 20,
                "delivered_qty": 0,
                "matched_qty": 0,
            },
        ]

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_outstanding_fc_rows",
            return_value=fc_rows,
        ), patch("frappe.db.set_value") as mock_set_value, patch("frappe.get_doc") as mock_get_doc:
            covered, note, touched = consume_fc_for_row("SO-NEW", "MC-TEST", "A", 25)

        self.assertEqual(covered, 25)
        self.assertEqual(note, "Clear")
        self.assertEqual(touched, {"SO-FC-1", "SO-FC-2"})
        mock_set_value.assert_any_call(
            "Sales Order Item", "SOI-OLD", "custom_fc_matched_qty", 10, update_modified=False
        )
        mock_set_value.assert_any_call(
            "Packed Item", "PI-NEW", "custom_fc_matched_qty", 15, update_modified=False
        )
        self.assertEqual(mock_get_doc.call_count, 2)

    def test_consume_fc_for_row_reports_remaining_when_fc_insufficient(self):
        fc_rows = [
            {
                "doctype": "Sales Order Item",
                "name": "SOI-OLD",
                "sales_order": "SO-FC-1",
                "qty": 10,
                "delivered_qty": 0,
                "matched_qty": 0,
            },
        ]

        with patch(
            "iib.iib.doctype.so_batch.so_batch.get_outstanding_fc_rows",
            return_value=fc_rows,
        ), patch("frappe.db.set_value"), patch("frappe.get_doc"):
            covered, note, touched = consume_fc_for_row("SO-NEW", "MC-TEST", "A", 25)

        self.assertEqual(covered, 10)
        self.assertEqual(note, "Ord. 15")
        self.assertEqual(touched, {"SO-FC-1"})

    def test_get_outstanding_fc_rows_merges_and_sorts_by_transaction_date(self):
        so_item_result = [
            {
                "doctype": "Sales Order Item",
                "name": "SOI-LATER",
                "qty": 5,
                "delivered_qty": 0,
                "matched_qty": 0,
                "transaction_date": "2026-06-10",
                "so_creation": "2026-06-10 09:00:00",
            }
        ]
        packed_item_result = [
            {
                "doctype": "Packed Item",
                "name": "PI-EARLIER",
                "qty": 5,
                "delivered_qty": 0,
                "matched_qty": 0,
                "transaction_date": "2026-06-01",
                "so_creation": "2026-06-01 09:00:00",
            }
        ]

        with patch("frappe.db.sql", side_effect=[so_item_result, packed_item_result]):
            rows = get_outstanding_fc_rows("MC-TEST", "A")

        self.assertEqual([r["name"] for r in rows], ["PI-EARLIER", "SOI-LATER"])

    def test_get_outstanding_fc_rows_breaks_same_day_ties_by_creation(self):
        """Two FC SOs entered on the same business day must not sort in an
        arbitrary order -- the one actually created first in the system
        (creation timestamp) should be consumed first."""
        so_item_result = [
            {
                "doctype": "Sales Order Item",
                "name": "SOI-AFTERNOON",
                "qty": 5,
                "delivered_qty": 0,
                "matched_qty": 0,
                "transaction_date": "2026-06-10",
                "so_creation": "2026-06-10 15:00:00",
            },
            {
                "doctype": "Sales Order Item",
                "name": "SOI-MORNING",
                "qty": 5,
                "delivered_qty": 0,
                "matched_qty": 0,
                "transaction_date": "2026-06-10",
                "so_creation": "2026-06-10 08:00:00",
            },
        ]

        with patch("frappe.db.sql", side_effect=[so_item_result, []]):
            rows = get_outstanding_fc_rows("MC-TEST", "A")

        self.assertEqual([r["name"] for r in rows], ["SOI-MORNING", "SOI-AFTERNOON"])

    def test_is_so_item_fully_covered_for_direct_component_row(self):
        so = frappe._dict({"packed_items": []})
        fully_covered_item = frappe._dict(
            {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 10}
        )
        partial_item = frappe._dict(
            {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 6}
        )

        self.assertTrue(is_so_item_fully_covered(so, fully_covered_item))
        self.assertFalse(is_so_item_fully_covered(so, partial_item))

    def test_is_so_item_fully_covered_for_bundle_row_checks_all_packed_items(self):
        bundle_item = frappe._dict(
            {"custom_master_card": None, "custom_component": None, "name": "SOI-BUNDLE", "qty": 10}
        )
        so_all_covered = frappe._dict(
            {
                "packed_items": [
                    frappe._dict(
                        {"parent_detail_docname": "SOI-BUNDLE", "qty": 10, "custom_fc_matched_qty": 10}
                    ),
                    frappe._dict(
                        {"parent_detail_docname": "SOI-BUNDLE", "qty": 5, "custom_fc_matched_qty": 5}
                    ),
                ]
            }
        )
        so_partially_covered = frappe._dict(
            {
                "packed_items": [
                    frappe._dict(
                        {"parent_detail_docname": "SOI-BUNDLE", "qty": 10, "custom_fc_matched_qty": 10}
                    ),
                    frappe._dict(
                        {"parent_detail_docname": "SOI-BUNDLE", "qty": 5, "custom_fc_matched_qty": 2}
                    ),
                ]
            }
        )
        so_no_packed_items = frappe._dict({"packed_items": []})

        self.assertTrue(is_so_item_fully_covered(so_all_covered, bundle_item))
        self.assertFalse(is_so_item_fully_covered(so_partially_covered, bundle_item))
        self.assertFalse(is_so_item_fully_covered(so_no_packed_items, bundle_item))

    def test_close_fc_sales_order_if_fully_covered_closes_when_all_items_covered(self):
        fake_so = MagicMock()
        fake_so.docstatus = 1
        fake_so.po_type = "FC"
        fake_so.status = "To Deliver and Bill"
        fake_so.items = [
            frappe._dict(
                {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 10}
            )
        ]
        fake_so.packed_items = []

        with patch("frappe.get_doc", return_value=fake_so):
            close_fc_sales_order_if_fully_covered("SO-FC-1")

        fake_so.update_status.assert_called_once_with("Closed")

    def test_close_fc_sales_order_if_fully_covered_skips_when_not_fully_covered(self):
        fake_so = MagicMock()
        fake_so.docstatus = 1
        fake_so.po_type = "FC"
        fake_so.status = "To Deliver and Bill"
        fake_so.items = [
            frappe._dict(
                {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 6}
            )
        ]
        fake_so.packed_items = []

        with patch("frappe.get_doc", return_value=fake_so):
            close_fc_sales_order_if_fully_covered("SO-FC-1")

        fake_so.update_status.assert_not_called()

    def test_close_fc_sales_order_if_fully_covered_skips_general_and_already_closed(self):
        for po_type, status in [("General", "To Deliver and Bill"), ("FC", "Closed"), ("FC", "Cancelled")]:
            fake_so = MagicMock()
            fake_so.docstatus = 1
            fake_so.po_type = po_type
            fake_so.status = status
            fake_so.items = [
                frappe._dict(
                    {
                        "custom_master_card": "MC-1",
                        "custom_component": "A",
                        "qty": 10,
                        "custom_fc_matched_qty": 10,
                    }
                )
            ]
            fake_so.packed_items = []

            with patch("frappe.get_doc", return_value=fake_so):
                close_fc_sales_order_if_fully_covered("SO-FC-1")

            fake_so.update_status.assert_not_called()

    def test_reopen_fc_sales_order_if_no_longer_covered_reopens_when_partial(self):
        fake_so = MagicMock()
        fake_so.docstatus = 1
        fake_so.status = "Closed"
        fake_so.items = [
            frappe._dict(
                {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 4}
            )
        ]
        fake_so.packed_items = []

        with patch("frappe.get_doc", return_value=fake_so):
            reopen_fc_sales_order_if_no_longer_covered("SO-FC-1")

        fake_so.update_status.assert_called_once_with("Draft")

    def test_reopen_fc_sales_order_if_no_longer_covered_skips_when_still_fully_covered(self):
        fake_so = MagicMock()
        fake_so.docstatus = 1
        fake_so.status = "Closed"
        fake_so.items = [
            frappe._dict(
                {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 10}
            )
        ]
        fake_so.packed_items = []

        with patch("frappe.get_doc", return_value=fake_so):
            reopen_fc_sales_order_if_no_longer_covered("SO-FC-1")

        fake_so.update_status.assert_not_called()

    def test_reopen_fc_sales_order_if_no_longer_covered_skips_when_not_closed(self):
        fake_so = MagicMock()
        fake_so.docstatus = 1
        fake_so.status = "To Deliver and Bill"
        fake_so.items = [
            frappe._dict(
                {"custom_master_card": "MC-1", "custom_component": "A", "qty": 10, "custom_fc_matched_qty": 4}
            )
        ]
        fake_so.packed_items = []

        with patch("frappe.get_doc", return_value=fake_so):
            reopen_fc_sales_order_if_no_longer_covered("SO-FC-1")

        fake_so.update_status.assert_not_called()

    def test_assert_sales_order_has_no_downstream_documents_passes_when_clean(self):
        with patch("frappe.db.count", return_value=0):
            assert_sales_order_has_no_downstream_documents("SO-1")

    def test_assert_sales_order_has_no_downstream_documents_blocks_when_referenced(self):
        with patch("frappe.db.count", side_effect=[0, 0, 2, 0]):
            self.assertRaises(
                frappe.ValidationError, assert_sales_order_has_no_downstream_documents, "SO-1"
            )

    def test_format_remark_qty_strips_decimal_noise_and_groups_thousands(self):
        self.assertEqual(format_remark_qty(29200.0), "29,200")
        self.assertEqual(format_remark_qty(500), "500")
        self.assertEqual(format_remark_qty(1234.5), "1,234.5")
        self.assertEqual(format_remark_qty(2000.0), "2,000")
