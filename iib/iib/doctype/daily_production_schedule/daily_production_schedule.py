import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

# Manual planner-entered fields that persist on a row.
MANUAL_FIELDS = ("req_qty", "proc_qty", "run_qty", "waktu", "remark")


class DailyProductionSchedule(Document):
	def autoname(self):
		from iib.iib.utils.naming import get_next_iib_number

		d = getdate(self.posting_date or frappe.utils.today())
		yymm = d.strftime("%y%m")
		seq = get_next_iib_number("dps", period=yymm, digits=4)
		self.name = f"{yymm}{seq}"

	def validate(self):
		self._block_duplicate()
		self._update_last_update()

	def _block_duplicate(self):
		existing = frappe.db.get_value(
			"Daily Production Schedule",
			{
				"posting_date": self.posting_date,
				"section": self.section,
				"name": ["!=", self.name],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("A Daily Production Schedule already exists for {0} on {1}: {2}").format(
					self.section, self.posting_date, existing
				)
			)

	def _update_last_update(self):
		stamp = f"{frappe.session.user} {frappe.utils.now()}"
		for row in self.items or []:
			row.last_update = stamp


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _mc_flute_colours(master_card, item_code):
	"""Return (flute, colours) for a Master Card Item line."""
	if not (master_card and item_code):
		return "", ""
	mc_item = frappe.db.get_value(
		"Master Card Item",
		{"parent": master_card, "item_code": item_code},
		[
			"custom_flute",
			"custom_colour_1",
			"custom_colour_2",
			"custom_colour_3",
			"custom_colour_4",
			"custom_colour_5",
		],
		as_dict=True,
	)
	if not mc_item:
		return "", ""
	colours = ", ".join(
		mc_item.get(f"custom_colour_{i}")
		for i in range(1, 6)
		if mc_item.get(f"custom_colour_{i}")
	)
	return mc_item.get("custom_flute") or "", colours


def _jo_display_row(jo_name):
	"""Build the read-only display dict for one Job Order Converting."""
	jo = frappe.db.get_value(
		"Job Order Converting",
		jo_name,
		["production_item", "item_name", "master_card", "qty", "due_date"],
		as_dict=True,
	)
	if not jo:
		return None

	so_row = frappe.db.get_value(
		"Job Order Converting Sales Order Item",
		{"parent": jo_name, "parenttype": "Job Order Converting"},
		["sales_order", "customer", "delivery_date"],
		as_dict=True,
		order_by="idx asc",
	)
	flute, colours = _mc_flute_colours(jo.master_card, jo.production_item)

	return {
		"job_order_converting": jo_name,
		"item_code": jo.production_item,
		"item_name": jo.item_name or "",
		"master_card": jo.master_card or "",
		"customer": (so_row or {}).get("customer") or "",
		"so_no": (so_row or {}).get("sales_order") or "",
		"so_qty": jo.qty or 0,
		"due_date": (so_row or {}).get("delivery_date") or jo.due_date,
		"flute": flute,
		"colours": colours,
	}


def _prior_dps_manual_map(section, posting_date):
	"""Manual field values from the most recent prior DPS for this section, keyed by
	Job Order name — used to carry forward planner input to a new day's schedule."""
	if not (section and posting_date):
		return {}
	prior = frappe.db.get_value(
		"Daily Production Schedule",
		{"section": section, "posting_date": ["<", posting_date]},
		"name",
		order_by="posting_date desc, creation desc",
	)
	if not prior:
		return {}
	rows = frappe.get_all(
		"Daily Production Schedule Item",
		filters={"parent": prior},
		fields=["job_order_converting", *MANUAL_FIELDS],
	)
	return {r["job_order_converting"]: r for r in rows if r.get("job_order_converting")}


def _merge_manual(row, src):
	"""Fill manual fields on a display row from a source dict (current grid or prior DPS)."""
	src = src or {}
	for f in MANUAL_FIELDS:
		val = src.get(f)
		if val in (None, ""):
			row[f] = "" if f == "remark" else 0
		else:
			row[f] = val
	return row


def _started_jo_names(section, jo_names):
	"""Subset of jo_names that have been started (appear in a non-cancelled PP
	for this section)."""
	if not (section and jo_names):
		return set()
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT ppi.job_order_converting
		FROM `tabProduction Process Item` ppi
		JOIN `tabProduction Process` pp ON pp.name = ppi.parent
		JOIN `tabJob Order Converting Operation` op ON op.name = ppi.job_order_converting_operation
		WHERE ppi.job_order_converting IN %(jos)s
		  AND op.production_section = %(section)s
		  AND pp.docstatus != 2
		""",
		{"jos": tuple(jo_names), "section": section},
	)
	return {r[0] for r in rows}


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def refresh_and_carry_forward(section, posting_date, current_rows):
	"""Build the full desired row set in one pass: carry forward the previous DPS's
	unstarted jobs (with their manual values) AND drop any job already started in a
	Production Process for this section. Manual values come from the live grid first,
	then the prior day. Display fields are rebuilt fresh, so this never wipes a row."""
	frappe.has_permission("Daily Production Schedule", "read", throw=True)
	if not section:
		return []

	current = json.loads(current_rows) if current_rows else []
	current_map = {
		r["job_order_converting"]: r for r in current if r.get("job_order_converting")
	}
	prior_map = _prior_dps_manual_map(section, posting_date)

	# Today's rows first, then carried-forward ones — deduped, order preserved.
	candidates = list(dict.fromkeys(list(current_map) + list(prior_map)))
	if not candidates:
		return []

	started = _started_jo_names(section, candidates)

	rows = []
	for jo in candidates:
		if jo in started:
			continue
		row = _jo_display_row(jo)
		if not row:
			continue
		_merge_manual(row, current_map.get(jo) or prior_map.get(jo))
		rows.append(row)
	return rows


@frappe.whitelist()
def get_jo_row(job_order_converting):
	"""Display fields for a single JO — used to auto-fill a manually added row."""
	frappe.has_permission("Daily Production Schedule", "read", throw=True)
	return _jo_display_row(job_order_converting) or {}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_jo_for_section(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for DPS items — submitted, active JOs assigned to this section,
	optionally narrowed to a single item (used by the unified Add Job dialog)."""
	section = (filters or {}).get("section") or ""
	item_code = (filters or {}).get("item_code") or ""
	return frappe.db.sql(
		"""
		SELECT DISTINCT jo.name, jo.production_item
		FROM `tabJob Order Converting` jo
		JOIN `tabJob Order Converting Operation` op ON op.parent = jo.name
		WHERE jo.docstatus = 1
		  AND jo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
		  AND op.production_section = %(section)s
		  AND (%(item_code)s = '' OR jo.production_item = %(item_code)s)
		  AND (jo.name LIKE %(txt)s OR jo.production_item LIKE %(txt)s)
		ORDER BY jo.name
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"section": section,
			"item_code": item_code,
			"txt": f"%{txt}%",
			"start": start,
			"page_len": page_len,
		},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_jo_items_for_section(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for the 'Get Jobs by Item' dialog — items that have active JOs
	assigned to this section."""
	section = (filters or {}).get("section") or ""
	return frappe.db.sql(
		"""
		SELECT DISTINCT i.name, i.item_name
		FROM `tabItem` i
		JOIN `tabJob Order Converting` jo ON jo.production_item = i.name
		JOIN `tabJob Order Converting Operation` op ON op.parent = jo.name
		WHERE jo.docstatus = 1
		  AND jo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
		  AND op.production_section = %(section)s
		  AND (i.name LIKE %(txt)s OR i.item_name LIKE %(txt)s)
		ORDER BY i.name
		LIMIT %(start)s, %(page_len)s
		""",
		{"section": section, "txt": f"%{txt}%", "start": start, "page_len": page_len},
	)
