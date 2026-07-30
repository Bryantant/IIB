import frappe


def execute(dry_run=False):
    """Backfill Colour.colour_group (Table MultiSelect) from real usage on
    Master Card Item rows, since most Colour records were never tagged.

    For every custom_colour_N value found across all Master Card Item rows
    (N=1..5), tag that Colour with "Colour N" if it isn't already tagged --
    e.g. MC 14419 has custom_colour_1=BLACK, custom_colour_2=WHITE03, so
    BLACK gets group "Colour 1" and WHITE03 gets group "Colour 2". Existing
    tags are left untouched; this only adds missing ones. Idempotent -- safe
    to re-run.
    """
    needed = {}  # colour_name -> set of "Colour N" strings
    for i in range(1, 6):
        field = f"custom_colour_{i}"
        rows = frappe.db.sql(
            f"""
            select distinct `{field}` as colour_name
            from `tabMaster Card Item`
            where `{field}` is not null and `{field}` != ''
            """,
            as_dict=True,
        )
        for r in rows:
            needed.setdefault(r.colour_name, set()).add(f"Colour {i}")

    print("Distinct colours referenced on Master Card Item:", len(needed))

    updated = 0
    added_tags = 0
    conflicts = []  # colours referenced in more than one slot
    missing_colours = []

    for colour_name, groups in sorted(needed.items()):
        if len(groups) > 1:
            conflicts.append((colour_name, sorted(groups)))

        if not frappe.db.exists("Colour", colour_name):
            missing_colours.append(colour_name)
            continue

        existing = set(
            frappe.db.get_all(
                "Colour Colour Group",
                filters={"parent": colour_name, "parenttype": "Colour"},
                pluck="colour_group",
            )
        )
        to_add = groups - existing
        if not to_add:
            continue

        updated += 1
        added_tags += len(to_add)
        if dry_run:
            print(f"  {colour_name}: would add {sorted(to_add)}")
            continue

        doc = frappe.get_doc("Colour", colour_name)
        for g in sorted(to_add):
            doc.append("colour_group", {"colour_group": g})
        doc.save(ignore_permissions=True)

    if not dry_run:
        frappe.db.commit()

    print(f"Colours {'to update' if dry_run else 'updated'}: {updated}")
    print(f"Group tags {'to add' if dry_run else 'added'}: {added_tags}")

    print(f"Colours referenced in more than one slot: {len(conflicts)}")
    for name, groups in conflicts[:30]:
        print("  -", name, "->", groups)

    if missing_colours:
        print(f"Referenced colours not found in Colour doctype ({len(missing_colours)}):")
        for c in missing_colours[:30]:
            print("  -", c)

    return {
        "referenced": len(needed),
        "updated": updated,
        "added_tags": added_tags,
        "conflicts": len(conflicts),
        "missing_colours": len(missing_colours),
    }
