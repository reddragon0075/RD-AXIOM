# Axiom Mobility (Fleetline) Production Launch & Operations Runbook

## 1. ARCHITECTURE & TOPOLOGY OVERVIEW

Axiom Mobility (Fleetline) is an Enterprise B2B Mobility and Dual-Ledger FinTech platform powering corporate commute (ETS) and rental/outstation (RAC) transport.

```
+-----------------------------------------------------------------------------------------+
|                                    CLIENT SURFACES                                      |
|  +------------------------+  +----------------------+  +-----------------------------+  |
|  | VendorCommandDashboard |  |    AdminSaasConsole  |  | Driver App (PWA + App.tsx)  |  |
|  | (500-ring telemetry)  |  | (Tenant Impersonate) |  | (Wake-Lock, LocalStorage)   |  |
+--+-----------+------------+--+----------+-----------+--+--------------+--------------+--+
               |                          |                             |
               +--------------------+     |     +-----------------------+
                                    |     |     |
                                    v     v     v
+-----------------------------------------------------------------------------------------+
|                            HIGH-CONCURRENCY API GATEWAY                                 |
|  `fleetline-mvp/server.py` (ThreadingHTTPServer / Uvicorn ASGI, backlog: 512)            |
|  - Insecure Direct Object Reference (IDOR) Tenant Isolation                             |
|  - Mutability Guards (Status-locked trips / duties cannot mutate)                       |
|  - Pure-Agent Reimbursement GST Segregation (SAC 996601)                                 |
+-------------------------------------------+---------------------------------------------+
                                            |
               +----------------------------+----------------------------+
               v                                                         v
+-------------------------------+                       +---------------------------------+
|   TARIFF & FINTECH ENGINE     |                       |    PERSISTENCE & AUDIT LOGS     |
|   `tariff_engine.py`          |                       |    Supabase PostgreSQL + WAL    |
|   - 6 Billing Models          |                       |    - Idempotent Migrations      |
|   - Paise Decimal Precision   |                       |    - Row-Level Security (RLS)   |
|   - Pass-Through Toll/Parking |                       |    - Immutable Tamper-Proof Log |
+-------------------------------+                       +---------------------------------+
```

---

## 2. PRODUCTION ENVIRONMENT VARIABLE CHECKLIST

### 2.1 Backend Server (`fleetline-mvp/server.py`)
| Variable | Value / Format | Required | Purpose |
|---|---|---|---|
| `AXIOM_ENV` | `production` | **YES** | Enforces strict CORS, disables mock tokens, and turns on security gates |
| `PORT` | `4173` / `8000` | **YES** | Port for HTTP/REST gateway |
| `AXIOM_ALLOWED_ORIGINS` | `https://ops.fleetline.io,https://admin.fleetline.io` | **YES** | Restricts CORS to authorized corporate and vendor domains |
| `AXIOM_COOKIE_SECURE` | `1` | **YES** | Enforces `Secure; HttpOnly; SameSite=Strict` on session cookies |
| `AXIOM_DATA_DIR` | `/var/lib/axiom/data` | **YES** | Persistent directory for SQLite WAL / operational caches |
| `AXIOM_DB_PATH` | `/var/lib/axiom/data/axiom_fleet.sqlite3` | **YES** | Path to primary database storage |
| `AXIOM_PAYMENT_WEBHOOK_SECRET`| `whsec_live_9x8a7b6c5d4e3f` | **YES** | HMAC SHA-256 signature verification secret |
| `AXIOM_ALLOW_DEMO_ACCOUNT` | `0` | **YES** | Disables fallback demo user logins in production |
| `AXIOM_ALLOW_MOCK_PAYMENTS`| `0` | **YES** | Forces real payment gateway calls |

### 2.2 Database & Supabase Migrations
| Variable | Value / Format | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:[PWD]@db.[REF].supabase.co:5432/postgres` | **YES** | Direct connection pool for migrations and backend queries |
| `SUPABASE_URL` | `https://[REF].supabase.co` | **YES** | Supabase REST/Realtime endpoint |
| `SUPABASE_ANON_KEY` | `eyJhbGciOi...` | **YES** | Public API gateway key |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJhbGciOi...` | **YES** | Admin service role key for audit and security jobs |

### 2.3 Mobile & Driver App Client
| Variable | Value / Format | Required | Purpose |
|---|---|---|---|
| `EXPO_PUBLIC_API_URL` | `https://api.fleetline.io` | **YES** | Base URL for driver REST and telemetry pings |
| `EXPO_PUBLIC_GPS_INTERVAL_MS`| `5000` | **YES** | Telemetry broadcast cadence |
| `EXPO_PUBLIC_STORAGE_KEY` | `axiomfleet_driver_active_duty` | **YES** | Offline persistence key in AsyncStorage / localStorage |

---

## 3. ZERO-DOWNTIME MIGRATION SEQUENCE & ROLLBACK

### 3.1 Migration Sequence (Forward)
Apply PostgreSQL migrations in strict timestamp order using Supabase CLI or `psql`:

```bash
# 1. Verify DB connection
psql "$DATABASE_URL" -c "SELECT version();"

# 2. Run idempotent migrations in order
MIGRATIONS_DIR="fleetline-mvp/supabase/migrations"
for sql_file in $(ls $MIGRATIONS_DIR/*.sql | sort); do
  echo "[+] Applying $sql_file..."
  psql "$DATABASE_URL" -f "$sql_file" --set ON_ERROR_STOP=1
done

# 3. Verify Table & View Integrity
psql "$DATABASE_URL" -c "
  SELECT table_name, table_type 
  FROM information_schema.tables 
  WHERE table_schema = 'public' 
  ORDER BY table_name;
"
```

### 3.2 Automated Rollback Procedure
If any migration fails or breaks an active operational contract:

1. **Rollback Script:**
   ```bash
   # Revert latest migration patch
   psql "$DATABASE_URL" -c "
     BEGIN;
     -- Drop views and triggers added in patch
     DROP VIEW IF EXISTS v_vendor_command_dual_ledger CASCADE;
     DROP VIEW IF EXISTS v_duty_billing_summary CASCADE;
     -- Revert policy
     ALTER TABLE domain_duties ENABLE ROW LEVEL SECURITY;
     COMMIT;
   "
   ```
2. **Container Image Rollback:**
   ```bash
   # Revert to previous healthy Docker image tag
   docker service update --image fleetline-api:v2.9.4 fleetline_production_api
   ```
3. **Verify Health Check:**
   ```bash
   curl -sS https://api.fleetline.io/healthz | grep '"status":"ok"'
   ```

---

## 4. 5 GO-LIVE SMOKE TEST COMMANDS

Execute these commands against the live or staging deployment endpoint to certify go-live readiness:

### Smoke Test 1: Service Health & Queue Capacity
```bash
curl -f -sS http://localhost:4173/healthz
# Expected Response:
# {"status":"ok","timestamp":"...","environment":"production"}
```

### Smoke Test 2: Admin SaaS Tenant Listing & KPI Strip
```bash
curl -f -sS -H "Cookie: axiom_session=ADMIN_SESSION_TOKEN" \
  http://localhost:4173/api/v1/admin/saas/tenants
# Expected Response:
# {"tenants":[{"tenant_id":169,"tenant_name":"Zion Travels",...}],"kpi_strip":{"active_corporates":71,...}}
```

### Smoke Test 3: Duty Booking & IDOR Multi-Tenant Fence
```bash
curl -f -sS -X POST http://localhost:4173/api/v1/duties \
  -H "Content-Type: application/json" \
  -H "Cookie: axiom_session=VENDOR_A_TOKEN" \
  -d '{"booking_id":"bk_test_01","driver_id":"drv_vendor_b_01"}'
# Expected Response:
# 403 Forbidden or 404 Not Found (Cross-tenant assignment blocked)
```

### Smoke Test 4: Pure-Agent GST Dual-Ledger Calculation
```bash
python -c "
from fleetline_mvp.tariff_engine import calculate_dual_ledger_duty
card = {'billing_mode':'slab','client_base_fare_paise':150000,'client_base_distance_km':40,'client_base_duration_hr':4,'client_extra_km_rate_paise':1800,'client_extra_hr_rate_paise':15000,'supplier_base_fare_paise':110000,'supplier_base_distance_km':40,'supplier_base_duration_hr':4,'supplier_extra_km_rate_paise':1400,'supplier_extra_hr_rate_paise':10000,'fuel_rate_current':100,'fuel_rate_base':100,'fuel_efficiency_km_per_l':15,'gst_rate_pct':5}
res = calculate_dual_ledger_duty({'billing_mode':'slab','distance_km':45,'duration_hours':4.5,'toll_charges_paise':25000}, card)
assert res['client_receivable']['pure_agent_passthrough_paise'] == 25000
assert res['client_receivable']['gst_total_paise'] == 8325
print('[PASS] Pure Agent GST calculation verified.')
"
```

### Smoke Test 5: Live Pilot Simulator Fast-Pass
```bash
python fleetline-mvp/simulate_pilot.py --fast
# Expected Response:
# [OK] Pilot Simulation Completed Successfully.
# Total Telemetry Pings Streamed: 160
# Pro-Forma Invoices Generated:  5 (Dual-ledger with Pure-Agent GST)
# Compliance & Odometer Anomaly:  Duty 'd-pilot-025' held in 'distance_hold' (63.5km variance)
```

---

## 5. SHIFT-CHANGE CONCURRENCY THRESHOLDS

During morning (07:30 - 08:30) and evening (17:30 - 18:30) shift stampedes, the system maintains the following operational SLOs:

- **P95 Latency:** < 50ms (locally) / < 120ms (cloud edge)
- **Max Request Queue Backlog:** 512 connections (absorbed without drops)
- **Dispatcher Memory Leak Ceiling:** 500 records max in telemetry stream & audit buffer
- **Driver Mobile Resilience:** Screen Wake Lock active during trip, `localStorage` mirror updated on each step

---

## 6. INCIDENT RESPONSE & ESCALATION MATRIX

| Incident Level | Condition | Response Action | Escalation Target |
|---|---|---|---|
| **SEV-1 (CRITICAL)** | Tariff calculation mismatch, double-billing, or API outage | Roll back deployment, lock affected duty IDs, notify finance | Lead Systems Architect / SRE |
| **SEV-2 (HIGH)** | GPS telemetry drop > 10% during shift change | Verify Redis/connection pool queue, restart worker nodes | Platform Engineer |
| **SEV-3 (MEDIUM)** | Odometer variance holds exceeding 15 duties | Dispatcher manual audit queue review | Vendor Operations Lead |
