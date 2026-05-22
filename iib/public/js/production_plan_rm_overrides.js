(() => {
	if (window.iib_production_plan_rm_overrides_loaded) {
		return;
	}
	window.iib_production_plan_rm_overrides_loaded = true;

	function escape_html(value) {
		return frappe.utils.escape_html(value || "");
	}

	function get_plan_item_rows(frm) {
		return (frm.doc.po_items || [])
			.filter((row) => row.name && row.item_code)
			.map((row) => {
				let title_parts = [__("Row {0}: {1}", [row.idx || "", row.item_code]).trim()];
				if (row.sales_order) {
					title_parts.push(row.sales_order);
				} else if (frm.doc.combine_items) {
					title_parts.push(__("Consolidated"));
				}

				let details = [];
				if (row.planned_qty) {
					details.push(__("Qty: {0} {1}", [row.planned_qty, row.stock_uom || ""]));
				}
				if (row.bom_no) {
					details.push(__("BOM: {0}", [row.bom_no]));
				}
				if (row.sales_order_item) {
					details.push(__("SO Item: {0}", [row.sales_order_item]));
				}
				if (row.warehouse) {
					details.push(__("Warehouse: {0}", [row.warehouse]));
				}

				let title = title_parts.join(" - ");
				let detail = details.join(" | ");
				let label = [title, detail].filter(Boolean).join(" | ");

				return {
					name: row.name,
					item_code: row.item_code,
					title,
					detail,
					label,
					value: row.name,
					search_text: [
						row.idx,
						row.item_code,
						row.sales_order,
						row.sales_order_item,
						row.bom_no,
						row.warehouse,
						row.planned_qty,
						row.stock_uom,
						frm.doc.combine_items ? __("Consolidated") : "",
					]
						.filter(Boolean)
						.join(" ")
						.toLowerCase(),
				};
			});
	}

	function get_plan_item(frm, row_name) {
		return (frm.doc.po_items || []).find(
			(row) => row.name === row_name || row.temporary_name === row_name
		);
	}

	function get_plan_item_label(frm, row_name) {
		let plan_item = get_plan_item_rows(frm).find((row) => row.name === row_name);
		return plan_item ? plan_item.label : row_name || "";
	}

	function set_rm_override_grid_options(frm) {
		let grid = frm.fields_dict.custom_rm_overrides?.grid;
		if (!grid || !grid.wrapper || !grid.update_docfield_property) {
			return;
		}

		let formatter = (value) => escape_html(get_plan_item_label(frm, value));

		grid.update_docfield_property("production_plan_item", "label", __("Assembly Item Row"));
		grid.update_docfield_property("production_plan_item", "fieldtype", "Data");
		grid.update_docfield_property("production_plan_item", "read_only", 1);
		grid.update_docfield_property(
			"production_plan_item",
			"placeholder",
			__("Use Add Overrides")
		);
		grid.update_docfield_property("production_plan_item", "formatter", formatter);

		let meta_field = frappe.meta.get_docfield(
			"Production Plan RM Override",
			"production_plan_item",
			frm.doc.name
		);
		if (meta_field) {
			meta_field.label = __("Assembly Item Row");
			meta_field.fieldtype = "Data";
			meta_field.read_only = 1;
			meta_field.formatter = formatter;
		}

		if (grid.add_custom_button) {
			grid.add_custom_button(__("Add Overrides"), () => show_bulk_override_dialog(frm));
		}
		bind_inline_plan_item_picker(frm, grid);
	}

	function sync_override_fg_item(frm, cdt, cdn, clear_invalid = false) {
		let row = locals[cdt][cdn];
		let plan_item = get_plan_item(frm, row.production_plan_item);

		if (!plan_item && clear_invalid && row.production_plan_item) {
			frappe.model.set_value(cdt, cdn, "production_plan_item", "");
		}
		frappe.model.set_value(cdt, cdn, "fg_item", plan_item ? plan_item.item_code : "");
	}

	function sync_override_table(frm, clear_invalid = false) {
		(frm.doc.custom_rm_overrides || []).forEach((row) => {
			sync_override_fg_item(frm, row.doctype, row.name, clear_invalid);
		});
	}

	function refresh_rm_override_grid(frm, clear_invalid = false) {
		set_rm_override_grid_options(frm);
		sync_override_table(frm, clear_invalid);
		frm.refresh_field("custom_rm_overrides");
	}

	function safely_refresh_rm_override_grid(frm, clear_invalid = false) {
		try {
			if (!frm || frm.doctype !== "Production Plan") {
				return;
			}
			refresh_rm_override_grid(frm, clear_invalid);
		} catch (error) {
			console.error("IIB Raw Material Override UX failed:", error);
		}
	}

	function schedule_refresh_rm_override_grid(frm, clear_invalid = false) {
		window.setTimeout(() => safely_refresh_rm_override_grid(frm, clear_invalid), 0);
	}

	function set_override_plan_item(frm, row, plan_item_name) {
		let plan_item = get_plan_item(frm, plan_item_name);
		frappe.model.set_value(row.doctype, row.name, "production_plan_item", plan_item_name || "");
		frappe.model.set_value(row.doctype, row.name, "fg_item", plan_item ? plan_item.item_code : "");
	}

	function bind_inline_plan_item_picker(frm, grid) {
		grid.wrapper
			.off("click.iib_rm_override_picker")
			.on(
				"click.iib_rm_override_picker",
				".grid-body .grid-row [data-fieldname='production_plan_item']",
				(event) => {
					let docname = $(event.currentTarget).closest(".grid-row").attr("data-name");
					let row = (frm.doc.custom_rm_overrides || []).find((d) => d.name === docname);
					if (!row) {
						return;
					}

					event.preventDefault();
					event.stopPropagation();
					show_single_plan_item_dialog(frm, row);
				}
			);
	}

	function mount_plan_item_picker({ frm, $wrapper, selected_names, multiselect, on_pick }) {
		let selected = selected_names || new Set();
		let rows = get_plan_item_rows(frm);

		function filtered_rows() {
			let query = ($wrapper.find(".iib-rm-row-search").val() || "").toLowerCase().trim();
			if (!query) {
				return rows;
			}

			let terms = query.split(/\s+/).filter(Boolean);
			return rows.filter((row) => terms.every((term) => row.search_text.includes(term)));
		}

		function render_list() {
			let visible = filtered_rows();
			let rows_html = visible
				.map((row) => {
					let checked = selected.has(row.name) ? "checked" : "";
					let input = multiselect
						? `<input type="checkbox" class="iib-rm-row-check" data-name="${escape_html(
								row.name
						  )}" ${checked}>`
						: "";
					return `
						<div class="iib-rm-row" data-name="${escape_html(row.name)}">
							<div class="iib-rm-row-pick">${input}</div>
							<div class="iib-rm-row-main">
								<div class="iib-rm-row-title">${escape_html(row.title)}</div>
								<div class="iib-rm-row-detail">${escape_html(row.detail)}</div>
							</div>
						</div>
					`;
				})
				.join("");

			if (!rows_html) {
				rows_html = `<div class="text-muted small" style="padding: 12px">${__(
					"No Assembly Items match the search."
				)}</div>`;
			}

			$wrapper.find(".iib-rm-row-list").html(rows_html);
			$wrapper
				.find(".iib-rm-row-count")
				.text(__("{0} selected | {1} shown | {2} total", [selected.size, visible.length, rows.length]));
		}

		$wrapper.html(`
			<style>
				.iib-rm-picker-toolbar {
					display: flex;
					gap: 8px;
					align-items: center;
					margin-bottom: 10px;
				}
				.iib-rm-picker-toolbar .iib-rm-row-search {
					flex: 1;
				}
				.iib-rm-row-list {
					border: 1px solid var(--border-color);
					border-radius: 6px;
					max-height: 420px;
					overflow: auto;
					background: var(--fg-color);
				}
				.iib-rm-row {
					display: grid;
					grid-template-columns: 28px 1fr;
					gap: 8px;
					padding: 9px 10px;
					border-bottom: 1px solid var(--border-color);
					cursor: pointer;
				}
				.iib-rm-row:last-child {
					border-bottom: 0;
				}
				.iib-rm-row:hover {
					background: var(--control-bg);
				}
				.iib-rm-row-title {
					font-weight: 600;
					line-height: 1.25;
				}
				.iib-rm-row-detail {
					color: var(--text-muted);
					font-size: 12px;
					line-height: 1.35;
					margin-top: 2px;
				}
				.iib-rm-row-count {
					margin-top: 8px;
				}
			</style>
			<div class="iib-rm-picker-toolbar">
				<input class="form-control input-sm iib-rm-row-search"
					placeholder="${escape_html(__("Search row, item, sales order, BOM, warehouse"))}">
				${
					multiselect
						? `<button type="button" class="btn btn-xs btn-secondary iib-rm-select-visible">${__(
								"Select Shown"
						  )}</button>
						  <button type="button" class="btn btn-xs btn-secondary iib-rm-clear-selection">${__(
								"Clear"
						  )}</button>`
						: ""
				}
			</div>
			<div class="iib-rm-row-list"></div>
			<div class="text-muted small iib-rm-row-count"></div>
		`);

		$wrapper.find(".iib-rm-row-search").on("input", render_list);
		$wrapper.on("change", ".iib-rm-row-check", (event) => {
			let row_name = $(event.currentTarget).data("name");
			if (event.currentTarget.checked) {
				selected.add(row_name);
			} else {
				selected.delete(row_name);
			}
			render_list();
		});
		$wrapper.on("click", ".iib-rm-row", (event) => {
			let row_name = $(event.currentTarget).data("name");
			if (multiselect) {
				if ($(event.target).is("input")) {
					return;
				}
				let checkbox = $(event.currentTarget).find(".iib-rm-row-check").get(0);
				checkbox.checked = !checkbox.checked;
				$(checkbox).trigger("change");
			} else {
				on_pick(row_name);
			}
		});
		$wrapper.find(".iib-rm-select-visible").on("click", () => {
			filtered_rows().forEach((row) => selected.add(row.name));
			render_list();
		});
		$wrapper.find(".iib-rm-clear-selection").on("click", () => {
			selected.clear();
			render_list();
		});

		render_list();
		return selected;
	}

	function show_single_plan_item_dialog(frm, override_row) {
		if (!get_plan_item_rows(frm).length) {
			frappe.msgprint(__("Get Assembly Items before choosing an override row."));
			return;
		}

		let dialog = new frappe.ui.Dialog({
			title: __("Choose Assembly Item Row"),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "rows_html" }],
		});

		dialog.show();
		mount_plan_item_picker({
			frm,
			$wrapper: dialog.fields_dict.rows_html.$wrapper,
			selected_names: new Set(override_row.production_plan_item ? [override_row.production_plan_item] : []),
			multiselect: false,
			on_pick(row_name) {
				set_override_plan_item(frm, override_row, row_name);
				dialog.hide();
			},
		});
	}

	function show_bulk_override_dialog(frm) {
		let plan_rows = get_plan_item_rows(frm);
		if (!plan_rows.length) {
			frappe.msgprint(__("Get Assembly Items before adding raw material overrides."));
			return;
		}

		let selected = new Set(plan_rows.map((row) => row.name));
		let dialog = new frappe.ui.Dialog({
			title: __("Add Raw Material Overrides"),
			size: "extra-large",
			fields: [
				{
					fieldtype: "Link",
					fieldname: "original_item",
					label: __("Original Item"),
					options: "Item",
					reqd: 1,
				},
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Link",
					fieldname: "replacement_item",
					label: __("Replacement Item"),
					options: "Item",
					reqd: 1,
				},
				{ fieldtype: "Section Break", label: __("Assembly Rows") },
				{ fieldtype: "HTML", fieldname: "rows_html" },
			],
			primary_action_label: __("Add / Update Overrides"),
			primary_action(values) {
				if (!selected.size) {
					frappe.msgprint(__("Select at least one Assembly row."));
					return;
				}

				let added = 0;
				let updated = 0;
				let selected_rows = plan_rows.filter((row) => selected.has(row.name));

				selected_rows.forEach((plan_row) => {
					let existing = (frm.doc.custom_rm_overrides || []).find(
						(row) =>
							row.production_plan_item === plan_row.name &&
							row.original_item === values.original_item
					);

					if (existing) {
						existing.replacement_item = values.replacement_item;
						existing.fg_item = plan_row.item_code;
						updated++;
					} else {
						frm.add_child("custom_rm_overrides", {
							production_plan_item: plan_row.name,
							fg_item: plan_row.item_code,
							original_item: values.original_item,
							replacement_item: values.replacement_item,
						});
						added++;
					}
				});

				refresh_rm_override_grid(frm);
				frm.dirty();
				dialog.hide();
				frappe.show_alert({
					message: __("Added {0}, updated {1} raw material override rows.", [added, updated]),
					indicator: "green",
				});
			},
		});

		dialog.show();
		selected = mount_plan_item_picker({
			frm,
			$wrapper: dialog.fields_dict.rows_html.$wrapper,
			selected_names: selected,
			multiselect: true,
		});
	}

	frappe.ui.form.on("Production Plan", {
		refresh(frm) {
			schedule_refresh_rm_override_grid(frm);
		},
		onload_post_render(frm) {
			schedule_refresh_rm_override_grid(frm);
		},
		get_items(frm) {
			frappe.after_ajax(() => schedule_refresh_rm_override_grid(frm, true));
		},
		get_sales_orders(frm) {
			frappe.after_ajax(() => schedule_refresh_rm_override_grid(frm, true));
		},
		combine_items(frm) {
			frappe.after_ajax(() => schedule_refresh_rm_override_grid(frm, true));
		},
	});

	frappe.ui.form.on("Production Plan Item", {
		po_items_add(frm) {
			set_rm_override_grid_options(frm);
		},
		po_items_delete(frm) {
			set_rm_override_grid_options(frm);
		},
		item_code(frm) {
			set_rm_override_grid_options(frm);
		},
		planned_qty(frm) {
			set_rm_override_grid_options(frm);
		},
		bom_no(frm) {
			set_rm_override_grid_options(frm);
		},
		warehouse(frm) {
			set_rm_override_grid_options(frm);
		},
	});

	frappe.ui.form.on("Production Plan RM Override", {
		form_render(frm, cdt, cdn) {
			set_rm_override_grid_options(frm);
			sync_override_fg_item(frm, cdt, cdn);
			frappe.after_ajax(() => sync_override_fg_item(frm, cdt, cdn));
		},
		production_plan_item(frm, cdt, cdn) {
			sync_override_fg_item(frm, cdt, cdn);
			frappe.after_ajax(() => sync_override_fg_item(frm, cdt, cdn));
		},
	});
})();
