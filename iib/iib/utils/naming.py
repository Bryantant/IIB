import frappe


_SINGLETON = "IIB Document Naming Settings"


def get_next_iib_number(counter_key, period=None, digits=5):
    """Return the next zero-padded sequence number for a given counter key.

    Locks tabSingles for the IIB Document Naming Settings singleton to prevent
    race conditions. Resets the counter to 1 when the period string changes
    (e.g. year changes for YY-based series, or year-month changes for YYMM-based).

    counter_key : str  — key prefix, e.g. 'so_batch', 'jop1', 'dps'
    period      : str | None — current period string (e.g. '26', '2606'). None = never reset.
    digits      : int  — zero-pad width for the returned number string
    """
    frappe.db.sql(
        "SELECT value FROM `tabSingles` WHERE doctype=%s FOR UPDATE",
        (_SINGLETON,),
    )

    period_field = f"{counter_key}_current_period"
    number_field = f"{counter_key}_next_number"

    current_period = frappe.db.get_single_value(_SINGLETON, period_field) or ""
    current_number = int(frappe.db.get_single_value(_SINGLETON, number_field) or 1)

    if period is not None and current_period != period:
        current_number = 1

    result = str(current_number).zfill(digits)

    frappe.db.set_single_value(_SINGLETON, number_field, current_number + 1)
    if period is not None:
        frappe.db.set_single_value(_SINGLETON, period_field, period)

    return result
