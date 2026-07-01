import frappe


# Relabel app titles shown in the desk workspace sidebar.
APP_TITLE_OVERRIDES = {
	"erpnext": "Hicom System",
	"frappe": "Hicom Core",
}


def boot_session(bootinfo):
	"""Extend the boot payload without touching core files."""
	for app in bootinfo.get("app_data") or []:
		new_title = APP_TITLE_OVERRIDES.get(app.get("app_name"))
		if new_title:
			app["app_title"] = new_title
