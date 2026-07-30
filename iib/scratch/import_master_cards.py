import re
import openpyxl
import frappe
from collections import defaultdict

VALID_COMPONENT = re.compile(r"[A-Z]")

# Quantity used for the synthetic "no minimum" tier that carries a component's
# base price when the legacy data has no MOQ level to hang it on.
BASE_TIER = 0.0

PATH = "/Users/bryantantonio/Documents/Hicom/Client/IIB/Import/Master Card.xlsx"
SKIP_MCNO = set()  # "1"/"2" were excluded during the bulk import (name collision
# with dev test data); that data has since been deleted, so both are importable now.
SINGDOUB_MAP = {0: "", 1: "Single A", 2: "Single B/C", 3: "Double BC", 4: "Double AB"}
UOM_NORMALIZE = {"pcs": "Pcs", "": "Pcs"}
PLACEHOLDER = {"", "-", None}


def _s(v):
    if v is None:
        return ""
    return str(v).strip()


def _f(v):
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _truthy(v):
    try:
        return v not in (None, "") and float(v) != 0
    except (ValueError, TypeError):
        return bool(v)


def load_sheets():
    wb = openpyxl.load_workbook(PATH, read_only=True, data_only=True)

    def rows_of(sheet_name):
        ws = wb[sheet_name]
        header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
        idx = {name: i for i, name in enumerate(header)}
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            out.append({k: row[i] for k, i in idx.items()})
        return out

    return rows_of("MastCard"), rows_of("MastCardSub"), rows_of("MastCardMOQ")


def build_context(mc_rows, sub_rows, moq_rows):
    sub_by_mcno = defaultdict(list)
    for r in sub_rows:
        comp = _s(r.get("Component")).upper()
        if not VALID_COMPONENT.fullmatch(comp):
            continue
        if not _s(r.get("PartNo")) and not _s(r.get("PartNo2")):
            continue
        sub_by_mcno[_s(r["MCNo"])].append(r)

    moq_by_mcno = defaultdict(list)
    for r in moq_rows:
        moq_by_mcno[_s(r["MCNo"])].append(r)

    return sub_by_mcno, moq_by_mcno


def build_moq_list(header, moq_tier_rows):
    values = set()
    for col in ("MOQ1", "MOQ2", "MOQ3", "MOQ4", "MOQ5", "MOQ6", "MOQ7", "MOQ8"):
        v = header.get(col)
        try:
            if v not in (None, "") and float(v) != 0:
                values.add(float(v))
        except (ValueError, TypeError):
            pass
    for r in moq_tier_rows:
        v = r.get("MOQ")
        try:
            if v not in (None, "") and float(v) != 0:
                values.add(float(v))
        except (ValueError, TypeError):
            pass
    return sorted(values)


def build_item_row(sub_row):
    component = _s(sub_row["Component"]).upper()
    item_description = _s(sub_row["PartNo"])
    part_no = _s(sub_row["PartNo2"]) or item_description

    unit = _s(sub_row["Unit"])
    uom = UOM_NORMALIZE.get(unit.lower(), unit) if unit.lower() in UOM_NORMALIZE else unit

    board_quality = _s(sub_row["BoardQua"])
    flute = _s(sub_row["CorFlut"])
    pic = _s(sub_row["PIC"])

    singdoub_raw = sub_row.get("SingDoub")
    try:
        singdoub_key = int(singdoub_raw) if singdoub_raw is not None else 0
    except (ValueError, TypeError):
        singdoub_key = 0

    row = {
        "component": component,
        "item_description": item_description,
        "custom_part_no": part_no,
        "custom_printing": 1 if _truthy(sub_row.get("Printing")) else 0,
        "custom_assembly": 1 if _truthy(sub_row.get("Assembly")) else 0,
        "custom_colour_1": _s(sub_row.get("Colours")) or None,
        "custom_colour_2": _s(sub_row.get("Colour2")) or None,
        "custom_colour_3": _s(sub_row.get("Colour3")) or None,
        "custom_colour_4": _s(sub_row.get("Colour4")) or None,
        "custom_colour_5": _s(sub_row.get("Colour5")) or None,
        "custom_finishing": _s(sub_row.get("Finishing")) or None,
        "qty": float(sub_row["Sub"]) if sub_row.get("Sub") not in (None, "", 0) else 1,
        "uom": uom or "Pcs",
        "custom_inside_measure_l": int(sub_row.get("ISizeL") or 0),
        "custom_inside_measure_w": int(sub_row.get("ISizeW") or 0),
        "custom_inside_measure_h": int(sub_row.get("ISizeH") or 0),
        "custom_single_double": SINGDOUB_MAP.get(singdoub_key, ""),
        "custom_width": int(sub_row.get("Width") or 0),
        "custom_length": int(sub_row.get("Length") or 0),
        "custom_dc": int(sub_row.get("DieCutSht") or 0),
        "custom_board_quality": board_quality if board_quality not in PLACEHOLDER else None,
        "custom_flute": flute if flute not in PLACEHOLDER else None,
        "custom_crease_w": _s(sub_row.get("CreaseW")),
        "custom_crease_l": _s(sub_row.get("CreaseL")),
        "custom_slotting": _s(sub_row.get("Slotting")),
        "custom_display": 1 if _truthy(sub_row.get("DispFlag")) else 0,
        "custom_joint_1": _s(sub_row.get("ManfJoin1")) or None,
        "custom_joint_2": _s(sub_row.get("ManfJoin2")) or None,
        "custom_remarks": _s(sub_row.get("Remark")),
        "custom_weight": float(sub_row.get("Weight") or 0),
        "custom_pic": pic if pic not in PLACEHOLDER and pic != "NA" else None,
    }
    return row


def build_master_card_doc(mcno, header, sub_group, moq_tier_rows):
    components = {_s(r["Component"]).upper() for r in sub_group}
    moq_list = build_moq_list(header, moq_tier_rows)

    items = [build_item_row(r) for r in sub_group]

    price_items = []
    # Tier-specific prices from MastCardMOQ, keyed component -> moq value.
    tier_rows_by_comp = defaultdict(dict)
    for r in moq_tier_rows:
        comp = _s(r.get("Component")).upper()
        if comp not in components:
            continue
        try:
            moq_val = float(r.get("MOQ"))
        except (ValueError, TypeError):
            continue
        if moq_val not in moq_list:
            continue
        tier_rows_by_comp[comp][moq_val] = r

    # The MastCardSub row is the component's base price. It occupies the
    # lowest tier that MastCardMOQ does not already price. When every tier is
    # taken, it is either a duplicate of one of them (drop it) or a genuinely
    # distinct "no minimum" price, which earns an extra qty-0 tier.
    base_assignment = {}
    needs_base_tier = False
    for r in sub_group:
        comp = _s(r["Component"]).upper()
        priced = tier_rows_by_comp.get(comp, {})
        free = [t for t in moq_list if t not in priced]
        if free:
            base_assignment[comp] = min(free)
            continue
        base_vals = (round(_f(r.get("Price")), 4), round(_f(r.get("Total")), 4))
        duplicate = any(
            (round(_f(x.get("Price")), 4), round(_f(x.get("Total")), 4)) == base_vals
            for x in priced.values()
        )
        if duplicate:
            base_assignment[comp] = None
        else:
            base_assignment[comp] = BASE_TIER
            needs_base_tier = True

    # If a base tier gets created at all, price every component there. A
    # component whose base merely duplicated a higher tier was dropped above;
    # leaving it out would render a tier that prices only some components.
    if needs_base_tier:
        for comp, tier in base_assignment.items():
            if tier is None:
                base_assignment[comp] = BASE_TIER

    final_moq_list = ([BASE_TIER] if needs_base_tier else []) + moq_list

    def _price_row(comp, src, tier_value):
        material = _f(src.get("Price"))
        labour = _f(src.get("vLabour"))
        profit = _f(src.get("Profit"))
        ext_profit = _f(src.get("ExtProfit"))
        legacy_total = _f(src.get("Total"))

        # Some legacy rows carry only a lump Total with no breakdown. The app
        # recomputes total = material + labour + profit + ext_profit in
        # _calculate_price_items, so such a row would import as 0.00 and the
        # price would be lost. Book the lump sum as material to preserve it.
        if legacy_total and not (material or labour or profit or ext_profit):
            material = legacy_total

        # moq_idx links to the Master Card MOQ child row's `idx`, which Frappe
        # numbers from 1 (see render_price_items_editor in master_card.js).
        return {
            "component": comp,
            "material": material,
            "labour": labour,
            "profit": profit,
            "ext_profit": ext_profit,
            "total": legacy_total,
            "moq_idx": final_moq_list.index(tier_value) + 1,
        }

    for r in sub_group:
        comp = _s(r["Component"]).upper()
        tier_value = base_assignment.get(comp)
        if tier_value is None:
            continue
        price_items.append(_price_row(comp, r, tier_value))

    for comp, priced in tier_rows_by_comp.items():
        for moq_val, r in priced.items():
            price_items.append(_price_row(comp, r, moq_val))

    manf_joint_1 = _s(header.get("ManfJoin1"))
    manf_joint_2 = _s(header.get("ManfJoin2"))
    currency = _s(header.get("Currcode"))
    obsolete = _s(header.get("Obsolete"))

    customer_code = _s(header.get("CustCode"))
    doc_dict = {
        "doctype": "Master Card",
        "customer": f"C{customer_code}" if customer_code else None,
        "description": _s(header.get("Descr")),
        "remark": _s(header.get("Remark")),
        "disabled": 1 if obsolete == "-1" else 0,
        "currency": currency or None,
        "custom_manufacturing_joint_1": manf_joint_1 or None,
        "custom_manufacturing_joint_2": manf_joint_2 or None,
        "items": items,
        "price_items": price_items,
        "moq_items": [{"moq_qty": v} for v in final_moq_list],
    }
    return doc_dict


def execute(limit=None, dry_run=False, only=None):
    mc_rows, sub_rows, moq_rows = load_sheets()
    sub_by_mcno, moq_by_mcno = build_context(mc_rows, sub_rows, moq_rows)

    only_set = {str(m) for m in only} if only else None

    processed = 0
    succeeded = 0
    failed = []
    skipped_no_items = 0

    for header in mc_rows:
        mcno = _s(header["MCNo"])
        if mcno in SKIP_MCNO:
            continue
        if only_set is not None and mcno not in only_set:
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1

        sub_group = sub_by_mcno.get(mcno, [])
        if not sub_group:
            skipped_no_items += 1
            continue

        moq_tier_rows = moq_by_mcno.get(mcno, [])

        try:
            doc_dict = build_master_card_doc(mcno, header, sub_group, moq_tier_rows)
            if dry_run:
                succeeded += 1
                continue
            doc = frappe.get_doc(doc_dict)
            doc.name = mcno
            doc.flags.name_set = True
            doc.insert(ignore_permissions=True)
            succeeded += 1
        except Exception as e:
            failed.append((mcno, str(e)))

        if processed % 500 == 0:
            print(f"...processed {processed}, succeeded {succeeded}, failed {len(failed)}")
            if not dry_run:
                frappe.db.commit()

    if not dry_run:
        frappe.db.commit()

    print()
    print(f"Processed: {processed}")
    print(f"Succeeded: {succeeded}")
    print(f"Skipped (no component rows in MastCardSub): {skipped_no_items}")
    print(f"Failed: {len(failed)}")
    for mcno, err in failed[:30]:
        print(f"  MCNo {mcno}: {err}")
    if len(failed) > 30:
        print(f"  ... and {len(failed) - 30} more")

    return {"processed": processed, "succeeded": succeeded, "failed": failed, "skipped_no_items": skipped_no_items}
