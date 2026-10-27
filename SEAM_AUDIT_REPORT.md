# Axiom Mobility (Fleetline) · Cross-Boundary Seam Bug Audit Report

**Audit Target:** Axiom Mobility (Fleetline) Tri-Stack B2B Enterprise Platform  
**Scope:** `server.py`, `tariff_engine.py`, `supabase/migrations/`, `VendorCommandDashboard.js`, `AdminSaasConsole.js`, `driver-app/index.html`, `mobile-driver/App.tsx`  
**Date:** 2026-10-27  

---

## Executive Summary
A comprehensive security and architectural seam audit across all 143 repository files revealed **14 critical and high-severity seam bugs** spanning:
1. JSON contract & type drift between Python backend and ES6+/TSX frontends.
2. Tariff engine model omission and asymmetric dual-ledger breakdowns.
3. DOM lifecycle destruction, uncleaned window listeners, and zombie async mutations.
4. Client-side state mutability and double-click submission races.
5. Missing server-side state-machine locks on invoiced/completed trips.
6. Multi-tenant authorization vulnerabilities and missing Supabase PostgreSQL RLS write policies.

---

## Detailed Seam Bug Inventory

### Seam A: Python (`server.py` / `tariff_engine.py`) <-> ES6+ / TSX JSON Key & Type Contracts

#### Bug A.1: Missing `PER_SEAT_SHARED_POOL` Model in Tariff Engine
- **Files & Lines:** `fleetline-mvp/tariff_engine.py:7, 129-188`
- **Root Cause:** Model #4 (`PER_SEAT_SHARED_POOL`) is documented in docstrings as a core Tri-Stack capability (MoveInSync benchmark), but is omitted from the `if/elif` dispatch chain in `calculate_dual_ledger_duty()`. It falls into the `else:` block, erroneously billing employee shuttle seat pools as standard 4H/40KM spot rentals.
- **Severity:** CRITICAL (Financial calculation error)

#### Bug A.2: Outstation & Zone Ring Double-Deduction & Asymmetric Breakdown in Supplier Payable
- **Files & Lines:** `fleetline-mvp/tariff_engine.py:208, 230-237`
- **Root Cause:** In `calculate_dual_ledger_duty()`, line 208 unconditionally computes supplier extra km by subtracting 40 km (`billable_km - 40.0`) regardless of billing mode. For `OUTSTATION_CALENDAR_DAY`, this double-charges mileage above base rate. For `RADIAL_ZONE_RING`, it tacks extra km onto a fixed-ring rate. Additionally, `supplier_payable` lacks `extra_km_paise`, `extra_hr_paise`, and `fuel_surcharge_paise`, breaking contract symmetry with `client_receivable`.
- **Severity:** HIGH (Financial ledger corruption)

#### Bug A.3: Metric Key Drift Between Tariff Engine and Vendor Command Dashboard
- **Files & Lines:** `fleetline-mvp/tariff_engine.py:239` vs `fleetline-mvp/frontend/js/components/VendorCommandDashboard.js:66, 592-594`
- **Root Cause:** `tariff_engine.py` returns `gross_margin_percentage`, whereas `VendorCommandDashboard.js` reads `margin_pct`. Furthermore, `corporate_pnl` references `client_billing` and `vendor_cost`, while backend services return `client_receivable_paise` and `supplier_payable_paise`. Direct references without fallback normalization result in `NaN` displays.
- **Severity:** MEDIUM (UI data contract mismatch)

#### Bug A.4: Driver App Odometer & Duty Closure Seam
- **Files & Lines:** `fleetline-mvp/driver-app/index.html:131`, `fleetline-mvp/mobile-driver/App.tsx:192` vs `fleetline-mvp/backend_operations_parity.py:432-461`
- **Root Cause:** Both the PWA driver app and React Native driver app complete trips via `PATCH /api/duties/{id}` with `{ status: 'completed' }` and no odometer inputs. `backend_operations_parity.py` defines `/api/duties/{id}/close` with mandatory `start_odometer` and `end_odometer` (`end >= start >= 0`). The driver apps bypass this contract, leaving completed duties with NULL odometer readings.
- **Severity:** HIGH (Telemetry & audit compliance break)

#### Bug A.5: Odometer Negative Delta & Inversion Allowed in `_update_duty`
- **Files & Lines:** `fleetline-mvp/backend_domain.py:781-786`
- **Root Cause:** While `_close_duty` validates `end_odometer >= start_odometer`, `_update_duty` does not validate odometer values. A caller can send `start_odometer: 5000` and `end_odometer: 4000`, recording negative distance deltas into the database.
- **Severity:** HIGH (Data integrity defect)

---

### Seam B: View Switching, DOM Lifecycle & Event Listener Integrity

#### Bug B.1: Dead Listeners from `.innerHTML` Overwrite Without Event Delegation
- **Files & Lines:** `fleetline-mvp/frontend/js/components/VendorCommandDashboard.js:611-689` and `fleetline-mvp/frontend/js/components/AdminSaasConsole.js:348-393`
- **Root Cause:** Components bind click listeners directly to individual button elements. On lens switch (`btn-lens-ops` / `btn-lens-rev`) or tab switch, `.innerHTML` overwrites the DOM and `bindEvents()` is re-invoked. Any dynamic drawer or modal action not in the initial query selector loses its binding, while static parent nodes accumulate duplicate listeners.
- **Severity:** HIGH (Memory leaks & unresponsive UI buttons)

#### Bug B.2: Leaking Window Keydown Event Listeners on Re-mount
- **Files & Lines:** `fleetline-mvp/frontend/js/components/VendorCommandDashboard.js:127-138`
- **Root Cause:** `setupSpotlightShortcut()` binds `window.addEventListener("keydown", ...)` during `init()`. The `destroy()` method only clears `timerInterval` and does NOT remove the window keydown listener. Repeatedly mounting/unmounting the dashboard stacks global keydown listeners.
- **Severity:** MEDIUM (Event listener leak)

#### Bug B.3: Missing `destroy()` / `unmount()` Lifecycle Hook in `AdminSaasConsole`
- **Files & Lines:** `fleetline-mvp/frontend/js/components/AdminSaasConsole.js:40-100`
- **Root Cause:** `AdminSaasConsole` does not implement `destroy()` or `unmount()`. When navigating away, event listeners attached to persistent DOM nodes and modals remain active.
- **Severity:** MEDIUM (Resource leak)

#### Bug B.4: Zombie Async View Mutations from In-Flight `fetch()`
- **Files & Lines:** `fleetline-mvp/frontend/js/components/AdminSaasConsole.js:47-54`
- **Root Cause:** `fetchData()` performs an un-aborted `fetch("/api/v1/admin/saas/tenants")`. If the user switches views before the network request resolves, the promise callback executes and modifies `this.state` and the DOM of an unmounted component.
- **Severity:** HIGH (Race condition & view corruption)

---

### Seam C: State Mutations, Financial Locks & Multi-Tenant Authorization

#### Bug C.1: Unprotected Client State & Double-Click Submission Race
- **Files & Lines:** `fleetline-mvp/frontend/js/components/VendorCommandDashboard.js:12-80`, `AdminSaasConsole.js:544-552`
- **Root Cause:** Application state is stored in plain, mutable objects without `Proxy` guards or freeze mechanisms. Critical action buttons (e.g. wallet top-up, impersonation start/end, shadow mode switch) lack in-flight disable guards, allowing rapid double-clicking to trigger duplicate network mutations.
- **Severity:** HIGH (Financial double-charge risk)

#### Bug C.2: Server-Side Financial State Machine Lock Bypass
- **Files & Lines:** `fleetline-mvp/backend_domain.py:770-817, 960-976`
- **Root Cause:** `_calculate` and `_update_duty` do not verify whether a duty has already been invoiced or locked. When an invoice has been generated or issued (`domain_invoices.status IN ('draft', 'issued', 'sent')`), an actor can call `POST /api/duties/{id}/calculate` or `PATCH /api/duties/{id}` to alter the underlying pricing, odometer, or driver, silently invalidating the issued financial snapshot.
- **Severity:** CRITICAL (FinTech audit breach & ledger mismatch)

#### Bug C.3: Unauthenticated Session Minting via `/api/auth/sync-session`
- **Files & Lines:** `fleetline-mvp/server.py:1014-1025`
- **Root Cause:** `_api_sync_session` accepts a JSON body with `{"user": {"email": "..."}}` and generates a valid session cookie without verifying passwords, OTPs, or signatures. Any unauthenticated caller can impersonate any user on the platform simply by providing their email.
- **Severity:** CRITICAL (Authentication bypass)

#### Bug C.4: Unchecked Admin Impersonation & SaaS Management Authorization
- **Files & Lines:** `fleetline-mvp/backend_impersonation.py:216-248, 303-314`
- **Root Cause:** `handle_impersonation_api()` does not verify whether `actor_user` possesses admin privileges (`role == 'admin'`, `@axiomfleet.in`, or `is_axiom_hq`). Any authenticated driver or vendor can call `POST /api/v1/admin/impersonate` to generate shadow JWTs and access other tenants' data.
- **Severity:** CRITICAL (Multi-tenant B2B isolation failure)

#### Bug C.5: Client-Supplied `vendor_id` Trusted in Partner SLA Evaluation
- **Files & Lines:** `fleetline-mvp/backend_tristack.py:426-454`
- **Root Cause:** In `/api/tri-stack/sla/evaluate`, the server trusts `data.get("vendor_id")` directly from the request payload to demote tiers and issue penalty debit notes, rather than verifying the caller's authorized tenant/organization.
- **Severity:** HIGH (Cross-tenant tampering)

#### Bug C.6: Missing Supabase PostgreSQL RLS Write Policies on SaaS Tables
- **Files & Lines:** `fleetline-mvp/supabase/migrations/20261027080000_saas_console_and_impersonation.sql:77-105`
- **Root Cause:** While RLS is enabled on `tenant_wallets` and `tenant_feature_flags`, policies only permit `SELECT` for vendors. There are no `INSERT` or `UPDATE` policies for Super-Admins or platform users, blocking legitimate balance adjustments and feature toggles from authenticated clients.
- **Severity:** HIGH (Database permission block)
