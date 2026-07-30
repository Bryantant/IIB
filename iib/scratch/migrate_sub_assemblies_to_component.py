import frappe


def execute():
    """Reassign master-data references to the 'Sub Assemblies' Item Group over
    to 'Component': Item.item_group, Master Card.mc_fg_item_group, and the
    IIB Settings singleton's mc_fg_item_group value.

    Does NOT delete the 'Sub Assemblies' Item Group itself or touch submitted
    transaction history -- 2 rows in Sales Order Item (submitted Sales Orders
    2600003/2600004, item 10001A) still snapshot 'Sub Assemblies' and are left
    as-is per Bry's call. The Item Group record stays around (unused for new
    master data) so that historical snapshot link remains valid.

    Pure classification change -- no accounting/stock impact -- so direct SQL /
    frappe.db.set_value is used instead of the full Document.save() path.
    """
    item_names = [
        r["name"]
        for r in frappe.db.sql(
            "select name from tabItem where item_group = %s",
            ("Sub Assemblies",),
            as_dict=True,
        )
    ]
    print("Items in 'Sub Assemblies' to reassign:", len(item_names))

    for i in range(0, len(item_names), 1000):
        chunk = tuple(item_names[i : i + 1000])
        frappe.db.sql(
            "update tabItem set item_group = 'Component' where name in %(names)s",
            {"names": chunk},
        )

    mc_updated = frappe.db.sql(
        "update `tabMaster Card` set mc_fg_item_group = 'Component' where mc_fg_item_group = 'Sub Assemblies'"
    )
    print("Master Card rows updated:", mc_updated)

    if frappe.db.get_single_value("IIB Settings", "mc_fg_item_group") == "Sub Assemblies":
        frappe.db.set_single_value("IIB Settings", "mc_fg_item_group", "Component")
        print("Updated IIB Settings.mc_fg_item_group -> Component")

    remaining_items = frappe.db.count("Item", {"item_group": "Sub Assemblies"})
    print("Items still in 'Sub Assemblies':", remaining_items)
    print(
        "Leaving Item Group 'Sub Assemblies' in place (2 historical Sales Order "
        "Item rows on submitted orders 2600003/2600004 still reference it)."
    )

    frappe.db.commit()
    print("Remaining -> Item (Component):", frappe.db.count("Item", {"item_group": "Component"}))
