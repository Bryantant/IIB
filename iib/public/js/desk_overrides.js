// IIB desk overrides: start with sidebar closed on form/list pages (not workspace)
frappe.router.on("change", function () {
	setTimeout(function () {
		var route = frappe.get_route();
		// Skip workspace — its left nav should stay open
		if (!route || !route[0] || route[0] === "Workspaces") return;

		var $sidebar = $(".layout-side-section");
		if ($sidebar.is(":visible")) {
			$sidebar.hide();
			var $icon = $(".sidebar-toggle-btn .sidebar-toggle-icon");
			if ($icon.length && frappe.utils) {
				$icon.html(frappe.utils.icon("es-line-sidebar-expand", "md"));
			}
		}
	}, 100);
});
