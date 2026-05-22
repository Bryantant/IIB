// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("IIB BOM Creator", {
	refresh(frm) {
		// MC Number is auto-assigned — never let the user edit it
		frm.set_df_property("item_code", "read_only", 1);
		frm.trigger("render_mc_badge");
		frm.trigger("add_action_buttons");
	},

	render_mc_badge(frm) {
		if (frm.doc.item_code) {
			frm.dashboard.clear_comment();
			frm.dashboard.add_comment(
				`<strong>${__("MC Number")}:</strong> <code>${frm.doc.item_code}</code>` +
					(frm.doc.customer
						? ` &nbsp;|&nbsp; <strong>${__("Customer")}:</strong> ${frm.doc.customer}`
						: ""),
				"blue",
				true
			);
		}
	},

	add_action_buttons(frm) {
		// Copy Sub-Assemblies
		frm.add_custom_button(__("Copy Sub-Assemblies"), () => {
			copy_table(frm, "items");
		});

		// Copy Raw Materials
		frm.add_custom_button(__("Copy Raw Materials"), () => {
			copy_table(frm, "rm_items");
		});

		// Create BOMs (submitted, not yet completed)
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Completed") {
			frm.add_custom_button(
				__("Create BOMs"),
				() => {
					frappe.call({
						method: "enqueue_create_boms",
						doc: frm.doc,
						callback() {
							frm.reload_doc();
						},
					});
				},
				__("Actions")
			);
		}
	},
});

// ------------------------------------------------------------------
// Sub-assembly child table — inline editing
// ------------------------------------------------------------------

frappe.ui.form.on("IIB BOM Creator Item", {
	component(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.component) return;

		let letter = row.component.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 1);
		if (!letter) {
			frappe.model.set_value(cdt, cdn, "component", "");
			return;
		}

		frappe.model.set_value(cdt, cdn, "component", letter);

		if (frm.doc.name && !frm.is_new()) {
			frappe.model.set_value(cdt, cdn, "item_code", frm.doc.name + letter);
		}
	},
});

// ------------------------------------------------------------------
// Raw material child table — auto-fetch item name
// ------------------------------------------------------------------

frappe.ui.form.on("IIB BOM Creator RM", {
	item_code(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.item_code) {
			frappe.model.set_value(cdt, cdn, "item_name", "");
			return;
		}

		frappe.db
			.get_value("Item", row.item_code, [
				"item_name",
				"default_material_request_type",
			])
			.then((r) => {
				let data = r.message || {};
				if (data.item_name) {
					frappe.model.set_value(cdt, cdn, "item_name", data.item_name);
				}
				if (data.default_material_request_type) {
					frappe.model.set_value(
						cdt,
						cdn,
						"default_material_request_type",
						data.default_material_request_type
					);
				}
			});
	},
});

// ------------------------------------------------------------------
// Copy table helper — writes TSV to clipboard
// ------------------------------------------------------------------

function copy_table(frm, fieldname) {
	let grid = frm.fields_dict[fieldname] && frm.fields_dict[fieldname].grid;
	if (!grid) {
		frappe.show_alert({ message: __("Table not found"), indicator: "red" });
		return;
	}

	let rows = frm.doc[fieldname] || [];
	if (!rows.length) {
		frappe.show_alert({ message: __("No rows to copy"), indicator: "orange" });
		return;
	}

	// Use visible grid columns so column order matches what the user sees
	let columns = (grid.columns || []).map((c) => c.fieldname).filter(Boolean);

	// Header row
	let header = columns.join("\t");
	// Data rows
	let data = rows
		.map((r) => columns.map((f) => (r[f] !== undefined && r[f] !== null ? r[f] : "")).join("\t"))
		.join("\n");

	let tsv = header + "\n" + data;

	if (navigator.clipboard && navigator.clipboard.writeText) {
		navigator.clipboard
			.writeText(tsv)
			.then(() => {
				frappe.show_alert({
					message: __("Copied {0} row(s) to clipboard", [rows.length]),
					indicator: "green",
				});
			})
			.catch(() => _fallback_copy(tsv));
	} else {
		_fallback_copy(tsv);
	}
}

function _fallback_copy(text) {
	let el = document.createElement("textarea");
	el.value = text;
	el.style.position = "fixed";
	el.style.opacity = "0";
	document.body.appendChild(el);
	el.select();
	try {
		document.execCommand("copy");
		frappe.show_alert({ message: __("Copied to clipboard"), indicator: "green" });
	} catch {
		frappe.show_alert({ message: __("Copy failed — please copy manually"), indicator: "red" });
	}
	document.body.removeChild(el);
}
