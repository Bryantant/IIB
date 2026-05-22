import frappe


def on_stock_entry_change(doc, method=None):
	"""When a Stock Entry tied to a Job Order P2 is submitted or cancelled,
	refresh produced_qty on the Job Order P2 (and cascade to Production Plan P2)."""
	jop2 = getattr(doc, "iib_job_order_p2", None)
	if not jop2:
		return
	if not frappe.db.exists("Job Order P2", jop2):
		return
	jo = frappe.get_doc("Job Order P2", jop2)
	jo.update_produced_qty()
