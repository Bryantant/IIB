import frappe


def execute():
	if not frappe.db.has_column("Job Card P2", "section_group"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabJob Card P2` jc
		JOIN `tabIIB Production Section` ps ON ps.name = jc.section
		SET
			jc.section_group = CASE
				WHEN IFNULL(ps.is_group, 0) = 1 THEN ps.name
				ELSE ps.parent_iib_production_section
			END,
			jc.section = CASE
				WHEN IFNULL(ps.is_group, 0) = 1 THEN NULL
				ELSE jc.section
			END
		WHERE IFNULL(jc.section, '') != ''
		  AND IFNULL(jc.section_group, '') = ''
		"""
	)
