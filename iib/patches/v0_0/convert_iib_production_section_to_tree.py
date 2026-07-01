import frappe
from frappe.utils.nestedset import rebuild_tree


def execute():
	if not frappe.db.has_column("IIB Production Section", "is_group"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabIIB Production Section`
		SET is_group = 1
		WHERE IFNULL(is_group, 0) = 0
		"""
	)
	rebuild_tree("IIB Production Section", "parent_iib_production_section")
	frappe.clear_cache(doctype="IIB Production Section")
