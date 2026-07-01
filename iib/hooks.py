app_name = "iib"
app_title = "IIB"
app_publisher = "Hicom System"
app_description = "IIB Custom App"
app_email = "h1com.syst3m@gmail.com"
app_license = "mit"

required_apps = ["erpnext"]

# Desk-only Hicom branding and global UI overrides.
app_include_css = ["/assets/iib/css/custom.css?v=iib-hicom-desk-1"]
app_include_js = ["/assets/iib/js/iib_desk_overrides.bundle.js"]
extend_bootinfo = "iib.boot.boot_session"

doc_events = {
	"Delivery Note": {
		"before_save": "iib.iib.doctype.so_batch.so_batch.set_dn_po_line_no",
		"autoname": "iib.overrides.delivery_note.autoname",
	},
	"Sales Order": {
		"autoname": "iib.overrides.sales_order.autoname",
		"validate": "iib.overrides.sales_order.validate",
	},
	"Purchase Order": {
		"autoname": "iib.overrides.purchase_order.autoname",
	},
}

override_doctype_dashboards = {
	"Sales Order": "iib.overrides.sales_order_dashboard.get_data"
}

company_data_to_be_ignored = ["Master Card"]

fixtures = [
	{"dt": "Role", "filters": [["name", "in", ["IIB Manufacturing Manager"]]]},
	{"dt": "Custom Field", "filters": [["module", "=", "IIB"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "IIB"]]},
	{"dt": "Client Script", "filters": [["module", "=", "IIB"]]},
	{"dt": "Server Script", "filters": [["module", "=", "IIB"]]},
	{"dt": "Item Group", "filters": [["name", "in", ["Master Card", "Sub Assemblies", "Component"]]]},
	"Translation",
]
