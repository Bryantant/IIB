// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("IIB BOM Creator", {
	refresh(frm) {
		frm.trigger("render_fg_badge");

		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Add Sub-Assembly (L1)"), () => {
				frm.trigger("add_l1_dialog");
			});

			if ((frm.doc.items || []).some((r) => r.level === 1)) {
				frm.add_custom_button(__("Add Component (L2)"), () => {
					frm.trigger("add_l2_dialog");
				});
			}

			if ((frm.doc.items || []).length) {
				frm.add_custom_button(
					__("Remove Item"),
					() => {
						frm.trigger("remove_item_dialog");
					},
					__("Actions")
				);
			}
		}

		if (frm.doc.docstatus === 1 && frm.doc.status !== "Completed") {
			frm.add_custom_button(__("Create BOMs"), () => {
				frappe.call({
					method: "enqueue_create_boms",
					doc: frm.doc,
					callback() {
						frm.reload_doc();
					},
				});
			});
		}
	},

	render_fg_badge(frm) {
		if (frm.doc.item_code) {
			frm.dashboard.clear_comment();
			frm.dashboard.add_comment(
				`<strong>${__("FG Item Code")}:</strong> <code>${frm.doc.item_code}</code>`,
				"blue",
				true
			);
		}
	},

	add_l1_dialog(frm) {
		if (!frm.doc.item_code) {
			frappe.throw(__("Save the document first to generate the FG item code."));
			return;
		}

		let d = new frappe.ui.Dialog({
			title: __("Add Level-1 Sub-Assembly"),
			fields: [
				{
					fieldname: "letter",
					fieldtype: "Data",
					label: __("Sub-Assembly Letter (A–Z)"),
					reqd: 1,
					description: __(
						"Will create item: {0}<letter>",
						[frm.doc.item_code]
					),
				},
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("Qty"),
					default: 1,
					reqd: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				if (!/^[A-Za-z]$/.test(values.letter)) {
					frappe.throw(__("Enter exactly one letter A–Z."));
					return;
				}
				frappe.call({
					method: "iib.iib.doctype.iib_bom_creator.iib_bom_creator.add_level1_item",
					args: {
						parent: frm.doc.name,
						letter: values.letter,
						qty: values.qty,
					},
					freeze: true,
					freeze_message: __("Creating sub-assembly {0}{1}...", [
						frm.doc.item_code,
						values.letter.toUpperCase(),
					]),
					callback(r) {
						if (r.message) {
							d.hide();
							frappe.show_alert({
								message: __("Added {0}", [
									frm.doc.item_code + values.letter.toUpperCase(),
								]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},

	add_l2_dialog(frm) {
		let l1_items = (frm.doc.items || []).filter((r) => r.level === 1);

		if (!l1_items.length) {
			frappe.throw(__("Add a Level-1 sub-assembly first."));
			return;
		}

		let d = new frappe.ui.Dialog({
			title: __("Add Level-2 Component"),
			fields: [
				{
					fieldname: "parent_ref",
					fieldtype: "Select",
					label: __("Parent Sub-Assembly"),
					options: l1_items.map((r) => r.item_code).join("\n"),
					reqd: 1,
				},
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("Qty"),
					default: 1,
					reqd: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				let parent_row = l1_items.find((r) => r.item_code === values.parent_ref);
				let next_counter =
					(frm.doc.items || []).filter(
						(r) => r.fg_reference_id === parent_row.name
					).length + 1;

				frappe.call({
					method: "iib.iib.doctype.iib_bom_creator.iib_bom_creator.add_level2_item",
					args: {
						parent: frm.doc.name,
						parent_ref_id: parent_row.name,
						qty: values.qty,
					},
					freeze: true,
					freeze_message: __("Creating component {0}-{1}...", [
						values.parent_ref,
						next_counter,
					]),
					callback(r) {
						if (r.message) {
							d.hide();
							frappe.show_alert({
								message: __("Added {0}-{1}", [values.parent_ref, next_counter]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},

	remove_item_dialog(frm) {
		let all_items = (frm.doc.items || []).map(
			(r) => `L${r.level} — ${r.item_code}`
		);

		let d = new frappe.ui.Dialog({
			title: __("Remove Item"),
			fields: [
				{
					fieldname: "row_label",
					fieldtype: "Select",
					label: __("Item to Remove"),
					options: all_items.join("\n"),
					reqd: 1,
					description: __(
						"Removing a Level-1 sub-assembly will also remove all its components."
					),
				},
			],
			primary_action_label: __("Remove"),
			primary_action(values) {
				let idx = all_items.indexOf(values.row_label);
				let row = frm.doc.items[idx];

				frappe.call({
					method: "iib.iib.doctype.iib_bom_creator.iib_bom_creator.remove_item",
					args: { parent: frm.doc.name, row_name: row.name },
					freeze: true,
					callback(r) {
						if (r.message) {
							d.hide();
							frm.reload_doc();
						}
					},
				});
			},
		});
		d.show();
	},
});
