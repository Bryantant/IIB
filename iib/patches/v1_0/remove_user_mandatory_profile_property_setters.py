import frappe


def execute():
	for name in (
		"User-module_profile-reqd",
		"User-role_profile_name-reqd",
	):
		if frappe.db.exists("Property Setter", name):
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="User")
