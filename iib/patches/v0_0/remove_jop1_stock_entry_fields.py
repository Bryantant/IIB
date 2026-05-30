import frappe


def execute():
	"""Remove obsolete Stock Entry links from the retired JOP1 Stock Entry flow."""
	for custom_field in (
		"Stock Entry-job_order_corrugator",
		"Stock Entry Detail-job_order_corrugator",
		"Stock Entry Detail-job_order_corrugator_item",
	):
		if frappe.db.exists("Custom Field", custom_field):
			frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)

	for doctype in ("Stock Entry", "Stock Entry Detail", "Job Order Corrugator"):
		frappe.clear_cache(doctype=doctype)
