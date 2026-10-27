# SYSTEM RESILIENCE & DISTRIBUTED SYSTEMS AUDIT REPORT
**Platform:** Axiom Mobility (Fleetline) Tri-Stack Platform  
**Target Core Pillars:** `fleetline-mvp/server.py`, `fleetline-mvp/tariff_engine.py`, `fleetline-mvp/supabase/migrations/`, `fleetline-mvp/backend_domain.py`, `fleetline-mvp/backend_operations_parity.py`, `fleetline-mvp/backend_fare.py`, `frontend/`, `mobile-driver/`  
**Audit Status:** COMPLETE  

---

## 1. Concurrency & Double-Execution Risks

### 1.1 Driver & Vehicle Concurrent Assignment Collision
- **File & Lines:** `fleetline-mvp/backend_domain.py:693-736`
- **Vulnerability:** When a dispatcher creates a duty or assigns resources via `_create_duty`, the server validates ownership of `driver_id` and `vehicle_id` (`_assert_owned`), but fails to verify whether either resource is actively dispatched on an overlapping or in-progress duty (`status IN ('assigned', 'accepted', 'en_route', 'arrived', 'started', 'active')`). 
- **Impact:** Two dispatchers acting concurrently can assign the exact same driver and vehicle to two distinct active duties, leading to severe operational collisions and conflicting telemetry streams.
- **Remediation:** Add an atomic concurrency check rejecting duty assignment if the driver or vehicle is currently bound to an active, unclosed duty.

### 1.2 Duplicate Duty Creation for Single Booking
- **File & Lines:** `fleetline-mvp/backend_domain.py:696-736`
- **Vulnerability:** `_create_duty` checks `booking_id` status for `pending_approval`, but does not verify whether an active duty already exists for this `booking_id`.
- **Impact:** Double-clicking "Dispatch" generates two separate duty slips for the same customer booking.
- **Remediation:** Enforce uniqueness or atomic check: reject duty creation if an active duty (`status != 'cancelled'`) already exists for the given `booking_id`.

### 1.3 Invoice Generation Race & Double-Billing
- **File & Lines:** `fleetline-mvp/backend_domain.py:1019-1036`
- **Vulnerability:** `_create_invoice` does not check whether an invoice already exists for `duty_id`, does not check `idempotency_key`, and performs a naked `INSERT INTO domain_invoices`.
- **Impact:** Rapid duplicate calls to `POST /api/invoices` create multiple draft/issued invoices for the same trip duty, leading to duplicate customer billing and accounting discrepancies.
- **Remediation:** Check existing active invoices for `duty_id` and support atomic `idempotency_key` handling on `_create_invoice`.

### 1.4 Non-Atomic Duty Closure
- **File & Lines:** `fleetline-mvp/backend_operations_parity.py:484`
- **Vulnerability:** In `_close_duty`, `UPDATE domain_duties SET status = 'completed' ... WHERE id = ? AND organization_id = ?` is executed after an in-memory status check (`duty["status"] in ("cancelled", "completed")`). Concurrent requests arriving simultaneously pass the in-memory check before the DB row is committed.
- **Impact:** Concurrent close calls can insert duplicate closure evidence and duty closure records.
- **Remediation:** Enforce atomic conditional updates: `WHERE id = ? AND organization_id = ? AND status NOT IN ('completed', 'cancelled')`.

---

## 2. Financial & Tariff Integrity

### 2.1 Floating-Point Tax & Margin Precision Drift
- **File & Lines:** `fleetline-mvp/tariff_engine.py:270-282`
- **Vulnerability:** Calculation of GST tax and unit economics uses native Python binary floating-point arithmetic:
  ```python
  c_tax = round(c_gross * (gst_rate / 100.0))
  margin_pct = round((gross_margin_paise / c_gross) * 100.0, 2)
  ```
- **Impact:** Inherent IEEE 754 float representation errors cause 1-paise discrepancies between invoice line item sums and totals under large transaction volumes.
- **Remediation:** Refactor monetary and tax calculations to use `decimal.Decimal` with explicit `ROUND_HALF_UP` quantization before integer paise and string serialization.

### 2.2 Retroactive Tariff Recalculation on Closed/Invoiced Duties
- **File & Lines:** `fleetline-mvp/backend_fare.py:595-756`
- **Vulnerability:** `/api/fare/duties/{duty_id}/recalculate` allows re-running tariff resolution and overwriting `calculation_snapshot_json` on duties without checking whether `duty["status"]` is `completed`, `invoiced`, or `locked`.
- **Impact:** Tariff updates in SaaS Admin retroactively alter historical revenue, invoiced ledger amounts, and audited financial statements.
- **Remediation:** Reject `/api/fare/duties/{duty_id}/recalculate` with HTTP 409 Conflict if the duty is `completed`, `invoiced`, or `locked`. Store an immutable `tariff_snapshot` on finalized duties.

### 2.3 Outstation Calendar-Day & Slab Minimum Guarantee Boundaries
- **File & Lines:** `fleetline-mvp/tariff_engine.py:189-202`
- **Vulnerability:** When `calendar_days` is 0 or negative, `max(1, int(duty_params.get("calendar_days", 1)))` defaults to 1, but multi-day outstation trips spanning midnight without minimum daily km guarantees (e.g. 250 km/day) could undercharge if `calendar_days` calculation fails on timestamps.
- **Remediation:** Validate that multi-day outstation trips strictly apply `days * min_km_per_day` and non-negative timestamps across calendar boundaries.

---

## 3. Physical Plausibility & Offline Replay

### 3.1 Unbounded / Impossible Odometer Delta Validation
- **File & Lines:** `fleetline-mvp/backend_operations_parity.py:452-461`, `fleetline-mvp/tariff_engine.py:108-120`
- **Vulnerability:** Duty closure validates only that `end_odometer >= start_odometer`. It does not evaluate physical feasibility:
  - Total distance exceeding 1,500 km for a single local duty.
  - Implied average speed exceeding 180 km/h based on `(end_odo - start_odo) / duration_hours`.
- **Impact:** Erroneous driver inputs (e.g., typing `150000` instead of `15000`) result in astronomical billing charges to clients.
- **Remediation:** Implement a Physical Plausibility Gate that flags duties exceeding max plausible speed (>180 km/h) or excessive single-duty distance (>1,500 km local) for mandatory Maker-Checker manual audit.

---

## 4. Multi-Tenant IDOR & Privilege Escalation

### 4.1 Insecure Authentication Header Spoofing (`X-Axiom-User`)
- **File & Lines:** `fleetline-mvp/server.py:638-652`
- **Vulnerability:** In `current_user()`, if no valid session token is found, the server inspects `X-Axiom-User` and `X-Axiom-User-Email` HTTP headers:
  ```python
  client_email = handler.headers.get("X-Axiom-User-Email", "").strip().lower()
  if client_email:
      row = conn.execute(user_select_sql() + " WHERE lower(u.email) = ?", (client_email,)).fetchone()
      if row is not None:
          return row
  ```
- **Impact:** Any unauthenticated external client can bypass authentication and impersonate any tenant, vendor, corporate admin, or superadmin by simply supplying an `X-Axiom-User-Email` header.
- **Remediation:** Remove untrusted header-based identity resolution in production. Enforce cryptographic session tokens or verified HMAC/JWT tokens.

### 4.2 Cross-Tenant IDOR in Rate Card Copy
- **File & Lines:** `fleetline-mvp/backend_fare.py:379-425`
- **Vulnerability:** The visual rate card copy endpoint `/api/fare/rules/copy` accepted `source_entity_id` and `target_entity_id` without verifying that customer entities belong to the caller's `organization_id`.
- **Impact:** A tenant could clone proprietary corporate contract pricing belonging to another tenant.
- **Remediation:** Verify that `source_entity_id` and `target_entity_id` belong strictly to the authenticated `organization_id`.

---

## 5. Compliance Gates (Vehicle & Driver Expiry)

### 5.1 Unchecked Dispatch of Inactive/Expired Drivers & Vehicles
- **File & Lines:** `fleetline-mvp/backend_domain.py:700-708`
- **Vulnerability:** `_create_duty` asserts that the driver and vehicle belong to the organization, but completely ignores:
  - Driver `status` (can dispatch `inactive`, `suspended`, or `terminated` drivers).
  - Driver `license_expiry` (can dispatch drivers with expired commercial licenses).
  - Vehicle `status` (can dispatch vehicles in `maintenance` or `scrapped`).
  - Vehicle statutory documents: `insurance_expiry`, `puc_expiry`, and `rc_expiry`.
- **Impact:** Massive statutory liability, regulatory non-compliance under Indian Motor Vehicles Act, and invalid commercial insurance coverage in case of accidents.
- **Remediation:** Add strict compliance gates in `_create_duty`: block assignment of drivers or vehicles with `status != 'active'`/`status != 'available'` or with expired statutory documents unless an explicit compliance bypass is recorded.

---

## 6. Database N+1 Queries & Missing Indexes

### 6.1 N+1 Query in Vendor Overview
- **File & Lines:** `fleetline-mvp/server.py:385`
- **Vulnerability:** An unbatched query iterates over all vendor organizations:
  ```python
  for vrow in vendor_orgs:
      cust_count = conn.execute("SELECT count(*) FROM domain_customers WHERE organization_id = ?", (vrow["id"],)).fetchone()[0]
  ```
- **Impact:** Database performance degrades linearly $O(N)$ with the number of onboarded vendors.
- **Remediation:** Replace the loop with a single grouped aggregation query:
  `SELECT organization_id, count(*) FROM domain_customers GROUP BY organization_id`.

### 6.2 Missing Indexes on Foreign Keys and High-Frequency Filter Columns
- **File & Lines:** `fleetline-mvp/supabase/migrations/`
- **Vulnerability:** Critical operational tables (`domain_duties`, `domain_bookings`, `domain_invoices`) lack composite indexes for tenant-scoped state lookups:
  - `(organization_id, status, scheduled_at)` on `domain_bookings`
  - `(organization_id, status, reporting_at)` on `domain_duties`
  - `(organization_id, status, duty_id)` on `domain_invoices`
  - Foreign key indexes on `driver_id`, `vehicle_id`, and `customer_id`.
- **Impact:** Table scans occur on every dashboard poll and trip listing query under high concurrency.
- **Remediation:** Add SQL migration `20261027100000_system_resilience_indexes.sql` creating covering and composite indexes.

---

## 7. Secret & Config Leakage

### 7.1 Development Localhost Fallback in Mobile Client
- **File & Lines:** `fleetline-mvp/mobile-driver/src/api.ts:4`
- **Vulnerability:** `API_BASE` defaults to `http://localhost:4173` if `EXPO_PUBLIC_API_URL` is undefined.
- **Impact:** Production standalone mobile builds can fail silently if the environment variable is not bundled.
- **Remediation:** Ensure a secure fallback or runtime validation alerting if `API_BASE` is unconfigured.
