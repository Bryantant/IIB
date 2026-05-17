import frappe
from frappe.utils import flt
from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan


class ProductionPlanExtended(ProductionPlan):
    def create_work_order(self, item):
        from erpnext.manufacturing.doctype.work_order.work_order import OverProductionError

        if flt(item.get("qty")) <= 0:
            return

        wo = frappe.new_doc("Work Order")
        wo.update(item)
        wo.planned_start_date = item.get("planned_start_date") or item.get("schedule_date")

        if item.get("warehouse"):
            wo.fg_warehouse = item.get("warehouse")

        wo.set_work_order_operations()
        wo.set_required_items()

        # Apply per-run RM substitutions
        plan_item = item.get("production_plan_item")
        overrides = [
            r for r in self.get("custom_rm_overrides", [])
            if r.production_plan_item == plan_item
        ]
        if overrides:
            _apply_rm_overrides(wo, overrides)

        try:
            wo.flags.ignore_mandatory = True
            wo.flags.ignore_validate = True
            wo.insert()
            return wo.name
        except OverProductionError:
            pass


def _apply_rm_overrides(wo, overrides):
    for override in overrides:
        if not override.original_item or not override.replacement_item:
            continue
        for req in wo.required_items:
            if req.item_code == override.original_item:
                req.item_code = override.replacement_item
                item_data = (
                    frappe.db.get_value(
                        "Item",
                        override.replacement_item,
                        ["item_name", "stock_uom"],
                        as_dict=True,
                    )
                    or {}
                )
                req.item_name = item_data.get("item_name", req.item_name)
                req.stock_uom = item_data.get("stock_uom", req.stock_uom)
