import frappe


def autoname(doc, method=None):
    """Name Customers C<first letter of name><4-digit sequence>, e.g. CA0001.

    Continues the legacy per-letter numbering migrated from the old system.
    A caller-supplied name is honoured during a data import so migration
    files keep their own IDs.
    """
    if frappe.flags.in_import and doc.name:
        return

    letter = (doc.customer_name or "").strip()[:1].upper()
    if not letter.isalpha():
        letter = "X"
    prefix = f"C{letter}"

    last = frappe.db.sql(
        """
        SELECT MAX(CAST(SUBSTRING(name, %s) AS UNSIGNED))
        FROM `tabCustomer`
        WHERE name LIKE %s AND name REGEXP '^C[A-Z][0-9]+$'
        FOR UPDATE
        """,
        (len(prefix) + 1, prefix + "%"),
    )[0][0]

    doc.name = f"{prefix}{int(last or 0) + 1:04d}"
