import frappe


def execute():
	_rename_doctypes()
	_rename_custom_fields()


def _rename_doctypes():
	rename_map = [
		# P1 → Corrugator (child tables first, then parents)
		("Job Order P1 Receipt Item", "Job Order Corrugator Receipt Item"),
		("Job Order P1 Receipt", "Job Order Corrugator Receipt"),
		("Job Order P1 Item", "Job Order Corrugator Item"),
		("Job Order P1", "Job Order Corrugator"),
		("IIB Settings JOP1 Tolerance", "IIB Settings Corrugator Tolerance"),
		# P2 → Converting (child tables first, then parents)
		("Job Order P2 Sales Order Item", "Job Order Converting Sales Order Item"),
		("Job Order P2 Rm To Wip Item", "Job Order Converting Rm To Wip Item"),
		("Job Order P2 Wip To Fg Item", "Job Order Converting Wip To Fg Item"),
		("Job Order P2 Rm To Wip", "Job Order Converting Rm To Wip"),
		("Job Order P2 Wip To Fg", "Job Order Converting Wip To Fg"),
		("Job Order P2 Operation", "Job Order Converting Operation"),
		("Job Order P2", "Job Order Converting"),
		("IIB Settings JOP2 Tolerance", "IIB Settings Converting Tolerance"),
	]

	for old_name, new_name in rename_map:
		old_exists = frappe.db.exists("DocType", old_name)
		new_exists = frappe.db.exists("DocType", new_name)

		if not old_exists:
			# Already renamed or never existed — nothing to do.
			continue

		# A stale tabDocType row can survive when the physical table was dropped
		# by an earlier failed migration. delete_doc/rename_doc both issue SQL on
		# the table and blow up if it's missing — guard against that.
		old_table_exists = bool(
			frappe.db.sql("SHOW TABLES LIKE %s", (f"tab{old_name}",))
		)

		if new_exists:
			if old_table_exists:
				frappe.delete_doc("DocType", old_name, force=True, ignore_permissions=True)
			else:
				frappe.db.delete("DocType", {"name": old_name})
				frappe.db.delete("DocField", {"parent": old_name})
				frappe.db.delete("Custom Field", {"dt": old_name})
		else:
			if old_table_exists:
				frappe.rename_doc("DocType", old_name, new_name, force=True)
			else:
				# No table to rename — drop the orphaned record so schema sync
				# can recreate the DocType cleanly under the new name.
				frappe.db.delete("DocType", {"name": old_name})
				frappe.db.delete("DocField", {"parent": old_name})
				frappe.db.delete("Custom Field", {"dt": old_name})


def _rename_custom_fields():
	# Custom fields whose fieldnames changed (old_cf_doc_name, new_cf_doc_name)
	cf_rename_map = [
		("Stock Entry-iib_job_order_p2", "Stock Entry-iib_job_order_converting"),
		("Sales Order Item-custom_jop1_qty", "Sales Order Item-custom_corrugator_qty"),
	]

	for old_cf, new_cf in cf_rename_map:
		if frappe.db.exists("Custom Field", old_cf) and not frappe.db.exists("Custom Field", new_cf):
			frappe.rename_doc("Custom Field", old_cf, new_cf, force=True)
