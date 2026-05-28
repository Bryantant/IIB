import frappe
from erpnext.accounts.utils import get_currency_precision
from frappe.utils import flt
from frappe.model.document import Document


class SOBatch(Document):
    def validate(self):
        if not self.company:
            self.company = frappe.db.get_single_value("Global Defaults", "default_company")
        self.set_resolved_items()
        self.set_validated_rates()

    def on_submit(self):
        self.create_sales_orders()

    def on_cancel(self):
        self.cancel_related_sales_orders()

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
        for row in self.so_batch_items:
            item_code = row.resolved_set_item_code or row.resolved_item_code
            expected_rate, component_rates = get_expected_rate_for_so_batch_row(row)
            expected_rate = get_sales_order_rate(expected_rate)
            key = (row.po_no, row.po_date)
            po_groups.setdefault(key, []).append(
                {
                    "item_code": item_code,
                    "qty": row.qty,
                    "rate": expected_rate,
                    "component_rates": component_rates,
                }
            )

        created_sos = []
        for (po_no, po_date), items in po_groups.items():
            so = frappe.new_doc("Sales Order")
            so.company = company
            so.customer = self.customer
            so.order_type = "Sales"
            so.transaction_date = self.transaction_date
            so.delivery_date = self.delivery_date
            so.currency = self.currency
            so.conversion_rate = self.conversion_rate
            so.selling_price_list = selling_price_list
            so.payment_terms_template = self.payment_terms_template
            so.set_warehouse = self.default_warehouse
            so.po_no = po_no
            so.po_date = po_date
            so.so_batch = self.name

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
                        "delivery_date": self.delivery_date,
                        "warehouse": self.default_warehouse,
                    },
                )

            try:
                so.insert(ignore_permissions=True)
                apply_validated_rates_to_sales_order(so, items)
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
            lines = ["<b>{0} Sales Order(s) created:</b>".format(len(created_sos))]
            for name in created_sos:
                lines.append("&bull; <a href='/app/sales-order/{0}'>{0}</a>".format(name))
            frappe.msgprint("<br>".join(lines), title="SO Batch Complete", indicator="green")
        else:
            frappe.msgprint("No Sales Orders were created.", title="SO Batch", indicator="orange")

    def cancel_related_sales_orders(self):
        sales_orders = frappe.get_all(
            "Sales Order",
            filters={"so_batch": self.name, "docstatus": ["!=", 2]},
            fields=["name", "docstatus"],
        )

        for row in sales_orders:
            sales_order = frappe.get_doc("Sales Order", row.name)
            if sales_order.docstatus == 1:
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
    rows = frappe.get_all(
        "Master Card Price Item",
        filters={
            "parent": master_card,
            "parentfield": "price_items",
            "parenttype": "Master Card",
        },
        fields=["moq_qty", "component", "total"],
        order_by="moq_qty desc, component asc",
    )
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


def apply_validated_rates_to_sales_order(sales_order, items):
    sales_order.reload()

    for index, item in enumerate(items):
        so_item = sales_order.items[index]
        set_sales_order_item_rate(so_item, item["rate"])

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
