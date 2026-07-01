from frappe.tests.utils import FrappeTestCase


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
