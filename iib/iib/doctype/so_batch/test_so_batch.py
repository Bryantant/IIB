from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from iib.iib.doctype.so_batch.so_batch import (
    SOBatch,
    get_expected_set_rate,
    get_master_card_price_map,
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
        ):
            SOBatch.set_validated_rates(doc)

        self.assertEqual(doc.so_batch_items[0].rate, 1.2345)

    def test_price_map_uses_highest_moq_not_exceeding_qty(self):
        rows = [
            frappe._dict({"moq_qty": 100, "component": "A", "total": 9.9999}),
            frappe._dict({"moq_qty": 50, "component": "A", "total": 1.2345}),
            frappe._dict({"moq_qty": 1, "component": "A", "total": 2.3456}),
        ]

        with patch("frappe.get_all", return_value=rows):
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
