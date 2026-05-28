// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Master Card", {
	setup(frm) {
		set_process_queries(frm);
	},

	refresh(frm) {
		frm.set_df_property("item_code", "read_only", 1);
		frm.trigger("render_mc_badge");
		frm.trigger("render_copy_buttons");
		frm.trigger("add_action_buttons");
		apply_price_currency_formatters(frm);
		calculate_price_rows(frm);
		render_price_items_summary(frm);

		// Force correct column definitions on the processes grid.
		// Browser localStorage may cache an older schema, so patch docfields
		// directly to match the server schema.
		ensure_process_grid_columns(frm);
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

	price_items_add(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	price_items_remove(frm) {
		render_price_items_summary(frm);
	},

	currency(frm) {
		apply_price_currency_formatters(frm);
		render_price_items_summary(frm);
		frm.refresh_field("price_items");
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

		// Re-render tabs so the new component letter appears
		frm.trigger("render_process_tabs");
		render_price_items_summary(frm);
	},

	qty(frm) {
		render_price_items_summary(frm);
	},

	items_remove(frm) {
		// Re-render tabs after a component row is deleted
		frm.trigger("render_process_tabs");
		render_price_items_summary(frm);
	},
});

frappe.ui.form.on("Master Card Price Item", {
	moq_qty(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	component(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		let component = (row.component || "").toUpperCase().replace(/[^A-Z]/g, "").slice(0, 1);
		frappe.model.set_value(cdt, cdn, "component", component).then(() => {
			render_price_items_summary(frm);
		});
	},

	material(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	labour(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	profit(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	ext_profit(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	price_items_add(frm, cdt, cdn) {
		calculate_price_row(frm, cdt, cdn);
	},

	price_items_remove(frm) {
		render_price_items_summary(frm);
	},
});

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

// ------------------------------------------------------------------
// Ensure processes grid always has the correct column definitions.
// Browser localStorage may cache a stale schema, so the grid meta is patched
// in-place before Frappe lays out the child table.
// Fix: patch frappe.meta directly so grid.setup_fields() re-reads correctly.
// columns must sum to ≤ 10:
//   component(1)+sequence(1)+section(3)+est_time(2)+description(3) = 10
// ------------------------------------------------------------------

const PROCESS_GRID_COLUMNS = [
	{ fieldname: "component",    label: "Comp",                fieldtype: "Data", in_list_view: 1, columns: 1, reqd: 1, read_only: 1, parent: "Master Card Process" },
	{ fieldname: "sequence",     label: "Seq",                 fieldtype: "Int",  in_list_view: 1, columns: 1, reqd: 1, parent: "Master Card Process" },
	{ fieldname: "section",      label: "Section Group",       fieldtype: "Link", in_list_view: 1, columns: 3, reqd: 1, options: "IIB Production Section", parent: "Master Card Process" },
	{ fieldname: "est_time_mins",label: "Est Time (mins)",     fieldtype: "Int",  in_list_view: 1, columns: 2, parent: "Master Card Process" },
	{ fieldname: "description",  label: "Description",         fieldtype: "Data", in_list_view: 1, columns: 3, parent: "Master Card Process" },
	{ fieldname: "remarks",      label: "Remarks",             fieldtype: "Data", in_list_view: 0, parent: "Master Card Process" },
];

function ensure_process_grid_columns(frm) {
	const DT = "Master Card Process";
	const map = (frappe.meta.docfield_map || {})[DT] || {};

	// 1. Patch frappe.meta.docfield_map (keyed by fieldname)
	frappe.provide("frappe.meta.docfield_map." + DT);
	PROCESS_GRID_COLUMNS.forEach((col) => {
		const cur = frappe.meta.docfield_map[DT][col.fieldname];
		if (cur) {
			Object.assign(cur, col);
		} else {
			frappe.meta.docfield_map[DT][col.fieldname] = Object.assign({}, col);
		}
	});
	if (map.machine) {
		Object.assign(map.machine, { hidden: 1, in_list_view: 0, reqd: 0 });
	}

	// 2. Patch frappe.meta.docfield_list (ordered array)
	if (!frappe.meta.docfield_list) frappe.meta.docfield_list = {};
	const list = frappe.meta.docfield_list[DT] || [];
	const ordered = PROCESS_GRID_COLUMNS.map((col) => {
		const existing = list.find((f) => f.fieldname === col.fieldname);
		return Object.assign(existing || {}, col);
	});
	list
		.filter((f) => !PROCESS_GRID_COLUMNS.some((col) => col.fieldname === f.fieldname))
		.forEach((f) => {
			if (f.fieldname === "machine") {
				Object.assign(f, { hidden: 1, in_list_view: 0, reqd: 0 });
			}
			ordered.push(f);
		});
	frappe.meta.docfield_list[DT] = ordered;

	// 3. Patch locals['DocType'] so frappe.get_meta() is consistent
	const meta = frappe.get_meta(DT);
	if (meta) {
		PROCESS_GRID_COLUMNS.forEach((col) => {
			const f = (meta.fields || []).find((x) => x.fieldname === col.fieldname);
			if (f) {
				Object.assign(f, col);
			} else {
				meta.fields = meta.fields || [];
				meta.fields.push(Object.assign({}, col));
			}
		});
		const machine = (meta.fields || []).find((x) => x.fieldname === "machine");
		if (machine) {
			Object.assign(machine, { hidden: 1, in_list_view: 0, reqd: 0 });
		}
	}

	// 4. Re-run setup_fields() so grid re-reads from the now-correct meta,
	//    then rebuild the header row. Do NOT call grid.refresh() — that
	//    would re-trigger setup_fields() and create a loop.
	const grid = frm.fields_dict.processes && frm.fields_dict.processes.grid;
	if (!grid) return;
	grid.setup_fields();
	grid.make_head();
}

function set_process_queries(frm) {
	frm.set_query("section", "processes", () => ({
		filters: {
			is_group: 1,
			disabled: 0,
		},
	}));
}

function calculate_price_rows(frm) {
	apply_price_currency_formatters(frm);
	(frm.doc.price_items || []).forEach((row) => {
		calculate_price_row(frm, row.doctype, row.name, false);
	});
	render_price_items_summary(frm);
}

function calculate_price_row(frm, cdt, cdn, render = true) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row) return;

	const total =
		flt(row.material) + flt(row.labour) + flt(row.profit) + flt(row.ext_profit);
	frappe.model.set_value(cdt, cdn, "total", total);

	if (render) {
		render_price_items_summary(frm);
	}
}

function render_price_items_summary(frm) {
	const field = frm.fields_dict.price_items_html;
	if (!field) return;

	const rows = (frm.doc.price_items || []).slice().sort((a, b) => {
		const moqDiff = flt(a.moq_qty) - flt(b.moq_qty);
		if (moqDiff) return moqDiff;
		return String(a.component || "").localeCompare(String(b.component || ""));
	});

	if (!rows.length) {
		field.$wrapper.html(
			`<p class="text-muted small" style="margin:4px 0 8px">${__(
				"Add price rows below. Rows are grouped by MOQ quantity."
			)}</p>`
		);
		return;
	}

	const grouped = rows.reduce((acc, row) => {
		const moq = flt(row.moq_qty);
		if (!acc[moq]) acc[moq] = [];
		acc[moq].push(row);
		return acc;
	}, {});
	const qty_by_component = get_component_qty_map(frm);

	const blocks = Object.keys(grouped)
		.map((moq) => {
			const body = grouped[moq]
				.map((row) => {
					const component = (row.component || "").toUpperCase().trim();
					const qty = qty_by_component[component] || 1;
					const set_total = flt(row.total) * qty;
					return `
						<tr>
							<td>${frappe.utils.escape_html(component)}</td>
							<td class="text-right">${format_price_currency(row.material, frm.doc.currency)}</td>
							<td class="text-right">${format_price_currency(row.labour, frm.doc.currency)}</td>
							<td class="text-right">${format_price_currency(row.profit, frm.doc.currency)}</td>
							<td class="text-right">${format_price_currency(row.ext_profit, frm.doc.currency)}</td>
							<td class="text-right">${format_qty(qty)}</td>
							<td class="text-right">${format_price_currency(row.total, frm.doc.currency)}</td>
							<td class="text-right">${format_price_currency(set_total, frm.doc.currency)}</td>
						</tr>`;
				})
				.join("");

			const total = grouped[moq].reduce((sum, row) => {
				const component = (row.component || "").toUpperCase().trim();
				const qty = qty_by_component[component] || 1;
				return sum + flt(row.total) * qty;
			}, 0);
			return `
				<div style="margin:0 0 12px">
					<div class="text-muted small" style="margin-bottom:4px">${__("MOQ Qty")}: <strong>${moq}</strong> &nbsp; ${__(
						"Total Set Price"
					)}: <strong>${format_price_currency(total, frm.doc.currency)}</strong></div>
					<div class="table-responsive">
						<table class="table table-bordered table-condensed" style="margin-bottom:0">
							<thead>
								<tr>
									<th>${__("Comp")}</th>
									<th class="text-right">${__("Material")}</th>
									<th class="text-right">${__("Labour")}</th>
									<th class="text-right">${__("Profit")}</th>
									<th class="text-right">${__("Ext Profit")}</th>
									<th class="text-right">${__("Qty")}</th>
									<th class="text-right">${__("Unit Total")}</th>
									<th class="text-right">${__("Set Total")}</th>
								</tr>
							</thead>
							<tbody>${body}</tbody>
						</table>
					</div>
				</div>`;
		})
		.join("");

	field.$wrapper.html(blocks);
}

function get_component_qty_map(frm) {
	return (frm.doc.items || []).reduce((acc, row) => {
		const component = (row.component || "").toUpperCase().trim();
		if (component) {
			acc[component] = flt(row.qty) || 1;
		}
		return acc;
	}, {});
}

function format_qty(value) {
	const qty = flt(value);
	return Number.isInteger(qty) ? String(qty) : String(qty);
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
