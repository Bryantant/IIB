// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Master Card", {
	setup(frm) {
		set_process_queries(frm);
		set_colour_queries(frm);
	},

	refresh(frm) {
		// Close sidebar — runs after all rendering is done, so it wins the timing race
		// with desk_overrides.js which fires too early on route change.
		frm.page.sidebar && frm.page.sidebar.hide();

		frm.set_df_property("item_code", "read_only", 1);
		frm.trigger("render_mc_badge");
		frm.trigger("render_copy_buttons");
		frm.trigger("add_action_buttons");
		apply_price_currency_formatters(frm);
		calculate_price_rows(frm);
		render_price_items_editor(frm);

		frm.trigger("render_process_tabs");

		// Hide connections/links section (no BOMs linked anymore)
		frm.dashboard.connections_area && $(frm.dashboard.connections_area).hide();

		// Re-apply active tab filter whenever the processes grid re-renders
		frm.fields_dict.processes.grid.on_page_render = function () {
			if (frm._active_process_tab) {
				filter_processes_grid(frm, frm._active_process_tab);
			}
		};

		// Clicking a row in the Finish Goods table auto-switches the process tab
		frm.fields_dict.items.grid.wrapper
			.off("click.mc_tab")
			.on("click.mc_tab", ".grid-row", function () {
				const name = $(this).attr("data-name");
				const row = name && locals["Master Card Item"][name];
				if (row && row.component) {
					set_active_process_tab(frm, row.component);
				}
			});
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

	render_copy_buttons(frm) {
		frm.fields_dict["copy_fg_html"].$wrapper.html(`
			<button class="btn btn-xs btn-default" style="margin-bottom:6px">
				${__("Copy Finish Goods")}
			</button>
		`);
		frm.fields_dict["copy_fg_html"].$wrapper
			.find("button")
			.on("click", () => copy_table(frm, "items"));
	},

	render_process_tabs(frm) {
		// Inject the tab bar directly before the processes table in the DOM.
		// We don't rely on an HTML field wrapper — this is more robust against
		// Frappe meta-cache issues with newly added HTML fields.
		const $processesWrapper = frm.fields_dict.processes.$wrapper;

		// Remove any previously rendered tab bar
		$processesWrapper.siblings(".mc-process-tab-bar-outer").remove();

		// Collect unique component letters from items table, sorted
		const letters = [
			...new Set((frm.doc.items || []).map((r) => r.component).filter(Boolean)),
		].sort();

		const $outer = $(`<div class="mc-process-tab-bar-outer"></div>`);

		if (!letters.length) {
			$outer.html(
				`<p class="text-muted small" style="margin:4px 0 8px">
					${__("Add components in the Finish Goods table to enable process tabs.")}
				</p>`
			);
			$processesWrapper.before($outer);
			return;
		}

		// Build tab bar
		const $bar = $(`<div class="mc-process-tab-bar" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;"></div>`);
		letters.forEach((letter) => {
			$(`<button class="btn btn-sm btn-default btn-mc-tab" data-component="${letter}">
					${__("Comp {0}", [letter])}
				</button>`)
				.appendTo($bar)
				.on("click", () => set_active_process_tab(frm, letter));
		});
		$outer.append($bar);
		$processesWrapper.before($outer);

		// Determine initial active tab: keep current if still valid, else first
		const current = frm._active_process_tab;
		const initial = letters.includes(current) ? current : letters[0];
		set_active_process_tab(frm, initial);
	},

	add_action_buttons(frm) {
		if (!frm.is_new() && frm.doc.customer) {
			frm.add_custom_button(__("Customer"), () => {
				frappe.set_route("Form", "Customer", frm.doc.customer);
			});
		}

		// New Version — show on any saved (non-new) doc
		if (!frm.is_new()) {
			frm.add_custom_button(__("New Version"), () => {
				frappe.confirm(
					__("Create a new independent Master Card copied from this one?"),
					() => {
						frappe.call({
							method: "create_new_version",
							doc: frm.doc,
							callback(r) {
								if (r.message) {
									frappe.set_route("Form", "Master Card", r.message);
								}
							},
						});
					}
				);
			});
		}
	},

	processes_add(frm, cdt, cdn) {
		set_process_component_from_tab(frm, cdt, cdn);
		set_process_sequence(frm, cdt, cdn);
	},

	currency(frm) {
		apply_price_currency_formatters(frm);
		render_price_items_editor(frm);
	},

});

// ------------------------------------------------------------------
// Finish Good child table — component letter handling
// ------------------------------------------------------------------

frappe.ui.form.on("Master Card Item", {
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

		frm.trigger("render_process_tabs");
	},

	custom_printing(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.custom_printing) {
			[1, 2, 3, 4, 5].forEach((i) => {
				frappe.model.set_value(cdt, cdn, `custom_colour_${i}`, null);
			});
		}
	},

	items_remove(frm) {
		frm.trigger("render_process_tabs");
	},
});

// Master Card Price Item events are handled by the HTML widget inputs directly.

// ------------------------------------------------------------------
// Process child table — auto-fill component from active tab
// ------------------------------------------------------------------

frappe.ui.form.on("Master Card Process", {
	// Triggered with child doctype when Add Row fires (Frappe v15 routing)
	processes_add(frm, cdt, cdn) {
		set_process_component_from_tab(frm, cdt, cdn);
		set_process_sequence(frm, cdt, cdn);
	},

	// Triggered when a row dialog opens — fallback for component fill
	form_render(frm, cdt, cdn) {
		set_process_component_from_tab(frm, cdt, cdn);
	},
});

// ------------------------------------------------------------------
// Tab helpers
// ------------------------------------------------------------------

function set_active_process_tab(frm, letter) {
	frm._active_process_tab = letter;
	fill_blank_process_components(frm, letter);

	// Update button styles in the DOM-injected tab bar
	const $bar = frm.fields_dict.processes.$wrapper
		.siblings(".mc-process-tab-bar-outer")
		.find(".mc-process-tab-bar");
	$bar.find(".btn-mc-tab").removeClass("btn-primary").addClass("btn-default");
	$bar.find(`.btn-mc-tab[data-component="${letter}"]`)
		.removeClass("btn-default")
		.addClass("btn-primary");

	filter_processes_grid(frm, letter);
}

function filter_processes_grid(frm, letter) {
	const grid = frm.fields_dict.processes.grid;
	if (!grid) return;

	let visible = 0;
	grid.wrapper.find(".grid-row[data-name]").each(function () {
		const rowName = $(this).attr("data-name");
		const row = rowName && locals["Master Card Process"][rowName];
		const show = !!(row && row.component === letter);
		$(this).toggle(show);
		if (show) visible++;
	});

	// Empty-state hint inside the grid body
	grid.wrapper.find(".mc-no-rows-hint").remove();
	if (!visible) {
		grid.wrapper.find(".grid-body").append(
			`<div class="mc-no-rows-hint text-muted" style="padding:8px 12px;font-size:var(--text-sm)">
				${__("No processes for component {0} — click Add Row to create one.", [letter])}
			</div>`
		);
	}
}

function set_process_queries(frm) {
	frm.set_query("section", "processes", () => ({
		filters: {
			is_group: 1,
			disabled: 0,
		},
	}));
}

function set_colour_queries(frm) {
	[1, 2, 3, 4, 5].forEach((i) => {
		frm.set_query(`custom_colour_${i}`, "items", () => ({
			filters: { colour_group: `Colour ${i}` },
		}));
	});
}

function calculate_price_rows(frm) {
	apply_price_currency_formatters(frm);
	(frm.doc.price_items || []).forEach((row) => {
		calculate_price_row(frm, row.doctype, row.name, false);
	});
	render_price_items_editor(frm);
}

function calculate_price_row(frm, cdt, cdn, rerender = true) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row) return;
	const total = flt(row.material) + flt(row.labour) + flt(row.profit) + flt(row.ext_profit);
	frappe.model.set_value(cdt, cdn, "total", total);
	if (rerender) render_price_items_editor(frm);
}

// ------------------------------------------------------------------
// Interactive Item Price Set editor (Access-style layout)
// ------------------------------------------------------------------

function render_price_items_editor(frm) {
	const field = frm.fields_dict.price_items_html;
	if (!field) return;

	const $w = field.$wrapper.empty();
	const moqList = (frm.doc.moq_items || []).slice().sort((a, b) => a.idx - b.idx);
	const priceRows = (frm.doc.price_items || []);

	if (!moqList.length) {
		$(`<p class="text-muted small" style="margin:4px 0 8px">${__(
			'Click "+ Add MOQ Level" to define pricing tiers.'
		)}</p>`).appendTo($w);
	} else {
		const $table = $(`
			<table class="table table-bordered table-condensed mc-price-table" style="margin-bottom:8px">
				<thead><tr>
					<th style="min-width:130px"></th>
					<th style="width:54px">${__("Comp")}</th>
					<th class="text-right">${__("Material")}</th>
					<th class="text-right">${__("Labour")}</th>
					<th class="text-right">${__("Profit")}</th>
					<th class="text-right">${__("Ext Profit")}</th>
					<th class="text-right">${__("Total")}</th>
					<th style="width:26px"></th>
				</tr></thead>
				<tbody></tbody>
			</table>
		`).appendTo($w);
		const $tbody = $table.find("tbody");

		moqList.forEach((moqRow, listIdx) => {
			const moqNum = listIdx + 1;
			const compRows = priceRows
				.filter((r) => r.moq_idx === moqRow.idx)
				.sort((a, b) => (a.idx || 0) - (b.idx || 0));
			// +1 for "Add Component" row; +1 for totals row (only when there are components)
			const rowspan = compRows.length > 0
				? compRows.length + 2
				: 2;

			const $moqTd = $(`<td rowspan="${rowspan}" style="vertical-align:top;padding:6px 8px;white-space:nowrap;">
				<div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;">
					<span class="text-muted" style="font-size:var(--text-sm)">MOQ ${moqNum} :</span>
					<input type="number" step="any" value="${flt(moqRow.moq_qty)}"
						class="mc-moq-input"
						data-moq-name="${moqRow.name}"
						style="width:64px;padding:2px 4px;border:1px solid var(--border-color);border-radius:var(--border-radius-sm);text-align:right;font-size:var(--text-sm);">
				</div>
				<button class="btn btn-xs" style="color:var(--red-500);padding:0 4px;line-height:1.4;font-size:10px;" data-del-moq="${moqRow.name}" title="${__("Remove MOQ level")}">✕ ${__("Remove")}</button>
			</td>`);

			if (compRows.length === 0) {
				// Empty MOQ group
				const $tr = $("<tr>").appendTo($tbody);
				$tr.append($moqTd);
				$(`<td colspan="6" class="text-muted" style="vertical-align:middle;font-size:var(--text-sm);padding:6px 10px;">${__(
					"No components — use Add below"
				)}</td>`).appendTo($tr);
				$("<td></td>").appendTo($tr);
			} else {
				compRows.forEach((compRow, compIdx) => {
					const $tr = $("<tr>").appendTo($tbody);
					if (compIdx === 0) $tr.append($moqTd);

					// Comp
					$("<td>").append(
						$(`<input type="text" maxlength="1" value="${frappe.utils.escape_html(compRow.component || "")}"
							class="mc-price-input" data-row="${compRow.name}" data-field="component"
							style="width:36px;padding:2px 3px;border:1px solid var(--border-color);border-radius:var(--border-radius-sm);text-align:center;font-weight:600;">`)
					).appendTo($tr);

					// Currency fields
					["material", "labour", "profit", "ext_profit"].forEach((f) => {
						$("<td>").append(
							$(`<input type="number" step="0.0001" value="${flt(compRow[f], 4)}"
								class="mc-price-input" data-row="${compRow.name}" data-field="${f}"
								style="width:100%;min-width:82px;padding:2px 4px;border:1px solid var(--border-color);border-radius:var(--border-radius-sm);text-align:right;font-size:var(--text-sm);">`)
						).appendTo($tr);
					});

					// Total (read-only)
					$(`<td class="text-right" style="vertical-align:middle;white-space:nowrap;padding:4px 6px;"
						data-total-row="${compRow.name}">${format_price_currency(compRow.total, frm.doc.currency)}</td>`).appendTo($tr);

					// Delete component button
					$('<td style="vertical-align:middle;text-align:center;padding:2px;">').append(
						$(`<button class="btn btn-xs" style="color:var(--red-500);padding:0 5px;line-height:1.6">×</button>`)
							.on("click", () => remove_price_row(frm, compRow.name))
					).appendTo($tr);
				});
			}

			// Totals row — each component value × its qty from the Finish Goods table
			if (compRows.length > 0) {
				const qtyMap = get_component_qty_map(frm);
				const qty = (r) => qtyMap[(r.component || "").toUpperCase().trim()] || 1;
				const sumMaterial  = compRows.reduce((s, r) => s + flt(r.material)  * qty(r), 0);
				const sumLabour    = compRows.reduce((s, r) => s + flt(r.labour)    * qty(r), 0);
				const sumProfit    = compRows.reduce((s, r) => s + flt(r.profit)    * qty(r), 0);
				const sumExtProfit = compRows.reduce((s, r) => s + flt(r.ext_profit)* qty(r), 0);
				const sumTotal     = compRows.reduce((s, r) => s + flt(r.total)     * qty(r), 0);
				const $totTr = $("<tr>").appendTo($tbody);
				const cellStyle = "text-align:right;padding:3px 6px;font-weight:600;background:var(--bg-light-gray);border-top:2px solid var(--border-color);white-space:nowrap;";
				$(`<td style="padding:3px 6px;background:var(--bg-light-gray);border-top:2px solid var(--border-color);font-size:var(--text-sm);color:var(--text-muted);">Total</td>`).appendTo($totTr);
				[sumMaterial, sumLabour, sumProfit, sumExtProfit, sumTotal].forEach((val) => {
					$(`<td style="${cellStyle}">${format_price_currency(val, frm.doc.currency)}</td>`).appendTo($totTr);
				});
				$(`<td style="background:var(--bg-light-gray);border-top:2px solid var(--border-color);"></td>`).appendTo($totTr);
			}

			// "Add Component" action row for this MOQ group
			const $addTr = $("<tr>").appendTo($tbody);
			$(`<td colspan="6" style="padding:3px 6px;border-top:none;">`).append(
				$(`<button class="btn btn-xs btn-default">+ ${__("Add Component")}</button>`)
					.on("click", () => {
						const newRow = frappe.model.add_child(frm.doc, "Master Card Price Item", "price_items");
						frappe.model.set_value("Master Card Price Item", newRow.name, "moq_idx", moqRow.idx).then(() => {
							render_price_items_editor(frm);
						});
					})
			).appendTo($addTr);
			$("<td></td>").appendTo($addTr);
		});
	}

	// "Add MOQ Level" button
	$(`<button class="btn btn-xs btn-default" style="margin-top:4px">+ ${__("Add MOQ Level")}</button>`)
		.appendTo($w)
		.on("click", () => {
			frappe.model.add_child(frm.doc, "Master Card MOQ", "moq_items");
			frm.refresh_field("moq_items");
			render_price_items_editor(frm);
		});

	// --- Event handlers ---

	// MOQ qty change
	$w.find(".mc-moq-input").on("change", function () {
		const moqName = $(this).data("moq-name");
		const newQty = flt($(this).val());
		frappe.model.set_value("Master Card MOQ", moqName, "moq_qty", newQty);
		frm.dirty();
	});

	// Remove MOQ level (and its component rows)
	$w.find("[data-del-moq]").on("click", function () {
		const moqName = $(this).data("del-moq");
		const moqRow = (frm.doc.moq_items || []).find((r) => r.name === moqName);
		if (!moqRow) return;

		const affectedComps = (frm.doc.price_items || []).filter((r) => r.moq_idx === moqRow.idx);
		const msg = affectedComps.length
			? __("Remove MOQ level and its {0} component row(s)?", [affectedComps.length])
			: __("Remove this MOQ level?");

		frappe.confirm(msg, () => {
			remove_moq_row(frm, moqName);
		});
	});

	// Component field changes
	$w.find(".mc-price-input").on("change", function () {
		const rowName = $(this).data("row");
		const fieldname = $(this).data("field");
		let value = $(this).val();

		if (fieldname === "component") {
			value = String(value).toUpperCase().replace(/[^A-Z]/g, "").slice(0, 1);
			$(this).val(value);
			frappe.model.set_value("Master Card Price Item", rowName, "component", value);
		} else {
			value = flt(value);
			frappe.model.set_value("Master Card Price Item", rowName, fieldname, value).then(() => {
				const row = locals["Master Card Price Item"] && locals["Master Card Price Item"][rowName];
				if (!row) return;
				const total = flt(row.material) + flt(row.labour) + flt(row.profit) + flt(row.ext_profit);
				frappe.model.set_value("Master Card Price Item", rowName, "total", total).then(() => {
					$w.find(`[data-total-row="${rowName}"]`).html(
						format_price_currency(total, frm.doc.currency)
					);
				});
			});
		}
		frm.dirty();
	});
}

// ------------------------------------------------------------------
// Row removal helpers — grids are hidden so we manipulate frm.doc directly
// ------------------------------------------------------------------

function remove_price_row(frm, rowName) {
	frappe.model.clear_doc("Master Card Price Item", rowName);
	const rows = frm.doc.price_items || [];
	const i = rows.findIndex((r) => r.name === rowName);
	if (i !== -1) rows.splice(i, 1);
	rows.forEach((r, j) => { r.idx = j + 1; });
	frm.dirty();
	render_price_items_editor(frm);
}

function remove_moq_row(frm, moqName) {
	const moqRows = frm.doc.moq_items || [];
	const moqRow = moqRows.find((r) => r.name === moqName);
	if (!moqRow) return;

	// Remove all component rows for this MOQ level
	const compRows = (frm.doc.price_items || []).filter((r) => r.moq_idx === moqRow.idx);
	compRows.forEach((r) => frappe.model.clear_doc("Master Card Price Item", r.name));
	frm.doc.price_items = (frm.doc.price_items || []).filter((r) => r.moq_idx !== moqRow.idx);
	(frm.doc.price_items || []).forEach((r, j) => { r.idx = j + 1; });

	// Remove the MOQ row itself
	frappe.model.clear_doc("Master Card MOQ", moqName);
	const i = moqRows.findIndex((r) => r.name === moqName);
	if (i !== -1) moqRows.splice(i, 1);
	moqRows.forEach((r, j) => { r.idx = j + 1; });

	frm.dirty();
	render_price_items_editor(frm);
}

function get_component_qty_map(frm) {
	return (frm.doc.items || []).reduce((acc, row) => {
		const comp = (row.component || "").toUpperCase().trim();
		if (comp) acc[comp] = flt(row.qty) || 1;
		return acc;
	}, {});
}

function apply_price_currency_formatters(frm) {
	const map = (frappe.meta.docfield_map || {})["Master Card Price Item"];
	if (!map) return;

	["material", "labour", "profit", "ext_profit", "total"].forEach((fieldname) => {
		if (!map[fieldname]) return;
		map[fieldname].formatter = (value) => format_price_currency(value, frm.doc.currency);
	});
}

function format_price_currency(value, currency) {
	const formatted = format_currency(value, currency, 4);
	const symbol = get_price_currency_symbol(currency);

	if (!currency || !symbol || symbol === currency) {
		return formatted;
	}

	return formatted.replace(new RegExp(`^${escape_regex(currency)}\\s*`), `${symbol} `);
}

function get_price_currency_symbol(currency) {
	const symbols = {
		SGD: "S$",
		USD: "$",
		IDR: "Rp",
		MYR: "RM",
	};
	return symbols[currency] || get_currency_symbol(currency);
}

function escape_regex(value) {
	return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function set_process_sequence(frm, cdt, cdn) {
	// Auto-increment: max(sequence) for the active component + 10
	const component = frm._active_process_tab;
	const maxSeq = (frm.doc.processes || [])
		.filter((r) => r.name !== cdn && r.component === component)
		.reduce((max, r) => Math.max(max, parseInt(r.sequence) || 0), 0);
	frappe.model.set_value(cdt, cdn, "sequence", maxSeq + 10);
}

function set_process_component_from_tab(frm, cdt, cdn) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || !frm._active_process_tab) return;
	if (row.component) return;
	frappe.model.set_value(cdt, cdn, "component", frm._active_process_tab).then(() => {
		filter_processes_grid(frm, frm._active_process_tab);
	});
}

function fill_blank_process_components(frm, letter) {
	(frm.doc.processes || []).forEach((row) => {
		if (!row.component) {
			frappe.model.set_value(row.doctype, row.name, "component", letter);
		}
	});
}

// ------------------------------------------------------------------
// Copy table helper — writes TSV to clipboard (data rows only)
// ------------------------------------------------------------------

function copy_table(frm, fieldname) {
	let field = frm.fields_dict[fieldname];
	if (!field || !field.grid) {
		frappe.show_alert({ message: __("Table not found"), indicator: "red" });
		return;
	}

	let rows = frm.doc[fieldname] || [];
	if (!rows.length) {
		frappe.show_alert({ message: __("No rows to copy"), indicator: "orange" });
		return;
	}

	let grid = field.grid;
	let columns = (grid.docfields || [])
		.filter((df) => df.in_list_view && !df.hidden)
		.map((df) => df.fieldname);

	if (!columns.length) {
		frappe.show_alert({ message: __("No visible columns found"), indicator: "orange" });
		return;
	}

	let tsv = rows
		.map((r) =>
			columns.map((f) => (r[f] !== undefined && r[f] !== null ? r[f] : "")).join("\t")
		)
		.join("\n");

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
