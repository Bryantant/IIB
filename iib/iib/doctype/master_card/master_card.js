// Copyright (c) 2026, Hicom System and contributors
// For license information, please see license.txt

frappe.ui.form.on("Master Card", {
	refresh(frm) {
		frm.set_df_property("item_code", "read_only", 1);
		frm.trigger("render_mc_badge");
		frm.trigger("render_copy_buttons");
		frm.trigger("add_action_buttons");

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
	},

	items_remove(frm) {
		// Re-render tabs after a component row is deleted
		frm.trigger("render_process_tabs");
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
// Browser localStorage may cache a stale schema (missing machine/remarks).
// Fix: patch frappe.meta directly so grid.setup_fields() re-reads correctly.
// columns must sum to ≤ 10:
//   component(1)+sequence(1)+section(2)+est_time(1)+machine(2)+remarks(3) = 10
// ------------------------------------------------------------------

const PROCESS_GRID_COLUMNS = [
	{ fieldname: "component",    label: "Comp",                fieldtype: "Data", in_list_view: 1, columns: 1, reqd: 1, parent: "Master Card Process" },
	{ fieldname: "sequence",     label: "Seq",                 fieldtype: "Int",  in_list_view: 1, columns: 1, reqd: 1, parent: "Master Card Process" },
	{ fieldname: "section",      label: "Section",             fieldtype: "Link", in_list_view: 1, columns: 2, reqd: 1, options: "IIB Production Section", parent: "Master Card Process" },
	{ fieldname: "est_time_mins",label: "Est Time (mins)",     fieldtype: "Int",  in_list_view: 1, columns: 1, parent: "Master Card Process" },
	{ fieldname: "machine",      label: "Machine/Workstation", fieldtype: "Data", in_list_view: 1, columns: 2, parent: "Master Card Process" },
	{ fieldname: "remarks",      label: "Remarks",             fieldtype: "Data", in_list_view: 1, columns: 3, parent: "Master Card Process" },
	{ fieldname: "description",  label: "Description",         fieldtype: "Data", in_list_view: 0, parent: "Master Card Process" },
];

function ensure_process_grid_columns(frm) {
	const DT = "Master Card Process";

	// Check if already correct (machine present with in_list_view=1)
	const map = (frappe.meta.docfield_map || {})[DT] || {};
	if (map["machine"] && map["machine"].in_list_view) return;

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

	// 2. Patch frappe.meta.docfield_list (ordered array)
	if (!frappe.meta.docfield_list) frappe.meta.docfield_list = {};
	const list = frappe.meta.docfield_list[DT] || [];
	PROCESS_GRID_COLUMNS.forEach((col) => {
		const idx = list.findIndex((f) => f.fieldname === col.fieldname);
		if (idx >= 0) {
			Object.assign(list[idx], col);
		} else {
			list.push(Object.assign({}, col));
		}
	});
	frappe.meta.docfield_list[DT] = list;

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
	}

	// 4. Re-run setup_fields() so grid re-reads from the now-correct meta,
	//    then rebuild the header row. Do NOT call grid.refresh() — that
	//    would re-trigger setup_fields() and create a loop.
	const grid = frm.fields_dict.processes && frm.fields_dict.processes.grid;
	if (!grid) return;
	grid.setup_fields();
	grid.make_head();
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
