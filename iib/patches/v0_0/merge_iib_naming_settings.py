import frappe


FIELDS = [
	"master_card_next_number",
	"fg_item_group",
	"sub_assembly_item_group",
	"component_item_group",
	"default_uom",
	"mc_bundle_item_group",
	"mc_fg_item_group",
]


def execute():
	if not frappe.db.exists("DocType", "IIB Naming Settings"):
		return

	for field in FIELDS:
		value = frappe.db.get_single_value("IIB Naming Settings", field)
		if value:
			frappe.db.set_single_value("IIB Settings", field, value)
