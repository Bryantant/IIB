(() => {
  // ../iib/iib/public/js/iib_desk_overrides.bundle.js
  (function hideMenuItems() {
    var HIDDEN_LABELS = ["Help", "About", "Frappe Support"];
    function removeItems() {
      document.querySelectorAll(".frappe-menu .dropdown-menu-item").forEach(function(item) {
        var title = item.querySelector(".menu-item-title");
        if (title && HIDDEN_LABELS.indexOf(title.textContent.trim()) !== -1) {
          item.style.display = "none";
        }
      });
    }
    removeItems();
    var observer = new MutationObserver(removeItems);
    observer.observe(document.body, { childList: true, subtree: true });
  })();
  frappe.router.on("change", function() {
    setTimeout(function() {
      var route = frappe.get_route();
      if (!route || !route[0] || route[0] === "Workspaces")
        return;
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
})();
//# sourceMappingURL=iib_desk_overrides.bundle.DMYASCMH.js.map
