import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, getdate

from iib.iib.utils.tolerance import lookup_tolerance


JOP1_TARGET_WAREHOUSE = "Raw Material - IIB"


class JobOrderCorrugator(Document):
	def autoname(self):
		from iib.iib.utils.naming import get_next_iib_number

		d = getdate(self.transaction_date or frappe.utils.today())
		yy = d.strftime("%y")
		seq = get_next_iib_number("jop1", period=yy, digits=4)
		self.name = f"IIB{yy}{seq}"

	def validate(self):
		self.target_warehouse = JOP1_TARGET_WAREHOUSE
		self.fetch_item_metadata()
		self.validate_items()
		self.compute_totals()
		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		self.validate_corrugator_tolerance()

	def on_submit(self):
		self.db_set("status", "To Receive")
		self.update_so_item_corrugator_qty()

	def before_cancel(self):
		self.guard_against_submitted_receipts()

	def on_cancel(self):
		self.delete_draft_receipts()
		self.db_set("status", "Cancelled")
		self.db_set("created_receipts", "")
		self.update_so_item_corrugator_qty()

	# ---- validate helpers ----

	def fetch_item_metadata(self):
		for row in self.items:
			if not row.sales_order or not row.sales_order_item:
				continue
			so_item = frappe.db.get_value(
				"Sales Order Item",
				row.sales_order_item,
				["item_code", "item_name", "description", "uom", "rate", "delivery_date", "parent"],
				as_dict=True,
			)
			if not so_item:
				frappe.throw(
					_("Row {0}: Sales Order Item {1} not found").format(row.idx, row.sales_order_item)
				)
			if so_item.parent != row.sales_order:
				frappe.throw(
					_("Row {0}: Sales Order Item {1} does not belong to {2}").format(
						row.idx, row.sales_order_item, row.sales_order
					)
				)
			# Check if the SO item is a Product Bundle — packed items have already been
			# expanded by get_so_items_for_corrugator; preserve the row's item_code in that case.
			is_bundle = frappe.db.exists("Product Bundle", so_item.item_code)
			so_header = frappe.db.get_value(
				"Sales Order", row.sales_order, ["customer", "transaction_date"], as_dict=True
			)
			if is_bundle:
				# Only fill delivery_date / customer; item fields come from the packed item
				if not row.delivery_date:
					row.delivery_date = so_item.delivery_date
				row.customer = so_header.customer
				if not row.so_date:
					row.so_date = so_header.transaction_date
			else:
				item_details = self.get_stock_item_details(so_item.item_code, row.idx)
				self.validate_sales_order_stock_uom(
					row, so_item.item_code, so_item.uom, item_details.stock_uom
				)
				row.item_code = so_item.item_code
				row.item_name = so_item.item_name
				row.description = so_item.description
				row.uom = item_details.stock_uom
				row.rate = so_item.rate
				if not row.delivery_date:
					row.delivery_date = so_item.delivery_date
				row.customer = so_header.customer
				if not row.so_date:
					row.so_date = so_header.transaction_date

	def get_stock_item_details(self, item_code, row_idx):
		item_details = frappe.db.get_value(
			"Item", item_code, ["is_stock_item", "stock_uom"], as_dict=True
		)
		if not item_details:
			frappe.throw(_("Row {0}: Item {1} not found").format(row_idx, item_code))
		if not item_details.is_stock_item:
			frappe.throw(
				_("Row {0}: Item {1} must be a stock item for Job Order Corrugator").format(
					row_idx, frappe.bold(item_code)
				)
			)
		if not item_details.stock_uom:
			frappe.throw(_("Row {0}: Item {1} has no Stock UOM").format(row_idx, item_code))
		return item_details

	def validate_sales_order_stock_uom(self, row, item_code, sales_order_uom, stock_uom):
		if sales_order_uom and sales_order_uom != stock_uom:
			frappe.throw(
				_(
					"Row {0}: Sales Order Item {1} uses UOM {2}, but Item {3} stock UOM is {4}. "
					"Job Order Corrugator only supports stock UOM lines."
				).format(
					row.idx,
					row.sales_order_item,
					frappe.bold(sales_order_uom),
					frappe.bold(item_code),
					frappe.bold(stock_uom),
				)
			)

	def validate_row_stock_uom(self, row, stock_uom):
		if row.uom and row.uom != stock_uom:
			frappe.throw(
				_(
					"Row {0}: Item {1} must use stock UOM {2}; current UOM is {3}. "
					"Job Order Corrugator does not support UOM conversion."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(stock_uom),
					frappe.bold(row.uom),
				)
			)
		row.uom = stock_uom

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Items table is empty"))

		seen = set()
		customers = set()
		for row in self.items:
			if row.due_date and getdate(row.due_date) < getdate(self.transaction_date):
				frappe.throw(
					_("Row {0}: Due Date cannot be before Transaction Date ({1}).").format(
						row.idx, self.transaction_date
					)
				)
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be positive").format(row.idx))
			key = (row.sales_order, row.sales_order_item, row.item_code)
			if key in seen:
				frappe.throw(_("Row {0}: Duplicate item {1} for Sales Order line {2}").format(row.idx, row.item_code, row.sales_order_item))
			seen.add(key)
			if row.item_code:
				item_details = self.get_stock_item_details(row.item_code, row.idx)
				self.validate_row_stock_uom(row, item_details.stock_uom)
			if row.customer:
				customers.add(row.customer)

		self.customer = list(customers)[0] if len(customers) == 1 else None

	def compute_totals(self):
		total_qty = sum(flt(r.qty) for r in self.items)
		total_received = sum(flt(r.received_qty) for r in self.items)
		self.total_qty = total_qty
		self.total_received_qty = total_received
		self.per_received = (total_received / total_qty * 100) if total_qty else 0
		for row in self.items:
			row.pending_qty = max(flt(row.qty) - flt(row.received_qty), 0)

	# ---- submit / cancel guards ----

	def guard_against_submitted_receipts(self):
		submitted = frappe.db.sql(
			"""
			SELECT DISTINCT r.name
			FROM `tabJob Order Corrugator Receipt` r
			JOIN `tabJob Order Corrugator Receipt Item` ri ON ri.parent = r.name
			WHERE ri.job_order_corrugator = %s
			  AND r.docstatus = 1
			""",
			(self.name,),
			as_dict=True,
		)
		names = [r.name for r in submitted]
		if names:
			frappe.throw(
				_(
					"Cannot cancel: submitted Job Order Corrugator Receipts exist for this Job Order Corrugator: {0}. Cancel them first."
				).format(", ".join(names))
			)

	def delete_draft_receipts(self):
		drafts = frappe.db.sql(
			"""
			SELECT DISTINCT r.name
			FROM `tabJob Order Corrugator Receipt` r
			JOIN `tabJob Order Corrugator Receipt Item` ri ON ri.parent = r.name
			WHERE ri.job_order_corrugator = %s
			  AND r.docstatus = 0
			""",
			(self.name,),
			as_dict=True,
		)
		for r in drafts:
			frappe.delete_doc("Job Order Corrugator Receipt", r.name, ignore_permissions=True, force=True)

	# ---- tolerance validation ----

	def validate_corrugator_tolerance(self):
		"""Block submit if any SO Item would be over-ordered beyond the tolerance tier.

		Non-bundle SO items: compare JO P1 qty directly against the SO Item qty.
		Bundle SO items: the JO P1 rows carry the packed *component* item code; compare
		against (SO Item qty × packed-component qty-per-set) from the Product Bundle
		table so the tolerance always applies to the actual component qty, not the
		parent-bundle set qty.
		"""
		tolerance_rows = frappe.get_all(
			"IIB Settings Corrugator Tolerance",
			filters={"parent": "IIB Settings", "parenttype": "IIB Settings"},
			fields=["corrugator_qty", "corrugator_toleransi"],
			order_by="corrugator_qty asc",
		)
		if not tolerance_rows:
			return  # No table configured — allow any qty

		# Group current-doc qtys by (sales_order_item, item_code).
		# For bundles a single SO item can have multiple packed components, so we
		# must key on the component as well.
		current_qty_map: dict = {}
		for row in self.items:
			if not row.sales_order_item:
				continue
			key = (row.sales_order_item, row.item_code or "")
			current_qty_map[key] = flt(current_qty_map.get(key, 0)) + flt(row.qty)

		for (so_item_name, item_code), current_qty in current_qty_map.items():
			so_data = frappe.db.get_value(
				"Sales Order Item",
				so_item_name,
				["qty", "item_code", "custom_corrugator_qty"],
				as_dict=True,
			)
			if not so_data:
				continue

			is_bundle = frappe.db.exists("Product Bundle", so_data.item_code)

			if is_bundle:
				# Reference qty = SO set qty × packed-component qty-per-set
				packed_qty_per_set = frappe.db.get_value(
					"Product Bundle Item",
					{"parent": so_data.item_code, "item_code": item_code},
					"qty",
				)
				if not packed_qty_per_set:
					continue  # Component not in bundle definition — skip
				so_qty = flt(so_data.qty) * flt(packed_qty_per_set)
				# Previously submitted JO P1 qty for this specific component + SO item
				# (excluding the current document so resubmit / amend works correctly)
				prev_corrugator_qty = flt(
					frappe.db.sql(
						"""
						SELECT IFNULL(SUM(i.qty), 0)
						FROM `tabJob Order Corrugator Item` i
						JOIN `tabJob Order Corrugator` p ON p.name = i.parent
						WHERE i.sales_order_item = %s
						  AND i.item_code = %s
						  AND p.docstatus = 1
						  AND p.name != %s
						""",
						(so_item_name, item_code, self.name),
					)[0][0]
				)
			else:
				so_qty = flt(so_data.qty)
				prev_corrugator_qty = flt(so_data.custom_corrugator_qty or 0)

			total_qty = prev_corrugator_qty + current_qty
			tolerance = lookup_tolerance(
				tolerance_rows, so_qty, "corrugator_qty", "corrugator_toleransi"
			)

			if total_qty > so_qty + tolerance:
				display_item = item_code if is_bundle else so_data.item_code
				frappe.throw(
					_(
						"SO Item {0} (item {1}): total JO P1 qty {2} exceeds "
						"packed component SO qty {3} + tolerance {4} = {5}."
					).format(
						frappe.bold(so_item_name),
						frappe.bold(display_item),
						frappe.bold(flt(total_qty, 3)),
						so_qty,
						tolerance,
						frappe.bold(so_qty + tolerance),
					)
				)

	# ---- SO Item JO P1 qty sync ----

	def update_so_item_corrugator_qty(self):
		"""Recompute custom_corrugator_qty on each affected SO Item or Packed Item.

		- Non-bundle SO lines: update Sales Order Item.custom_corrugator_qty.
		- Bundle SO lines: update Packed Item.custom_corrugator_qty per component,
		  because the bundle parent qty is not meaningful for corrugator tracking.

		Called after submit AND cancel so the field always reflects the live
		total of all submitted (docstatus=1) JO P1 Item qtys.
		"""
		# Collect (so_item_name → {sales_order, item_codes}) from this JOP1's rows
		so_item_data: dict = {}
		for r in self.items:
			if not r.sales_order_item:
				continue
			entry = so_item_data.setdefault(r.sales_order_item, {"sales_order": r.sales_order, "item_codes": set()})
			if r.item_code:
				entry["item_codes"].add(r.item_code)

		for so_item_name, data in so_item_data.items():
			so_item_code = frappe.db.get_value("Sales Order Item", so_item_name, "item_code")
			if not so_item_code:
				continue

			is_bundle = bool(frappe.db.exists("Product Bundle", so_item_code))

			if is_bundle:
				# Update Packed Item.custom_corrugator_qty for each component separately
				for item_code in data["item_codes"]:
					recomputed = frappe.db.sql(
						"""
						SELECT IFNULL(SUM(i.qty), 0)
						FROM `tabJob Order Corrugator Item` i
						JOIN `tabJob Order Corrugator` p ON p.name = i.parent
						WHERE i.sales_order_item = %s
						  AND i.item_code = %s
						  AND p.docstatus = 1
						""",
						(so_item_name, item_code),
					)[0][0]
					packed_item_name = frappe.db.get_value(
						"Packed Item",
						{
							"parent": data["sales_order"],
							"parent_detail_docname": so_item_name,
							"item_code": item_code,
						},
						"name",
					)
					if packed_item_name:
						frappe.db.set_value(
							"Packed Item",
							packed_item_name,
							"custom_corrugator_qty",
							flt(recomputed),
							update_modified=False,
						)
			else:
				# Non-bundle: update Sales Order Item directly
				recomputed = frappe.db.sql(
					"""
					SELECT IFNULL(SUM(i.qty), 0)
					FROM `tabJob Order Corrugator Item` i
					JOIN `tabJob Order Corrugator` p ON p.name = i.parent
					WHERE i.sales_order_item = %s
					  AND p.docstatus = 1
					""",
					(so_item_name,),
				)[0][0]
				frappe.db.set_value(
					"Sales Order Item",
					so_item_name,
					"custom_corrugator_qty",
					flt(recomputed),
					update_modified=False,
				)

	# ---- post-receipt recompute ----

	def recompute_received_qty(self):
		"""Aggregate received_qty from submitted Job Order Corrugator Receipt rows and refresh status."""
		received_by_row = {}
		receipt_rows = frappe.db.sql(
			"""
			SELECT ri.job_order_corrugator_item AS row_name, SUM(ri.qty) AS qty
			FROM `tabJob Order Corrugator Receipt Item` ri
			JOIN `tabJob Order Corrugator Receipt` r ON r.name = ri.parent
			WHERE ri.job_order_corrugator = %(name)s
			  AND ri.job_order_corrugator_item IS NOT NULL
			  AND ri.job_order_corrugator_item != ''
			  AND r.docstatus = 1
			GROUP BY ri.job_order_corrugator_item
			""",
			{"name": self.name},
			as_dict=True,
		)
		for d in receipt_rows:
			received_by_row[str(d.row_name)] = flt(d.qty)

		total_received = 0.0
		total_qty = 0.0
		for row in self.items:
			received = flt(received_by_row.get(str(row.name), 0))
			pending = max(flt(row.qty) - received, 0)
			row.db_set("received_qty", received, update_modified=False)
			row.db_set("pending_qty", pending, update_modified=False)
			total_received += received
			total_qty += flt(row.qty)

		self.db_set("total_received_qty", total_received, update_modified=False)
		self.db_set(
			"per_received",
			(total_received / total_qty * 100) if total_qty else 0,
			update_modified=False,
		)
		self._update_status_from_received_qty(total_qty, total_received)

	def _update_status_from_received_qty(self, total_qty, total_received):
		if self.status in ("Closed", "Cancelled"):
			return
		if self.docstatus != 1:
			return
		if total_received <= 0:
			new_status = "To Receive"
		elif total_received < total_qty:
			new_status = "Partially Received"
		else:
			new_status = "Completed"
		if new_status != self.status:
			self.db_set("status", new_status)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Whitelisted endpoints
# -----------------------------------------------------------------------------


@frappe.whitelist()
def make_corrugator_receipt(source_name, target_doc=None):
	"""Build a draft Job Order Corrugator Receipt from a submitted Job Order Corrugator."""

	def update_header(source, target, source_parent=None):
		target.company = source.company
		target.naming_series = "JOP1R-.YY.-.#####"
		target.status = "Draft"  # prevent JOP1 status ("To Receive" etc.) from leaking in
		# Auto-fetch GL defaults from IIB Settings
		default_cc = frappe.db.get_single_value(
			"IIB Settings", "default_cost_center"
		) or frappe.get_cached_value("Company", source.company, "cost_center")
		if default_cc:
			target.cost_center = default_cc
		default_exp = frappe.db.get_single_value("IIB Settings", "default_expense_account")
		if default_exp:
			target.expense_account = default_exp

	def update_row(source_row, target_row, source_parent):
		pending = flt(source_row.qty) - flt(source_row.received_qty)
		target_row.qty = pending
		target_row.job_order_corrugator = source_parent.name
		target_row.job_order_corrugator_item = source_row.name
		target_row.target_warehouse = JOP1_TARGET_WAREHOUSE

	doc = get_mapped_doc(
		"Job Order Corrugator",
		source_name,
		{
			"Job Order Corrugator": {
				"doctype": "Job Order Corrugator Receipt",
				"validation": {"docstatus": ["=", 1]},
				"postprocess": update_header,
			},
			"Job Order Corrugator Item": {
				"doctype": "Job Order Corrugator Receipt Item",
				"field_map": {
					"item_code": "item_code",
					"description": "description",
					"sales_order": "sales_order",
					"uom": "uom",
				},
				"postprocess": update_row,
				"condition": lambda d: flt(d.qty) - flt(d.received_qty) > 0,
			},
		},
		target_doc,
	)
	return doc


@frappe.whitelist()
def update_status(status, name):
	"""Close / Re-open a submitted Job Order Corrugator."""
	frappe.has_permission("Job Order Corrugator", "submit", doc=name, throw=True)
	if status not in ("Closed", "To Receive"):
		frappe.throw(_("Invalid status transition: {0}").format(status))
	corrugator = frappe.get_doc("Job Order Corrugator", name)
	if corrugator.docstatus != 1:
		frappe.throw(_("Only submitted Job Order Corrugator can be closed or re-opened"))
	if status == "Closed":
		corrugator.db_set("status", "Closed")
	else:
		corrugator.recompute_received_qty()
	return frappe.db.get_value("Job Order Corrugator", name, "status")


@frappe.whitelist()
def get_items_from_so_for_corrugator(source_name, target_doc=None, kwargs=None):
	"""Map Sales Order items into a Job Order Corrugator document.

	Called by ``frappe.model.mapper.map_docs`` via ``erpnext.utils.map_current_doc``.
	``kwargs`` may contain ``filtered_children`` — a list of Sales Order Item row names
	selected in the child-item-selection dialog.  When the list is present only those
	rows are mapped; when absent all rows are mapped.

	Product Bundle items are automatically expanded to their packed components.
	"""
	if isinstance(target_doc, str):
		target_doc = frappe.get_doc(json.loads(target_doc))
	if isinstance(kwargs, str):
		kwargs = json.loads(kwargs)
	kwargs = frappe._dict(kwargs or {})
	filtered_children = kwargs.get("filtered_children") or []

	so = frappe.get_doc("Sales Order", source_name)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} is not submitted").format(source_name))
	customer = so.customer

	for so_item in so.items:
		if filtered_children and so_item.name not in filtered_children:
			continue

		packed_items = frappe.get_all(
			"Product Bundle Item",
			filters={"parent": so_item.item_code},
			fields=["item_code", "description", "qty as qty_per_bundle"],
			order_by="idx",
		)

		if packed_items:
			for packed_item in packed_items:
				item_meta = (
					frappe.db.get_value(
						"Item", packed_item["item_code"], ["item_name", "stock_uom"], as_dict=True
					)
					or {}
				)
				target_doc.append(
					"items",
					{
						"sales_order": source_name,
						"sales_order_item": so_item.name,
						"item_code": packed_item["item_code"],
						"item_name": item_meta.get("item_name") or packed_item["item_code"],
						"description": packed_item.get("description") or "",
						"uom": item_meta.get("stock_uom") or "Nos",
						"qty": flt(so_item.qty) * flt(packed_item["qty_per_bundle"]),
						"rate": 0,
						"delivery_date": so_item.delivery_date,
						"customer": customer,
					},
				)
		else:
			target_doc.append(
				"items",
				{
					"sales_order": source_name,
					"sales_order_item": so_item.name,
					"item_code": so_item.item_code,
					"item_name": so_item.item_name,
					"description": so_item.description or "",
					"uom": so_item.uom,
					"qty": flt(so_item.qty),
					"rate": so_item.rate,
					"delivery_date": so_item.delivery_date,
					"customer": customer,
				},
			)

	return target_doc


@frappe.whitelist()
def get_so_items_for_corrugator_dialog(sales_orders):
	"""Return available SO items for the custom two-step JO P1 picker dialog.

	Accepts a JSON list of Sales Order names.  For each SO, expands Product Bundle
	lines to their packed components so the dialog shows the actual item codes that
	will land in the JO P1.  ``corrugator_qty`` is read from ``Packed Item`` for
	bundle components (where tracking lives) and from ``Sales Order Item`` for plain
	items.

	Returns a flat list of dicts, one per item row to display.
	"""
	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)
	if not sales_orders:
		return []

	result = []
	for so_name in sales_orders:
		so = frappe.get_doc("Sales Order", so_name)
		if so.docstatus != 1:
			continue

		customer = so.customer
		so_date = str(so.transaction_date) if so.transaction_date else ""

		for so_item in so.items:
			packed_items = frappe.get_all(
				"Product Bundle Item",
				filters={"parent": so_item.item_code},
				fields=["item_code", "description", "qty as qty_per_bundle"],
				order_by="idx",
			)

			if packed_items:
				# Bundle → one result row per packed component.
				# Corrugator qty is tracked per component on Packed Item, not on the
				# bundle parent SO Item row.
				for packed_item in packed_items:
					item_meta = (
						frappe.db.get_value(
							"Item",
							packed_item["item_code"],
							["item_name", "stock_uom"],
							as_dict=True,
						)
						or {}
					)
					component_corrugator_qty = flt(
						frappe.db.get_value(
							"Packed Item",
							{
								"parent": so_name,
								"parent_detail_docname": so_item.name,
								"item_code": packed_item["item_code"],
							},
							"custom_corrugator_qty",
						)
						or 0
					)
					result.append(
						{
							"sales_order": so_name,
							"so_date": so_date,
							"sales_order_item": so_item.name,
							"item_code": packed_item["item_code"],
							"item_name": item_meta.get("item_name") or packed_item["item_code"],
							"description": packed_item.get("description") or "",
							"uom": item_meta.get("stock_uom") or "Nos",
							"qty": flt(so_item.qty) * flt(packed_item["qty_per_bundle"]),
							"corrugator_qty": component_corrugator_qty,
							"delivery_date": str(so_item.delivery_date) if so_item.delivery_date else "",
							"customer": customer,
						}
					)
			else:
				result.append(
					{
						"sales_order": so_name,
						"so_date": so_date,
						"sales_order_item": so_item.name,
						"item_code": so_item.item_code,
						"item_name": so_item.item_name or so_item.item_code,
						"description": so_item.description or "",
						"uom": so_item.uom,
						"qty": flt(so_item.qty),
						"corrugator_qty": flt(so_item.get("custom_corrugator_qty") or 0),
						"delivery_date": str(so_item.delivery_date) if so_item.delivery_date else "",
						"customer": customer,
					}
				)

	return result


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_so_component_items(doctype, txt, searchfield, start, page_len, filters):
	"""Custom item_code search for the JO P1 items child table.

	Returns Component stock items that belong to the selected Sales Order —
	either directly as a non-bundle line, or as a packed component of a bundle
	line on that SO.  Falls back to all Component stock items when no SO is given.
	"""
	sales_order = (filters or {}).get("sales_order")

	if sales_order:
		so_item_codes = frappe.get_all(
			"Sales Order Item",
			filters={"parent": sales_order},
			pluck="item_code",
		)

		# Expand any bundle items to their packed components
		allowed: set = set()
		for ic in so_item_codes:
			packed = frappe.get_all(
				"Product Bundle Item",
				filters={"parent": ic},
				pluck="item_code",
			)
			if packed:
				allowed.update(packed)
			else:
				allowed.add(ic)

		if not allowed:
			return []

		return frappe.db.sql(
			"""
			SELECT name, item_name
			FROM `tabItem`
			WHERE name IN %(allowed)s
			  AND is_stock_item = 1
			  AND item_group = 'Component'
			  AND (name LIKE %(txt)s OR item_name LIKE %(txt)s)
			ORDER BY name
			LIMIT %(start)s, %(page_len)s
			""",
			{"allowed": list(allowed), "txt": f"%{txt}%", "start": start, "page_len": page_len},
		)

	# No SO selected — show all Component stock items
	return frappe.db.sql(
		"""
		SELECT name, item_name
		FROM `tabItem`
		WHERE is_stock_item = 1
		  AND item_group = 'Component'
		  AND (name LIKE %(txt)s OR item_name LIKE %(txt)s)
		ORDER BY name
		LIMIT %(start)s, %(page_len)s
		""",
		{"txt": f"%{txt}%", "start": start, "page_len": page_len},
	)


@frappe.whitelist()
def get_so_item_for_component(sales_order, item_code):
	"""Return the Sales Order Item name that corresponds to a component item_code.

	Checks direct matches first, then bundle expansion (packed components).
	Used client-side to auto-fill sales_order_item when item_code is selected.
	"""
	# Direct match: SO item whose item_code IS the component
	direct = frappe.db.get_value(
		"Sales Order Item",
		{"parent": sales_order, "item_code": item_code},
		"name",
	)
	if direct:
		return direct

	# Bundle match: item_code is a packed component of a bundle SO line
	so_item_codes = frappe.get_all(
		"Sales Order Item",
		filters={"parent": sales_order},
		fields=["name", "item_code"],
	)
	for row in so_item_codes:
		packed = frappe.db.get_value(
			"Product Bundle Item",
			{"parent": row.item_code, "item_code": item_code},
			"name",
		)
		if packed:
			return row.name

	return None
