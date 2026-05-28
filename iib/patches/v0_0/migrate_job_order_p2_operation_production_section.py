import frappe


def execute():
	if not frappe.db.has_column("Job Order P2 Operation", "production_section"):
		return
	if not frappe.db.has_column("Job Card P2", "section"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabJob Order P2 Operation` op
		JOIN `tabJob Card P2` jc
		  ON jc.job_order_p2_operation = op.name
		 AND jc.job_order_p2 = op.parent
		JOIN `tabIIB Production Section` ps ON ps.name = jc.section
		SET op.production_section = jc.section
		WHERE IFNULL(op.production_section, '') = ''
		  AND IFNULL(jc.section, '') != ''
		  AND IFNULL(ps.is_group, 0) = 0
		  AND IFNULL(ps.disabled, 0) = 0
		"""
	)
