# SO Batch Feature - Testing Guide

## Build Status

✅ **COMPLETED:**
- SO Batch DocType (submittable, with 15 fields)
- SO Batch Item child table (with 10 fields)  
- IIB Settings Single DocType (with default_so_warehouse field)
- Custom Field: Sales Order-so_batch (Link to SO Batch, read-only)
- Server Script: "SO Batch - Create Sales Orders" (On Submit event)
- Payment Terms Template fixture
- All three DocTypes migrated to database
- All fixtures created and ready to import

## Test Scenario

This test validates the full SO Batch creation workflow.

### Setup (Run Once)

1. Ensure `bench --site iib.localhost migrate` has completed
2. Navigate to `http://iib.localhost:8001/app/iib-settings`
3. Set "Default SO Warehouse" to "Raw Material - IIB"
4. Save

### Create Test SO Batch

1. Navigate to `http://iib.localhost:8001/app/so-batch/new`
2. Fill in form:
   - **Customer**: TDK ELECTRONICS INDONESIA, PT
   - **Transaction Date**: Today
   - **Delivery Date**: Today  
   - **Currency**: IDR
   - **Conversion Rate**: 1.0
   - **Payment Terms Template**: Standard - Net 30
   - **Default Warehouse**: Raw Material - IIB
   
3. Add SO Batch Items (click "Add Row" in the table):

   **Row 1 (Set Bundle)**
   - PO No: PO-TEST-001
   - PO Date: Today
   - Set / Pcs: Set
   - Part No: **31A**
   - Qty: 10
   - Rate: 1000

   **Row 2 (Component Pcs - same PO)**
   - PO No: PO-TEST-001
   - PO Date: Today
   - Set / Pcs: Pcs
   - Part No: **67A**
   - Qty: 5
   - Rate: 500

   **Row 3 (Component Pcs - different PO)**
   - PO No: PO-TEST-002
   - PO Date: Today
   - Set / Pcs: Pcs
   - Part No: **67A**
   - Qty: 3
   - Rate: 500

4. Click **Save** (should save as Draft)
5. Click **Submit**

### Verify Results

After submission, check the following:

**In SO Batch Document:**
- [ ] "Created Sales Orders" field shows 2 SO names (separated by comma)
- [ ] Example: `SAL-ORD-2026-00123, SAL-ORD-2026-00124`

**Navigate to Sales Order List** (`http://iib.localhost:8001/app/sales-order`):
- [ ] Two new Sales Orders exist with today's date
- [ ] Both have "SO Batch" field populated with the SO Batch name
- [ ] PO-TEST-001 SO has 2 items:
  - Item code = "31 SET" (parent bundle), qty=10, rate=1000
  - Item code = "67A" (component), qty=5, rate=500
- [ ] PO-TEST-002 SO has 1 item:
  - Item code = "67A" (component), qty=3, rate=500

**Expected Item Resolution:**
- 31A (part_no in Set type) → resolves to "31 SET" (the parent bundle item code)
- 67A (part_no in Pcs type, custom_part_no=Z25000A6048B583) → resolves to "67A"

## Troubleshooting

### Error: "Unable to find item with part_no: 67A"
- The item "67A" might not exist in the database
- Verify: `frappe.db.get_value("Item", {"name": "67A"})`

### Error: "No Product Bundle contains part_no: 31A"
- The Product Bundle "31 SET" might not have 31A as a bundle item
- Verify: Product Bundle Item rows where item_code="31A" and parent="31 SET"

### Error: "Payment Terms Template required but not found"
- Run: `bench --site iib.localhost migrate`
- Verify: "Standard - Net 30" exists in Payment Terms Template list

### Sales Orders Created as Draft Instead of Submitted
- This is **Phase A** behavior - currently designed to create as Draft
- For Phase B (auto-submit), update Server Script and change `so.insert()` to `so.insert()` then `so.submit()`

## Files Modified/Created

| File | Status |
|------|--------|
| `apps/iib/iib/doctype/so_batch/so_batch.json` | Created ✓ |
| `apps/iib/iib/doctype/so_batch/so_batch.py` | Created ✓ |
| `apps/iib/iib/doctype/so_batch_item/so_batch_item.json` | Created ✓ |
| `apps/iib/iib/doctype/so_batch_item/so_batch_item.py` | Created ✓ |
| `apps/iib/iib/doctype/iib_settings/iib_settings.json` | Created ✓ |
| `apps/iib/iib/doctype/iib_settings/iib_settings.py` | Created ✓ |
| `apps/iib/fixtures/custom_field.json` | Updated ✓ |
| `apps/iib/fixtures/server_script.json` | Updated ✓ |
| `apps/iib/fixtures/payment_terms_template.json` | Created ✓ |

## Next Steps (Phase B)

1. Update Server Script to automatically submit SOs instead of Draft
2. Add client-side validation and auto-population (customer payment terms auto-fetch)
3. Add error logging/audit trail
4. Performance testing with large batches (50+ PO numbers)
5. Add scheduled job support
