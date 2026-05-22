# Copyright (c) 2026, IIB and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _, msgprint
from frappe.model.document import Document
from frappe.query_builder.functions import IfNull
from frappe.utils import (
	add_days,
	cint,
	comma_and,
	flt,
	get_link_to_form,
	now_datetime,
	nowdate,
)
from pypika.terms import ExistsCriterion

from erpnext.manufacturing.doctype.production_plan.production_plan import (
	get_items_for_material_requests,
	get_sales_orders,
	get_sub_assembly_items as walk_bom_for_sub_assembly,
)
from erpnext.manufacturing.doctype.work_order.work_order import (
	get_default_warehouse,
	get_item_details,
)
from erpnext.stock.utils import get_or_make_bin


class CustomProductionPlan(Document):
	# ---------- Lifecycle ----------

	def validate(self):
		self.calculate_total_planned_qty()
		self.set_status()
		self._validate_items()

	def before_submit(self):
		if not self.items:
			frappe.throw(_("Please add items before submitting. Use 'Get Items' to populate."))

	def _validate_items(self):
		for d in self.items:
			if d.type in ("Finished Good", "Sub Assembly") and not d.bom_no:
				frappe.throw(
					_("Row #{0}: BOM is required for {1} item {2}").format(d.idx, d.type, d.item_code)
				)
			if not flt(d.planned_qty):
				frappe.throw(
					_("Row #{0}: Planned Qty is required for item {1}").format(d.idx, d.item_code)
				)

	def calculate_total_planned_qty(self):
		self.total_planned_qty = sum(
			flt(r.planned_qty) for r in self.items if r.type == "Finished Good"
		)
		self.total_produced_qty = sum(
			flt(r.produced_qty) for r in self.items if r.type == "Finished Good"
		)

	def set_status(self):
		self.status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(self.docstatus, "Draft")

		if self.docstatus == 1:
			if any(flt(r.requested_qty) for r in self.items if r.type == "Raw Material"):
				self.status = "Material Requested"

			if any(
				flt(r.ordered_qty) or flt(r.produced_qty) or flt(r.received_qty)
				for r in self.items
				if r.type in ("Finished Good", "Sub Assembly")
			):
				self.status = "In Process"

			if self._all_finished_goods_completed() and self._linked_work_orders_completed():
				self.status = "Completed"

	def _all_finished_goods_completed(self):
		finished_goods = [r for r in self.items if r.type == "Finished Good"]
		return bool(finished_goods) and all(
			flt(r.produced_qty) >= flt(r.planned_qty) for r in finished_goods
		)

	def _linked_work_orders_completed(self):
		if not frappe.get_meta("Work Order").has_field("custom_production_plan"):
			return True

		incomplete_work_orders = frappe.get_all(
			"Work Order",
			filters={
				"custom_production_plan": self.name,
				"docstatus": ("<", 2),
				"status": ("not in", ["Completed", "Closed", "Stopped", "Cancelled"]),
			},
			limit=1,
		)
		return not incomplete_work_orders

	def on_submit(self):
		self.update_bin_qty()
		self.update_sales_order()

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		self.update_bin_qty()
		self.update_sales_order()

	def update_bin_qty(self):
		seen = set()
		for d in self.items:
			if not d.warehouse:
				continue
			key = (d.item_code, d.warehouse)
			if key in seen:
				continue
			seen.add(key)
			bin_name = get_or_make_bin(d.item_code, d.warehouse)
			frappe.get_doc("Bin", bin_name, for_update=True).update_reserved_qty_for_production_plan()

	def update_sales_order(self):
		"""Sync Sales Order Item.production_plan_qty from submitted Custom Production Plans."""
		sales_order_items = {
			r.sales_order_item
			for r in self.items
			if r.type == "Finished Good" and r.sales_order_item
		}

		for sales_order_item in sales_order_items:
			planned = self.get_sales_order_item_planned_qty(sales_order_item)
			frappe.db.set_value(
				"Sales Order Item", sales_order_item, "production_plan_qty", planned
			)

	@staticmethod
	def get_sales_order_item_planned_qty(sales_order_item):
		data = frappe.get_all(
			"Custom Production Plan Item",
			fields=["SUM(planned_qty) as qty"],
			filters={
				"type": "Finished Good",
				"sales_order_item": sales_order_item,
				"docstatus": 1,
			},
		)
		return flt(data[0].qty) if data else 0

	# ---------- Helper expected by get_sales_orders() ----------

	def get_bom_item_condition(self):
		"""Mirror of ProductionPlan.get_bom_item_condition; called by module helper."""
		bom_item_condition = None
		has_bom = frappe.db.exists({"doctype": "BOM", "item": self.item_code, "docstatus": 1})
		if not has_bom:
			bom = frappe.qb.DocType("BOM")
			template_item = frappe.db.get_value("Item", self.item_code, ["variant_of"])
			bom_item_condition = bom.item == template_item or None
		return bom_item_condition

	# ---------- Sales Orders ----------

	@frappe.whitelist()
	def get_open_sales_orders(self):
		"""Pull pending Sales Orders matching the filters into the sales_orders table."""
		open_so = get_sales_orders(self)

		if not open_so:
			frappe.msgprint(_("No Sales Orders are available for production"))
			return

		self.set("sales_orders", [])
		for data in open_so:
			self.append(
				"sales_orders",
				{
					"sales_order": data.name,
					"sales_order_date": data.transaction_date,
					"customer": data.customer,
					"grand_total": data.base_grand_total,
				},
			)

	# ---------- One-shot populate of unified items table ----------

	@frappe.whitelist()
	def get_items(self):
		"""Populate `items` with FG + Sub Assembly + Raw Material rows in one shot."""
		so_list = [d.sales_order for d in self.sales_orders if d.sales_order]
		if not so_list:
			frappe.throw(_("Please click 'Get Sales Orders' first."), title=_("Sales Orders Required"))

		self.set("items", [])

		fg_rows = self._populate_finished_goods(so_list)
		if not fg_rows:
			frappe.msgprint(_("No items with active BOM found in selected Sales Orders."))
			return

		self._populate_sub_assemblies(fg_rows)
		self._populate_raw_materials()
		self.calculate_total_planned_qty()

	# -------- FG --------

	def _populate_finished_goods(self, so_list):
		bom = frappe.qb.DocType("BOM")
		so_item = frappe.qb.DocType("Sales Order Item")
		so = frappe.qb.DocType("Sales Order")

		bom_subquery = frappe.qb.from_(bom).select(bom.name).where(bom.is_active == 1)

		q = (
			frappe.qb.from_(so_item)
			.inner_join(so)
			.on(so_item.parent == so.name)
			.select(
				so_item.parent.as_("sales_order"),
				so.transaction_date.as_("sales_order_date"),
				so.customer.as_("customer"),
				so_item.item_code,
				so_item.warehouse,
				so_item.qty,
				so_item.work_order_qty,
				so_item.delivered_qty,
				so_item.conversion_factor,
				so_item.description,
				so_item.name.as_("so_item_name"),
				so_item.bom_no,
				so_item.uom,
				so_item.stock_uom,
			)
			.distinct()
			.where(
				(so_item.parent.isin(so_list))
				& (so_item.docstatus == 1)
				& (so_item.qty > so_item.work_order_qty)
			)
		)

		if self.item_code and frappe.db.exists("Item", self.item_code):
			q = q.where(so_item.item_code == self.item_code)
			bom_subquery = bom_subquery.where(
				self.get_bom_item_condition() or bom.item == so_item.item_code
			)

		q = q.where(ExistsCriterion(bom_subquery))

		rows = q.run(as_dict=True)

		appended = []
		consolidate = cint(self.combine_items)
		consolidated = {}

		for r in rows:
			pending_qty = (
				flt(r.qty) - max(flt(r.work_order_qty), flt(r.delivered_qty), 0)
			) * (flt(r.conversion_factor) or 1.0)
			if pending_qty <= 0:
				continue

			item_details = get_item_details(r.item_code, throw=False) or {}
			bom_no = r.bom_no or item_details.get("bom_no")
			if not bom_no:
				continue

			payload = {
				"type": "Finished Good",
				"sales_order": r.sales_order,
				"sales_order_date": r.sales_order_date,
				"customer": r.customer,
				"item_code": r.item_code,
				"item_name": item_details.get("item_name"),
				"bom_no": bom_no,
				"planned_qty": pending_qty,
				"pending_qty": pending_qty,
				"uom": r.uom or r.stock_uom,
				"stock_uom": r.stock_uom or item_details.get("stock_uom"),
				"conversion_factor": flt(r.conversion_factor) or 1.0,
				"warehouse": r.warehouse,
				"planned_start_date": now_datetime(),
				"description": r.description or item_details.get("description"),
				"sales_order_item": r.so_item_name,
				"indent": 0,
				"bom_level": 0,
			}

			if consolidate:
				key = (r.item_code, bom_no, r.warehouse or "")
				if key in consolidated:
					existing = consolidated[key]
					existing.planned_qty = flt(existing.planned_qty) + pending_qty
					existing.pending_qty = flt(existing.pending_qty) + pending_qty
					continue
				row = self.append("items", payload)
				consolidated[key] = row
				appended.append(row)
			else:
				row = self.append("items", payload)
				appended.append(row)

		return appended

	# -------- Sub Assemblies --------

	def _populate_sub_assemblies(self, fg_rows):
		bin_details = frappe._dict()
		all_sub = []

		for fg in fg_rows:
			if not fg.bom_no or not fg.item_code:
				continue
			if cint(self.skip_available_sub_assembly_item) and not self.sub_assembly_warehouse:
				frappe.throw(_("Please select Sub Assembly Warehouse to skip available items."))

			bom_data = []
			walk_bom_for_sub_assembly(
				[r.item_code for r in all_sub],
				bin_details,
				fg.bom_no,
				bom_data,
				flt(fg.planned_qty),
				self.company,
				warehouse=self.sub_assembly_warehouse,
				skip_available_sub_assembly_item=cint(self.skip_available_sub_assembly_item),
			)

			is_group_warehouse = (
				frappe.db.get_value("Warehouse", self.sub_assembly_warehouse, "is_group")
				if self.sub_assembly_warehouse
				else 0
			)

			for d in bom_data:
				row_payload = {
					"type": "Sub Assembly",
					"sales_order": fg.sales_order,
					"sales_order_date": fg.sales_order_date,
					"customer": fg.customer,
					"sales_order_item": fg.sales_order_item,
					"item_code": d.production_item,
					"item_name": d.item_name,
					"bom_no": d.bom_no,
					"bom_level": d.bom_level,
					"parent_item_code": d.parent_item_code,
					"description": d.description,
					"uom": d.uom,
					"stock_uom": d.stock_uom,
					"planned_qty": flt(d.stock_qty),
					"pending_qty": flt(d.stock_qty),
					"actual_qty": flt(d.actual_qty),
					"planned_start_date": fg.planned_start_date,
					"schedule_date": fg.planned_start_date,
					"type_of_manufacturing": "Subcontract" if d.is_sub_contracted_item else "In House",
					"warehouse": (None if is_group_warehouse else self.sub_assembly_warehouse),
					"indent": flt(d.bom_level),
					"conversion_factor": 1.0,
				}
				row = self.append("items", row_payload)
				all_sub.append(frappe._dict({"item_code": d.production_item, "row": row}))

		# default supplier for subcontract
		subcontract_items = [r.item_code for r in self.items if r.type == "Sub Assembly" and r.type_of_manufacturing == "Subcontract"]
		if subcontract_items:
			defaults = frappe._dict(
				frappe.get_all(
					"Item Default",
					fields=["parent", "default_supplier"],
					filters={"parent": ("in", subcontract_items), "default_supplier": ("is", "set")},
					as_list=1,
				)
			)
			for r in self.items:
				if r.type == "Sub Assembly" and r.type_of_manufacturing == "Subcontract":
					r.supplier = defaults.get(r.item_code)

	# -------- Raw Materials --------

	def _populate_raw_materials(self):
		"""Use module-level helper to compute MR rows from current items, then append with type=Raw Material."""
		# Build a synthetic dict shaped like a Production Plan that get_items_for_material_requests expects.
		fg_items = [
			frappe._dict(
				{
					"item_code": r.item_code,
					"bom_no": r.bom_no,
					"warehouse": r.warehouse,
					"planned_qty": flt(r.planned_qty),
					"pending_qty": flt(r.pending_qty) or flt(r.planned_qty),
					"sales_order": r.sales_order,
					"sales_order_item": r.sales_order_item,
					"description": r.description,
					"include_exploded_items": 1,
					"ignore_existing_ordered_qty": cint(self.ignore_existing_ordered_qty),
					"idx": r.idx,
					"name": r.name,
				}
			)
			for r in self.items
			if r.type == "Finished Good"
		]
		sub_items = [
			frappe._dict(
				{
					"production_item": r.item_code,
					"qty": flt(r.planned_qty),
					"bom_no": r.bom_no,
					"type_of_manufacturing": r.type_of_manufacturing,
				}
			)
			for r in self.items
			if r.type == "Sub Assembly"
		]

		shim = frappe._dict(
			{
				"company": self.company,
				"po_items": fg_items,
				"sub_assembly_items": sub_items,
				"include_non_stock_items": cint(self.include_non_stock_items),
				"include_subcontracted_items": cint(self.include_subcontracted_items),
				"include_safety_stock": cint(self.include_safety_stock),
				"ignore_existing_ordered_qty": cint(self.ignore_existing_ordered_qty),
				"skip_available_sub_assembly_item": cint(self.skip_available_sub_assembly_item),
				"for_warehouse": self.for_warehouse,
				"sub_assembly_warehouse": self.sub_assembly_warehouse,
				"name": self.name,
				"consider_minimum_order_qty": cint(self.consider_minimum_order_qty),
			}
		)

		try:
			mr_items = get_items_for_material_requests(shim) or []
		except frappe.ValidationError:
			# helper throws if items table empty — fine, just return
			return

		for d in mr_items:
			if isinstance(d, dict):
				d = frappe._dict(d)
			self.append(
				"items",
				{
					"type": "Raw Material",
					"sales_order": d.get("sales_order"),
					"item_code": d.get("item_code"),
					"item_name": d.get("item_name"),
					"description": d.get("description"),
					"planned_qty": flt(d.get("quantity")),
					"pending_qty": flt(d.get("quantity")),
					"uom": d.get("uom"),
					"stock_uom": d.get("stock_uom"),
					"conversion_factor": flt(d.get("conversion_factor")) or 1.0,
					"warehouse": d.get("warehouse"),
					"from_warehouse": d.get("from_warehouse"),
					"schedule_date": d.get("schedule_date"),
					"min_order_qty": flt(d.get("min_order_qty")),
					"safety_stock": flt(d.get("safety_stock")),
					"actual_qty": flt(d.get("actual_qty")),
					"projected_qty": flt(d.get("projected_qty")),
					"material_request_type": d.get("material_request_type"),
					"indent": 99,
				},
			)

	# ---------- Create Work Orders ----------

	@frappe.whitelist()
	def make_work_order(self):
		default_warehouses = get_default_warehouse() or {}
		wo_list, po_list = [], []
		subcontracted_po = {}

		# Finished Good rows -> Work Orders
		for r in self.items:
			if r.type != "Finished Good":
				continue
			qty = flt(r.planned_qty) - flt(r.ordered_qty)
			if qty <= 0:
				continue

			wo_data = {
				"production_item": r.item_code,
				"item_name": r.item_name,
				"bom_no": r.bom_no,
				"qty": qty,
				"company": self.company,
				"description": r.description,
				"stock_uom": r.stock_uom,
				"sales_order": r.sales_order,
				"sales_order_item": r.sales_order_item,
				"custom_production_plan": self.name,
				"custom_production_plan_item": r.name,
				"fg_warehouse": r.warehouse or default_warehouses.get("fg_warehouse"),
				"wip_warehouse": default_warehouses.get("wip_warehouse"),
				"scrap_warehouse": default_warehouses.get("scrap_warehouse"),
				"planned_start_date": r.planned_start_date or now_datetime(),
				"use_multi_level_bom": 0 if any(x.type == "Sub Assembly" for x in self.items) else 1,
			}
			wo_name = self._create_work_order(wo_data)
			if wo_name:
				wo_list.append(wo_name)
				self.sync_item_quantities(r.name)

		# Sub Assembly rows -> Work Orders or pooled into Subcontract POs
		for r in self.items:
			if r.type != "Sub Assembly":
				continue
			if r.type_of_manufacturing == "Material Request":
				continue
			qty = flt(r.planned_qty) - flt(r.ordered_qty)
			if qty <= 0:
				continue

			if r.type_of_manufacturing == "Subcontract":
				subcontracted_po.setdefault(r.supplier, []).append(r)
				continue

			wo_data = {
				"production_item": r.item_code,
				"item_name": r.item_name,
				"bom_no": r.bom_no,
				"qty": qty,
				"company": self.company,
				"description": r.description,
				"stock_uom": r.stock_uom,
				"sales_order": r.sales_order,
				"sales_order_item": r.sales_order_item,
				"custom_production_plan": self.name,
				"custom_production_plan_item": r.name,
				"fg_warehouse": r.warehouse or default_warehouses.get("fg_warehouse"),
				"wip_warehouse": default_warehouses.get("wip_warehouse"),
				"scrap_warehouse": default_warehouses.get("scrap_warehouse"),
				"planned_start_date": r.planned_start_date or r.schedule_date or now_datetime(),
				"bom_level": r.bom_level,
				"use_multi_level_bom": 0,
			}
			wo_name = self._create_work_order(wo_data)
			if wo_name:
				wo_list.append(wo_name)
				self.sync_item_quantities(r.name)

		# Subcontract grouping -> Purchase Orders
		self._make_subcontracted_purchase_order(subcontracted_po, po_list)

		if wo_list:
			msgprint(
				_("Work Orders created: {0}").format(
					comma_and([get_link_to_form("Work Order", n) for n in wo_list])
				)
			)
		else:
			frappe.msgprint(_("No Work Orders were created"))

		if po_list:
			msgprint(
				_("Purchase Orders created: {0}").format(
					comma_and([get_link_to_form("Purchase Order", n) for n in po_list])
				)
			)

	def _create_work_order(self, item):
		from erpnext.manufacturing.doctype.work_order.work_order import OverProductionError

		if flt(item.get("qty")) <= 0:
			return None

		wo = frappe.new_doc("Work Order")
		wo.update(item)
		wo.planned_start_date = item.get("planned_start_date") or now_datetime()
		if item.get("fg_warehouse"):
			wo.fg_warehouse = item.get("fg_warehouse")

		try:
			wo.set_work_order_operations()
			wo.set_required_items()
			wo.flags.ignore_mandatory = True
			wo.flags.ignore_validate = True
			wo.insert()
			return wo.name
		except OverProductionError:
			return None

	def _make_subcontracted_purchase_order(self, subcontracted_po, purchase_orders):
		if not subcontracted_po:
			return

		for supplier, rows in subcontracted_po.items():
			if not supplier:
				frappe.msgprint(
					_("Skipped subcontract Purchase Order: no supplier for {0}").format(
						comma_and([r.item_code for r in rows])
					)
				)
				continue

			po = frappe.new_doc("Purchase Order")
			po.company = self.company
			po.supplier = supplier
			po.schedule_date = rows[0].schedule_date or nowdate()
			po.is_subcontracted = 1

			for r in rows:
				po.append(
					"items",
					{
						"fg_item": r.item_code,
						"warehouse": r.warehouse,
						"bom": r.bom_no,
						"custom_production_plan": self.name,
						"custom_production_plan_item": r.name,
						"fg_item_qty": flt(r.planned_qty),
						"qty": flt(r.planned_qty),
						"schedule_date": r.schedule_date,
						"description": r.description,
						"sales_order": r.sales_order,
						"sales_order_item": r.sales_order_item,
					},
				)

			try:
				po.set_service_items_for_finished_goods()
			except Exception:
				pass
			po.set_missing_values()
			po.flags.ignore_mandatory = True
			po.flags.ignore_validate = True
			po.insert()
			purchase_orders.append(po.name)
			for r in rows:
				self.sync_item_quantities(r.name)

	# ---------- Create Material Requests ----------

	@frappe.whitelist()
	def make_material_request(self):
		"""Group Raw Material rows by SO + MR Type + Customer and create draft MRs."""
		mr_list = []
		mr_map = {}
		submit = cint(self.get("submit_material_request"))
		raw_material_row_names = [r.name for r in self.items if r.type == "Raw Material"]

		for r in self.items:
			if r.type != "Raw Material":
				continue

			item_doc = frappe.get_cached_doc("Item", r.item_code)
			mr_type = r.material_request_type or item_doc.default_material_request_type or "Purchase"
			schedule_date = r.schedule_date or add_days(nowdate(), cint(item_doc.lead_time_days))

			key = "{}:{}:{}".format(r.sales_order or "", mr_type, item_doc.customer or "")

			if key not in mr_map:
				mr = frappe.new_doc("Material Request")
				mr.update(
					{
						"transaction_date": nowdate(),
						"status": "Draft",
						"company": self.company,
						"material_request_type": mr_type,
						"customer": item_doc.customer or "",
					}
				)
				mr_map[key] = mr
				mr_list.append(mr)
			else:
				mr = mr_map[key]

			mr.append(
				"items",
				{
					"item_code": r.item_code,
					"from_warehouse": r.from_warehouse if mr_type == "Material Transfer" else None,
					"qty": flt(r.planned_qty),
					"schedule_date": schedule_date,
					"warehouse": r.warehouse,
					"sales_order": r.sales_order,
					"custom_production_plan": self.name,
					"custom_production_plan_item": r.name,
					"project": frappe.db.get_value("Sales Order", r.sales_order, "project")
					if r.sales_order
					else None,
				},
			)

		for mr in mr_list:
			mr.flags.ignore_mandatory = True
			mr.flags.ignore_validate = True
			mr.insert()
			if submit:
				mr.submit()

		if mr_list:
			msgprint(
				_("Material Requests created: {0}").format(
					comma_and([get_link_to_form("Material Request", m.name) for m in mr_list])
				)
			)
			for row_name in raw_material_row_names:
				self.sync_item_quantities(row_name)
		else:
			msgprint(_("No Material Request created"))

	# ---------- Downstream tracking ----------

	def sync_item_quantities(self, item_row_name):
		row = next((r for r in self.items if r.name == item_row_name), None)
		if not row:
			return

		if row.type in ("Finished Good", "Sub Assembly"):
			ordered_qty, produced_qty = get_custom_work_order_qty(item_row_name)
			po_qty, received_qty = get_custom_purchase_order_qty(item_row_name)
			row.db_set("ordered_qty", ordered_qty + po_qty, update_modified=False)
			row.db_set("produced_qty", produced_qty, update_modified=False)
			row.db_set("received_qty", received_qty, update_modified=False)

		elif row.type == "Raw Material":
			requested_qty = get_custom_material_request_qty(item_row_name)
			row.db_set("requested_qty", requested_qty, update_modified=False)

		self.reload()
		self.calculate_total_planned_qty()
		self.set_status()
		self.db_set("total_produced_qty", self.total_produced_qty, update_modified=False)
		self.db_set("status", self.status, update_modified=False)


def has_custom_field(doctype, fieldname):
	return frappe.get_meta(doctype).has_field(fieldname)


def get_custom_work_order_qty(custom_production_plan_item):
	if not has_custom_field("Work Order", "custom_production_plan_item"):
		return 0, 0

	ordered = frappe.get_all(
		"Work Order",
		fields=["SUM(qty) as qty"],
		filters={
			"custom_production_plan_item": custom_production_plan_item,
			"docstatus": ("<", 2),
			"status": ("not in", ["Closed", "Stopped", "Cancelled"]),
		},
	)
	produced = frappe.get_all(
		"Work Order",
		fields=["SUM(produced_qty) as qty"],
		filters={
			"custom_production_plan_item": custom_production_plan_item,
			"docstatus": 1,
			"status": ("not in", ["Closed", "Stopped", "Cancelled"]),
		},
	)

	return flt(ordered[0].qty if ordered else 0), flt(produced[0].qty if produced else 0)


def get_custom_purchase_order_qty(custom_production_plan_item):
	if not has_custom_field("Purchase Order Item", "custom_production_plan_item"):
		return 0, 0

	ordered = frappe.get_all(
		"Purchase Order Item",
		fields=["SUM(qty) as qty", "SUM(received_qty) as received_qty"],
		filters={
			"custom_production_plan_item": custom_production_plan_item,
			"docstatus": ("<", 2),
		},
	)

	return (
		flt(ordered[0].qty if ordered else 0),
		flt(ordered[0].received_qty if ordered else 0),
	)


def get_custom_material_request_qty(custom_production_plan_item):
	if not has_custom_field("Material Request Item", "custom_production_plan_item"):
		return 0

	requested = frappe.get_all(
		"Material Request Item",
		fields=["SUM(qty) as qty"],
		filters={
			"custom_production_plan_item": custom_production_plan_item,
			"docstatus": ("<", 2),
		},
	)
	return flt(requested[0].qty if requested else 0)


def sync_custom_plan_item(custom_production_plan, custom_production_plan_item):
	if not custom_production_plan or not custom_production_plan_item:
		return
	if not frappe.db.exists("Custom Production Plan", custom_production_plan):
		return

	plan = frappe.get_doc("Custom Production Plan", custom_production_plan)
	plan.sync_item_quantities(custom_production_plan_item)


def sync_from_work_order(doc, method=None):
	if not has_custom_field("Work Order", "custom_production_plan"):
		return

	sync_custom_plan_item(
		doc.get("custom_production_plan"),
		doc.get("custom_production_plan_item"),
	)


def sync_from_material_request(doc, method=None):
	if not has_custom_field("Material Request Item", "custom_production_plan"):
		return

	seen = set()
	for row in doc.get("items"):
		key = (row.get("custom_production_plan"), row.get("custom_production_plan_item"))
		if key in seen:
			continue
		seen.add(key)
		sync_custom_plan_item(*key)


def sync_from_purchase_order(doc, method=None):
	if not has_custom_field("Purchase Order Item", "custom_production_plan"):
		return

	seen = set()
	for row in doc.get("items"):
		key = (row.get("custom_production_plan"), row.get("custom_production_plan_item"))
		if key in seen:
			continue
		seen.add(key)
		sync_custom_plan_item(*key)
