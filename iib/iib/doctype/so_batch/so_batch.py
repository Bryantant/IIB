import frappe
from erpnext.accounts.utils import get_currency_precision
from frappe.utils import flt, getdate
from frappe.model.document import Document

PO_TYPE_GENERAL = "General"
PO_TYPE_FC = "FC"
FC_QTY_TOLERANCE = 1e-6


class SOBatch(Document):
    def autoname(self):
        from iib.iib.utils.naming import get_next_iib_number

        d = getdate(self.transaction_date or frappe.utils.today())
        yy = d.strftime("%y")
        seq = get_next_iib_number("so_batch", period=yy, digits=5)
        self.name = f"{yy}{seq}"

    def validate(self):
        if getdate(self.transaction_date) < getdate(frappe.utils.today()):
            frappe.throw("Transaction Date cannot be backdated.")
        if not self.company:
            self.company = frappe.db.get_single_value("Global Defaults", "default_company")
        self.validate_po_types()
        self.validate_delivery_dates()
        self.set_resolved_items()
        self.set_validated_rates()

    def validate_po_types(self):
        # PO No is forced to the literal "FC" for FC rows and forbidden as a
        # General PO No below, so (po_no, po_date, line_no) grouping in
        # create_sales_orders() can never merge a General and an FC row into
        # the same Sales Order -- General and FC always land under disjoint
        # po_no values.
        for row in self.so_batch_items:
            po_type = row.po_type or PO_TYPE_GENERAL
            row.po_type = po_type

            if po_type == PO_TYPE_FC:
                row.po_no = PO_TYPE_FC
                row.po_date = self.transaction_date
            elif po_type == PO_TYPE_GENERAL:
                if (row.po_no or "").strip().upper() == PO_TYPE_FC:
                    frappe.throw(
                        "Row {0}: PO No 'FC' is reserved for Jenis PO = FC".format(row.idx)
                    )
            else:
                frappe.throw("Row {0}: Unknown Jenis PO {1}".format(row.idx, po_type))

    def validate_delivery_dates(self):
        for row in self.so_batch_items:
            if not row.delivery_date:
                continue
            if getdate(row.delivery_date) < getdate(self.transaction_date):
                frappe.throw(
                    "Row {0}: Delivery Date cannot be before Transaction Date ({1}).".format(
                        row.idx, self.transaction_date
                    )
                )
            if row.po_date and getdate(row.delivery_date) < getdate(row.po_date):
                frappe.throw(
                    "Row {0}: Delivery Date cannot be before PO Date ({1}).".format(
                        row.idx, row.po_date
                    )
                )

    def on_submit(self):
        self.create_sales_orders()

    def on_cancel(self):
        self.cancel_related_sales_orders()

    def on_trash(self):
        self.delete_related_sales_orders()

    def set_resolved_items(self):
        for row in self.so_batch_items:
            item_code, set_item_code = resolve_item(row.part_no, row.set_or_pcs, self.customer)
            row.resolved_item_code = item_code
            row.resolved_set_item_code = set_item_code

    def set_validated_rates(self):
        for row in self.so_batch_items:
            expected_rate, _component_rates = get_expected_rate_for_so_batch_row(row)
            expected_rate = get_sales_order_rate(expected_rate)
            if not flt(row.rate):
                row.rate = expected_rate
            elif not rate_matches(row.rate, expected_rate):
                frappe.throw(
                    "Row {0}: Rate {1} does not match system price {2} for Part No {3}".format(
                        row.idx, row.rate, expected_rate, row.part_no
                    )
                )
            else:
                row.rate = expected_rate

    def create_sales_orders(self):
        if not self.so_batch_items:
            frappe.throw("SO Batch Items table is empty")

        existing_sales_orders = frappe.get_all(
            "Sales Order",
            filters={"so_batch": self.name, "docstatus": ["!=", 2]},
            pluck="name",
        )
        if existing_sales_orders:
            frappe.throw(
                "Sales Orders already exist for this SO Batch: {0}".format(
                    ", ".join(existing_sales_orders)
                )
            )

        company = self.company or frappe.db.get_single_value("Global Defaults", "default_company")
        selling_price_list = (
            frappe.db.get_single_value("Selling Settings", "selling_price_list")
            or "Standard Selling"
        )

        po_groups = {}
        po_group_types = {}
        for row in self.so_batch_items:
            item_code = row.resolved_set_item_code or row.resolved_item_code
            expected_rate, component_rates = get_expected_rate_for_so_batch_row(row)
            expected_rate = get_sales_order_rate(expected_rate)
            match_info = resolve_match_info(row)
            key = (row.po_no, row.po_date, row.line_no)
            po_group_types[key] = row.po_type
            po_groups.setdefault(key, []).append(
                {
                    "item_code": item_code,
                    "qty": row.qty,
                    "rate": expected_rate,
                    "component_rates": component_rates,
                    "delivery_date": row.delivery_date,
                    "match_info": match_info,
                }
            )

        created_sos = []
        for (po_no, po_date, line_no), items in po_groups.items():
            po_type = po_group_types[(po_no, po_date, line_no)]
            so = frappe.new_doc("Sales Order")
            so.company = company
            so.customer = self.customer
            so.order_type = "Sales"
            so.transaction_date = self.transaction_date
            so.delivery_date = min(
                getdate(i["delivery_date"]) for i in items if i.get("delivery_date")
            )
            so.currency = self.currency
            so.conversion_rate = self.conversion_rate
            so.selling_price_list = selling_price_list
            so.payment_terms_template = self.payment_terms_template
            so.set_warehouse = self.default_warehouse
            so.po_no = po_no
            so.po_date = po_date
            so.po_line_no = line_no
            so.so_batch = self.name
            so.po_type = po_type

            for item in items:
                so.append(
                    "items",
                    {
                        "item_code": item["item_code"],
                        "qty": item["qty"],
                        "rate": item["rate"],
                        "price_list_rate": item["rate"],
                        "discount_amount": 0,
                        "discount_percentage": 0,
                        "delivery_date": item["delivery_date"],
                        "warehouse": self.default_warehouse,
                    },
                )

            try:
                so.insert(ignore_permissions=True)
                apply_validated_rates_to_sales_order(so, items, po_type)
                so.submit()
                created_sos.append(so.name)
            except Exception:
                frappe.throw(
                    "Error creating Sales Order for PO {0}: {1}".format(
                        po_no, frappe.get_traceback()
                    )
                )

        frappe.db.delete(
            "SO Batch Created SO",
            {"parent": self.name, "parenttype": "SO Batch"},
        )
        for idx, name in enumerate(created_sos, 1):
            frappe.get_doc(
                {
                    "doctype": "SO Batch Created SO",
                    "parent": self.name,
                    "parenttype": "SO Batch",
                    "parentfield": "created_sales_orders",
                    "idx": idx,
                    "sales_order": name,
                }
            ).insert(ignore_permissions=True)

        if created_sos:
            lines = ["<b>{0} Sales Order(s) created and submitted:</b>".format(len(created_sos))]
            for name in created_sos:
                lines.append("&bull; <a href='/app/sales-order/{0}'>{0}</a>".format(name))
            frappe.msgprint("<br>".join(lines), title="SO Batch Complete", indicator="green")
        else:
            frappe.msgprint("No Sales Orders were created.", title="SO Batch", indicator="orange")

    def cancel_related_sales_orders(self):
        sales_orders = frappe.get_all(
            "Sales Order",
            filters={"so_batch": self.name, "docstatus": ["!=", 2]},
            fields=["name", "docstatus", "po_type"],
        )

        # Release first: if this same SO Batch contains both an FC row and the
        # General row that consumed it (mixed Jenis PO in one batch), the
        # consumption must be undone before the guard below runs -- otherwise
        # it would wrongly see the FC row as still claimed by a Sales Order
        # that's being cancelled in this very same operation.
        for row in sales_orders:
            release_fc_matches(row.name)

        for row in sales_orders:
            if row.po_type == PO_TYPE_FC:
                assert_fc_not_yet_consumed(row.name)

        for row in sales_orders:
            sales_order = frappe.get_doc("Sales Order", row.name)
            if sales_order.docstatus == 1:
                if sales_order.status == "Closed":
                    # ERPNext refuses to cancel a Closed order outright --
                    # reopen it first (mirrors the standard "Re-Open" action).
                    sales_order.update_status("Draft")
                    sales_order.reload()
                sales_order.cancel()
            else:
                frappe.delete_doc(
                    "Sales Order",
                    sales_order.name,
                    ignore_permissions=True,
                    force=True,
                )

        if sales_orders:
            frappe.db.delete(
                "SO Batch Created SO",
                {"parent": self.name, "parenttype": "SO Batch"},
            )

    def delete_related_sales_orders(self):
        """Runs on SO Batch delete (draft or already-cancelled). Frappe's own
        link check would otherwise deadlock: the Sales Order can't be deleted
        while it's listed in this batch's Created Sales Orders table, and this
        batch can't be deleted while a Sales Order still points back via
        so_batch. Deleting the Sales Orders here first breaks that cycle."""
        sales_orders = frappe.get_all(
            "Sales Order",
            filters={"so_batch": self.name},
            fields=["name", "docstatus", "po_type"],
        )
        if not sales_orders:
            return

        for row in sales_orders:
            release_fc_matches(row.name)

        for row in sales_orders:
            if row.po_type == PO_TYPE_FC:
                assert_fc_not_yet_consumed(row.name)
            assert_sales_order_has_no_downstream_documents(row.name)

        for row in sales_orders:
            sales_order = frappe.get_doc("Sales Order", row.name)
            if sales_order.docstatus == 1:
                if sales_order.status == "Closed":
                    sales_order.update_status("Draft")
                    sales_order.reload()
                sales_order.cancel()
            frappe.delete_doc(
                "Sales Order",
                row.name,
                ignore_permissions=True,
                force=True,
            )


def resolve_item(part_no, set_or_pcs, customer):
    if not customer:
        frappe.throw("Customer is required before resolving SO Batch items")

    item_codes = get_customer_items_by_part_no(part_no, customer)

    if set_or_pcs != "Set":
        if len(item_codes) > 1:
            frappe.throw(
                "Multiple active Items found with Part No {0} for customer {1}: {2}".format(
                    part_no, customer, ", ".join(item_codes)
                )
            )

        item_code = item_codes[0]
        return item_code, ""

    for item_code in item_codes:
        bundle_parents = frappe.get_all(
            "Product Bundle Item",
            filters={"item_code": item_code},
            pluck="parent",
        )

        for bundle_parent in bundle_parents:
            candidate = frappe.db.get_value("Product Bundle", bundle_parent, "new_item_code")
            if candidate and item_belongs_to_customer(candidate, customer):
                return item_code, candidate

    frappe.throw(
        "No Product Bundle item for Part No {0} belongs to customer {1}".format(
            part_no, customer
        )
    )


def get_customer_items_by_part_no(part_no, customer):
    items = frappe.get_all(
        "Item",
        filters={
            "custom_part_no": part_no,
            "linked_customer": customer,
            "disabled": 0,
        },
        pluck="name",
    )

    if not items:
        frappe.throw(
            "No active Item found with Part No {0} for customer {1}".format(
                part_no, customer
            )
        )

    return items


def item_belongs_to_customer(item_code, customer):
    return (
        frappe.db.get_value(
            "Item",
            {"name": item_code, "linked_customer": customer, "disabled": 0},
            "name",
        )
        is not None
    )


def get_expected_rate_for_so_batch_row(row):
    if flt(row.qty) <= 0:
        frappe.throw("Row {0}: Qty must be greater than zero".format(row.idx))

    if row.set_or_pcs == "Set":
        return get_expected_set_rate(row.resolved_set_item_code, row.qty, row.idx)

    master_card, component = get_master_card_component_for_item(row.resolved_item_code, row.idx)
    price_map, moq_qty = get_master_card_price_map(master_card, row.qty, row.idx)
    if component not in price_map:
        frappe.throw(
            "Row {0}: No price found for Master Card {1}, MOQ {2}, component {3}".format(
                row.idx, master_card, moq_qty, component
            )
        )

    return price_map[component], {}


def get_expected_set_rate(set_item_code, qty, row_idx):
    if not set_item_code:
        frappe.throw("Row {0}: Set item could not be resolved".format(row_idx))

    master_card = get_master_card_for_set_item(set_item_code, row_idx)
    price_map, moq_qty = get_master_card_price_map(master_card, qty, row_idx)
    bundle_items = frappe.get_all(
        "Product Bundle Item",
        filters={"parent": set_item_code},
        fields=["item_code", "qty"],
        order_by="idx",
    )
    if not bundle_items:
        frappe.throw("Row {0}: Product Bundle {1} has no components".format(row_idx, set_item_code))

    component_by_item = get_master_card_components_by_item(master_card)
    expected_rate = 0
    component_rates = {}
    for bundle_item in bundle_items:
        component = component_by_item.get(bundle_item.item_code)
        if not component:
            frappe.throw(
                "Row {0}: Bundle item {1} is not a component of Master Card {2}".format(
                    row_idx, bundle_item.item_code, master_card
                )
            )
        if component not in price_map:
            frappe.throw(
                "Row {0}: No price found for Master Card {1}, MOQ {2}, component {3}".format(
                    row_idx, master_card, moq_qty, component
                )
            )

        component_rate = price_map[component]
        component_rates[bundle_item.item_code] = component_rate
        expected_rate += flt(component_rate) * flt(bundle_item.qty or 1)

    return flt(expected_rate, get_price_matrix_precision()), component_rates


def get_master_card_component_for_item(item_code, row_idx):
    row = frappe.db.get_value(
        "Master Card Item",
        {"item_code": item_code},
        ["parent", "component"],
        as_dict=True,
    )
    if not row:
        frappe.throw(
            "Row {0}: Item {1} is not linked to a Master Card component".format(
                row_idx, item_code
            )
        )
    return row.parent, row.component.upper().strip()


def get_master_card_for_set_item(set_item_code, row_idx):
    if frappe.db.exists("Master Card", set_item_code):
        return set_item_code

    master_card = frappe.db.get_value("Master Card", {"item_code": set_item_code}, "name")
    if not master_card:
        frappe.throw(
            "Row {0}: Set item {1} is not linked to a Master Card".format(
                row_idx, set_item_code
            )
        )
    return master_card


def get_master_card_components_by_item(master_card):
    rows = frappe.get_all(
        "Master Card Item",
        filters={"parent": master_card, "parentfield": "items", "parenttype": "Master Card"},
        fields=["item_code", "component"],
    )
    return {
        row.item_code: row.component.upper().strip()
        for row in rows
        if row.item_code and row.component
    }


def get_master_card_price_map(master_card, qty, row_idx):
    moq_rows = frappe.get_all(
        "Master Card MOQ",
        filters={
            "parent": master_card,
            "parentfield": "moq_items",
            "parenttype": "Master Card",
        },
        fields=["idx", "moq_qty"],
    )
    moq_qty_by_idx = {row.idx: flt(row.moq_qty) for row in moq_rows}

    rows = frappe.get_all(
        "Master Card Price Item",
        filters={
            "parent": master_card,
            "parentfield": "price_items",
            "parenttype": "Master Card",
        },
        fields=["moq_idx", "component", "total"],
    )
    for row in rows:
        row.moq_qty = moq_qty_by_idx.get(row.moq_idx)
    rows = [row for row in rows if row.moq_qty is not None]
    rows.sort(key=lambda row: (-flt(row.moq_qty), row.component or ""))

    eligible = [row for row in rows if flt(row.moq_qty) <= flt(qty)]
    if not eligible:
        frappe.throw(
            "Row {0}: No Master Card price found for {1} at qty {2}".format(
                row_idx, master_card, qty
            )
        )

    selected_moq = flt(eligible[0].moq_qty)
    price_map = {}
    precision = get_price_matrix_precision()
    for row in eligible:
        if flt(row.moq_qty) != selected_moq:
            continue

        component = (row.component or "").upper().strip()
        if component in price_map:
            frappe.throw(
                "Row {0}: Duplicate price for Master Card {1}, MOQ {2}, component {3}".format(
                    row_idx, master_card, selected_moq, component
                )
            )
        price_map[component] = flt(row.total, precision)

    return price_map, selected_moq


def apply_validated_rates_to_sales_order(sales_order, items, po_type):
    sales_order.reload()

    for index, item in enumerate(items):
        so_item = sales_order.items[index]
        set_sales_order_item_rate(so_item, item["rate"])
        so_item.custom_po_type = po_type

        master_card, components = item["match_info"]
        if so_item.item_code in components:
            so_item.custom_master_card = master_card
            so_item.custom_component = components[so_item.item_code]

        if item["component_rates"]:
            for packed_item in sales_order.packed_items or []:
                if packed_item.parent_detail_docname != so_item.name:
                    continue
                if packed_item.item_code not in item["component_rates"]:
                    frappe.throw(
                        "Packed item {0} has no validated component rate".format(
                            packed_item.item_code
                        )
                    )
                packed_item.rate = item["component_rates"][packed_item.item_code]
                packed_item.custom_po_type = po_type
                packed_item.custom_master_card = master_card
                packed_item.custom_component = components.get(packed_item.item_code)

    sales_order.calculate_taxes_and_totals()
    sales_order.save(ignore_permissions=True)
    sales_order.reload()

    for index, item in enumerate(items):
        so_item = sales_order.items[index]
        if not rate_matches(so_item.rate, item["rate"]):
            frappe.throw(
                "Sales Order {0} row {1}: ERPNext recalculated rate {2}, expected {3}".format(
                    sales_order.name, so_item.idx, so_item.rate, item["rate"]
                )
            )

    if po_type == PO_TYPE_GENERAL:
        match_fc_quantities(sales_order)
        # match_fc_quantities writes coverage results via db.set_value, bypassing
        # this in-memory doc -- reload so a subsequent submit() doesn't overwrite
        # them with the stale pre-match values.
        sales_order.reload()


def resolve_match_info(row):
    """Return (master_card, {item_code: component}) describing which Master Card
    component(s) this SO Batch Item row will produce. Used to match FC (Forecast)
    quantities against later General PO quantities for the same component."""
    if row.set_or_pcs == "Set":
        master_card = get_master_card_for_set_item(row.resolved_set_item_code, row.idx)
        component_by_item = get_master_card_components_by_item(master_card)
        bundle_item_codes = frappe.get_all(
            "Product Bundle Item",
            filters={"parent": row.resolved_set_item_code},
            pluck="item_code",
        )
        components = {
            item_code: component_by_item[item_code]
            for item_code in bundle_item_codes
            if item_code in component_by_item
        }
        return master_card, components

    master_card, component = get_master_card_component_for_item(row.resolved_item_code, row.idx)
    return master_card, {row.resolved_item_code: component}


def match_fc_quantities(sales_order):
    """For a General Sales Order, consume outstanding FC (Forecast) quantities
    FIFO by (Master Card, Component), and record on this order how much of it
    is already covered by prior FC production vs. still needs fresh production."""
    rows_to_cover = []
    for so_item in sales_order.items:
        if so_item.custom_master_card and so_item.custom_component:
            rows_to_cover.append(("Sales Order Item", so_item))
    for packed_item in sales_order.packed_items or []:
        if packed_item.custom_master_card and packed_item.custom_component:
            rows_to_cover.append(("Packed Item", packed_item))

    touched_fc_sales_orders = set()
    for doctype, row in rows_to_cover:
        covered_qty, note, touched = consume_fc_for_row(
            sales_order.name, row.custom_master_card, row.custom_component, flt(row.qty)
        )
        frappe.db.set_value(
            doctype,
            row.name,
            {"custom_fc_covered_qty": covered_qty, "custom_fc_coverage_note": note},
            update_modified=False,
        )
        touched_fc_sales_orders.update(touched)

    for fc_so_name in touched_fc_sales_orders:
        close_fc_sales_order_if_fully_covered(fc_so_name)


def consume_fc_for_row(sales_order_name, master_card, component, qty_needed):
    fc_rows = get_outstanding_fc_rows(master_card, component)

    remaining = flt(qty_needed)
    covered = 0.0
    touched_fc_sales_orders = set()
    for fc_row in fc_rows:
        if remaining <= 0:
            break
        outstanding = flt(fc_row["qty"]) - flt(fc_row["matched_qty"]) - flt(fc_row["delivered_qty"])
        if outstanding <= 0:
            continue

        take = min(outstanding, remaining)
        frappe.db.set_value(
            fc_row["doctype"],
            fc_row["name"],
            "custom_fc_matched_qty",
            flt(fc_row["matched_qty"]) + take,
            update_modified=False,
        )
        frappe.get_doc(
            {
                "doctype": "FC Match Log",
                "source_doctype": fc_row["doctype"],
                "source_name": fc_row["name"],
                "sales_order": sales_order_name,
                "master_card": master_card,
                "component": component,
                "qty": take,
            }
        ).insert(ignore_permissions=True)

        covered += take
        remaining -= take
        touched_fc_sales_orders.add(fc_row["sales_order"])

    note = "Clear" if remaining <= 0 else "Ord. {0}".format(format_remark_qty(remaining))
    return covered, note, touched_fc_sales_orders


def format_remark_qty(value):
    """Format a qty for the Remark text with thousands separators and no
    trailing decimal noise, e.g. 29200.0 -> "29,200", 1234.5 -> "1,234.5"."""
    return "{:,.2f}".format(flt(value)).rstrip("0").rstrip(".")


def get_outstanding_fc_rows(master_card, component):
    """FIFO pool of outstanding FC quantity for one (Master Card, Component).

    Ordered by transaction_date first (the business date the user assigned),
    then by the parent Sales Order's creation timestamp as a tie-breaker --
    transaction_date is a Date field with no time component, so two FC SOs
    entered on the same business day would otherwise sort in an arbitrary,
    non-deterministic order. creation is a full datetime every Frappe
    document already has, so this needs no schema change.
    """
    so_item_rows = frappe.db.sql(
        """
        SELECT
            'Sales Order Item' AS doctype,
            soi.name AS name,
            soi.parent AS sales_order,
            soi.qty AS qty,
            soi.delivered_qty AS delivered_qty,
            soi.custom_fc_matched_qty AS matched_qty,
            so.transaction_date AS transaction_date,
            so.creation AS so_creation
        FROM `tabSales Order Item` soi
        INNER JOIN `tabSales Order` so ON so.name = soi.parent
        WHERE so.docstatus = 1
          AND so.po_type = %(fc)s
          AND soi.custom_master_card = %(master_card)s
          AND soi.custom_component = %(component)s
        """,
        {"fc": PO_TYPE_FC, "master_card": master_card, "component": component},
        as_dict=True,
    )

    packed_item_rows = frappe.db.sql(
        """
        SELECT
            'Packed Item' AS doctype,
            pi.name AS name,
            pi.parent AS sales_order,
            pi.qty AS qty,
            pi.packed_qty AS delivered_qty,
            pi.custom_fc_matched_qty AS matched_qty,
            so.transaction_date AS transaction_date,
            so.creation AS so_creation
        FROM `tabPacked Item` pi
        INNER JOIN `tabSales Order` so ON so.name = pi.parent
        WHERE so.docstatus = 1
          AND pi.parenttype = 'Sales Order'
          AND so.po_type = %(fc)s
          AND pi.custom_master_card = %(master_card)s
          AND pi.custom_component = %(component)s
        """,
        {"fc": PO_TYPE_FC, "master_card": master_card, "component": component},
        as_dict=True,
    )

    rows = list(so_item_rows) + list(packed_item_rows)
    rows.sort(key=lambda r: (getdate(r["transaction_date"]), r["so_creation"]))
    return rows


def close_fc_sales_order_if_fully_covered(sales_order_name):
    """Close an FC Sales Order once every item on it has been fully claimed by
    later General PO(s) -- there's nothing left on it still waiting on a
    customer PO, so it shouldn't sit open in To Deliver/To Bill lists."""
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.docstatus != 1 or so.po_type != PO_TYPE_FC or so.status in ("Closed", "Cancelled"):
        return
    if not so.items:
        return

    if all(is_so_item_fully_covered(so, item) for item in so.items):
        so.update_status("Closed")


def is_so_item_fully_covered(so, so_item):
    if so_item.custom_master_card and so_item.custom_component:
        return flt(so_item.qty) - flt(so_item.custom_fc_matched_qty) <= FC_QTY_TOLERANCE

    packed_rows = [
        p for p in (so.packed_items or []) if p.parent_detail_docname == so_item.name
    ]
    if not packed_rows:
        return False

    return all(
        flt(p.qty) - flt(p.custom_fc_matched_qty) <= FC_QTY_TOLERANCE for p in packed_rows
    )


def release_fc_matches(sales_order_name):
    """Undo any FC quantity this Sales Order consumed, e.g. when the SO Batch
    that created it is cancelled. Safe to call even if nothing was consumed."""
    logs = frappe.get_all(
        "FC Match Log",
        filters={"sales_order": sales_order_name},
        fields=["name", "source_doctype", "source_name", "qty"],
    )
    touched_fc_sales_orders = set()
    for log in logs:
        current = flt(
            frappe.db.get_value(log.source_doctype, log.source_name, "custom_fc_matched_qty")
        )
        frappe.db.set_value(
            log.source_doctype,
            log.source_name,
            "custom_fc_matched_qty",
            max(current - flt(log.qty), 0),
            update_modified=False,
        )
        touched_fc_sales_orders.add(
            frappe.db.get_value(log.source_doctype, log.source_name, "parent")
        )
        frappe.delete_doc("FC Match Log", log.name, ignore_permissions=True, force=True)

    for fc_so_name in touched_fc_sales_orders:
        reopen_fc_sales_order_if_no_longer_covered(fc_so_name)


def reopen_fc_sales_order_if_no_longer_covered(sales_order_name):
    """Mirror of close_fc_sales_order_if_fully_covered: if releasing a
    consumed quantity leaves a Closed FC Sales Order no longer fully
    covered, reopen it so it doesn't sit misleadingly Closed."""
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.docstatus != 1 or so.status != "Closed":
        return
    if not all(is_so_item_fully_covered(so, item) for item in so.items):
        so.update_status("Draft")


def assert_fc_not_yet_consumed(sales_order_name):
    """Block cancelling an FC Sales Order once a later General PO has already
    claimed some of its quantity — that General order's coverage would go stale."""
    consumed = frappe.db.sql(
        """
        SELECT COUNT(*) FROM `tabSales Order Item`
        WHERE parent = %s AND IFNULL(custom_fc_matched_qty, 0) > 0
        UNION ALL
        SELECT COUNT(*) FROM `tabPacked Item`
        WHERE parent = %s AND parenttype = 'Sales Order' AND IFNULL(custom_fc_matched_qty, 0) > 0
        """,
        (sales_order_name, sales_order_name),
    )
    if any(r[0] for r in consumed):
        frappe.throw(
            "Sales Order {0} (FC) already has quantity claimed by a later PO. "
            "Cancel or amend those Sales Orders first.".format(sales_order_name)
        )


def assert_sales_order_has_no_downstream_documents(sales_order_name):
    """Force-deleting a Sales Order (via SO Batch delete) skips Frappe's normal
    linked-document check. Re-check the doctypes that actually matter here so
    a Delivery Note, Sales Invoice, or Job Order doesn't end up pointing at a
    Sales Order that no longer exists."""
    checks = [
        ("Delivery Note Item", "against_sales_order"),
        ("Sales Invoice Item", "sales_order"),
        ("Job Order Corrugator Item", "sales_order"),
        ("Job Order Converting Sales Order Item", "sales_order"),
    ]
    blockers = []
    for doctype, fieldname in checks:
        count = frappe.db.count(doctype, {fieldname: sales_order_name})
        if count:
            blockers.append("{0} {1} row(s)".format(count, doctype))

    if blockers:
        frappe.throw(
            "Cannot delete Sales Order {0}: still referenced by {1}. "
            "Remove those first.".format(sales_order_name, ", ".join(blockers))
        )


def block_fc_sales_orders(doc, method=None):
    """Doc event: block Delivery Note / Sales Invoice items that reference a
    Sales Order still marked Jenis PO = FC — those need a confirmed customer
    PO Number before they can be delivered or invoiced."""
    so_fieldname = "against_sales_order" if doc.doctype == "Delivery Note" else "sales_order"
    so_names = {row.get(so_fieldname) for row in doc.items if row.get(so_fieldname)}
    if not so_names:
        return

    fc_sales_orders = frappe.get_all(
        "Sales Order",
        filters={"name": ["in", list(so_names)], "po_type": PO_TYPE_FC},
        pluck="name",
    )
    if fc_sales_orders:
        frappe.throw(
            "Cannot proceed: Sales Order {0} is still Jenis PO = FC. "
            "Wait for the customer's PO Number before creating a Delivery Note / Sales Invoice.".format(
                ", ".join(fc_sales_orders)
            )
        )


def set_sales_order_item_rate(so_item, rate):
    so_item.rate = rate
    so_item.price_list_rate = rate
    so_item.discount_amount = 0
    so_item.discount_percentage = 0
    so_item.margin_rate_or_amount = 0


def rate_matches(actual, expected):
    precision = get_rate_precision()
    return flt(actual, precision) == flt(expected, precision)


def get_sales_order_rate(rate):
    return flt(rate, get_rate_precision())


def get_rate_precision():
    return get_currency_precision() or 2


def get_price_matrix_precision():
    return max(
        frappe.get_precision("SO Batch Item", "rate") or 2,
        frappe.get_precision("Master Card Price Item", "total") or 2,
    )


def set_dn_po_line_no(doc, method=None):
    """Copy po_line_no from the linked Sales Order onto each Delivery Note Item."""
    for item in doc.items or []:
        if item.against_sales_order and not item.get("po_line_no"):
            item.po_line_no = frappe.db.get_value(
                "Sales Order", item.against_sales_order, "po_line_no"
            ) or ""
