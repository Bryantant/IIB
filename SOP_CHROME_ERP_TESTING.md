# SOP: Chrome Testing for ERP Customizations

## Purpose

Every ERP customization must be tested through the Chrome browser before it is considered complete. Bench commands and database checks are useful, but they do not replace browser validation because ERPNext behavior often depends on form scripts, permissions, field visibility, route state, dialogs, and client-side events.

## Scope

This SOP applies to every customization in the IIB ERP app, including:

- DocType changes
- Custom Fields and Property Setters
- Client Scripts and Server Scripts
- Python controller hooks
- Workflow, permission, and role changes
- Print formats, reports, dashboards, and workspace changes
- ERPNext override methods and document event hooks

## Required Rule

Do not mark an ERP customization as done until it has been tested in Chrome against the target site.

If Chrome testing is blocked, record the blocker clearly in the delivery note and do not describe the change as fully verified.

## Standard Test Flow

1. Confirm the target site and route.
   - Example site: `iib.localhost`
   - Example route: `/app/so-batch/new`

2. Run required backend preparation.
   - Apply schema or fixture changes with `bench --site <site> migrate`.
   - Clear cache with `bench --site <site> clear-cache`.
   - Restart or reload services when the change affects Python hooks, assets, or long-running workers.

3. Open the target workflow in Chrome.
   - Use the logged-in Chrome profile when user permissions, session state, or installed browser extensions matter.
   - Prefer the exact route a real user would open from Desk.

4. Validate the happy path.
   - Create or open the relevant document.
   - Fill the fields a real user would fill.
   - Save, submit, cancel, amend, or run the action being customized.
   - Confirm the resulting document state and linked records.

5. Validate at least one guard path.
   - Missing required data
   - Invalid mapping
   - Duplicate submission
   - Permission or role-specific behavior
   - Cancel or rollback behavior, when relevant

6. Inspect the browser UI result.
   - Confirm fields are visible or hidden as expected.
   - Confirm client scripts fire at the right time.
   - Confirm generated links, dialogs, messages, and buttons are usable.
   - Confirm no obvious console-visible breakage or page-level error appears.

7. Verify persisted data.
   - Use the browser first.
   - Use bench or database queries only as supporting evidence.
   - Confirm linked documents, child table rows, status, docstatus, and mapped fields.

8. Capture evidence.
   - Record the Chrome route tested.
   - Record the document names created or updated.
   - Record the actions tested.
   - Include screenshots when UI behavior changed or when the workflow is important.

## Minimum Evidence Format

Use this format in delivery notes, PR descriptions, or implementation summaries:

```text
Chrome Test:
- Site:
- Route:
- Role/User:
- Scenario:
- Created/Updated Docs:
- Result:
- Screenshot/Evidence:
```

## SO Batch Example Checklist

Use this checklist when changing SO Batch behavior:

- Open `/app/so-batch/new` in Chrome.
- Create an SO Batch with at least two rows.
- Include rows with the same PO No and same PO Date.
- Include rows with a different PO No or different PO Date.
- Save and confirm resolved item fields are populated.
- Submit and confirm Sales Orders are created.
- Confirm Sales Order `PO No`, `PO Date`, `SO Batch`, warehouse, delivery date, item, quantity, and rate.
- Try submitting again or amending in a way that would duplicate Sales Orders, and confirm the guard works.
- Cancel the SO Batch and confirm related draft Sales Orders are deleted and submitted Sales Orders are canceled.

## Blocker Handling

If Chrome cannot be used:

- State that Chrome testing was blocked.
- State the exact blocker, such as Chrome not running, Codex Chrome Extension unavailable, login missing, server down, or route inaccessible.
- Complete backend verification where possible.
- Ask for the blocker to be resolved before final sign-off.

## Completion Standard

A customization is complete only when:

- Code or metadata changes are applied.
- Migration/cache steps are complete when needed.
- The target workflow is tested in Chrome.
- Data persistence is verified.
- Evidence is recorded.
- Any limitations or skipped cases are explicitly documented.
