import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class IIBProductionSection(NestedSet):
	nsm_parent_field = "parent_iib_production_section"

	def validate(self):
		if not self.parent_iib_production_section:
			return

		parent = frappe.db.get_value(
			"IIB Production Section",
			self.parent_iib_production_section,
			["is_group", "disabled"],
			as_dict=True,
		)
		if not parent:
			frappe.throw(_("Parent Production Section {0} does not exist").format(self.parent_iib_production_section))
		if not parent.is_group:
			frappe.throw(_("Parent Production Section must be a group"))
		if parent.disabled:
			frappe.throw(_("Parent Production Section {0} is disabled").format(self.parent_iib_production_section))

	def on_update(self):
		NestedSet.on_update(self)

	def on_trash(self):
		NestedSet.on_trash(self, allow_root_deletion=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_section_leaf_query(doctype, txt, searchfield, start, page_len, filters):
	conditions = [
		"disabled = 0",
		"is_group = 0",
		f"({searchfield} LIKE %(txt)s OR section_name LIKE %(txt)s)",
	]
	values = {
		"txt": f"%{txt}%",
		"start": start,
		"page_len": page_len,
	}

	section_group = (filters or {}).get("section_group")
	if section_group:
		group = frappe.db.get_value(
			"IIB Production Section",
			section_group,
			["lft", "rgt"],
			as_dict=True,
		)
		if group and group.lft and group.rgt:
			conditions.append("lft > %(group_lft)s AND rgt < %(group_rgt)s")
			values.update({"group_lft": group.lft, "group_rgt": group.rgt})

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT name, section_name
		FROM `tabIIB Production Section`
		WHERE {where}
		ORDER BY lft ASC, name ASC
		LIMIT %(start)s, %(page_len)s
		""",
		values,
	)
