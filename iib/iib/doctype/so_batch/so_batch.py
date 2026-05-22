import frappe
from frappe.model.document import Document


class SOBatch(Document):
    def validate(self):
        self.set_resolved_items()

    def on_submit(self):
        self.create_sales_orders()

    def on_cancel(self):
        self.cancel_related_sales_orders()

    def set_resolved_items(self):
        for row in self.so_batch_items:
            item_code, set_item_code = resolve_item(row.part_no, row.set_or_pcs)
            row.resolved_item_code = item_code
            row.resolved_set_item_code = set_item_code

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

        company = frappe.db.get_single_value("Global Defaults", "default_company")
        selling_price_list = (
            frappe.db.get_single_value("Selling Settings", "selling_price_list")
            or "Standard Selling"
        )

        po_groups = {}
        for row in self.so_batch_items:
            item_code = row.resolved_set_item_code or row.resolved_item_code
            key = (row.po_no, row.po_date)
            po_groups.setdefault(key, []).append(
                {
                    "item_code": item_code,
                    "qty": row.qty,
                    "rate": row.rate or 0,
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
                        "delivery_date": self.delivery_date,
                        "warehouse": self.default_warehouse,
                    },
                )

            try:
                so.insert(ignore_permissions=True)
                created_sos.append(so.name)
            except Exception:
                frappe.throw(
                    "Error creating Sales Order for PO {0}: {1}".format(
                        po_no, frappe.get_traceback()
                    )
                )

        self.db_set("created_sales_orders", ", ".join(created_sos) if created_sos else "")

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
            self.db_set("created_sales_orders", "")


def resolve_item(part_no, set_or_pcs):
    item_code = frappe.db.get_value(
        "Item",
        {"custom_part_no": part_no, "disabled": 0},
        "name",
    )
    if not item_code:
        frappe.throw("No item found with Part No: {0}".format(part_no))

    if set_or_pcs != "Set":
        return item_code, ""

    bundle_parent = frappe.db.get_value(
        "Product Bundle Item",
        {"item_code": item_code},
        "parent",
    )
    if not bundle_parent:
        frappe.throw(
            "No Product Bundle found containing item {0} (Part No: {1})".format(
                item_code, part_no
            )
        )

    bundle_item_code = frappe.db.get_value("Product Bundle", bundle_parent, "new_item_code")
    if not bundle_item_code:
        frappe.throw("Could not resolve bundle item code for bundle: {0}".format(bundle_parent))

    return item_code, bundle_item_code
