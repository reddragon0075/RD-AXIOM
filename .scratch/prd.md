




Technical PRD — Car Rental Operations Platform

 :root {
 --bg: #ffffff;
 --surface: #f8f9fa;
 --border: #e2e6ea;
 --text: #1a1d23;
 --muted: #6b7280;
 --accent: #1e40af;
 --accent-light: #dbeafe;
 --warn: #b45309;
 --warn-light: #fef3c7;
 --ok: #166534;
 --ok-light: #dcfce7;
 --red: #991b1b;
 --red-light: #fee2e2;
 --tag-p0: #dc2626;
 --tag-p1: #d97706;
 --tag-p2: #4b5563;
 --code-bg: #f1f5f9;
 }
 @media (prefers-color-scheme: dark) {
 :root:not([data-theme="light"]) {
 --bg: #0f172a;
 --surface: #1e293b;
 --border: #334155;
 --text: #e2e8f0;
 --muted: #94a3b8;
 --accent: #60a5fa;
 --accent-light: #1e3a5f;
 --warn: #fbbf24;
 --warn-light: #292524;
 --ok: #4ade80;
 --ok-light: #14532d;
 --red: #f87171;
 --red-light: #450a0a;
 --code-bg: #1e293b;
 }
 }
 \* { box-sizing: border-box; margin: 0; padding: 0; }
 html { scroll-behavior: smooth; }
 body {
 font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
 background: var(--bg);
 color: var(--text);
 font-size: 14px;
 line-height: 1.65;
 }
 .layout { display: flex; }
 nav {
 width: 260px;
 min-width: 260px;
 background: var(--surface);
 border-right: 1px solid var(--border);
 height: 100vh;
 position: sticky;
 top: 0;
 overflow-y: auto;
 padding: 24px 0;
 flex-shrink: 0;
 }
 nav .logo {
 padding: 0 20px 20px;
 font-size: 13px;
 font-weight: 700;
 color: var(--accent);
 border-bottom: 1px solid var(--border);
 margin-bottom: 12px;
 text-transform: uppercase;
 letter-spacing: 0.08em;
 }
 nav ul { list-style: none; }
 nav ul li a {
 display: block;
 padding: 5px 20px;
 font-size: 12.5px;
 color: var(--muted);
 text-decoration: none;
 border-left: 3px solid transparent;
 transition: all 0.15s;
 }
 nav ul li a:hover { color: var(--text); border-left-color: var(--accent); background: var(--accent-light); }
 nav ul li.section > a { font-weight: 600; color: var(--text); margin-top: 8px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; }
 nav ul li.sub > a { padding-left: 32px; font-size: 12px; }
 main {
 flex: 1;
 padding: 48px 60px;
 max-width: 1100px;
 overflow-x: hidden;
 }
 .cover {
 border: 1px solid var(--border);
 border-radius: 12px;
 padding: 40px;
 margin-bottom: 48px;
 background: var(--surface);
 }
 .cover h1 { font-size: 28px; font-weight: 800; color: var(--text); line-height: 1.2; margin-bottom: 8px; }
 .cover .subtitle { font-size: 15px; color: var(--muted); margin-bottom: 24px; }
 .meta-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
 .meta-item { padding: 12px 16px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; }
 .meta-item .label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; }
 .meta-item .value { font-size: 13px; font-weight: 600; color: var(--text); }
 .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
 .badge.p0 { background: var(--red-light); color: var(--red); }
 .badge.p1 { background: var(--warn-light); color: var(--warn); }
 .badge.p2 { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
 .badge.mvp { background: var(--ok-light); color: var(--ok); }
 .badge.v1 { background: var(--accent-light); color: var(--accent); }
 .badge.v2 { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
 .badge.new { background: #fef3c7; color: #92400e; }
 .badge.gap { background: #fee2e2; color: #7f1d1d; }
 h2 {
 font-size: 22px;
 font-weight: 700;
 color: var(--text);
 margin: 48px 0 16px;
 padding-bottom: 8px;
 border-bottom: 2px solid var(--border);
 }
 h3 { font-size: 17px; font-weight: 700; margin: 32px 0 12px; color: var(--text); }
 h4 { font-size: 14px; font-weight: 700; margin: 20px 0 8px; color: var(--text); }
 p { margin-bottom: 12px; }
 table {
 width: 100%;
 border-collapse: collapse;
 margin: 16px 0;
 font-size: 13px;
 }
 th {
 background: var(--surface);
 padding: 8px 12px;
 text-align: left;
 font-size: 11px;
 font-weight: 700;
 text-transform: uppercase;
 letter-spacing: 0.06em;
 color: var(--muted);
 border: 1px solid var(--border);
 }
 td {
 padding: 8px 12px;
 border: 1px solid var(--border);
 vertical-align: top;
 }
 tr:nth-child(even) td { background: var(--surface); }
 code {
 font-family: 'SF Mono', 'Fira Mono', monospace;
 font-size: 12px;
 background: var(--code-bg);
 padding: 2px 6px;
 border-radius: 4px;
 color: var(--accent);
 }
 pre {
 background: var(--code-bg);
 border: 1px solid var(--border);
 border-radius: 8px;
 padding: 16px;
 overflow-x: auto;
 font-size: 12px;
 line-height: 1.6;
 margin: 12px 0;
 }
 pre code { background: none; padding: 0; }
 .req {
 border: 1px solid var(--border);
 border-radius: 10px;
 margin: 16px 0;
 overflow: hidden;
 }
 .req-header {
 display: flex;
 align-items: flex-start;
 gap: 10px;
 padding: 14px 16px;
 background: var(--surface);
 border-bottom: 1px solid var(--border);
 flex-wrap: wrap;
 }
 .req-id { font-size: 12px; font-weight: 700; color: var(--accent); font-family: monospace; min-width: 72px; }
 .req-title { font-size: 14px; font-weight: 700; flex: 1; }
 .req-body { padding: 14px 16px; }
 .req-body p { margin-bottom: 8px; }
 .ac { background: var(--ok-light); border-left: 3px solid var(--ok); padding: 10px 14px; border-radius: 0 6px 6px 0; margin-top: 10px; font-size: 12.5px; }
 .tech-note { background: var(--accent-light); border-left: 3px solid var(--accent); padding: 10px 14px; border-radius: 0 6px 6px 0; margin-top: 10px; font-size: 12.5px; }
 .gap-note { background: var(--red-light); border-left: 3px solid var(--red); padding: 10px 14px; border-radius: 0 6px 6px 0; margin: 10px 0; font-size: 12.5px; }
 .warn-box { background: var(--warn-light); border-left: 3px solid var(--warn); padding: 12px 16px; border-radius: 0 6px 6px 0; margin: 16px 0; font-size: 13px; }
 .section-anchor { display: block; position: relative; top: -80px; visibility: hidden; }
 ul { padding-left: 20px; margin: 8px 0; }
 ul li { margin-bottom: 4px; }
 .arch-box { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 24px; margin: 16px 0; }
 .arch-box h4 { margin-top: 0; }
 .legacy-fleet-teardown { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px; padding: 20px 24px; margin: 16px 0; }
 .legacy-fleet-teardown h4 { color: #9a3412; margin-top: 0; }
 @media (max-width: 900px) {
 nav { display: none; }
 main { padding: 24px 20px; }
 .meta-grid { grid-template-columns: 1fr 1fr; }
 }






Technical PRD
* [Document Header](#s0)
* [1. Introduction](#s1)
* [1.1 Purpose](#s1-1)
* [1.2 Background & Competitor Analysis](#s1-2)
* [1.3 Product Goals](#s1-3)
* [1.4 Non-Goals](#s1-4)
* [2. System Architecture](#s2)
* [2.1 High-Level Architecture](#s2-1)
* [2.2 Technology Stack](#s2-2)
* [2.3 Infrastructure & Hosting](#s2-3)
* [2.4 Scaling Architecture](#s2-4)
* [2.5 API Design Principles](#s2-5)
* [3. Users & Personas](#s3)
* [4. Release Strategy](#s4)
* [5. Functional Requirements](#s5)
* [E1 Identity & Access](#e1)
* [E2 Masters & Pricing](#e2)
* [E3 Bookings & Duties](#e3)
* [E4 Duty Slip & Calc Engine](#e4)
* [E5 Billing, E-Invoice, Collections](#e5)
* [E6 Purchase & Fleet Cost](#e6)
* [E7 Corporate Module](#e7)
* [E8 Driver Mobile App](#e8)
* [E9 Passenger App](#e9)
* [E10 Tracking & Alerts](#e10)
* [E11 Communications](#e11)
* [E12 Reports & Analytics](#e12)
* [E13 Network & Settlements](#e13)
* [E14 Platform Admin Console](#e14)
* [E15 Offline & Resilience](#e15)
* [6. Key User Journeys](#s6)
* [7. Business Rules (Normative)](#s7)
* [8. UX / UI Requirements](#s8)
* [9. Non-Functional Requirements](#s9)
* [10. Data Model](#s10)
* [11. Integration Requirements](#s11)
* [12. Security, Privacy & Compliance](#s12)
* [13. Dependencies & Constraints](#s13)
* [14. Risks](#s14)
* [15. Acceptance & DoD](#s15)
* [16. Glossary](#s16)







# Car Rental Operations Platform


Technical Product Requirements Document

Document TypeTechnical PRD
StatusDraft for Engineering Review
ClassificationConfidential
Prepared byProduct Management
DateSeptember 2026
CompanionBusiness Requirements Document (BRD)



**Approvals Required Before Build**  

 Head of Product · Head of Engineering · Head of Design · Fleet Operations SME · Information Security / Compliance

**Conventions:** Functional requirements are numbered **FR-100…** grouped by epic. Priority: P0 = MVP must-have, P1 = V1, P2 = V2+. Each requirement ends with testable **Acceptance Criteria (AC)** and a **Technical Note (TN)** describing the implementation contract. Business rules in §7 are normative.




## 1. Introduction



### 1.1 Purpose


This Technical PRD specifies what the Car Rental Operations Platform must do and how it must be built: vendor (fleet) web console, corporate client web console, driver mobile app, passenger mobile app, and internal admin console — including architecture, data contracts, business rules, integrations, UX, and quality requirements. It is the authoritative build-to specification for design and engineering.



### 1.2 Background & Competitor Analysis (Legacy Rental Platform Teardown)


Legacy Rental Platform (Legacy Rental Platform Technology Services Pvt. Ltd, Mumbai) is the primary competitor in the Indian B2B fleet-operations SaaS segment. A systematic analysis of their published product surface reveals the following capabilities and structural gaps that this platform must address or exceed:



#### Legacy Rental Platform Product Surface — What They Ship




| Surface | App / Channel | Observed Capabilities | Known Weaknesses (from public reviews) |
| --- | --- | --- | --- |
| Fleet Web Console | app.legacyfleet.example.com | Duty allotment, driver notification, duty slip auto-creation (KM + time tracking), expense recording, fuel reports, digital signatures, customer management, invoicing, basic billing | No public API, no CSVbulk import documented, UI inconsistency flagged by users |
| Driver App (Legacy Rental Platform Go) | com.legacyfleet.app · 100K+ DL · 4.5★ | Push notifications on allotment, duty start/stop, auto KM+time tracking, expense input with photo receipts, fuel entry, digital signature capture | GPS lock failure on open areas, "stop duty" hang requiring cache clear (active July 2026), phone overheating reported on low-end devices, odometer photo re-upload loop (Aug 2026) |
| Corporate Passenger App | com.legacyfleet.app · 5K+ DL · 4.5★ | Booking requests, booking status, past trips + route history, supplier/driver contact | Very low adoption (5K vs 100K driver DLs), authentication issues ("daily issue making me late"), no self-service corporate policy controls visible |
| Indecall Dialer | com.legacyfleet.app · 10K+ DL · 3.9★ | Click-to-call from web platform to office phone, call log, duty activity log integration | Requires a separate app install for a basic click-to-dial; poor ratings (3.9); in-app purchases on a workflow tool; most reviews very old (2019–2022) |




#### Legacy Rental Platform Legacy Stack — Inferred Architectural Constraints


* **Monolithic web application:** Single web console for fleet operations. No evidence of micro-frontend or modular tenant architecture.
* **No offline-first driver app:** GPS failure on open areas + stop-duty hang requiring cache-clear are symptoms of a connected-only architecture that doesn't handle state transitions gracefully on reconnect.
* **Dialer as a separate app (Indecall):** A dedicated app just for click-to-call is a legacy integration pattern. It uses in-app purchases on a B2B workflow tool — an anti-pattern. This indicates masked telephony is not natively embedded in the core product.
* **Limited corporate module:** The corporate app has 5K downloads vs 100K for the driver app — a 20× gap. This signals their corporate module is underdeveloped or not actively sold.
* **No visible admin console:** No evidence of a multi-tenant SaaS admin panel; likely operated via direct DB queries or a basic internal tool.
* **Scaling limits:** No published SLA, no evidence of async processing for billing at scale, no public API / webhooks. Month-end billing peaks at enterprise fleet sizes (10K+ duties/month) are not addressed.
* **Data retention:** Corporate app data safety declaration: "Data can't be deleted" — a DPDP compliance gap that is a competitive and regulatory liability.
* **Telephony gap:** Indecall has in-app purchases and a 3.9 rating — indicating the feature is bolted-on and poorly received. No masked calling in core product.




**Key Differentiation Mandate:** This platform must ship with (1) a fully offline-capable driver app, (2) masked calling natively embedded — no separate app, (3) a corporate module designed for enterprise-scale (5K+ employee import, multi-level approvals, invoice verification), (4) a full multi-tenant admin console, (5) DPDP-compliant data erasure, and (6) async billing scale to 10K lines. These are not V2 features — they are baseline competitive requirements.


### 1.3 Product Goals


1. Any fleet operational within days via guided setup, templates, and bulk import.
2. Deterministic, explainable billing: every charge traceable to contract, measurement, and proof.
3. Field reliability: offline-tolerant driver app on Android and iOS on low-end devices.
4. Corporate transparency: live trips, verified invoices, enforced policy and SLA.
5. Enterprise trust: auditability, India data residency, DPDP privacy rights, SOC 2 path.
6. Operate the SaaS business from one admin console with full client, vendor, driver, cab, user, and payment visibility.



### 1.4 Non-Goals (this horizon)


Statutory payroll filing, vehicle-hardware sales, multi-country tax, consumer ride-hailing, in-house payment aggregation, reseller programme (deferred to V2).




## 2. System Architecture



### 2.1 High-Level Architecture




```

┌──────────────────────────────────────────────────────────────────────────┐
│                          CLIENT SURFACES                                 │
│  Vendor Web Console │ Corporate Web Console │ Admin Console (internal)  │
│  Driver App (iOS/Android)  │  Passenger App (iOS/Android)               │
│  Supplier Portal (web)  │  SMS Magic-Link (no-app close path)            │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │ HTTPS / WSS
┌────────────────────────────▼─────────────────────────────────────────────┐
│                         API GATEWAY / BFF LAYER                          │
│  Rate limiting · Auth token validation · Tenant context injection        │
│  Request routing · Response caching (CDN-eligible responses)             │
└─────┬──────────┬──────────────┬───────────────┬──────────────────────────┘
      │          │              │               │
┌─────▼──┐ ┌────▼────┐  ┌──────▼──────┐ ┌──────▼──────┐
│Identity│ │Booking/ │  │Billing/     │ │Tracking/    │
│& Auth  │ │Duty     │  │Invoice      │ │Alerts       │
│Service │ │Service  │  │Service      │ │Service      │
└─────┬──┘ └────┬────┘  └──────┬──────┘ └──────┬──────┘
      │         │              │               │
┌─────▼─────────▼──────────────▼───────────────▼──────────────────────────┐
│                        MESSAGE BUS (Event Streaming)                     │
│  duty.created · duty.started · duty.completed · invoice.issued           │
│  payment.received · alert.triggered · track.batch                        │
└──────────────────────────────────────────────────────────────────────────┘
      │         │              │               │
┌─────▼──┐ ┌────▼────┐  ┌──────▼──────┐ ┌──────▼──────┐
│ Primary│ │ Read    │  │  Object     │ │ Time-Series │
│  DB    │ │ Replica │  │  Store      │ │   Store     │
│(OLTP)  │ │(Reports)│  │(Files/Proof)│ │  (GPS pts)  │
└────────┘ └─────────┘  └─────────────┘ └─────────────┘

```



### 2.2 Technology Stack




| Layer | Chosen / Recommended | Rationale |
| --- | --- | --- |
| Web Frontend | React 18 + TypeScript, TanStack Query, Zustand, Vite | Component reuse across vendor/corporate/admin consoles; virtualised table (TanStack Virtual) |
| Mobile Apps | React Native (Expo managed) or Flutter — decision TBD by Q1 sprint-0 | Shared codebase for driver + passenger; offline-first via WatermelonDB / SQLite |
| API Layer | Node.js (NestJS) or Go — decision TBD by sprint-0 | NestJS for DX speed at MVP; Go for tracking ingest throughput; evaluate at sprint-0 |
| Primary Database | PostgreSQL 16 (RDS Multi-AZ, Mumbai) | Row-level security for tenant isolation; JSONB for flexible attributes; PITR support |
| Time-Series (GPS) | TimescaleDB or ClickHouse (read-heavy) | Hypertable partitioning by time + tenant for route query speed |
| Object Storage | AWS S3 (ap-south-1) | Evidence packs, invoice PDFs, odometer photos — presigned URL access |
| Cache / Session | Redis (ElastiCache, cluster mode) | Rate limiting, session store, idempotency keys, duty-state locks |
| Message Bus | AWS SQS + SNS (MVP); migrate to Kafka if throughput demands | SQS for async jobs (billing builds, e-invoice); SNS for fanout (alerts, push) |
| Push Notifications | FCM (Android) + APNs (iOS) via AWS Pinpoint or Firebase Admin SDK | Unified delivery with delivery receipts; quiet-hours enforcement |
| Maps | Google Maps Platform (server-side proxy + tenant quota) | Places API, Geocoding, Routes API; fallback evaluated to MapmyIndia for India |
| SMS / Voice | DLT-registered; primary: Kaleyra / Gupshup; fallback: Twilio / Exotel | Multi-provider failover with delivery log; provider abstraction layer |
| WhatsApp BSP | Gupshup or Interakt (approved BSP) | Template management + delivery receipts |
| Payment Gateway | Razorpay (primary) + Cashfree (fallback) | Idempotent webhook handling; UPI, NEFT, card, mandate for dunning |
| E-Invoice GSP | ClearTax GSP or Karvy GSP | IRN / QR / cancel; sandbox pre-prod test suite |
| Masked Telephony | Exotel Click-to-Call or Knowlarity (no separate app required) | Embedded in web/app via API; no Indecall-style separate dialer needed |
| Accounting Sync | Tally XML + Zoho Books REST API | V1; parties, invoices, receipts, notes |
| Secret Management | AWS Secrets Manager + Parameter Store | Rotation policies; no secrets in environment variables or code |
| Observability | OpenTelemetry → Grafana Cloud / Datadog; structured JSON logs; Sentry (mobile) | 100% services instrumented; PII/OTP redacted at log level |
| CI/CD | GitHub Actions → ECR → ECS Fargate (or EKS at V2 scale) | Feature-flag gated deployments; blue-green; rollback < 5 min |



### 2.3 Infrastructure & Hosting



#### Deployment Topology (India Data Residency Mandatory)


* **Primary Region:** AWS ap-south-1 (Mumbai) — all customer data plane.
* **DR Region:** AWS ap-south-2 (Hyderabad) — async replication; RTO ≤ 30 min, RPO ≤ 5 min.
* **CDN:** CloudFront with WAF — static assets, API response caching for public endpoints.
* **VPC:** Private subnets for all services; public subnets for ALB only; no direct DB exposure.
* **Compute:** ECS Fargate (stateless services), Lambda (event handlers, short jobs), RDS Multi-AZ (PostgreSQL).
* **Backups:** Daily automated snapshots + 30-day PITR; cross-region backup copy for DR.




### 2.4 Scaling Architecture




| Scenario | Baseline | Target Peak | Mechanism |
| --- | --- | --- | --- |
| Month-end billing | ~1K duties/day | 10K duties/day (10×) | Async invoice build via SQS worker pool; horizontal ECS scaling; no manual action required |
| GPS ingest | 100 concurrent drivers | 5K concurrent drivers | Dedicated ingest service; TimescaleDB bulk insert; Redis buffer; decouple from query path |
| Table rendering | 500 rows | 5,000 rows interactive | Virtualised scroll (TanStack Virtual); server-side pagination cursor; 50fps on reference device |
| Corporate employee import | 100 rows | 5,000 rows | Async CSV processor with row-level error report; <5 min for 5K rows |
| Tracking event visibility | — | p95 < 60s | WebSocket push from ingest service; fallback to 30s HTTP poll for poor-connectivity devices |



### 2.5 API Design Principles


* **REST + JSON** for all client-facing APIs; GraphQL evaluated for admin console V2 only if query fan-out becomes a problem.
* **Versioning:** URI-based versioning (`/v1/…`); version sunset policy published with 6-month notice.
* **Idempotency:** All mutating operations accept `Idempotency-Key` header; payment webhooks idempotent by design.
* **Pagination:** Cursor-based for all list endpoints; no offset-based pagination for large datasets.
* **Tenant isolation:** Tenant ID injected from JWT claims, never from request body; enforced at middleware layer before any resolver.
* **Rate limiting:** Per-tenant token bucket at API gateway; burst allowance for month-end ops.
* **Webhooks (V2):** HMAC-SHA256 signed; retry with exponential backoff; delivery log visible to tenant.




## 3. Users & Personas




| ID | Persona | Description | Primary Surface | Key Jobs |
| --- | --- | --- | --- | --- |
| U1 | Fleet Owner | Owns P&L | Vendor web | Margin per duty, collections, growth |
| U2 | Dispatcher | Daily coordination | Vendor web | Allot fast, handle exceptions |
| U3 | Billing Executive | Invoicing & dispatch | Vendor web | Same-day accurate bills |
| U4 | Driver | Executes duties | Driver app | Simple duties, correct payout |
| U5 | DCO Supplier | Driver + own vehicle | Driver app + supplier portal | Jobs, transparent settlement |
| U6 | Corporate Travel Admin | Policy + vendors | Corporate web | Compliance, SLA, vendor quality |
| U7 | Employee / Passenger | Books and rides | Passenger app | Book fast, ride safe |
| U8 | Corporate Finance | Verification + payables | Corporate web | Verified bills, forecasts |
| U9 | Associate Fleet | Overflow exchange | Vendor web — Network (V2) | Trusted duty exchange |
| U10 | Platform Admin | Operate the SaaS business | Admin console (internal) | Clients, vendors, drivers, cabs, users, subscriptions, payments, support, audit |




## 4. Release Strategy




| Phase | Timeline | Exit Gate | Key Deliverables |
| --- | --- | --- | --- |
| **MVP — "One Fleet Live"** | Months 1–3 | Pilot fleets run 100% of weekly duties and billing in-platform; ≥95% digital slips; invoice dispatch ≤24h of period close | Vendor console + driver app; E1–E6 (P0), E8, E10 core, E11 core, E12 standard, E14 core, E15 offline layer |
| **V1 — "Corporate Ready"** | Months 4–6 | Corporate client go-live; ≥70% invoice auto-accept; masked calling live; e-invoicing sandbox green | Corporate console + passenger app, OTP enforcement, live-share, e-invoicing, Tally/Zoho, purchase + duty P&L, payroll-lite, petty cash, feedback, permissions v2, masked calling (native, no separate app), SSO, full admin console |
| **V2 — "Automation Moat"** | Months 7–12 | AI allotment accuracy ≥85%; network onboarded with ≥3 associate fleets | AI allotment, anomaly detection, OCR, auto-collections/dunning, network + settlements, report builder, hardware-GPS ingest, public API/webhooks, white-label |




## 5. Functional Requirements




### E1 — Identity, Tenancy & Access Control




FR-101
Organisation Onboarding
P0MVP


The system shall provision a tenant company with branches, users, roles, numbering series, tax registrations, and company profile through a guided wizard with progress tracking and resumability.


**AC:** (1) New tenant completes wizard in ≤30 minutes with sample data optional; (2) all steps resumable after logout; (3) setup checklist persists on home until 100% complete.
**TN:** Tenant provisioned via a single `POST /tenants` API that atomically creates tenant record, default branch, owner-user, and default role assignments in a DB transaction. Wizard state persisted server-side (not localStorage). Onboarding checklist driven by a finite state machine with persisted completion flags per tenant.




FR-102
Authentication
P0MVP


The system shall support email+password, Google OIDC, and mobile-OTP login; TOTP-based 2FA shall be enforceable per role.


**AC:** (1) All three methods functional per policy; (2) 2FA cannot be bypassed by role; (3) brute-force lockout + alert after 5 failures; (4) Google OIDC redirect round-trip completes in <2s on 4G.
**TN:** Auth service issues short-lived access tokens (15-min JWT) + rotating refresh tokens (30-day, stored httpOnly cookie). OTP via SMS (DLT) with 6-digit code, 5-min expiry. TOTP via TOTP-compatible authenticator app (RFC 6238). Brute-force: Redis-backed counter per {email + IP}; lock at 5 failures, notify via email.




FR-103
Sessions & Devices
P0MVP


The system shall use short-lived access tokens with rotating refresh tokens, configurable idle timeout (default 30 min), device list, and remote revoke.


**AC:** (1) Idle timeout enforced ±60s; (2) refresh rotation invalidates reuse; (3) user can revoke any device from their profile.
**TN:** Refresh token family model: reuse of an old token in a family invalidates the entire family (theft detection). Device fingerprint = user-agent + device ID stored hashed. Remote revoke: DELETE /sessions/:id invalidates all tokens in that session's family. Driver app: device binding max 2 devices, self-release with 24h cooldown.




FR-104
Role-Based Access Control
P0MVP


The system shall enforce granular permissions (≥40 permission keys) across UI and API with deny-by-default; permissions enforced server-side on every request.


**AC:** (1) Permission matrix ≥40 keys enforced server-side; (2) unauthorised API calls return 403 and are audit-logged; (3) UI hides/disables unauthorised actions without client-side bypass.
**TN:** Permission matrix stored in DB per role; evaluated at request-handler middleware using a decorator pattern. UI: permission context provided via React context; components conditionally rendered but backend is the enforcement authority. Key permissions include: allot, force-close, price-edit, invoice-issue, supplier-manage-dco, supplier-manage-company, billing, payroll-approve, admin-impersonate. Audit log record on every 403.




FR-105
Audit Trail
P0MVP


The system shall record actor, action, entity, before/after values, timestamp, IP, and device for every mutation; retained immutably with billing-entity records for 7 years.


**AC:** (1) 100% of mutations produce audit rows in pilot; (2) audit rows have no update/delete code path; (3) per-entity history viewable in <2s for 90-day window.
**TN:** Audit log written to an append-only table with trigger-based row-hash chaining (SHA-256 of previous hash + current row). No foreign key cascades that could delete audit rows. Billing-entity audit rows flagged with `retention_class='financial'` and excluded from standard erasure policies. Separate read replica or columnar store for audit queries at scale.




FR-106
Corporate Linked Accounts
P1V1


The system shall link vendor tenants to corporate tenants via invitation with expiry, re-invite, and admin replacement.


**AC:** (1) Expired invites re-issuable; (2) admin replaceable without data loss; (3) link/unlink fully audited.
**TN:** Link stored as a TenantEdge record (vendor\_tenant\_id, corporate\_tenant\_id, status, invited\_by, accepted\_at). Invitation token: cryptographically random 32-byte hex, stored hashed, 7-day expiry. Re-invite invalidates previous token. Data shared across the edge: rate cards (selective), duty slips (read-only), invoice data.




### E2 — Vendor Masters & Pricing




FR-110
Core Masters
P0MVP


The system shall manage customers, suppliers (company/DCO), drivers, vehicles, duty types, vehicle groups, billing items, taxes, labels, branches, banks, and company profiles with active/inactive lifecycle and document/expiry tracking.


**AC:** (1) CRUD + bulk CSV import with dry-run error report; (2) duplicate detection on phone/registration/GSTIN; (3) deactivation blocked where open duties reference the record.
**TN:** All master entities implement soft-delete with `deleted_at` timestamp. Bulk import: CSV streamed through a validation pipeline; dry-run returns row-level errors without DB writes; wet-run uses DB transaction with rollback on fatal errors. Duplicate detection: exact match on normalised phone (E.164), registration number (uppercased, trimmed), GSTIN (15-char exact).




FR-111
Duty Types
P0MVP


Duty types shall support package km/hours (0.5-hour steps), extra rates, extra modes (sum / higher-of), minimum billing, grace, night windows, day-count rules, fixed-window (FGR) mode, and garage-billing toggles.


**AC:** (1) 0.5-hour packages compute without rounding errors (paise-exact); (2) FGR and higher-of modes covered by in-app worked examples; (3) changes versioned with effective date.
**TN:** All money stored as integer paise (int64). 0.5-hour step: stored as integer half-hours to avoid float arithmetic. Duty type versioned via event-sourced snapshot table; allotment always resolves the version effective on duty date. Calculation engine is a pure function: `calculateDuty(inputs, dutyType, priceBook) → breakdown` — tested with 1,000-case golden suite.




FR-112
Price Books
P0MVP


Pricing versioned by customer × city × duty type × vehicle group with effective dating, bulk clone, and CSV export/import with validation.


**AC:** (1) Overlapping effective dates rejected; (2) clone of 500 rows <30s with error report; (3) duty always prices from version effective on duty date.
**TN:** PriceBook table: (tenant\_id, customer\_id, city\_id, duty\_type\_id, vehicle\_group\_id, effective\_from, effective\_to, rates JSONB). Overlap check: DB constraint using exclusion constraint with daterange type. Clone: server-side bulk INSERT with new effective\_from; runs async for >100 rows.




FR-113
Unpriced-Combination Guard
P0MVP


Booking/duty creation for combinations without effective pricing shall be blocked by default, bypassable only by explicit permission with mandatory reason, fully logged.


**AC:** (1) Block triggers with message naming the missing combination; (2) bypass requires reason ≥10 chars; (3) bypass logged and appears in daily exception digest.
**TN:** Pricing lookup is part of booking creation validation pipeline. If no matching PriceBook row for (customer, city, duty\_type, vehicle\_group, duty\_date), return HTTP 422 with error code `UNPRICED_COMBINATION`. Bypass: if actor has `booking.create.unpriced_override` permission and provides reason, create booking with `price_override=true` flag and audit log entry.




FR-114
Allowances & Billing Items
P0MVP


System shall support chargeable-to-customer vs payable-to-driver allowance splits and billing items with taxable, driver-addable, mandatory, customer-exclusion, and active flags.


**AC:** (1) Mandatory items enforced identically on dashboard, app, SMS-link, and import paths; (2) missing items listed by name in error; (3) excluded items never appear on customer invoice.
**TN:** Billing item enforcement is applied in the shared close-duty service (not at client level). Mandatory items: if not present in submitted slip, return 422 with missing item names. Customer-excluded items: filtered server-side before invoice line generation — never pass to invoice template.




FR-115
Document-Expiry Policy
P0MVP


Documents (licence, RC, insurance, PUC, permit, fitness, police verification) shall carry expiries with T-30/7/1 alerts and per-class allotment policy (hard block / soft warn).


**AC:** (1) Alerts fire on schedule; (2) hard block prevents allotment, names the document; (3) overrides logged with reason.
**TN:** Document table: (entity\_type, entity\_id, doc\_class, expiry\_date, file\_key, status). Scheduled job (daily 06:00 IST) computes T-30/7/1 alerts and inserts into the notification queue. Allotment check: JOIN to active documents; if any hard-block document class is expired for the driver or vehicle, return 422 with document name. Policy configuration (hard/soft) per document class stored in tenant settings.




FR-116
Templates & Cloning
P0MVP


System shall ship starter templates (airport 4h/40km, 8h/80km, outstation per-km, monthly) and one-click copy of duty types, price books, and invoice presentation across customers.


**AC:** (1) New tenant starts from templates without blank-slate setup; (2) clone preserves rates and effective dates; (3) template library versioned.
**TN:** Starter templates stored as seed data in platform config (not per-tenant). On wizard completion, tenant can select templates to apply — a bulk insert into their duty\_types and price\_books. Template versioning: templates carry a `template_version` tag; tenant templates track which version they derived from.




### E3 — Bookings & Duties




FR-120
Booking Capture
P0MVP


Bookings shall capture customer, booker, passengers, city, duty type, vehicle group, reporting datetime/address (geocoded), drop, references (PO/cost-centre), labels, instructions, and source channel.


**AC:** (1) Address autocomplete with map pin confirm; (2) duplicate/similar booking warning (same passenger + overlapping window); (3) all sources land in one inbox with source badge.
**TN:** Address geocoding: server-side proxy to Google Places + Geocoding APIs; results cached per (tenant, address\_text, precision=6dp) to control API costs. Duplicate detection: query for bookings with same passenger\_id + overlapping [reporting\_at, reporting\_at + estimated\_duration] window; return as warning, not block. Source channels tracked: DASHBOARD, MOBILE, SMS\_LINK, CSV\_IMPORT, API, CORPORATE\_APP.




FR-121
Booking Lifecycle
P0MVP


Bookings/duties follow: Draft → Unconfirmed → Confirmed → Unallotted → Allotted → Dispatched → In-Progress → Completed → Billed, with Cancelled/No-Show branches, SLA timers, and guard conditions per transition.


**AC:** (1) Illegal transitions rejected server-side; (2) every transition timestamped + attributed; (3) cancel/no-show requires reason and evaluates charge rules.
**TN:** State machine implemented as a service with explicit allowed transitions map. Transition events published to message bus (duty.status\_changed). SLA timers: each status has a configurable SLA threshold stored in tenant settings; breach emits a duty.sla\_breached event consumed by the alerts service. All transitions append to a duty\_timeline table (duty\_id, from\_status, to\_status, actor\_id, reason, timestamp).




FR-122
Duties Board
P0MVP


Kanban + table views with filters, saved views, virtualised scrolling (5,000+ rows), bulk select actions, and command search.


**AC:** (1) 5,000-row roster renders and scrolls at ≥50fps on reference hardware; (2) bulk allot of 100 duties completes <60s with per-row results; (3) views shareable per role.
**TN:** Table: cursor-paginated API endpoint returning 50 rows at a time; client-side virtualised scroll (TanStack Virtual) renders only visible rows. Bulk allot: async job via SQS; client polls job status and receives per-row success/failure JSON. Saved views: serialised as (tenant\_id, user\_id, name, filter\_json, column\_json) — shareable by generating a view\_token.




FR-123
Attention Queue
P0MVP


System shall surface prioritised exceptions: unallotted <120 min, dispatched-not-started +20 min, tracking silence >45 min, driver far from pickup at T-30, expired docs, missing price, SLA-breach risk.


**AC:** (1) Each rule configurable (threshold, channel, quiet hours); (2) queue shows owner + due + one-click action; (3) digest batching + snooze to prevent alert fatigue.
**TN:** Alert rules evaluated by a scheduled processor (runs every 5 min) and by event-triggered handlers (e.g., tracking silence detected by ingest service). Alerts stored in an alerts table with status (open/snoozed/resolved). One-click actions: deep links back to the relevant duty/driver record. Digest: alerts within the same snooze window batched into one notification.




FR-124
Allotment
P0MVP


Allotment assigns exactly one active driver+vehicle or supplier per duty (temporary holds flagged and expirable), showing availability, live location, and compliance state; re-allotment preserves history.


**AC:** (1) Double-allotment impossible via unique active constraint; (2) expired holds auto-release with notice; (3) every allot/change diffed in history.
**TN:** Allotment: DB unique constraint on (driver\_id, active=true) within a duty's time window. Temporary hold: `hold_until` timestamp; a scheduled job (runs every 2 min) releases expired holds and emits duty.hold\_expired event. Allotment history: append-only allotment\_history table. Availability shown by querying active allotments for the duty window.




FR-125
Availability Roster
P0MVP


Shared driver/vehicle day/week roster with blocks, leaves, and maintenance holds that allotment respects.


**AC:** (1) Blocks prevent allotment with explanation; (2) roster supports 500+ resources; (3) changes propagate to open-duty warnings.
**TN:** Roster stored as availability\_blocks (entity\_type, entity\_id, block\_type, starts\_at, ends\_at, reason). Allotment check includes a join to availability\_blocks. Change propagation: when a block is created, query open allotments in that window and emit duty.availability\_conflict event for the attention queue.




FR-126
Import & Intake
P0MVP


Bookings importable via CSV and email-forward parsing with field mapping, dry-run validation, and error quarantine.


**AC:** (1) 1,000-row CSV imports <2 min with row-level errors; (2) quarantined rows fixable inline; (3) import jobs idempotent on retry.
**TN:** Import job: CSV uploaded to S3, SQS message triggers worker. Worker processes rows in batches of 50; row-level errors stored in import\_job\_errors table. Idempotency: each row carries a hash of its content; duplicate hashes within an import job are skipped. Email-forward: inbound email parsed via SendGrid Inbound Parse or AWS SES; field mapping configured per email sender.




### E4 — Duty Slip & Calculation Engine




FR-130
Convergent Close Paths
P0MVP


Dashboard-manual, driver-app, SMS magic-link, and network-import closes shall execute a single close service with identical validation, calculation, and versioning.


**AC:** (1) Same inputs on all paths produce identical totals (verified by test matrix); (2) magic links single-duty, expiring ≤72h, revocable; (3) network slips accepted read-only until confirmed.
**TN:** Single `DutyCloseService` called from all entry points. Magic link: signed JWT with duty\_id and exp=72h; revocable via blocklist in Redis. Network slips: status=PENDING\_CONFIRMATION until vendor explicitly confirms, preventing premature billing.




FR-131
Deterministic Calculation
P0MVP


Closing shall compute totals per §7 business rules from effective-dated pricing, with a line-by-line explainable breakdown shown before submit.


**AC:** (1) Preview shows "customer will be billed ₹X" with expandable math; (2) 1,000-case golden calculation suite passes; (3) parallel-run vs pilot history within 0.5%.
**TN:** Calculation engine: pure TypeScript/Go function with no side effects. Inputs: start/end datetime, start/end odometer, garage events, duty\_type\_snapshot (frozen at allotment date), price\_book\_snapshot (frozen at duty date). Output: CalculationResult with line\_items[], subtotal, tax\_lines[], total (all int64 paise). Golden suite: 1,000 JSON test cases covering all edge combinations, run in CI on every PR.




FR-132
Evidence Pack
P0MVP


Each slip version shall pin map snapshot, route log, OTP events, signature, odometer/expense photos, and scanned slips; attachments print/download inline with the slip.


**AC:** (1) Single PDF contains slip + attachments in order; (2) missing mandatory proofs block close; (3) evidence immutable per version.
**TN:** Evidence files stored in S3; references stored as slip\_evidence (slip\_version\_id, evidence\_type, s3\_key, uploaded\_at, uploaded\_by). Immutability: S3 object lock (compliance mode) on finalized slip versions. PDF assembly: server-side PDF generation (PDFKit or Puppeteer) combining slip data and evidence file pre-signed URLs. Evidence required per duty type configurable (mandatory list per duty\_type).




FR-133
Auto-Switch & FGR
P0MVP


Optional auto-switch of duty type to best-fit package (logged) and fixed-window (FGR) billing supported per customer/duty-type.


**AC:** (1) Switch shows delta before confirm (or auto per policy + post-hoc notice); (2) FGR bills fixed window while recording actuals for audit.
**TN:** Auto-switch: calculation engine computes billing for all applicable packages and returns the cheapest (or most appropriate per policy). Switch logged with before/after duty\_type\_id and billing delta. FGR: `billing_mode=FIXED_WINDOW`; actual KM/time recorded in actuals\_km, actuals\_hr columns but billing uses fixed\_km, fixed\_hr from duty type configuration.




FR-134
Supervisor Correction
P0MVP


Force-close and post-completion edits require permission + reason, create new versions, and notify affected parties.


**AC:** (1) No silent-edit path exists; (2) version diff viewable; (3) customer-visible documents regenerate from latest confirmed version only.
**TN:** DutySlip versioned: slip\_versions table (slip\_id, version, data JSONB, created\_by, reason, created\_at). Current version tracked via slip.current\_version\_id. Invoice PDFs generated from current slip version on demand; cached version invalidated on new slip version. Diff: JSON diff between version N-1 and version N stored in slip\_version\_diff table.




### E5 — Billing, E-Invoicing, Receipts & Collections




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-140 | Invoice builder — single, consolidated (≤10K lines), proforma; async build with progress notification | P0 MVP | Async SQS worker; progress via WebSocket; invoice lines streamed to temp table then atomically committed. Immutable on issue; credit/debit note workflow for corrections. |
| FR-141 | Tax / entity selection (CGST/SGST vs IGST by state of supply), letterheads, tamper seal | P0 MVP | State-of-supply logic: compare vendor GSTIN state vs customer billing address state. Tamper seal: HMAC of invoice data embedded in PDF metadata; broken on any post-issue modification attempt. |
| FR-142 | Dispatch via email/WhatsApp/link; delivery tracking; rejection intake | P0 MVP | Dispatch events stored in invoice\_dispatch\_log. Rejection: structured intake form (reason enum + free text); routes to billing queue as dispute record. |
| FR-143 | GST-linked credit/debit notes referencing original invoice | P0 MVP | Note cannot exceed original line values without explicit maker-checker approval. Linkage: foreign key to original invoice; GST recomputed from scratch on note. |
| FR-144 | Receipts + allocation (advance, on-account, against-invoice); FIFO-auto or manual; bulk bank-statement matching | P0 MVP | Double-allocation prevented by DB unique constraint on (receipt\_id, invoice\_id). Statement matching: fuzzy amount + date match, presented as suggestions requiring human confirm. |
| FR-145 | Payment links with expiry/reminders; gateway checkout (primary + fallback); idempotent webhooks; auto-receipt | P0 MVP | Idempotency: gateway webhook processed once via Redis SET NX on payment reference. Receipt created in transaction with payment confirmation. |
| FR-146 | E-invoicing: IRN/QR generation, cancellation within statutory window, error surfacing | P1 V1 | GSP integration via async queue; IRN stored on invoice record; cancelled IRNs cannot be reprinted without new IRN. Sandbox daily regression suite. |
| FR-147 | Tally XML + Zoho Books API sync for parties, invoices, receipts, notes | P1 V1 | Sync state machine per record: PENDING → SYNCED / FAILED. Retry with exponential backoff. Conflict resolution: manual override via mapping UI. |
| FR-148 | Dunning and auto-collect: card mandate, pre-debit notices, smart retries | P2 V2 | NACH mandate via Razorpay; pre-debit notice 3 days prior per RBI guidelines; retry schedule: T+1, T+4, T+7. |




### E6 — Purchase, Supplier & Fleet Cost




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-150 | Purchase duties board: estimated revenue vs supplier cost vs margin; supplier invoice intake | P1 V1 | Margin computed as (sale\_price - purchase\_price) / sale\_price; stored denormalised for board performance; recalculated on slip or price change event. |
| FR-151 | Three-way match: executed slip vs supplier bill vs our sale; tolerance-based auto-accept; payables aging | P1 V1 | Tolerance configurable per customer/supplier. Match status: AUTO\_ACCEPTED, MANUAL\_REVIEW, BLOCKED. Payables aging: computed from supplier\_invoice.due\_date; buckets: current, 0–30, 31–60, 61–90, 90+ days. |
| FR-152 | Supplier portal: view allotted/completed duties, upload slips/invoices, track payment status | P1 V1 | Separate portal subdomain; scoped JWT; supplier sees only tenant-scoped duties where they are the assigned supplier. File uploads: virus scan via ClamAV before processing. |
| FR-153 | Driver payroll-lite: per-duty earnings + salary + advances + deductions → payout sheets | P1 V1 | Payout sheet: aggregate of duty\_earnings + salary\_components - deductions. Approval chain: configurable multi-level approval before payment. Advance recovery: rule engine per driver contract. |
| FR-154 | Petty cash + vehicle costing: digital cash book, fuel/expense/EMI, mileage, per-vehicle P&L | P1 V1 | Cash book: double-entry ledger model (debit/credit). Vehicle P&L: allocate duty earnings to vehicle; subtract fuel, maintenance, EMI entries. Fuel entries support photo proof stored in S3. |
| FR-155 | Feedback: custom forms auto-sent on completion, ratings dashboard, issue routing | P1 V1 | Form trigger: duty.completed event → delayed message (configurable delay). Low-score threshold configurable; breach triggers alert to fleet owner. |




### E7 — Corporate Module




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-160 | Corporate structure: regions, cost centres, designation profiles, employees (CSV/HRMS import), booker/passenger/approver separation | P1 V1 | HRMS import via SFTP or REST webhook (configurable per corporate). 5K-employee async import with row-level errors. Self-registration closed by default; invite-only or allowlist domain. |
| FR-161 | Booking policy: profile-based entitlements enforced inline at request time | P1 V1 | Policy engine: rule tree evaluated at booking creation time. Out-of-policy result: BLOCKED or ESCALATE\_FOR\_APPROVAL per rule. Policy explanation stored on booking for transparency. |
| FR-162 | Approvals: multi-level chains, amount thresholds, auto-approve, delegation, SLA timers, nudges, escalation | P1 V1 | Approval chain: DAG of approval nodes (any/all). SLA timer per node; on breach: escalate to next node or auto-approve per policy. Delegation: time-bounded, revocable; auto-revoke on expiry. |
| FR-163 | Vendor management: rule-based allocation, scorecards from SLA/acceptance/rating/incident data | P1 V1 | Allocation rules evaluated in priority order: rate rank, zone match, score threshold, round-robin. Score: weighted composite recomputed daily by scheduled job. Explainer: allocation decision stored with rule-evaluation trace. |
| FR-164 | Corporate trip board: live view across vendors, tracking, proofs, OTP evidence, SLA state | P1 V1 | Read-only view across corporate's linked vendor tenants. Live tracking via WebSocket subscription to tracking events filtered by corporate's trips. SLA breach flags propagated from vendor's duty state machine. |
| FR-165 | Invoice verification: auto-verification vs contract rates, KM/time tolerances, duplicate detection, proof completeness | P1 V1 | Verification engine: rule-based checker producing verdict (AUTO\_ACCEPT / REVIEW / AUTO\_FLAG) with rule citations. Target: ≥70% auto-accept in pilot with zero false-accepts. Tolerances configurable per vendor. |
| FR-166 | Payables, budgets, forecasts, emissions summary | P1 V1 | Budget burn: real-time running total vs budget per cost centre. Forecast: rolling 90-day average of actuals. Emissions: kg CO₂ per KM factor table (source: MoEFCC); versioned and cited in UI. |
| FR-167 | Cancellation and no-show: per-duty-type cutoff, charge matrices, driver wait evidence | P1 V1 | Late-cancel charge computed from cutoff matrix. No-show: requires driver to upload wait log + photo; if missing, no-show charge blocked. Employee notified of charge with reason before application. |




### E8 — Driver Mobile App




FR-170
Access & Onboarding
P0MVP


Mobile-OTP login with device binding (max 2), language picker (8 languages), permission coach, OEM battery-exemption guide, and practice duty.


**AC:** (1) First-time login completes within 3 min; (2) language selection persists across reinstalls; (3) battery exemption guide covers top 10 OEM skins by India market share.
**TN:** Language preference stored server-side (not device-only) so it persists on reinstall. Battery exemption guide: deep-link to OEM settings where possible (Xiaomi, Samsung, Realme, Vivo, Oppo, OnePlus, Motorola, Nokia); fallback to illustrated step-by-step. Practice duty: sandbox duty that exercises all app flows without affecting production data.




FR-171
Duty List & Detail
P0MVP


Duty list with upcoming/active/completed sections; duty detail with all booking information, address deep-links, and pre-fetched for offline access.


**AC:** (1) Duty detail available offline within 30 min of allotment; (2) address taps open Maps navigation; (3) list refresh on push notification.
**TN:** Offline: duty details pre-fetched and stored in WatermelonDB (SQLite) on allotment push notification. Address deep-link: `geo:` URI for Maps navigation. Push-triggered refresh: FCM data message triggers a background sync without requiring user interaction.




FR-172
Start Duty
P0MVP


Start duty captures reporting location (GPS), odometer (manual + optional photo), reporting OTP (V1), and initiates background tracking.


**AC:** (1) Start confirmed to server or queued for sync within 5s of tap; (2) GPS accuracy <50m required or warned; (3) tracking initiated even if confirmation is delayed by poor connectivity.
**TN:** Offline-first: start event written to local WatermelonDB immediately; background sync queue retries until acknowledged by server. GPS: minimum accuracy threshold configurable; accuracy and battery level stored with each point. Tracking: background location service using platform APIs (Foreground Service on Android, Background Location on iOS); foreground notification persistent while duty is active — this directly addresses Legacy Rental Platform Go's GPS failure mode.




FR-173
In-Duty Tracking & Expenses
P0MVP


Background GPS batching (configurable interval: 30s default), expense add (toll/parking/other + photo), fuel entry, and connectivity-resilient sync.


**AC:** (1) GPS points queued locally during offline periods and synced with gap annotation on reconnect; (2) expense photos uploaded async without blocking duty flow; (3) no fabricated points (interpolated points marked).
**TN:** GPS batch: local SQLite buffer; flush when ≥10 points or 60s elapsed or connectivity restored. Gap annotation: if gap between last known point and reconnect point >5 min, both endpoints tagged with gap\_type='connectivity'. Photo upload: separate upload queue; slip close not blocked by pending photo uploads but uploads must complete before slip is finalised. Interpolated points marked with `source='interpolated'` — direct fix for Legacy Rental Platform Go's GPS accuracy issue.




FR-174
Stop Duty
P0MVP


Stop duty captures drop location (GPS), odometer, end OTP (V1), digital signature, and presents calculation preview before final submit.


**AC:** (1) Stop available offline and syncs on reconnect without hang; (2) calculation preview shown before submit; (3) final submit idempotent (retry safe).
**TN:** Stop duty: event written locally first; server submission with idempotency key = duty\_id + 'stop'. Retry logic: exponential backoff, max 5 retries, then escalate to attention queue. This directly addresses Legacy Rental Platform Go's "stop duty hang requiring cache clear" bug — state is never dependent on a synchronous server response before the local state transition. Calculation preview: computed locally from cached duty type + price book (synced at allotment); server validates and may adjust on submission.




FR-175–FR-182
SOS, Live Share, OTP, Post-Trip (Summary)
P1V1




| FR | Feature | Technical Note |
| --- | --- | --- |
| FR-175 | OTP start/stop: passenger-delivered codes; supervisor override | OTP: 6-digit, 10-min expiry, max 3 resends, 5-min resend cooldown. Override: permission-gated, requires reason + evidence note. OTP events stored in duty\_otp\_events. |
| FR-176 | SOS: single-tap distress; 3-channel delivery (push + SMS + WhatsApp) to configured contacts | SOS always visible as FAB during active duty. Delivery via 3 parallel channels; delivery receipts stored. SOS button non-dismissable during active trip. |
| FR-177 | Live share: tokenised link with expiry, revoke, view count | Token: 32-byte random, stored hashed, 24h expiry default. Revoke: Redis blocklist, effective in <5s. View count: Redis INCR on each access. |
| FR-178 | Masked calling: click-to-call from app; no separate dialer app required | Native SDK integration (Exotel/Knowlarity) — no separate app install, directly addressing Legacy Rental Platform's Indecall anti-pattern. Call log stored on duty timeline. Recording retention per policy. |
| FR-182 | Post-trip: history, slips, approve/reject with reason, rating with issue tags | Rating prompt: sent via push 10 min after duty completion, respects quiet hours (22:00–07:00 IST). |






### E9 — Passenger App Gap-Filled


**GAP IDENTIFIED:** The original PRD referenced the passenger app (U7) in personas and release strategy but had no dedicated epic with FRs. The corporate app is Legacy Rental Platform's weakest surface (5K downloads, auth failures). This is a major competitive opportunity — addressed here.


FR-185
Passenger Authentication & Onboarding
P1V1


Company-email-based authentication via corporate SSO (OIDC/SAML) or invite-code login; no manual registration without company admin action.


**AC:** (1) SSO login completes <5s round-trip; (2) invite-code auth works without SSO; (3) unauthenticated users see clear "contact your admin" message, not a blank error.
**TN:** SSO via OIDC: redirect flow; token exchanged for platform JWT. Invite-code: 8-char alphanumeric, single-use, 48h expiry, sent to corporate email. This fixes Legacy Rental Platform Corporate's "daily login failure" issue by supporting SSO as primary auth rather than username/password only.




FR-186
Booking Request
P1V1


Employee can request a ride with pickup/drop, date/time, purpose, cost centre — inline policy check and approval routing without leaving the app.


**AC:** (1) Booking submitted in ≤3 taps from home screen; (2) policy result shown inline before submission; (3) approval status visible with timeline.
**TN:** Policy check: synchronous call to corporate policy engine at submission time. Approval: WebSocket subscription to approval\_events for real-time status. Push notification on approval/rejection.




FR-187
Trip Tracking & Safety
P1V1


Live driver tracking, OTP delivery to passenger for start/stop, emergency SOS, share-with-family link.


**AC:** (1) Driver location visible within 60s of duty start; (2) OTP generation and display on passenger app; (3) share link sends via native share sheet.
**TN:** Tracking: passenger app subscribes to a tokenised WebSocket channel for the duty's tracking events. OTP: generated server-side, pushed to passenger app via FCM, never stored in client-readable storage beyond display.




FR-188
Trip History & Ratings
P1V1


Past trips with route history, slip preview, cost centre charge confirmation, and post-trip rating with issue tags.


**AC:** (1) Route history viewable on a map for each trip; (2) rating submitted within 10 min of prompt; (3) cost centre charge visible on trip detail.
**TN:** Route history: rendered from trip's track\_points stored in TimescaleDB; passenger-visible route uses address-enriched waypoints only (not raw GPS). Slip preview: PDF served via pre-signed S3 URL, 1h expiry.




### E10 — Tracking & Alerts




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-190 | Ingest and reconstruction: gap-tolerant route reconstruction, health states | P0 MVP | Ingest service: dedicated microservice accepting batch POST of GPS points. Bulk insert to TimescaleDB hypertable (tenant\_id, duty\_id, recorded\_at). Gap detection: any interval >5 min between consecutive points flagged. Reconstruction: straight-line interpolation marked as synthetic. Health states: LIVE (last point <2 min), PAUSED (2–10 min), GAP (>10 min). |
| FR-191 | Live share: tokenised links, expiry, revoke, view count | P1 V1 | See FR-177 for token mechanics. Shared link renders a lightweight web page (no app required) with auto-refreshing map. View count via Redis INCR, forwarding risk notice shown on first view. |
| FR-192 | Alert rules: stoppage, overspeed, idle-billing risk, geo-fence, silence gap | P1 V1 | Rules evaluated by ingest service stream processor. Geo-fence: polygon stored as PostGIS geometry; ST\_Contains check per point. Alert lifecycle: open → acknowledged → resolved. False-positive tuning: precision/recall dashboard per rule per tenant. |
| FR-193 | Route logs: address-enriched with server-side place caching | P1 V1 | Reverse geocoding via Google Geocoding API; results cached in Redis (key: lat\_lon\_rounded\_4dp) with 30-day TTL. Toggle per customer. Target: ≥60% cache hit rate in steady state. |
| FR-194 | Hardware GPS ingest: third-party device feeds stitched with app tracks | P2 V2 | Documented ingest protocol (REST + MQTT options). Source tagged per point (APP / HARDWARE). Duplicate point deduplication within 5s window. Device health monitoring via heartbeat events. |




### E11 — Communications & Telephony




FR-200
Template Studio
P0MVP


SMS/email/WhatsApp templates with namespaced variables, linting, preview, per-customer overrides, and per-event channel matrix with toggles.


**AC:** (1) Unknown variables fail validation with suggestion; (2) test-send to seed numbers; (3) every automated send has an off switch.
**TN:** Template variables: `{{namespace.field}}` syntax; linted at save time against known variable registry. WhatsApp: approved BSP templates stored with template\_id; variable substitution only in approved variable positions. Each event type has a channel\_config (SMS: on/off, WhatsApp: on/off, email: on/off, push: on/off) per tenant, overridable per customer.




FR-201
Delivery & Compliance
P0MVP


Provider failover, delivery log, DLT sender/template onboarding tracker; brand masking included in plan (no add-on).


**AC:** (1) Failover on provider error <60s; (2) 30-day delivery rate ≥97%; (3) brand masking never paywalled.
**TN:** Provider abstraction layer: `SmsProvider` interface with Kaleyra and Gupshup implementations; failover via circuit breaker (5 failures in 30s triggers switch). Delivery log: message\_events table (message\_id, provider, status, delivered\_at, error\_code). DLT tracker: manage DLT header IDs and template registration status per provider in platform config.




FR-202
Masked Calling (Native — No Separate App)
P1V1
Competitive Gap vs Legacy Rental Platform


Click-to-call with number masking, consent + recording disclosure, and call entries on the duty timeline. No separate dialer app required.


**AC:** (1) Real numbers never exposed to counterparties; (2) unanswered-call retries logged; (3) recordings retained per policy with access control; (4) no app install required beyond core platform apps.
**TN:** Integration via Exotel or Knowlarity API (not Legacy Rental Platform's "install a separate app" pattern). Web console: click-to-call button triggers API call that bridges the two parties. Driver app: in-app call via SDK bridge. Call events stored in duty\_call\_log (duty\_id, caller\_type, callee\_type, duration, recording\_key, timestamp). Recording: S3 storage, access restricted to supervisor+ roles, 90-day retention default.




### E12 — Reports & Analytics




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-210 | Standard reports: roster, sales, collections/aging, driver, vehicle, duty P&L, SLA exceptions | P0 MVP | Reports run against read replica to prevent OLTP impact. 100K-row CSV export: async job, S3 presigned URL delivered via in-app notification + email. Every number drills to source rows via filter preset. |
| FR-211 | Custom exports: saved column sets, filter presets, permission-aware rows | P0 MVP | Column selection stored per user/view. Permission-aware: row-level security enforced at DB query level, not filtered post-query. Async export: jobs queued in SQS, completed files available for 7 days. |
| FR-212 | Report builder: drag-and-drop, saved views, scheduled distribution | P2 V2 | Queries time-boxed at 30s; background execution for longer queries with progress notification. Certified vs ad-hoc labelling for governance. Scheduler: cron expression stored per report; executed by job processor. |




### E13 — Network & Settlements (V2)




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-220 | Associate graph: directory, invite/accept, selective rate-card sharing, duty push with bid/accept, real-time slip sync | P2 V2 | Associate graph: network\_edges table (from\_tenant, to\_tenant, trust\_level, cities, active). Duty push: separate duty\_offer record; bid/accept state machine. Shared data minimised to need-to-know (rate cards: only shared duty types; slip: read-only view). |
| FR-221 | Trust and settlement: trust scores, settlement ledger, evidence-locked disputes | P2 V2 | Trust score: composite of completion\_rate × acceptance\_rate × payment\_timeliness × rating\_avg. Formula published in UI. Disputes: freeze only the disputed duty's settlement amount; rest of settlement proceeds. Settlement statements exportable as CSV/PDF. |




### E14 — Platform Admin Console




FR-230
Admin Access & Staff RBAC
P0MVP


Separate admin console with SSO-enforced staff login, internal roles, deny-by-default permissions, and maker-checker on money/status actions.


**AC:** (1) Staff SSO mandatory; no shared accounts; (2) maker-checker enforced on refunds, credits, suspension, plan overrides; (3) every admin action attributed in audit with ticket reference.
**TN:** Admin console: separate React app on admin.{domain}; separate JWT issuer with admin\_role claims. No cross-contamination with tenant tokens. Maker-checker: pending\_actions table; checker must be a different authenticated user with appropriate role. Impersonation: requires open support ticket ID, logged with full session actions, bannered to impersonator in every page header.




| FR | Requirement | Priority | Key Technical Note |
| --- | --- | --- | --- |
| FR-231 | Admin dashboard: platform KPIs with drill-down | P0 MVP | KPIs computed from materialised views refreshed every 5 min. Finance vs support views permission-scoped at view level. Every KPI tile links to filtered record list. |
| FR-232 | Client registry: onboarding, GSTIN/PAN, status workflow (lead → trial → active → suspended → churned) | P0 MVP | Status FSM with permission-gated transitions. GSTIN validation: 15-char format check + duplicate check. Onboarding checklist: per tenant type (fleet vs corporate), SLA timers on each step. |
| FR-233 | Client 360°: KYC, users, drivers, cabs, subscription, dues, usage, tickets, health score | P1 V1 | Profile loads ≤2s with lazy-loaded tabs. Health score: composite of usage\_trend + payment\_timeliness + support\_ticket\_rate + activation\_completeness. Formula documented in-app. |
| FR-234 | Vendor registry: client linkages, fleet, compliance, performance | P1 V1 | Vendor↔client linkage graph queryable. Compliance expiry alerts scheduled daily. Underperformance flags: configurable thresholds per metric. |
| FR-235 | Driver registry: cross-tenant directory, identity, documents, platform blocks with appeal | P1 V1 | Privacy: PII fields (phone, aadhaar, address) masked for read-only auditor role; access logged. Block: reason + appeal URL sent to driver via SMS. Appeal: creates support ticket linked to driver block record. |
| FR-236 | Cab registry: cross-tenant vehicle directory, cab-type library | P1 V1 | Registration unique platform-wide: unique index on normalised registration\_number. Ownership changes: journaled in vehicle\_ownership\_history. Cab-type library: platform-managed with icons; changes propagate to eligible duty-type mappings with tenant notification. |
| FR-237 | User directory: cross-tenant search, lock/unlock, impersonation | P0 MVP | Search p95 <1s at 100K users via trigram index on name + email. Lock: Redis session invalidation + DB flag; effective ≤60s. Impersonation: requires open ticket, generates impersonation\_token scoped to ticket, all actions logged under original actor + impersonation context. |
| FR-238 | Subscriptions and plans: plan catalogue, trials, usage metering, overage, renewals | P0 MVP | Metering: completed duty count and tracking-day count from duty ledger ±0. Mid-cycle changes prorated by day. Renewal reminder: T-14/7/3/1 automated emails. |
| FR-239 | Tenant billing and payments: invoices, gateway transactions, receipts, collection dashboard | P0 MVP | Idempotency: gateway webhooks processed via Redis SET NX on payment reference. Invoice → transaction → receipt chain: bidirectional navigation. Daily reconciliation report: auto-generated at 23:00 IST. |
| FR-240 | Dues, dunning, credits, refunds; maker-checker above threshold | P1 V1 | Dunning sequences: configurable per tenant segment (startup/growth/enterprise). Every credit/refund linked to reason + ticket ID. Threshold for maker-checker: configurable by finance admin (default ₹10,000). |
| FR-241 | Operational oversight: cross-tenant read-only views, dispute interventions | P1 V1 | All oversight actions notify affected tenant via in-app + email. Dispute FSM: open → investigating → resolved → closed. SLA timers per priority. No silent mutation path. |
| FR-242 | Support ticketing: intake, categorisation, SLA, assignment, escalation, CSAT, linkage to records | P1 V1 | SLA clocks per priority (P1: 1h, P2: 4h, P3: 24h). Macros: saved response templates with variable substitution. CSAT: sent 24h after ticket resolution. Every ticket must link to ≥1 operational record. |
| FR-243 | Audit and access monitoring: unified audit search, saved investigations, anomaly flags | P0 MVP | Audit query p95 <2s over 90-day window via columnar index on (tenant\_id, entity\_type, created\_at). Anomaly rules: off-hours bulk export, repeated impersonation, mass status changes — stored in anomaly\_rules table, configurable thresholds. Exports watermarked with actor + timestamp in PDF footer. |
| FR-244 | Platform analytics and MIS: tenant growth, revenue/MRR, collections/DSO, usage, support load, churn signals | P1 V1 | KPI definitions documented in-app (no black-box metrics). Churn signal: usage\_velocity × payment\_delay × support\_ticket\_spike, reviewed monthly for false-positive calibration. Scheduled packs: cron-driven report jobs, delivery miss rate <0.1%. |
| FR-245 | Feature flags and announcements: tenant/user-targeted flags, kill switch, scheduled banners | P0 MVP | Feature flags via LaunchDarkly or in-house (Redis-backed). Kill effective ≤60s. Percentage rollout: deterministic bucketing by tenant\_id hash. Announcements targetable by plan/segment/cohort. |
| FR-246 | Platform configuration: cab-type library, duty-type templates, pricing starter packs, notification templates | P1 V1 | Config versioned with semantic version tag. Rollout: staged to pilot tenants first (feature flag gated). Tenant overrides preserved on library update — override comparison shown to admin. |
| FR-247 | Privacy centre: DSAR export/delete, retention policies, consent receipts, DPA support | P1 V1 | DSAR export: ≤24h; erasure: ≤72h with legal-hold exceptions itemised. Erasure verification: audit log entry with hash of deleted records. DPA generation: templated PDF with tenant data filled programmatically. |
| FR-248 | Network moderation: associate verification, trust interventions, dispute adjudication | P2 V2 | Action ladder: warn → limit → suspend, each with evidence links in audit. Appeal: creates reversal ticket with SLA. All actions audited. |
| FR-249 | Tenant suspension and offboarding: graceful suspend, data export, purge on retention expiry, reactivation | P1 V1 | Suspended tenant: read-only mode + data export access for 30 days. Purge: scheduled job with pre-purge verification query; certified by admin sign-off + audit record. Reactivation: restore within RTO (≤30 min). |




### E15 — Offline-First Architecture & Resilience New Epic


**GAP IDENTIFIED:** The original PRD mentioned offline tolerance as a goal and in UX notes but had no dedicated functional requirements defining the offline contract, sync protocol, or conflict resolution. This is a critical gap given that Legacy Rental Platform Go's most-reported failures are connectivity-related. This epic makes the offline contract explicit and testable.


FR-250
Offline Data Contract
P0MVP


The driver app shall remain fully functional for active duties during complete network loss of up to 4 hours, with no data loss or stuck-state on reconnect.


**AC:** (1) Start duty, add expenses, add GPS points, stop duty all work with zero connectivity; (2) on reconnect, all queued actions sync in order within 30s; (3) sync never requires a cache-clear or app restart.
**TN:** Local DB: WatermelonDB (SQLite) for structured duty data; GPS points: separate SQLite table with auto-increment. Sync queue: operations serialised as JSON with timestamp + idempotency key; retry processor with exponential backoff. Conflict resolution: server-authoritative for pricing calculations; local-authoritative for GPS points (server appends, never overwrites). Stuck-state protection: no UI state depends on a pending server response — all transitions write locally first.




FR-251
Pre-fetch Strategy
P0MVP


The app shall pre-fetch and cache duty details, customer information, pricing data, and map tiles for upcoming duties within 30 minutes of allotment.


**AC:** (1) All duty detail available offline within 30 min of allotment; (2) cache invalidated and refreshed if duty details change; (3) map tile cache covers ±10km radius of reported address.
**TN:** Pre-fetch trigger: FCM data message on allotment → background sync. Cache scope: duty record, customer info, pricing snapshot, driver type snapshot, map tiles (offline tiles via Google Maps SDK offline regions or Mapbox). Invalidation: if duty is re-allotted or booking details change, fresh FCM data message triggers cache refresh.




FR-252
Web Console Resilience
P0MVP


The web console shall display meaningful degraded states during API latency spikes or partial outages; critical actions (allotment, invoice issue) shall be queued for retry, not silently dropped.


**AC:** (1) API timeout >5s shows an inline retry, not a white screen; (2) failed allotment shows error reason + retry button; (3) async jobs (invoice builds, imports) show progress and complete even if the browser tab is closed.
**TN:** TanStack Query: stale-while-revalidate for reads; optimistic updates with rollback for mutations. Async jobs: job\_id returned immediately; progress via WebSocket or polling. Jobs stored server-side with completion status; notification delivered on completion regardless of browser state.




## 6. Key User Journeys


### J1 · Dispatcher — Morning Rush (30 Duties, 2 Hours)


1. Opens Attention queue → 6 unallotted <120 min highlighted with one-click allot action.
2. Bulk-selects 4 airport duties → allotment picker shows compliant, available, nearest drivers with live location → confirms in one action.
3. 2 duties blocked (expired insurance) → system names the document → reassigns; override path requires reason.
4. Dispatches all → automated SMS/WhatsApp confirmations sent → board goes green.


### J2 · Driver — Airport Duty with Poor Signal


1. Receives push → views duty pack (addresses pre-fetched, offline-ready) → navigates.
2. Starts duty (odometer photo) → enters tunnel, signal lost → app queues GPS points locally.
3. Signal returns → auto-sync, gap annotated → adds toll + photo, collects OTP + signature → closes.
4. Stop duty completes without hang or cache-clear — state was written locally first. Supervisor sees completed slip.


### J3 · Billing Executive — Month-End (2,000 Duties)


1. Filters completed unbilled duties → creates consolidated invoice (async build) → notified on completion.
2. Reviews exceptions (3 price overrides flagged) → issues → e-invoice generated → dispatches via email + WhatsApp.
3. Corporate rejects 2 lines (missing toll proof) → adds proofs → re-issues with linked correction → accepted → payment link sent → receipt auto-matched.


### J4 · Employee — Late-Night Booking (via Passenger App)


1. Logs in via corporate SSO (no separate password, no login failure) → requests airport drop for 23:40.
2. Policy engine approves inline → manager approves via push notification in 12 min.
3. Driver details + OTP arrive → live tracking visible in app → share link sent to family.
4. Ride ends → approves slip → rates in-app → cost centre charged automatically.


### J5 · Corporate Finance — Invoice Friday


1. Opens verification inbox → 47 invoices, 41 auto-accepted with rule citations, 6 flagged with reasons.
2. Drills into flagged invoice: tolerance exceeded by 12 min → checks route log → accepts with note.
3. Approves batch → payables updated → forecast refreshed → vendor paid per terms.


### J6 · Support Agent — Driver Payment Dispute


1. Ticket arrives linked to a duty → opens driver record (association history, payout sheet) and duty slip (versions + proofs).
2. Finds toll photo missing → annotates via dispute intervention → fleet uploads proof.
3. Supervisor re-closes (new version) → payout sheet updates → agent resolves with evidence → CSAT sent.




## 7. Business Rules (Normative)


These rules govern the calculation engine (FR-131). In any conflict between UI copy and this section, this section prevails.


### 7.1 Inputs


Start/end datetime (actuals), start/end odometer, optional garage events, duty type (version at allotment date), vehicle group, and the price-book version effective on the duty date.


### 7.2 Core Computation Sequence



```
1. total_km  = max(0, end_odo − start_odo) + garage_km          [if garage billing enabled]
2. total_hr  = ceil_to_step( (end − start − grace), step )      [step ∈ {0.5, 1.0} per duty type; paise-exact]
3. extra_km  = max(0, total_km − pkg_km)
   extra_hr  = max(0, total_hr − pkg_hr)
4. extra_charge:
     SUM mode:      extra_km × km_rate + extra_hr × hr_rate
     HIGHER_OF:     max(extra_km × km_rate, extra_hr × hr_rate)
5. night_charge:    minutes_in_night_window × night_rate_per_min  [or flat night allowance if configured]
6. FGR mode:        bill = fixed_window_amount; actuals recorded in actuals_km/actuals_hr for audit only
7. garage_charge:   haversine(reporting, garage) + haversine(drop, garage)
                    × company_factor, capped per policy
8. taxable_subtotal = base + extras + night + chargeable_allowances + billing_items
   GST             = per-line tax computation (CGST+SGST or IGST based on state of supply)
   grand_total     = taxable_subtotal + GST + round_off_line
   driver_payable  = computed in parallel, never shown on customer-facing documents
9. minimum_billing: if grand_total < minimum_amount, bill minimum_amount
                    delta shown as "Minimum Billing Adjustment" line item

```

### 7.3 Integrity Rules


1. Unpriced combinations blocked by default (FR-113).
2. Post-completion edits create new versions; originals immutable (FR-134).
3. All money in integer paise (int64); rounding disclosed as a named line item.
4. Cancellation/no-show charges computed per published matrices; no-show requires driver evidence (FR-167).
5. E-invoice documents render only from IRN-acknowledged snapshots (FR-146).
6. Driver-payable computation runs in the same calculation engine pass but is stored in a separate column; never surfaced on any customer-facing output.




## 8. UX / UI Requirements




| ID | Requirement | Technical Implication |
| --- | --- | --- |
| UX-1 | **Information Architecture:** Vendor IA: Home / Bookings / Duties Board / Availability / Billing / Receipts / Purchase / Fleet&People / Customers&Pricing / Reports / Network / Settings. Corporate IA: Home / Requests / Approvals / Trips / Invoices / Budgets / Vendors / People&Policy / Reports / Settings. Admin IA: Overview / Clients / Vendors / Drivers / Cabs / Users / Subscriptions&Payments / Operations / Support / Audit / Analytics / Settings. | Three separate React apps sharing a component library; separate routing trees; no shared session state across surfaces. |
| UX-2 | **Tables:** Virtualised, column chooser, filters, saved/shared views, bulk bar, empty states with template CTAs. No hidden-only actions. | TanStack Table + TanStack Virtual. Saved views stored server-side. Bulk actions via SQS async jobs with per-row result reporting. |
| UX-3 | **Money Transparency:** Every amount expands to its formula (rate × qty ± adjustments) with a link to the price-book version. | Calculation result stored as line\_items JSONB on slip record; expandable UI renders from stored breakdown, not recomputed on page load. |
| UX-4 | **Command Search:** ⌘K global search (duties, invoices, drivers, customers) with keyboard-first dispatch actions. | Full-text search via PostgreSQL tsvector or Elasticsearch (V2). Command palette: cmdk library. Dispatch actions: deep-links to record + pre-filled action modals. |
| UX-5 | **Mobile Driver Mode:** Persistent Start/Stop sheet, ≤12 taps start-to-close, 8 languages, large-touch driver mode, SOS always visible during active trips. | SOS: always-visible FAB, z-index above all other elements, non-dismissable. Large-touch mode: minimum 48×48dp touch targets. Language: i18n via i18next with lazy-loaded language packs. |
| UX-6 | **Accessibility:** WCAG 2.1 AA on web; dynamic type + voice-assisted flows on mobile; Hindi-first microcopy for driver journeys. | Automated a11y testing via axe-core in CI. Dynamic type: REM-based sizing. Hindi microcopy: separate translation file, reviewed by native speaker before each release. |
| UX-7 | **Feedback:** Async jobs always show progress + completion channels; empty/error states show cause + next action + support path. | Job progress via WebSocket; fallback to 15s polling. Error states: error\_code → human message mapping table; every error includes a "contact support" deep-link with pre-filled context. |




## 9. Non-Functional Requirements




| ID | Category | Requirement | Target | Measurement Method |
| --- | --- | --- | --- | --- |
| NFR-1 | Web Performance | Time-to-interactive on 4G reference device | <3.5s; LCP <2.5s | Lighthouse CI in CD pipeline; real-user monitoring via SpeedCurve |
| NFR-2 | API Latency | p95 authenticated API response | <600ms | Distributed tracing (OpenTelemetry); SLO dashboard |
| NFR-3 | Tracking Ingest | p95 event visible to dashboard operator | <60s online; 100% on reconnect | Synthetic test: inject GPS event, measure time to dashboard visibility |
| NFR-4 | Billing Scale | 10K-line invoice build (median) | <60s async | Load test with 10K synthetic duty lines; median P95 timing |
| NFR-5 | Roster Scale | Interactive table with 5,000 rows | ≥50fps scroll on reference hardware | Puppeteer scroll test; frame-time measurement |
| NFR-6 | Availability | Web/API uptime (monthly) | ≥99.9% | Synthetic uptime monitor (Pingdom/Better Uptime); SLO alerting |
| NFR-7 | Recovery | RPO / RTO | ≤5 min / ≤30 min | Quarterly DR drill with documented results; auto-failover test |
| NFR-8 | App Footprint | Install size / cold start (2GB RAM device) | <25MB / <2s | App bundle analyser; cold-start test on Redmi 10 reference device |
| NFR-9 | App Quality | Crash-free sessions (driver app) | ≥99.5% | Sentry crash-free session rate; weekly review |
| NFR-10 | Communications | SMS/WhatsApp delivery rate (30-day) | ≥97% | Provider delivery log aggregate; 30-day rolling rate in admin MIS |
| NFR-11 | Data Residency | All customer data at rest and in transit | India (ap-south-1) only | AWS Config rule: no cross-region data replication to non-India regions |
| NFR-12 | Backups | Snapshots + point-in-time recovery | Daily automated + 30-day PITR | Monthly restore test; restore time documented |
| NFR-13 | Observability | Tracing coverage; PII redaction in logs | 100% services instrumented; 0 PII/OTP in logs | OpenTelemetry coverage report; log sampling for PII leaks in CI |
| NFR-14 | Peak Load | Month-end absorption without manual scaling | 10× daily load, no manual action | Annual load test at simulated 10× volume; ECS auto-scaling verified |
| NFR-15 | Offline Duration | Driver app offline tolerance | 4 hours continuous offline, full functionality | Offline integration test: disable network, run full duty lifecycle, restore, verify sync |




## 10. Data Model


### 10.1 Core Entities




| Entity | Key Attributes | Notes |
| --- | --- | --- |
| Tenant | id, type (FLEET/CORPORATE), status, plan\_id, gstin, pan, created\_at | Root of all row-level security. type determines available features. |
| Branch | id, tenant\_id, name, city, address, gstin, numbering\_series | Invoice numbering per branch × financial year. |
| User | id, tenant\_id, email, phone, name, status, 2fa\_enabled, last\_login\_at | Platform-wide unique email. Driver users linked to driver record. |
| RoleGrant | id, user\_id, role\_id, branch\_id (nullable), granted\_by, expires\_at | A user may have multiple role grants across branches. |
| Customer | id, tenant\_id, name, gstin, billing\_address, type (CORPORATE/INDIVIDUAL), status | CustomerContactMethods (phone, email) as child table. |
| Supplier | id, tenant\_id, type (COMPANY/DCO), name, gstin, bank\_details | DCO suppliers also have a driver record. |
| Driver | id, tenant\_id (nullable for platform-level), name, phone, licence\_no, status | May be associated with multiple tenants (cross-tenant registry). |
| Vehicle | id, tenant\_id (nullable), registration\_no, cab\_type\_id, fuel\_type, seating, owner\_type, gps\_fitted | Registration unique platform-wide. Ownership journaled. |
| DutyType | id, tenant\_id, name, pkg\_km, pkg\_hr, step, extra\_mode, min\_billing, garage\_billing, fgr\_mode, version, effective\_from | Versioned; calculation engine uses snapshot at allotment date. |
| PriceBook | id, tenant\_id, customer\_id, city\_id, duty\_type\_id, vehicle\_group\_id, rates JSONB, effective\_from, effective\_to | Overlap excluded via daterange exclusion constraint. |
| Booking | id, tenant\_id, customer\_id, duty\_type\_id, vehicle\_group\_id, reporting\_at, reporting\_address, drop\_address, source\_channel, status | Status FSM; every transition in booking\_timeline. |
| DutySlip | id, booking\_id, version (FK to current\_version), start\_at, end\_at, start\_odo, end\_odo, status | Versioned. current\_version\_id points to latest confirmed version. |
| DutySlipVersion | id, slip\_id, version\_no, calculation\_result JSONB, created\_by, reason, created\_at | Immutable once created. JSON diff stored in slip\_version\_diff. |
| Invoice | id, tenant\_id, customer\_id, branch\_id, status, type (SINGLE/CONSOLIDATED/PROFORMA), total\_paise, irn, issued\_at | Immutable on issue; corrections via CreditDebitNote. |
| Receipt | id, tenant\_id, customer\_id, amount\_paise, mode (UPI/NEFT/CHEQUE/GATEWAY), gateway\_ref, received\_at | Allocations in receipt\_allocations (receipt\_id, invoice\_id, amount\_paise). |
| TrackPoint | duty\_id, recorded\_at, lat, lng, accuracy, battery\_pct, source (APP/HARDWARE/INTERPOLATED), is\_gap\_boundary | TimescaleDB hypertable partitioned by recorded\_at. No update path. |
| Tenant (Platform) | See Tenant above plus plan\_id, trial\_ends\_at, suspended\_at, churned\_at | Platform-level billing entities stored in admin schema (separate DB schema). |
| SupportTicket | id, tenant\_id, reporter\_type, subject, status, priority, sla\_due\_at, linked\_entity\_type, linked\_entity\_id | SLA clock paused while waiting on tenant response. |
| AuditLog | id, tenant\_id, actor\_id, action, entity\_type, entity\_id, before JSONB, after JSONB, ip, device\_fingerprint, created\_at, prev\_hash, row\_hash | Append-only. Hash-chained. No delete path. retention\_class: STANDARD / FINANCIAL. |


### 10.2 Data Rules


1. All money in integer paise (int64). Tax computed per line then summed. Rounding difference disclosed as a named line item.
2. Soft-delete with `deleted_at` timestamps; legal/financial holds exempt from erasure with itemised disclosure in DSAR response.
3. GPS data stored with source label (APP/HARDWARE/INTERPOLATED), accuracy, battery context. Interpolated points never used for billing.
4. PII minimised per purpose; field-level masking by role (driver phone masked for report-only role). Export/delete per DPDP retention matrix.
5. Tenant data export on demand (full-fidelity JSONL + attachments as ZIP) — no lock-in. Available within 24h of request.




## 11. Integration Requirements




| ID | Integration | Direction | Release | Technical Contract |
| --- | --- | --- | --- | --- |
| INT-1 | Maps (Google Places, Geocoding, Routes) | Out | MVP | Server-side proxy; responses cached per (query\_hash) with 30-day TTL; per-tenant quota alerts. Fallback: MapmyIndia evaluated for India-specific accuracy. |
| INT-2 | Push Notifications (FCM + APNs) | Out | MVP | FCM HTTP v1 API; APNs via token auth (p8 key). Retry: 3× with 5s backoff. Quiet hours enforced server-side (not device-only). Delivery receipts logged. |
| INT-3 | SMS + Voice (DLT-registered) | Out | MVP | Provider abstraction layer. Primary: Kaleyra (or Gupshup). Fallback: Exotel/Twilio. Circuit breaker: 5 failures/30s triggers failover. DLT header IDs managed in platform config. |
| INT-4 | WhatsApp BSP | Out | MVP | BSP: Gupshup or Interakt. Template IDs stored in platform config. Delivery webhooks stored in message\_events. Opt-out handling: record opt-out in customer preferences, suppress future messages. |
| INT-5 | Email (transactional + invoice dispatch) | Out | MVP | SendGrid or AWS SES. Branded custom domain (SPF/DKIM/DMARC configured). Bounce handling: hard bounces flag customer email as invalid. Open/click tracking for invoice dispatch only. |
| INT-6 | Payment Gateway (Razorpay primary + Cashfree fallback) | Both | MVP | Webhooks: HMAC-SHA256 signature verification; idempotency key = gateway\_payment\_id; Redis SET NX for deduplication. Auto-receipt: created in DB transaction with webhook processing. |
| INT-7 | E-Invoice GSP (ClearTax / Karvy) | Both | V1 | IRN request via async queue (SQS); polling for result. IRN stored on invoice record. Cancel: statutory 24h window. Printing only from IRN-acknowledged snapshots. Daily sandbox regression suite run in CI. |
| INT-8 | Tally XML + Zoho Books REST API | Both | V1 | Tally: XML push via Tally Prime XML bridge. Zoho: REST API with OAuth2. Sync state machine per record (PENDING/SYNCED/FAILED). Conflict resolution UI in vendor console. 10K-record initial sync with progress report. |
| INT-9 | Corporate SSO (Google OIDC / SAML 2.0) + HRMS import | In | V1 | OIDC: standard redirect flow; SAML: IdP-initiated and SP-initiated supported. HRMS import: SFTP or REST webhook, configurable per corporate client. Employee deprovisioning: SCIM protocol support planned. |
| INT-10 | Masked Telephony (Exotel / Knowlarity) — native, no separate app | Both | V1 | API-based click-to-call; no separate mobile app required. Recording: S3 storage via provider's recording callback. Consent disclosure: shown inline before first call per session. Call events on duty timeline. |
| INT-11 | Expense / Collaboration Webhooks | Out | V1/V2 | Standard event schema (CloudEvents format). HMAC-SHA256 signed payloads. Event types: duty.completed, invoice.issued, payment.received. Retry: 5× exponential backoff; delivery log in admin console. |
| INT-12 | Hardware GPS Feeds | In | V2 | Documented ingest protocol: REST (POST /v1/track-ingest) or MQTT. Auth: device API key. Source labelled per point. Duplicate deduplication within 5s window. Device health monitoring via heartbeat. |
| INT-13 | Public API + Webhooks (tenant-facing) | Both | V2 | Versioned REST API (/v1/…). OpenAPI 3.0 spec published. Rate limited per tenant (tier-based). Webhook signatures and delivery logs visible to tenant. All tiers receive access (no paywall on table-stakes). |




## 12. Security, Privacy & Compliance




| ID | Area | Requirement | Technical Implementation |
| --- | --- | --- | --- |
| SEC-1 | Tenancy & Access | Strict tenant isolation; deny-by-default APIs; secrets in managed vault | Row-level security via tenant\_id on every table; PostgreSQL RLS policies enabled. AWS Secrets Manager for all credentials with automatic rotation (90 days). No long-lived credentials in environment variables. |
| SEC-2 | Data Protection | TLS 1.2+ in transit; AES-256 at rest; field-level encryption for PII vault; OTPs never logged | TLS enforced at ALB; HSTS headers. RDS encryption at rest (AES-256). PII vault (phone, Aadhaar, bank details): application-level encryption via AWS KMS DEK. Log sanitiser strips OTPs, tokens, card numbers before any log sink. |
| SEC-3 | Privacy (DPDP 2023) | Consent receipts, purpose limitation, retention engine, DSAR self-service, breach runbook | Consent stored as consent\_receipts (purpose, version, granted\_at, ip). Retention engine: scheduled job applies retention\_matrix per entity class. DSAR: export ≤24h via async job; erasure ≤72h with legal-hold check. Breach notification runbook: documented in incident response playbook; regulatory notification within 72h. |
| SEC-4 | Assurance | SOC 2 Type I (month 9), ISO 27001 (month 12); annual pentest; SBOM | SOC 2 evidence collected via Vanta or Drata from day 1. Annual pentest: scope covers API, mobile apps, admin console. Dependency scanning: Snyk or Dependabot in CI. SBOM: generated per release in SPDX format. |
| SEC-5 | Financial Compliance | GST correctness, invoice immutability, 7-year financial record retention, maker-checker for payouts | GST logic: state-of-supply determination tested against all 28 states × 8 UTs. Invoice rows: immutable via DB trigger blocking UPDATE/DELETE on issued invoices. 7-year retention: retention\_class='financial' exempt from standard erasure. Maker-checker: configurable threshold, pending\_actions table, 4-eyes enforcement. |




## 13. Dependencies, Assumptions & Constraints


### External Dependencies




| Dependency | Required By | Risk | Mitigation |
| --- | --- | --- | --- |
| Google Maps Platform | MVP | Cost overrun at scale; API changes | Server-side proxy + aggressive caching; MapmyIndia evaluated as fallback |
| Payment Aggregators (Razorpay + Cashfree) | MVP | Outage at month-end | Primary + fallback implementation; idempotent webhooks; no single-provider dependency for critical flows |
| SMS / Voice (DLT) | MVP | DLT registration delays (4–6 weeks) | Start DLT registration at T-0 of project; maintain 2-provider setup |
| WhatsApp BSP | MVP | Template approval delays; policy changes | Apply for template approval immediately; design SMS fallback for all WhatsApp touchpoints |
| GSP E-Invoice (ClearTax / Karvy) | V1 | GSP API changes with GSTN | Abstraction layer behind GSP interface; daily sandbox test suite |
| Corporate SSO / HRMS | V1 | Varied IdP implementations per client | Standard OIDC/SAML support; SCIM planned for provisioning |
| Tally / Zoho | V1 | API version changes | Versioned client adapters; customer-specific mapping UI for remapping on changes |


### Key Assumptions


* BRD §11 assumptions apply in full.
* Pilot data (3 months billing history) available for parallel-run validation of calculation engine.
* Sprint-0 technology decision (Node.js vs Go; React Native vs Flutter) will be made by the Engineering Lead before development begins.
* At least 2 pilot fleet operators available for MVP validation within month 3.


### Constraints


* India data plane (ap-south-1) is non-negotiable for all customer data.
* Low-end device floor: minimum tested device Redmi 10 (2GB RAM, Android 12).
* Month-end 10× peak must be absorbed without manual scaling intervention.
* No paywalling of table-stakes features (brand masking, API access at standard tier).
* Hindi is the minimum language at MVP; 8 languages by V1.




## 14. Risks




| Risk | Likelihood | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| Pricing-edge calculation parity not proven before launch | Medium | High — billing disputes destroy fleet trust | Shadow billing mandatory: no launch without pilot-history parallel-run within 0.5% tolerance. Golden suite 1,000 cases must pass in CI. | Product + Engineering |
| OEM battery management kills background GPS on low-end phones | High | High — tracking gaps, slip inaccuracies | OEM battery exemption guide per top 10 OEM skins; battery exemption coach on first duty; per-release OEM matrix maintained. Foreground service with persistent notification. | Mobile Engineering |
| Offline sync conflicts on stop-duty | Medium | High — stuck drivers, duplicate slips | Server-authoritative conflict resolution; idempotency keys on all sync operations; no UI state dependent on server response before local transition. Integration test suite for offline scenarios. | Mobile Engineering |
| Invoice verification false-accepts at corporate | Medium | High — compliance failures, lost corporate trust | Weekly audit of accepted invoices until false-accept rate = 0; rule citations stored for every verdict; tolerance tuning UI for corporate finance. | Product |
| DLT registration delays block SMS at MVP | High | Medium — no driver notifications | Start DLT registration at project T-0; maintain WhatsApp + email as fallback channels from day 1. | Operations |
| Network/trust design has legal ambiguity (V2) | Medium | Medium | Legal review of network design required before V2 build begins; trust-score formula published in-app. | Legal + Product |
| DPDP compliance gaps (competitor has "data can't be deleted" on their apps) | Low (if built right) | High — regulatory liability | DSAR self-service from V1; erasure pipeline built before corporate launch; Data Protection Officer engaged from month 6. | Engineering + Legal |




## 15. Acceptance Criteria & Definition of Done


### Release Acceptance Gate


* All P-level FRs for the release pass their stated ACs.
* Golden calculation suite (1,000 cases) green on CI.
* Shadow-billing tolerance met (MVP/V1 billing changes): <0.5% deviation from pilot history.
* NFR spot-checks pass (p95 API latency, 5K-row table render, app cold start).
* Offline integration test suite green (FR-250 scenarios).
* Security review signed by InfoSec lead.
* Pilot UAT signed by at least 2 fleet operators (MVP) or 1 corporate client (V1).
* Docs + in-app guidance shipped (no placeholder "coming soon" on shipped features).


### Story Definition of Done


* Coded + unit tested (≥80% coverage for new code paths).
* Integration tested (API contract tested against OpenAPI spec).
* UX reviewed against designs (pixel-diff or designer sign-off).
* Audit coverage verified (every mutation produces an audit row — test in story AC).
* Permission coverage verified (unauthorised access returns 403 — test in story AC).
* Telemetry: relevant events instrumented (OpenTelemetry spans, custom metrics).
* Docs updated (internal wiki + in-app help text if user-facing).
* Feature-flag gated rollout plan in place for any change touching billing logic.




## 16. Glossary




| Term | Definition |
| --- | --- |
| Duty | One executed job from pickup to drop. |
| Duty Slip | The billable record of an executed duty; versioned and immutable once confirmed. |
| DCO | Driver-cum-Owner — a supplier who is both the driver and vehicle owner. |
| Garage KM/Time | Billable deadhead distance/time from garage to pickup and drop to garage, per policy. |
| FGR | Fixed-Gross-Rate — a billing mode that charges a fixed amount regardless of actuals; actuals recorded for audit only. |
| Higher-Of | Extra charge = max(km-extra, hr-extra), rather than their sum. |
| Allotment | Assigning a driver + vehicle (or supplier) to a duty. Temporary allotment = expirable hold. |
| Consolidated Invoice | A single invoice covering multiple completed duties within a billing period. |
| Purchase Duty | An outsourced job billed to the platform's customer but fulfilled by an associate supplier; tracked separately for cost and margin. |
| DSO | Days Sales Outstanding — average days from invoice dispatch to receipt. |
| Three-Way Match | Reconciliation of: (1) executed duty slip, (2) supplier bill, (3) customer sale. All three must match within tolerance for auto-accept. |
| IRN | Invoice Reference Number — the GSTN-issued identifier for a GST e-invoice. |
| Tenant | A customer organisation of the platform — either a fleet operator or a corporate client. Each tenant has full data isolation. |
| Client 360° | The unified admin profile of a tenant: KYC, contacts, subscription, usage, dues, open tickets, and health score. |
| Paise | Unit of all monetary storage (int64). 1 Indian Rupee = 100 paise. All calculations performed in paise to avoid floating-point errors. |
| DSAR | Data Subject Access Request — a request by an individual to access or delete their personal data, per DPDP 2023. |
| DPDP | Digital Personal Data Protection Act 2023 — India's primary data privacy legislation, effective 2024. |
| BSP | Business Solution Provider — an authorised WhatsApp Business API reseller and integration partner. |
| DLT | Distributed Ledger Technology platform (TRAI) — India's regulatory requirement for registering commercial SMS sender IDs and templates. |
| Maker-Checker | A four-eyes financial control: a "maker" initiates an action, a different "checker" must approve it before execution. |
| RLS | Row-Level Security — PostgreSQL feature enforcing tenant isolation at the database query level. |
| SLA | Service Level Agreement — a contractual commitment on response or completion time for a duty or support action. |


  



---



 Traceability: FR→BR mapping embedded per requirement. Change control: any post-sign-off change requires an impact assessment + re-approval from Product, Engineering, and Sponsor before implementation.







