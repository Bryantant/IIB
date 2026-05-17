import frappe


def execute():
    # autoincrement autoname on BOM Creator (set via Property Setter) requires
    # a MariaDB SEQUENCE object. Property Setter changes app-level behaviour but
    # doesn't create the sequence; this patch does it once.
    frappe.db.sql(
        "CREATE SEQUENCE IF NOT EXISTS `bom_creator_id_seq` START WITH 1 INCREMENT BY 1 NOCACHE"
    )
    frappe.db.commit()
