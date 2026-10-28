# Legacy Rental Platform Help Center → Axiom Fleet product gap analysis

**Research date:** 30 September 2026  
**Product compared:** Axiom Fleet local/mock-first product and Supabase production foundation  
**Source:** [Legacy Rental Platform Help Center](https://help.legacyfleet.example.com/)

## Implementation update — 30 September 2026

Since this comparison was written, the first production-oriented parity slices
have been implemented without replacing the Axiom Fleet architecture:

- corporate account setup, entitlements, policy evaluation, duty-slip approval,
  versioned masters and write guards;
- operations intake, deterministic availability, allotment/capacity locks and
  unified duty closure evidence;
- invoice runs, ageing/dunning, saved report definitions and finance exports;
- tenant-managed communication templates, suppression and idempotent dispatch
  evidence;
- supplier purchase/ageing/settlement, fuel, petty cash, driver allowance and
  payroll foundations;
- configurable post-duty feedback, sentiment and service-recovery actions.

The Supabase migrations, authenticated Edge boundaries, browser adapters,
OpenAPI routes, local smoke tests and regression checks are additive. Real
provider credentials, live Supabase validation, production storage, GST/e-
invoice, payment gateway, SMS/WhatsApp/email callbacks and the physical
Android driver matrix remain release gates. The comparison table below still
records the deeper product gaps that these slices do not claim to close.

## Executive summary

Legacy Rental Platform is not only a booking and dispatch tool. Its public help center describes a mature car-rental operating system built around:

1. deeply configurable masters and pricing;
2. booking, availability and multi-path allotment;
3. duty execution through dashboard, SMS, driver app and Network suppliers;
4. duty-slip, OTP, signature, attachment and billing evidence;
5. invoicing, e-invoicing, receipts, collections and supplier purchases;
6. a dedicated driver/location product;
7. corporate account hierarchy, entitlements and passenger workflows;
8. operational reports, Tally/export workflows and business settings;
9. invite-controlled supplier Network workflows; and
10. India-specific communications, GST and payment operations.

Axiom Fleet already has a stronger foundation in some areas—tenant isolation, auditability, idempotent replay, Supabase/RLS direction, additive Network governance, predictive/sustainability contracts, bill intelligence and an offline-first Driver foundation. The principal gap is **depth of operational productization**: many Axiom endpoints and contracts exist, but the Legacy Rental Platform comparison exposes missing domain detail, configuration UX, production integrations and several day-to-day car-rental workflows.

The most important next investment is not another KPI panel. It is a **versioned account, master, policy and entitlement foundation** that can drive booking, allotment, duty, billing and corporate experiences consistently.

## Research coverage

The help center was crawled recursively from its public home page.

- **282 internal URLs** were discovered and fetched.
- **1 stale public URL** returned 404: an old DLT SMS-template article.
- **490 unique embedded media assets** were catalogued; the public walkthrough media is GIF-based rather than MP4/WebM-based.
- The complete sanitized URL/page inventory is in [`legacy-fleet-help-crawl-20260930.json`](./legacy-fleet-help-crawl-20260930.json).
- The earlier corporate-account media review covered all seven corporate-account articles and their walkthroughs. For the full 490-asset corpus, this report uses the articles, captions, page flows and linked media inventory; it does not copy Legacy Rental Platform’s assets, code or protected implementation.

The crawl covered the top-level categories and linked articles for Getting Started, Masters, Operations, Duties, Driver App and Location Tracking, Reports, Network, Business Settings, Corporate Accounts, Tutorials, Purchase and Payments, and release updates through September 2026.

## What the public product teaches us

### 1. Legacy Rental Platform has a configuration-led operating model

The operating system starts with a large set of linked masters: duty types, vehicle groups and categories, taxes, customers, suppliers, drivers, vehicles, duty supporters, labels, feedback forms, employees, billing items, pricing, branches, bank accounts and company/sister-company records. Pricing, taxes, branches, customer defaults and supplier relationships are not secondary settings; they determine what can be booked, allotted, closed and invoiced.

Relevant sources:

- [Masters](https://help.legacyfleet.example.com/masters)
- [Duty Types](https://help.legacyfleet.example.com/duty-types)
- [Vehicle Groups](https://help.legacyfleet.example.com/vehicle-groups)
- [Pricing](https://help.legacyfleet.example.com/pricing)
- [Understanding copy pricing functionality](https://help.legacyfleet.example.com/understanding-copy-pricing-functionality-in-depth)
- [Branches and access/visibility](https://help.legacyfleet.example.com/different-ways-to-use-branches-for-access-visibility)
- [My Companies and sister companies](https://help.legacyfleet.example.com/how-to-setup-my-companies-and-sister-companies)

### 2. Booking is a policy and availability engine, not a single form

The help center describes manual, bulk, itinerary and monthly bookings, customer and passenger booking controls, city/duty-type/vehicle-group restrictions, pricing-dependent options, availability, multiple allotment paths, automatic allotment, temporary allotment, cross-vehicle-group allotment, company selection by city, customer-controlled allotment and approval/notification rules.

Relevant sources:

- [Bookings](https://help.legacyfleet.example.com/bookings)
- [How to add a booking](https://help.legacyfleet.example.com/how-to-add-a-booking)
- [Itinerary booking](https://help.legacyfleet.example.com/how-to-create-an-itinerary-booking)
- [Bulk booking](https://help.legacyfleet.example.com/how-to-add-a-bulk-booking)
- [Monthly booking](https://help.legacyfleet.example.com/how-to-add-a-monthly-booking)
- [Multiple ways to manage allotment](https://help.legacyfleet.example.com/multiple-ways-to-manage-allotment)
- [Automated allotment](https://help.legacyfleet.example.com/how-to-setup-and-use-automated-allotment)
- [City/duty type/vehicle group restrictions](https://help.legacyfleet.example.com/how-to-restrict-city-duty-type-vehicle-group-selection-based-on-pricing)

### 3. A duty is an evidence and settlement object

A duty can be closed manually, through an SMS link, through the driver app or through a Network associate. Closing captures start/end date and time, odometer, duty type, vehicle group, auto-switch behavior, price, extra-time/km rates, customer and driver allowances, billing items and scanned duty-slip evidence. The newer September 2026 update adds document checks, half-hour packages, mandatory billing items and combined duty-slip attachments.

Relevant sources:

- [How to close a duty](https://help.legacyfleet.example.com/how-to-close-a-duty)
- [Close via SMS link](https://help.legacyfleet.example.com/how-to-close-a-duty-via-an-sms-link)
- [Legacy Rental Platform Go Driver App](https://help.legacyfleet.example.com/an-introduction-to-the-legacy-fleet-go-driver-app)
- [Duty-based tracking](https://help.legacyfleet.example.com/how-to-setup-and-use-duty-based-tracking)
- [September 2026 updates](https://help.legacyfleet.example.com/updates-for-sep-2026)

### 4. Finance is a complete operational loop

The help center covers customer invoices, proforma invoices, monthly and per-duty invoicing, cover invoices, due dates, invoice editing rules, GST entities, e-invoice creation/export/cancellation, credit/debit notes, receipts and advances, payment requests, credit-card tokenisation, auto-collect, overdue reminders, supplier invoices and ageing, driver payroll, petty cash, fuel stations and fuel entries.

Relevant sources:

- [Billing and Receipts](https://help.legacyfleet.example.com/billing-and-receipts-articles)
- [How to generate an invoice](https://help.legacyfleet.example.com/how-to-generate-an-invoice)
- [Automatic invoice generation](https://help.legacyfleet.example.com/how-to-automatically-generate-an-invoice-once-a-duty-is-completed)
- [E-invoices](https://help.legacyfleet.example.com/how-to-create-an-e-invoice)
- [Receipts](https://help.legacyfleet.example.com/how-to-find-and-apply-receipts)
- [Payment Gateway](https://help.legacyfleet.example.com/payment-gateway)
- [Auto-collect](https://help.legacyfleet.example.com/how-to-setup-and-use-auto-collect)
- [Driver Payroll](https://help.legacyfleet.example.com/how-to-calculate-and-export-driver-payroll-data)

### 5. Corporate Accounts are an entitlement product

The corporate flow connects a customer-side corporate account to the rental account, copies selected duty types, vehicle groups and pricing, then creates a hierarchy of Corporate Super Admin, employee-admin and booker/passenger accounts. The account layer controls permissions, branches, customer entities, sister-company visibility, cities, vehicle groups, duty types, suppliers, auto-allotment, approval managers, notification recipients and time-based exceptions.

Relevant sources:

- [Understanding Corporate Accounts](https://help.legacyfleet.example.com/understanding-corporate-accounts)
- [Corporate account structure](https://help.legacyfleet.example.com/understanding-the-structure-of-corporate-accounts)
- [Admin employee accounts](https://help.legacyfleet.example.com/how-to-set-up-an-admin-employee-account)
- [Booker/passenger accounts](https://help.legacyfleet.example.com/how-to-create-booker-passenger-accounts)
- [Passenger duty-slip approval](https://help.legacyfleet.example.com/how-to-set-up-up-duty-slip-approval-by-passengers)
- [Custom booking SLA](https://help.legacyfleet.example.com/how-to-set-up-a-custom-sla-for-bookings)
- [Cancellation SLA](https://help.legacyfleet.example.com/how-to-set-a-booking-cancellation-time-sla)

### 6. Network is supplier collaboration, not a public marketplace

Legacy Rental Platform’s public documentation describes supplier invitations, associates, contract/rate synchronisation, booking requests, accept/decline, multiple supplier requests, duty-particular changes and Network duty completion. This confirms the direction already chosen for Axiom Network: closed B2B relationships and controlled handoff rather than public vendor registration.

Relevant sources:

- [Network](https://help.legacyfleet.example.com/network)
- [How to start using Network](https://help.legacyfleet.example.com/how-to-start-using-the-legacy-fleet-network)
- [Invite a supplier](https://help.legacyfleet.example.com/how-to-invite-a-supplier-to-the-legacy-fleet-network)
- [Add an associate](https://help.legacyfleet.example.com/how-to-add-an-associate)
- [Accept a Network booking](https://help.legacyfleet.example.com/how-to-accept-a-network-booking)
- [Auto-sync contracts](https://help.legacyfleet.example.com/how-to-auto-sync-contract-with-your-vendor-accounts)

### 7. The Driver product is operationally specific

Legacy Rental Platform documents mobile login, duty start/stop, automatic KM/time tracking, passenger signature, toll/parking images, battery settings, audio alerts, driver-efficiency controls, OTPs, route logging, garage-to-garage duties, SMS closure, DCO users and passenger/customer location sharing.

Relevant sources:

- [Driver App introduction](https://help.legacyfleet.example.com/an-introduction-to-the-legacy-fleet-go-driver-app)
- [Driver phone/battery settings](https://help.legacyfleet.example.com/driver-phone-battery-settings-for-the-legacy-fleet-go-driver-app)
- [Driver efficiency alerts](https://help.legacyfleet.example.com/driver-efficiency-alerts-and-controls)
- [Route logging](https://help.legacyfleet.example.com/how-to-enable-and-use-route-logging)
- [OTPs to start/stop a duty](https://help.legacyfleet.example.com/how-to-enable-and-use-otps-to-start-and-stop-a-duty)
- [Location sharing](https://help.legacyfleet.example.com/how-to-enable-or-disable-location-sharing)

### 8. Reports are configurable and export-oriented

Legacy Rental Platform documents business reports by duty or invoice date, customer and supplier ageing, number-of-duties reports, vehicle profitability by vehicle/group, favourites, refresh, filters by customer/supplier/duty type/vehicle group/city/branch/company, data import/export, Tally/Tally Prime and export profiles.

Relevant sources:

- [Understanding Reports](https://help.legacyfleet.example.com/understanding-reports)
- [Supplier Reports](https://help.legacyfleet.example.com/understanding-supplier-reports)
- [Export data](https://help.legacyfleet.example.com/how-to-export-data)
- [Export to Tally](https://help.legacyfleet.example.com/how-to-export-to-tally)
- [Create an export profile](https://help.legacyfleet.example.com/how-to-create-an-export-profile)
- [Vehicle profitability](https://help.legacyfleet.example.com/how-to-generate-a-vehicle-profitability-report)

## Comparison matrix

Status key:

- **Covered:** the local/API product has a tested contract and a usable surface.
- **Partial:** a local contract, mock or provisional UI exists, but the domain depth, production integration or complete workflow is missing.
- **Missing:** not currently represented as a complete Axiom Fleet capability.
- **Intentional boundary:** not a gap to copy because it conflicts with the chosen MVP boundary.

| Product area | Legacy Rental Platform capability observed | Axiom Fleet status | Gap / implication |
|---|---|---|---|
| Tenant identity and audit | Corporate/vendor/driver accounts, employee logins, role-based access and operating account hierarchy | **Covered / partial** | Axiom has Auth, tenant isolation, audit, invitations, roles and Supabase/RLS direction. Per-user corporate entitlements and production SSO are not complete. |
| Corporate-to-rental connection | Link customer-side corporate account to rental account; copy scope and pricing | **Missing / partial** | Axiom needs an explicit `corporate_account_connection` and setup wizard with source customer, default supplier, copied duty types, vehicle groups, pricing, GST/address and immutable setup evidence. |
| Corporate entitlement engine | Super Admin, employee-admin, booker/passenger, permission profiles, branch/customer/sister-company visibility | **Partial** | The redesigned home explains the model, but current employee records do not yet persist the full role, permission profile or visibility scope. This is the highest-value corporate gap. |
| Booker/passenger policy | Cities, base city, allowed/extended vehicle groups, duty types, visible entities, custom passenger, supplier choice, auto-allotment, manager, time exceptions and duty/vehicle mapping | **Partial / mostly missing** | Axiom has booking approvals and policy records, but not the structured passenger entitlement schema/evaluator or complete configuration UX. |
| Duty-slip approval | Email accept/reject, final duty-slip evidence, 48-hour auto-approval | **Partial** | Axiom has proof, notifications and audit contracts, but needs a dedicated passenger duty-slip state machine, signed/expiring action links, scheduled 48-hour auto-approval and tenant-configured notification templates. |
| Booking lead-time SLA | Customer-specific minute cutoff, default-supplier dependency, booking prevention/warning | **Partial** | Axiom has SLA records/events, but not the customer/account policy evaluator that blocks or explains a booking inside the cutoff. |
| Cancellation SLA | Minute cutoff and warning that cancellation may still be charged | **Partial** | Axiom has cancellation/booking workflows but needs a pre-cancellation charge-warning evaluator and immutable applied-policy evidence. |
| Core masters | Duty types, vehicle groups/categories, taxes, customers, suppliers, drivers, vehicles, branches, employees, companies, bank accounts, billing items, labels, feedback forms | **Partial** | Axiom covers core customers, suppliers, drivers, vehicles, branches, employees, policies and a generic master registry. Specialized schemas, relationships, bands, tax/company entities, billing items and feedback are incomplete. |
| Customer/supplier groups | Group-level visibility, pricing and reporting | **Missing / partial** | Customer/supplier records exist, but group membership and group-level pricing/ageing/reporting need a first-class model. |
| Pricing | Effective rates, duty packages, extra KM/time, allowances, auto-switch and copy pricing | **Partial** | Axiom has effective-dated price books and approvals. It lacks the full duty-package/rate-rule engine, half-hour package semantics, automatic switch/mapping and corporate copy-pricing wizard. |
| Availability | Availability board and resource-aware booking/allotment constraints | **Partial** | Axiom has capacity locks, live board and dispatch contracts, but not the full availability calendar and customer-facing availability behavior. |
| Booking intake | Manual, bulk, itinerary, monthly, import, passenger and API booking | **Partial** | Axiom has normal/import/recurring/multi-stop bookings. It needs a complete itinerary/monthly/bulk UX and the corporate/passenger request API surface. |
| Allotment | Manual, automated, multi-supplier, company-by-city, cross-group, customer-controlled, temporary and violation-aware allotment | **Partial / high gap** | Axiom has route plans, assignments, replacement and Network matching. A deterministic supplier/vehicle/driver allotment rules engine with availability, pricing, document and ETA guards is not complete. |
| Duty execution | Dashboard, SMS link, driver app and Network closure paths | **Partial** | Axiom has offline Driver, milestones, OTP/proof, expenses, location and Network handoff. SMS closure, DCO/attached-driver flows, garage-to-garage and the complete duty-slip form are missing. |
| Duty evidence | Odometer, signature, scanned slip, toll/parking photos, attachments bundled into print/PDF | **Partial** | Axiom has proof metadata, object-storage direction and bill evidence. Production upload, signed media, combined duty-slip PDF and evidence completeness rules remain. |
| Duty controls | Half-hour packages, auto-switch duty types, mandatory billing items, expired-document allotment guard, start/end OTP retrieval | **Partial / missing** | These September 2026 capabilities should be explicit Axiom rules and validations, not only generic policies. |
| Driver alerts | Stoppage, overspeeding, efficiency, stale GPS, route deviation and audio alerts | **Partial** | Axiom has predictive alerts, stale GPS, safety and deviation contracts. It needs source-specific thresholds, driver audio/notification behavior and production telematics evidence. |
| Location and route | Driver GPS, route log, duty-based tracking, customer/passenger sharing, Google Places | **Partial** | Axiom has GPS, map adapter, trip shares and tracking records; route logs, Google Places production integration and configurable sharing controls are not complete. |
| Communications | SMS templates, WhatsApp, email templates, suppression, placeholders, delivery details, Indecall | **Partial / production gap** | Axiom has mock messaging, notification records and masked telephony. DLT/SMS, WhatsApp BSP, email templates/delivery receipts, support placeholders and Indecall are not production-ready. |
| Customer billing | Invoices, proforma, monthly/cover/per-duty invoices, due dates, tax display, GST entities, letterhead, company switching | **Partial** | Axiom has invoice state, tax, e-invoice, notes, payments and payment links. Complete invoice configuration, document rendering, multi-company billing and invoice editing rules are incomplete. |
| E-invoicing | E-invoice creation, export, credit/debit e-invoices and error handling | **Partial** | Axiom has mock IRN/QR and cancellation contracts. Production GST/e-invoice provider, schema validation, error recovery and export workflows remain. |
| Collections | Receipts, advances, payment requests, gateway, card tokenisation, auto-collect, overdue reminders | **Partial / high gap** | Axiom has payment state, receipt allocation, mock links and queued workflows. Gateway/tokenization, auto-collect, reminders/dunning and reconciliation need production-grade implementation. |
| Supplier purchase | Purchase duties, supplier invoices, supplier payments, advances, supplier ageing | **Implemented / provider-gated** | Follow-on finance controls now cover payment requests, advances, settlement approvals, mock bank execution and tenant-scoped reconciliation; real banking remains a release gate. |
| Fleet finance | Vehicle expenses, fuel stations/entries, petty cash, driver payroll and allowances | **Implemented / provider-gated** | Fuel-station masters/history, variance/efficiency analytics, petty-cash reconciliation, driver payouts, bank-file payroll and statutory reports are wired through local and Supabase boundaries. |
| Reports | Business, duty count, customer/supplier ageing, vehicle profitability, supplier reports and configurable filters | **Implemented / provider-gated** | Configurable report builder, customer/supplier/city/branch/company/vehicle-group filters, favourites/refresh, profitability/pricing/bill-to-duty outputs and private async exports are present. |
| Export/import | Rich driver/vehicle/duty imports, Tally/Tally Prime, export profiles, customer/supplier pricing export and Bill To duty export | **Implemented except explicit exclusion** | Rich templates, validation preview, row-level correction/commit UX, CSV/JSON export profiles, pricing and bill-to-duty report types are present. Tally/Tally Prime formats are intentionally skipped. |
| Feedback | Feedback forms, post-duty feedback and service recovery | **Implemented / provider-gated** | Public token-only links, anonymous submission, notification queue/worker boundary, trend analytics and negative-feedback corrective-action routing are present. |
| Network | Invite suppliers, associates, contract sync, requests, accept/decline, multi-supplier requests, duty changes and Network completion | **Partial / stronger governance** | Axiom Network has deeper versioned demand, matching, quotes, awards, readiness, scorecards, settlements and disputes. It still needs legacy-fleet-parity associate onboarding, contract/rate sync, supplier booking UX and operational message flows. |
| Driver app | Mobile duty, GPS, digital slip, photo/signature, audio/battery guidance, route logging, SMS fallback | **Partial / release-gated** | Axiom has PWA/native foundations, offline replay, proof, expense, SOS, device and location contracts. Real Android matrix, push credentials, background location, production storage and pilot remain. |
| Carbon/sustainability | Carbon/emissions reports and vehicle profitability | **Axiom advantage / partial production** | Axiom Phase 3 has factor-versioned emissions, EV eligibility, charging, passenger-km intensity, avoided emissions and targets. Provider/factor governance and production deployment remain. |
| Product administration | Company profiles, signatures, custom fields, business settings, plan/add-on packaging | **Partial / missing** | Axiom has settings, onboarding, policies and security. Custom fields, company profile/signature, entitlement billing and plan/add-on administration are incomplete. |
| Security/privacy | Public help pages document access and account controls; implementation detail is not public | **Axiom advantage in foundation / production gate** | Axiom explicitly targets tenant RLS, audit, idempotency, MFA, retention and privacy workflows. Live Supabase validation, production MFA/storage/WAF and DPDP evidence remain. |

## Prioritized missing-feature backlog

### P0 — needed for a credible corporate and rental-operations product

1. **Corporate account connection and setup wizard**
   - Link a corporate customer to a rental/supplier organization.
   - Choose default supplier, supported cities, duty types and vehicle groups.
   - Copy or reference pricing, GST/address and customer scope with an audit snapshot.
   - Track invitation, activation, acceptance and setup completion.

2. **Corporate entitlement and visibility schema**
   - Persist account type: Super Admin, employee-admin, booker/passenger.
   - Add permission profiles, explicit grants/denies and visibility scopes.
   - Support branches, customer entities, sister companies, cities, vehicle groups and duty types.
   - Add supplier-selection, auto-allotment, manager approval, notification and time-window controls.
   - Evaluate every booking query and mutation against those entitlements server-side.

3. **Policy-driven booking evaluator**
   - Lead-time SLA and cancellation SLA by customer/corporate account.
   - Default supplier requirement and policy version applied to each booking.
   - Approval manager routing, direct/delegated request source and decision history.
   - Explainable block/warn outcomes rather than generic validation errors.

4. **Duty-slip approval state machine**
   - Passenger approve/reject link with expiry and replay protection.
   - Final duty-slip payload with KM, time, route, signature, billing items and attachments.
   - 48-hour scheduler/worker with automatic approval and audit reason.
   - Notification delivery, bounce/failure and resend state.

5. **Versioned master and scope foundation**
   - First-class duty types, vehicle groups/categories, billing items, taxes, customer/supplier groups, companies/sister companies and branches.
   - Effective-dated packages, extra KM/time rates, allowances, tax rules and copy-pricing snapshots.
   - Mandatory billing-item flags and expired-document allotment guards.

6. **Allotment rules engine**
   - Vehicle/driver/supplier/company selection by city, branch, duty type, vehicle group, pricing, document state and ETA constraints.
   - Manual, automatic, temporary and customer-controlled allotment.
   - Multi-supplier request/response with deterministic reasons.
   - Half-hour duty packages and exact overage calculations.

7. **Duty evidence and closure**
   - Unified closure contract for dashboard, SMS, Driver, Network and DCO flows.
   - Start/end OTP, odometer, signature, attachments, scanned slip and billing-item completeness.
   - Combined duty-slip PDF/print and immutable calculation snapshot.

### P1 — required for operating parity and retention

8. **Invoice and collection workbench**
   - Proforma, monthly, cover and per-duty invoices.
   - Invoice due dates, company/GST entity, letterhead, tax display and controlled edits.
   - Credit/debit notes, receipts, advances, payment requests, overdue reminders and ageing.
   - Production e-invoice and payment-gateway adapters with webhook idempotency.

9. **Purchases, supplier finance and fleet finance**
   - Purchase duties/invoices/payments and supplier invoice ageing.
   - Driver payroll, allowances, petty cash and fuel-station/vehicle-fuel ledgers.
   - Supplier/customer reconciliation and evidence-linked settlement views.

10. **Rich import/export and reporting**
    - Delivered: full vehicle/driver/duty import templates with validation and row-level correction/commit results.
    - Delivered: CSV/JSON export profiles, customer/supplier pricing exports and Bill To duty export; Tally/Tally Prime is explicitly skipped.
    - Delivered: configurable report builder with customer, supplier, city, branch, company and vehicle-group filters.
    - Delivered: favourites, refresh, async large exports and presigned downloads.

11. **Communications platform**
    - Tenant-managed SMS/email/WhatsApp templates and suppression rules.
    - DLT registration/template identity, delivery status, retries and provider references.
    - Indecall-equivalent masked calling UX and consent/retention policy.
    - Supporter/passenger/booking placeholders and account-specific notification routing.

12. **Driver operational parity**
    - Production Android device matrix, push, background location and storage.
    - SMS fallback, driver audio alerts, battery guidance, route logging, vehicle stoppage and overspeed thresholds.
    - Garage-to-garage, DCO/attached-driver and Network-driver flows.

13. **Customer feedback and service recovery**
    - Configurable feedback forms, questions/tags, response links, dashboards and corrective actions.

### P2 — valuable after the core operating loop is stable

14. **Company profiles and document presentation**
    - Signature profiles, custom fields, custom invoice letterhead and branding controls.

15. **Entitlement-based plans and add-ons**
    - Basic/Pro/driver-mobility/network/API feature entitlements, usage metering and billing. This is not a current MVP requirement but appears in Legacy Rental Platform’s public packaging.

16. **Expanded API/SSO surface**
    - Passenger SSO, company-email SSO, passenger API, HRMS sync, Google Places and external telematics connectors.

17. **Operational automation library**
    - Auto-switch rules, scheduled reminders, import/export profiles, supplier contract synchronization and recurring exception jobs.

## What Axiom Fleet should not copy

Some differences are deliberate product decisions rather than gaps:

- Do not open Axiom Network to anonymous vendor registration or consumer marketplace behavior.
- Do not build autonomous supplier awards or financial escrow in the MVP.
- Do not duplicate Fleet trips inside Network; keep Fleet as the canonical booking/duty source of truth.
- Do not start Passenger native development before the Driver physical-device matrix and pilot pass.
- Do not expose demo operational data simply to make the dashboard look populated.
- Do not copy Legacy Rental Platform’s proprietary visual design, code, private APIs or help-center text.

## Recommended Axiom Fleet improvement sequence

### Slice 1 — Account and policy foundation

Build the Supabase-first schema and local parity for:

- `corporate_account_connections`;
- `corporate_account_users` and activation state;
- `permission_profiles` and grants/denies;
- `visibility_scopes` for branch, customer entity, sister company, city, vehicle group and duty type;
- `booking_policies`, `approval_routes`, `supplier_rules` and `duty_slip_policies`;
- immutable setup/copy-pricing snapshots;
- scheduled policy evaluation and audit events.

Then replace the current dashboard’s explanatory cards with live entitlements and readiness checks.

### Slice 2 — Corporate setup and booking control

Ship a guided setup flow:

1. connect customer/rental account;
2. select copied scope and pricing;
3. invite Super Admin;
4. create employee-admin and booker/passenger records;
5. assign permission profile and visibility;
6. configure manager approvals, supplier selection, auto-allotment and time exceptions;
7. test a booking request against the policy evaluator.

### Slice 3 — Duty evidence and passenger close-out

Implement the signed duty-slip action link, approval/rejection state machine, 48-hour worker, notification delivery and evidence bundle. Add mandatory billing items and expired-document checks to closure/allotment.

### Slice 4 — Allotment and execution depth

Extend the current planning/dispatch contracts into a deterministic allotment engine. Add availability, half-hour packages, automatic duty-type/vehicle-group mapping, driver/vehicle compliance checks, SMS fallback, route log and source-specific alerts.

### Slice 5 — Finance and reporting parity

Delivered in the follow-on slice: supplier/fleet finance controls, payroll/fuel/petty-cash/reconciliation workflows, configurable reporting and private async exports, rich import preview/correction UX, and public feedback/service recovery. Tally/Tally Prime export formats remain intentionally out of scope; real bank, payroll, notification and storage providers remain release gates.

### Slice 6 — Production integrations and release gates

After the domain foundations are stable:

- apply Supabase migrations and RLS in a non-production project;
- configure Storage, email, SMS/WhatsApp, maps, telephony, e-invoice and payment credentials;
- complete Driver Android testing and two-fleet pilot;
- add Realtime with polling fallback;
- run browser/WCAG, load, recovery, security and retention tests.

## Immediate recommendation

The next implementation task should be **corporate account entitlements plus the setup/copy-scope wizard**, not another visual dashboard pass. It will unlock the largest set of missing capabilities at once: corporate visibility, booking restrictions, approval routing, supplier choice, auto-allotment, SLA evaluation and duty-slip governance.

I can continue assisting by converting this report into:

1. a Supabase migration and local SQLite parity schema;
2. an OpenAPI/JSON contract for the corporate entitlement evaluator;
3. a staged frontend implementation in `index.html` using the existing hybrid migration;
4. focused smoke tests for tenant isolation, permission leakage, idempotent invites, SLA decisions and 48-hour duty-slip auto-approval; and
5. an updated release checklist that preserves the Driver-device and Supabase gates.
