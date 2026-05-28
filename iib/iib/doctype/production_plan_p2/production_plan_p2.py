import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


SO_ITEM_WIP_FIELD = "custom_wip_quantity"


def so_item_wip_sql(alias="soi"):
	if frappe.db.has_column("Sales Order Item", SO_ITEM_WIP_FIELD):
		return f"IFNULL({alias}.{SO_ITEM_WIP_FIELD}, 0)"
	return "0"


def packed_item_wip_sql(alias="pi"):
	if frappe.db.has_column("Packed Item", SO_ITEM_WIP_FIELD):
		return f"IFNULL({alias}.{SO_ITEM_WIP_FIELD}, 0)"
	return "0"


class ProductionPlanP2(Document):
	def validate(self):
		self.validate_items()
		self.compute_totals()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		if not self.po_items:
			frappe.throw(_("Items table is empty. Use 'Get Items' to populate before submitting."))

	def on_submit(self):
		self.db_set("status", "Not Started")

	def before_cancel(self):
		self.guard_against_submitted_job_orders()

	def on_cancel(self):
		self.delete_draft_job_orders()
		self.db_set("status", "Cancelled")
		self.db_set("created_job_orders", "")

	# ---- validation helpers ----

	def validate_items(self):
		if not self.po_items:
			return
		seen = set()
		for row in self.po_items:
			if flt(row.planned_qty) <= 0:
				frappe.throw(_("Row {0}: Planned Qty must be positive").format(row.idx))
			if not self.combine_items:
				key = (row.sales_order or "", row.sales_order_item or "")
				if key in seen:
					frappe.throw(
						_("Row {0}: Duplicate Sales Order line {1}").format(row.idx, row.sales_order_item)
					)
				seen.add(key)

	def compute_totals(self):
		total_planned = sum(flt(r.planned_qty) for r in self.po_items)
		total_produced = sum(flt(r.produced_qty) for r in self.po_items)
		self.total_planned_qty = total_planned
		self.total_produced_qty = total_produced
		self.per_produced = (total_produced / total_planned * 100) if total_planned else 0
		for row in self.po_items:
			row.pending_qty = max(flt(row.planned_qty) - flt(row.produced_qty), 0)

	# ---- cancel guards ----

	def guard_against_submitted_job_orders(self):
		submitted = frappe.db.sql(
			"""
			SELECT name FROM `tabJob Order P2`
			WHERE production_plan_p2 = %s AND docstatus = 1
			""",
			(self.name,),
			as_dict=True,
		)
		if submitted:
			names = [r.name for r in submitted]
			frappe.throw(
				_(
					"Cannot cancel: submitted Job Order P2 exist for this plan: {0}. Cancel them first."
				).format(", ".join(names))
			)

	def delete_draft_job_orders(self):
		drafts = frappe.db.sql(
			"""
			SELECT name FROM `tabJob Order P2`
			WHERE production_plan_p2 = %s AND docstatus = 0
			""",
			(self.name,),
			as_dict=True,
		)
		for r in drafts:
			frappe.delete_doc("Job Order P2", r.name, ignore_permissions=True, force=True)

	# ---- post-production recompute ----

	def recompute_produced_qty(self):
		"""Aggregate produced_qty from submitted Job Order P2 across (SO, SO Item) pairs.

		A single JO may serve multiple SOs via its sales_order_items child table.
		We distribute the JO's produced_qty proportionally to each row's qty,
		then map each share to the matching po_items row by (sales_order, sales_order_item).
		"""
		jo_rows = frappe.db.sql(
			"""
			SELECT name, produced_qty, qty
			FROM `tabJob Order P2`
			WHERE production_plan_p2 = %(name)s AND docstatus = 1
			""",
			{"name": self.name},
			as_dict=True,
		)

		produced_by_so_pair = {}
		produced_by_item = {}
		for jo in jo_rows:
			jo_total = flt(jo.qty)
			jo_produced = flt(jo.produced_qty)
			if jo_total <= 0 or jo_produced <= 0:
				continue
			so_items = frappe.db.get_all(
				"Job Order P2 Sales Order Item",
				filters={"parent": jo.name, "parenttype": "Job Order P2"},
				fields=["sales_order", "sales_order_item", "qty"],
			)
			row_qty_total = sum(flt(r.qty) for r in so_items) or jo_total
			for r in so_items:
				share = jo_produced * (flt(r.qty) / row_qty_total) if row_qty_total else 0
				key = (r.sales_order or "", r.sales_order_item or "")
				produced_by_so_pair[key] = produced_by_so_pair.get(key, 0) + share

		allocation_item_by_pair = {
			(r.sales_order or "", r.sales_order_item or ""): r.item_code
			for r in (self.so_item_allocations or [])
			if r.sales_order_item and r.item_code
		}
		for key, produced in produced_by_so_pair.items():
			item_code = allocation_item_by_pair.get(key)
			if item_code:
				produced_by_item[item_code] = produced_by_item.get(item_code, 0) + flt(produced)

		total_planned = 0.0
		total_produced = 0.0
		for row in self.po_items:
			key = (row.sales_order or "", row.sales_order_item or "")
			if row.sales_order_item:
				produced = flt(produced_by_so_pair.get(key, 0))
			else:
				produced = flt(produced_by_item.get(row.item_code, 0))
			produced = min(produced, flt(row.planned_qty))
			pending = max(flt(row.planned_qty) - produced, 0)
			row.db_set("produced_qty", produced, update_modified=False)
			row.db_set("pending_qty", pending, update_modified=False)
			total_planned += flt(row.planned_qty)
			total_produced += produced

		self.db_set("total_planned_qty", total_planned, update_modified=False)
		self.db_set("total_produced_qty", total_produced, update_modified=False)
		self.db_set(
			"per_produced",
			(total_produced / total_planned * 100) if total_planned else 0,
			update_modified=False,
		)
		self._update_status_from_produced_qty(total_planned, total_produced)

	def _update_status_from_produced_qty(self, total_planned, total_produced):
		if self.status in ("Closed", "Cancelled"):
			return
		if self.docstatus != 1:
			return
		if total_produced <= 0:
			new_status = "Not Started"
		elif total_produced < total_planned:
			new_status = "In Process"
		else:
			new_status = "Completed"
		if new_status != self.status:
			self.db_set("status", new_status)


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def get_sales_orders(filters):
	"""Return submitted Sales Orders matching the filter criteria."""
	frappe.has_permission("Production Plan P2", "read", throw=True)
	frappe.has_permission("Sales Order", "read", throw=True)
	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = filters or {}

	wip_expr = packed_item_wip_sql("pi2")
	delivered_expr = "(pi2.qty * IFNULL(soi2.delivered_qty, 0) / NULLIF(soi2.qty, 0))"
	conditions = [
		"so.docstatus = 1",
		"so.status NOT IN ('Stopped', 'Closed', 'Cancelled')",
		"EXISTS (SELECT 1 FROM `tabPacked Item` pi2 "
		" JOIN `tabSales Order Item` soi2 ON soi2.name = pi2.parent_detail_docname "
		" JOIN `tabItem` item2 ON item2.name = pi2.item_code "
		" WHERE pi2.parent = so.name "
		" AND item2.item_group = 'Component' "
		f" AND pi2.qty - IFNULL({delivered_expr}, 0) - {wip_expr} > 0)",
	]
	values = {}

	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
		values["customer"] = filters["customer"]

	if filters.get("sales_order_status"):
		conditions.append("so.status = %(so_status)s")
		values["so_status"] = filters["sales_order_status"]

	if filters.get("from_date"):
		conditions.append("so.transaction_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("so.transaction_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("from_delivery_date"):
		conditions.append(
			"EXISTS (SELECT 1 FROM `tabSales Order Item` dsoi "
			" WHERE dsoi.parent = so.name AND dsoi.delivery_date >= %(from_del_date)s)"
		)
		values["from_del_date"] = filters["from_delivery_date"]

	if filters.get("to_delivery_date"):
		conditions.append(
			"EXISTS (SELECT 1 FROM `tabSales Order Item` dsoi2 "
			" WHERE dsoi2.parent = so.name AND dsoi2.delivery_date <= %(to_del_date)s)"
		)
		values["to_del_date"] = filters["to_delivery_date"]

	if filters.get("item_code"):
		item_wip_expr = packed_item_wip_sql("ipi")
		item_delivered_expr = "(ipi.qty * IFNULL(isoi.delivered_qty, 0) / NULLIF(isoi.qty, 0))"
		conditions.append(
			"EXISTS (SELECT 1 FROM `tabPacked Item` ipi "
			" JOIN `tabSales Order Item` isoi ON isoi.name = ipi.parent_detail_docname "
			" JOIN `tabItem` iitem ON iitem.name = ipi.item_code "
			" WHERE ipi.parent = so.name AND ipi.item_code = %(item_code)s "
			" AND iitem.item_group = 'Component' "
			f" AND ipi.qty - IFNULL({item_delivered_expr}, 0) - {item_wip_expr} > 0)"
		)
		values["item_code"] = filters["item_code"]

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT so.name AS sales_order,
		       so.transaction_date AS sales_order_date,
		       so.customer,
		       so.grand_total
		FROM `tabSales Order` so
		WHERE {where}
		ORDER BY so.transaction_date DESC, so.name
		""",
		values,
		as_dict=True,
	)


@frappe.whitelist()
def get_items(source_name=None, doc=None):
	"""Populate po_items and section_assignments from the sales_orders table on the plan."""
	frappe.has_permission("Sales Order", "read", throw=True)
	plan = get_or_save_plan(source_name, doc)
	if not plan.sales_orders:
		frappe.throw(_("Add Sales Orders first before fetching items"))

	so_names = [row.sales_order for row in plan.sales_orders if row.sales_order]
	if not so_names:
		frappe.throw(_("No valid Sales Orders found in the table"))

	settings = frappe.get_single("IIB Settings")
	default_wip = getattr(settings, "default_wip_warehouse", None) or ""
	default_fg = getattr(settings, "default_fg_warehouse", None) or ""

	wip_expr = packed_item_wip_sql("pi")
	delivered_expr = "(pi.qty * IFNULL(soi.delivered_qty, 0) / NULLIF(soi.qty, 0))"
	available_expr = f"(pi.qty - IFNULL({delivered_expr}, 0) - {wip_expr})"
	conditions = [
		"pi.parent IN %(sos)s",
		"so.docstatus = 1",
		"item.item_group = 'Component'",
		f"{available_expr} > 0",
	]
	values = {"sos": tuple(so_names)}
	if plan.item_code:
		conditions.append("pi.item_code = %(item_code)s")
		values["item_code"] = plan.item_code
	where = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			pi.name AS sales_order_item,
			pi.parent AS sales_order,
			pi.item_code,
			pi.item_name,
			pi.description,
			pi.uom,
			{available_expr} AS planned_qty,
			soi.delivery_date,
			so.customer
		FROM `tabPacked Item` pi
		JOIN `tabSales Order Item` soi ON soi.name = pi.parent_detail_docname
		JOIN `tabSales Order` so ON so.name = pi.parent
		JOIN `tabItem` item ON item.name = pi.item_code
		WHERE {where}
		ORDER BY pi.parent, soi.idx, pi.idx
		""",
		values,
		as_dict=True,
	)

	if not rows:
		frappe.msgprint(_("No open Sales Order lines found for the selected Sales Orders"))
		return []

	allocation_rows = [dict(r) for r in rows]

	if plan.combine_items:
		consolidated = {}
		for r in rows:
			key = r.item_code
			if key in consolidated:
				consolidated[key]["planned_qty"] += flt(r.planned_qty)
			else:
				consolidated[key] = dict(r)
		rows = list(consolidated.values())

	plan.set("po_items", [])
	plan.set("so_item_allocations", [])
	for r in allocation_rows:
		plan.append(
			"so_item_allocations",
			{
				"sales_order": r["sales_order"],
				"sales_order_item": r["sales_order_item"],
				"item_code": r["item_code"],
				"item_name": r["item_name"],
				"description": r["description"],
				"uom": r["uom"],
				"qty": flt(r["planned_qty"]),
				"delivery_date": r.get("delivery_date"),
				"customer": r.get("customer"),
			},
		)
	for r in rows:
		plan.append(
			"po_items",
			{
				"sales_order": r["sales_order"] if not plan.combine_items else "",
				"sales_order_item": r["sales_order_item"] if not plan.combine_items else "",
				"item_code": r["item_code"],
				"item_name": r["item_name"],
				"description": r["description"],
				"uom": r["uom"],
				"planned_qty": flt(r["planned_qty"]),
				"produced_qty": 0,
				"pending_qty": flt(r["planned_qty"]),
				"delivery_date": r.get("delivery_date"),
				"customer": r.get("customer"),
				"wip_warehouse": default_wip,
				"fg_warehouse": default_fg,
			},
		)

	_resolve_section_groups(plan, allocation_rows)

	plan.save()
	return [row.as_dict() for row in plan.po_items]


def _resolve_section_groups(plan, item_rows):
	"""Populate section_assignments with one row per (item_code, sequence) operation.

	Each item's Master Card processes are expanded in sequence order.
	Existing rows are preserved (by item_code + sequence key) so already-assigned
	production_sections are not lost when Get Items is clicked multiple times.
	"""
	unique_items = list({r["item_code"] for r in item_rows if r.get("item_code")})
	if not unique_items:
		return

	existing_keys = {
		(row.item_code, row.sequence) for row in (plan.section_assignments or [])
	}

	for item_code in unique_items:
		mc_name = frappe.db.get_value("Master Card Item", {"item_code": item_code}, "parent")
		if not mc_name:
			continue
		mc = frappe.get_cached_doc("Master Card", mc_name)

		component = None
		for row in mc.items:
			if row.item_code == item_code:
				component = (row.component or "").upper()
				break
		if not component:
			continue

		processes = sorted(
			[p for p in mc.processes if (p.component or "").upper() == component and p.section],
			key=lambda p: p.sequence,
		)
		for proc in processes:
			key = (item_code, proc.sequence)
			if key not in existing_keys:
				plan.append(
					"section_assignments",
					{
						"item_code": item_code,
						"item_name": frappe.db.get_value("Item", item_code, "item_name") or "",
						"sequence": proc.sequence,
						"section": proc.section,
						"production_section": "",
					},
				)
				existing_keys.add(key)


def get_or_save_plan(source_name=None, doc=None):
	if not doc:
		plan = frappe.get_doc("Production Plan P2", source_name)
		plan.check_permission("write")
		return plan

	if isinstance(doc, str):
		doc = json.loads(doc)

	plan = frappe.get_doc(doc)
	remove_blank_item_rows(plan)

	if plan.name and str(plan.name).startswith("new-"):
		plan.name = None

	plan.flags.ignore_mandatory = True
	if plan.name and frappe.db.exists("Production Plan P2", plan.name):
		plan.check_permission("write")
		plan.save()
	else:
		frappe.has_permission("Production Plan P2", "create", throw=True)
		plan.insert()

	return plan


def remove_blank_item_rows(plan):
	plan.set(
		"po_items",
		[row for row in plan.po_items if not is_blank_item_row(row)],
	)


def is_blank_item_row(row):
	return not any(
		[
			row.sales_order,
			row.sales_order_item,
			row.item_code,
			row.item_name,
			row.description,
			row.customer,
			row.uom,
			row.delivery_date,
			row.wip_warehouse,
			row.fg_warehouse,
			flt(row.planned_qty),
			flt(row.produced_qty),
			flt(row.pending_qty),
		]
	)


@frappe.whitelist()
def make_job_orders(source_name):
	"""Create one Job Order P2 per unique MC Component (item_code) across po_items.

	Each JO receives a sales_order_items child table with rows from every
	contributing po_items row, so a single JO can serve multiple SOs.
	Section assignments on the plan are applied to each JO's operations.
	"""
	plan = frappe.get_doc("Production Plan P2", source_name)
	plan.check_permission("write")
	frappe.has_permission("Job Order P2", "create", throw=True)
	frappe.has_permission("Sales Order", "read", throw=True)
	if plan.docstatus != 1:
		frappe.throw(_("Production Plan P2 must be submitted before creating Job Orders"))

	# Validate and build (item_code, sequence) → production_section mapping
	section_map = {}
	if plan.section_assignments:
		missing = [
			f"{sa.item_code} Seq {sa.sequence} ({sa.section})"
			for sa in plan.section_assignments
			if not sa.production_section
		]
		if missing:
			frappe.throw(
				_(
					"Assign a Production Section (machine) for: {0}. "
					"Fill in all rows in the Section Assignments table before creating Job Orders."
				).format(", ".join(missing))
			)
		section_map = {
			(sa.item_code, sa.sequence): sa.production_section
			for sa in plan.section_assignments
		}

	from iib.iib.doctype.job_order_p2.job_order_p2 import get_so_item_available_qty

	settings = frappe.get_single("IIB Settings")
	default_wip = getattr(settings, "default_wip_warehouse", None) or ""
	default_fg = getattr(settings, "default_fg_warehouse", None) or ""

	po_item_by_item = {}
	for row in plan.po_items:
		if row.item_code and row.item_code not in po_item_by_item:
			po_item_by_item[row.item_code] = row

	allocation_rows = [r for r in (plan.so_item_allocations or []) if r.sales_order_item]
	if not allocation_rows:
		allocation_rows = [
			r for r in (plan.po_items or []) if r.sales_order and r.sales_order_item
		]

	if not allocation_rows and any(flt(r.planned_qty) > flt(r.produced_qty) for r in plan.po_items):
		frappe.throw(
			_("SO Item allocation details are missing. Click Get Items again before creating Job Orders.")
		)

	groups = {}
	taken_by_so_item = {}
	for row in allocation_rows:
		available = get_so_item_available_qty(row.sales_order_item)
		available -= taken_by_so_item.get(row.sales_order_item, 0)
		qty_to_allocate = min(flt(row.get("qty") or row.get("planned_qty")), max(available, 0))
		if qty_to_allocate <= 0:
			continue
		taken_by_so_item[row.sales_order_item] = (
			taken_by_so_item.get(row.sales_order_item, 0) + qty_to_allocate
		)
		groups.setdefault(row.item_code, []).append((row, qty_to_allocate))

	created = []
	for item_code, members in groups.items():
		if not members:
			continue
		first_row = po_item_by_item.get(item_code) or members[0][0]
		total_qty = sum(p for _, p in members)

		master_card = frappe.db.get_value(
			"Master Card Item", {"item_code": item_code}, "parent"
		)

		jo = frappe.new_doc("Job Order P2")
		jo.company = plan.company
		jo.production_plan_p2 = plan.name
		jo.ppp2_item_row = first_row.name
		jo.production_item = item_code
		jo.item_name = first_row.item_name
		jo.description = first_row.description
		jo.master_card = master_card
		jo.qty = total_qty
		jo.wip_warehouse = getattr(first_row, "wip_warehouse", None) or default_wip
		jo.fg_warehouse = getattr(first_row, "fg_warehouse", None) or default_fg
		jo.posting_date = nowdate()
		jo.due_date = first_row.delivery_date or plan.expected_delivery_date

		for member_row, member_qty in members:
			if not member_row.sales_order:
				continue
			so_status = frappe.db.get_value("Sales Order", member_row.sales_order, "status")
			jo.append(
				"sales_order_items",
				{
					"sales_order": member_row.sales_order,
					"sales_order_item": member_row.sales_order_item or "",
					"item_code": item_code,
					"qty": member_qty,
					"delivery_date": member_row.delivery_date,
					"customer": member_row.customer,
					"so_status": so_status or "",
				},
			)

		jo.insert()

		# Apply production_section by (item_code, sequence) from plan's section assignments
		if section_map:
			for op in jo.operations:
				ps = section_map.get((item_code, op.sequence))
				if ps:
					op.db_set("production_section", ps, update_modified=False)

		created.append(jo.name)

	if created:
		plan.db_set("created_job_orders", "\n".join(created))
		plan.db_set("status", "In Process")
	return created
