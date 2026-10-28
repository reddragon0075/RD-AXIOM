# Axiom Fleet + Axiom Network — Master Product, Architecture and Engineering Build Prompt

> **Purpose:** This is a copy-paste master prompt for an AI coding agent, product-engineering agent or engineering team. It instructs the agent to build **Axiom Fleet** into an independently engineered, enterprise-grade fleet and employee-transportation platform, with **Axiom Network** as its controlled B2B transport-network and supplier-exchange module, inspired by publicly observable industry capabilities without copying any third-party proprietary implementation.
>
> **Use:** Paste this prompt into the conversation where the Axiom Fleet project, repository, portal or live preview is available. If the agent has access to the existing Axiom Fleet codebase, it must inspect and extend it. It must not blindly rebuild the product from scratch.

---

## 1. Role and mission

You are the lead product architect, staff software engineer, solutions architect, security engineer, QA lead, DevOps engineer and technical product manager for **Axiom Fleet** and its **Axiom Network** module.

Your mission is to build a production-ready, independently engineered, multi-tenant fleet-management and employee-transportation platform that can support:

- Fleet owners
- Corporate employee transportation programs
- Transport vendors
- Drivers
- Employees and passengers
- Transport administrators
- Security and command-centre teams
- Finance and billing teams
- Maintenance and compliance teams
- Enterprise HR, finance and workplace systems

The product must be comparable to leading employee-transportation platforms in functional depth, but it must be original in its:

- Source code
- Architecture
- Data model
- User experience
- Visual design
- API design
- Optimization implementation
- Workflows
- Documentation
- Product language
- Branding

Do **not** copy or imitate proprietary code, designs, text, private APIs, private technical documents, model weights, datasets, trademarks, product names or protected implementation details belonging to Legacy Dispatch Platform, Legacy ETS Platform or any other third party.

Build clean-room functionality based on generic industry requirements and Axiom Fleet and Axiom Network's own product strategy.

---

## 2. Product context

Axiom Fleet is intended to become a unified, configurable platform for fleet operations and employee mobility.

The product should eventually support three related but separable domains:

### A. Fleet management

- Vehicle master data
- Driver management
- Vendor management
- Vehicle maintenance
- Fuel and energy management
- GPS and telematics
- Compliance documents
- Inspections
- Driver behaviour
- Vehicle utilization
- Cost and operational analytics

### B. Employee transportation management

- Employee and shift management
- Transport demand and booking
- Rostering
- Route planning
- Vehicle and driver assignment
- Fixed-route shuttle operations
- Dynamic home-to-office trips
- Live trip monitoring
- Boarding and deboarding verification
- Safety and incident response
- Vendor and billing management
- Employee and driver mobile applications
- Enterprise integrations

### C. Axiom Network — controlled B2B transport network

- Employer transport requirements and RFPs
- Approved-vendor onboarding and governance
- Service-zone, capacity and capability discovery
- Deterministic vendor matching
- Structured vendor quotes and normalized comparison
- Commercial award, contract and SLA records
- Service-order activation into Axiom Fleet operations
- Vendor communications and controlled collaboration
- Replacement capacity and exception handling
- Evidence-backed settlement and billing
- Vendor performance, ETA and service scorecards
- Renewal, suspension and offboarding workflows

Axiom Network must be a governed operating network, not a superficial lead-generation directory. A network transaction is successful only when it can be converted into a safe, measurable and auditable transport service in Axiom Fleet.

The platform must be modular. A customer must be able to use fleet management without employee transportation, employee transportation without maintenance, Axiom Network without unrelated fleet modules where operationally safe, or the complete platform.

### 2.1 Naming, product boundary and Axiom Network

Use the following naming model consistently in product copy, documentation, code comments, demos, analytics and customer-facing material:

- **Axiom Fleet** is the product family and transport operating system. It remains the source of truth for organizations, employees, vehicles, drivers, vendors, bookings, routes, trips, GPS, safety, billing and operational history.
- **Axiom Network** is a named module within Axiom Fleet. It is a controlled, invite-only B2B network that connects employer transport demand with approved transport vendors and then hands the awarded service into Axiom Fleet for execution.
- In navigation and customer-facing surfaces, label the module **Axiom Network**. Where useful, use the supporting relationship **Axiom Network, powered by Axiom Fleet**. Do not present it as a separate unrelated product unless a future product decision explicitly requires that separation.
- Do not use the name Axiom Network to imply an open consumer travel marketplace, unrestricted public vendor directory, social network or anonymous lead-selling service. The initial operating model is a closed, governed corporate-mobility network.
- Do not rename existing Axiom Fleet routes, APIs, database tables, package names or deployment resources solely for branding. If the existing repository uses Axiom Fleet terminology, preserve backward compatibility, add display labels or aliases where needed, and document any migration in an ADR.
- Axiom Network must share Axiom Fleet identity, tenant isolation, master data, safety policies, dispatch, GPS, ETA, billing, audit, analytics, notification and integration foundations. It must not create a parallel operational source of truth.
- Enable Axiom Network per tenant and per operating region with feature flags. A customer that does not use the network must not see network workflows or network data.

The canonical Axiom Network operating flow is:

```text
Employer requirement / RFP
→ Approved-vendor eligibility and matching
→ Structured quotes
→ Normalized comparison and controlled negotiation
→ Award / contract / SLA
→ Roster, route and service-order setup
→ Dispatch, GPS and ETA execution in Axiom Fleet
→ Safety, support and exception management
→ Evidence-backed billing and settlement
→ Vendor scorecard, renewal or corrective action
```

The first recommended use case is recurring B2B employee transportation in a dense operating region such as Bengaluru, but geography, vertical, vendor count and commercial model must remain configurable. Start with a closed network of compliant vendors. Do not open public registration or optimize for marketplace volume until fulfillment quality, replacement capacity, safety accountability and billing reconciliation are proven.

Axiom Network must optimize for:

- Safe fulfillment rather than the cheapest quote alone
- Explainable and policy-compliant supplier selection
- Reliable service-level performance
- Accurate ETA and evidence-based performance measurement
- Protection of employee, employer and vendor confidential data
- Fast replacement when a vendor or vehicle fails
- Clear ownership of customer communication and incident response
- Auditable commercial outcomes

---

## 3. Project variables

Before implementation, inspect the existing repository, portal and workspace. Do not assume the following values. Populate them in `docs/axiom-context.md`.

```yaml
product_name: Axiom Fleet
product_family: Axiom Fleet
network_name: Axiom Network
network_module_enabled: TBD
network_mode: closed_b2b_controlled
network_vertical: employee_transport
network_pilot_city: TBD  # recommended first pilot: Bengaluru, subject to validation
network_pilot_geography: TBD
network_vendor_approval_required: true
network_public_registration: false
network_minimum_vendor_count: TBD
portal_url: TBD
repository_url: TBD
existing_repository_path: TBD
existing_frontend_stack: TBD
existing_backend_stack: TBD
existing_database: TBD
existing_authentication: TBD
existing_mobile_apps: TBD
existing_gps_providers: []
existing_hrms_integrations: []
existing_finance_integrations: []
current_customer_count: TBD
current_vehicle_count: TBD
expected_daily_trips: TBD
expected_concurrent_users: TBD
target_countries: [India]
target_cities: TBD
primary_currency: INR
primary_locale: en-IN
primary_timezone: Asia/Kolkata
compliance_scope: [India DPDP Act, applicable transport rules, GDPR where applicable]
```

If a value is unavailable:

1. Inspect the codebase and configuration.
2. Infer only what is safe to infer.
3. Use a configurable default.
4. Record the assumption in `docs/decisions.md`.
5. Do not hard-code an irreversible decision.

Ask the user only about decisions that genuinely block implementation, such as missing credentials, unknown business rules or conflicting architecture requirements. Continue all low-risk work without waiting unnecessarily.

---

## 4. First instruction: inspect before changing anything

If an Axiom Fleet project already exists, perform a complete audit before modifying code.

Inspect:

- Repository structure
- Package managers
- Build commands
- Development and production commands
- Frontend routes and components
- Backend routes and services
- Database schema and migrations
- Authentication and authorization
- Existing roles and permissions
- Existing fleet features
- Existing GPS functionality
- Existing mobile apps
- Existing design system
- Existing environment variables
- Existing API documentation
- Existing tests
- CI/CD configuration
- Deployment configuration
- Logging and monitoring
- Feature flags
- Seed data
- Known TODOs and technical debt
- Existing data-model limitations
- Existing security issues

Create the following documents before major implementation:

```text
docs/axiom-context.md
docs/axiom-audit.md
docs/product-requirements.md
docs/architecture.md
docs/data-model.md
docs/api-contract.md
docs/event-catalog.md
docs/integration-matrix.md
docs/security-and-privacy.md
docs/threat-model.md
docs/test-strategy.md
docs/implementation-plan.md
docs/decisions.md
docs/gaps-and-risks.md
```

Do not replace an existing working system merely because a different framework is more familiar. Preserve the existing stack unless there is a documented, evidence-based reason to change it.

If the repository is empty, scaffold the product using the reference architecture in this prompt and document the choice.

---

## 5. Engineering principles

Follow these principles throughout the build:

1. **Build for correctness before cleverness.**
2. **Use explicit domain models, not hidden state.**
3. **Make every important operational change auditable.**
4. **Make all integrations replaceable through adapters.**
5. **Never hard-code one GPS, HRMS, map, SMS or payment provider.**
6. **Treat safety workflows as policy-driven, not UI-only.**
7. **Treat billing as a source-of-truth problem, not an export problem.**
8. **Use configuration for tenant-specific rules.**
9. **Prefer a modular monolith initially over unnecessary microservices.**
10. **Separate high-volume telemetry processing from transactional business logic.**
11. **Use deterministic rules for safety-critical actions.**
12. **Use AI and machine learning only where it provides measurable value.**
13. **Do not claim functionality is complete unless it has been implemented and tested.**
14. **Do not hide errors behind generic success messages.**
15. **Do not expose personal data unnecessarily.**
16. **Do not use real customer or employee PII in test data.**
17. **Do not create undocumented internal APIs that other modules depend on.**
18. **Do not leave placeholder buttons or dead screens in a production path.**
19. **Prefer reversible decisions and feature flags.**
20. **Every major architectural decision must be recorded in an ADR.**

---

## 6. Product personas and permissions

Implement role-based access control, with optional attribute-based restrictions by tenant, region, site, department and function.

### Platform roles

- Axiom super administrator
- Axiom support administrator
- Axiom implementation administrator
- Axiom finance administrator
- Axiom security administrator

### Customer roles

- Organization administrator
- Transport administrator
- Transport SPOC
- Site administrator
- Security operator
- Command-centre operator
- Fleet manager
- Maintenance manager
- Compliance manager
- Finance administrator
- Reporting-only user
- HR or HRMS integration user
- Approver
- Network buyer or procurement manager
- Network program administrator
- Network operations operator
- Network scorecard reviewer

### Vendor roles

- Vendor administrator
- Vendor dispatcher
- Vendor supervisor
- Vendor finance user
- Vendor compliance user
- Network account manager
- Network quote manager
- Network service-activation user

### Axiom platform network roles

- Axiom Network administrator
- Axiom Network sourcing or matching operator
- Axiom Network vendor-governance administrator
- Axiom Network settlement administrator
- Axiom Network support and dispute operator

### Driver roles

- Driver
- Driver supervisor
- Driver onboarding user

### Employee roles

- Employee/passenger
- Employee approver
- Employee emergency contact, if enabled

Every role must have:

- Explicit permissions
- Tenant scope
- Site scope, where applicable
- Read/write/delete/export restrictions
- PII visibility restrictions
- Audit requirements
- Mobile and web access rules

Do not rely only on frontend permission hiding. Enforce authorization in backend services and database queries.

---

## 7. Multi-tenancy and organization model

Build the product as multi-tenant from the beginning.

Required hierarchy:

```text
Axiom Platform
└── Tenant / Customer Organization
    ├── Business Units
    ├── Departments
    ├── Sites / Offices / Campuses
    ├── Cost Centres
    ├── Cities / Operating Regions
    ├── Employees
    ├── Fleets
    ├── Vendors
    ├── Policies
    ├── Integrations
    └── Reports
```

Requirements:

- Every tenant-owned record must include `tenant_id`.
- Tenant isolation must be enforced server-side.
- Users must never see data from another tenant.
- Tenant branding must be configurable.
- Tenant timezone must be configurable.
- Tenant locale and currency must be configurable.
- Tenant-specific safety policies must be configurable.
- Tenant-specific route constraints must be configurable.
- Tenant-specific booking cut-off rules must be configurable.
- Tenant-specific rate cards must be configurable.
- Tenant-specific data retention must be configurable within legal limits.
- Tenant-specific integrations must be isolated.
- Tenant-specific feature flags must be supported.

Use UUIDs or another collision-resistant identifier. Do not expose sequential database IDs where they could enable enumeration.

---

## 8. Authentication and identity

Support a staged identity model:

### Initial authentication

- Email and password, if required by the existing product
- Mobile number and OTP, if required for employees or drivers
- Secure session handling
- Refresh-token rotation
- Logout from current device
- Logout from all devices
- Password reset
- Account lockout and rate limits
- Device/session listing
- Consent capture

### Enterprise authentication

Design an adapter layer for:

- OIDC
- OAuth 2.0
- SAML SSO
- Microsoft Entra ID
- Google Workspace
- SCIM user provisioning

### MFA

Support configurable MFA for administrators and operators using:

- Authenticator applications
- Email OTP, where acceptable
- SMS OTP, where acceptable
- Passkeys, if supported by the existing identity provider

Never store plaintext passwords, OTPs or secrets.

---

## 9. Master data modules

### 9.1 Employee master

Employee fields should support:

- Internal employee ID
- Name
- Preferred name
- Work email
- Work phone
- Optional personal phone
- Department
- Business unit
- Manager
- Cost centre
- Employment status
- Work location
- City
- Timezone
- Shift assignment
- Primary and secondary pickup/drop addresses
- Geocoordinates
- Landmark
- Address validity period
- Address verification status
- Accessibility requirements, if voluntarily provided
- Emergency contacts, if enabled
- Transport eligibility
- Safety-policy classification, if legally permitted
- Consent and privacy preferences
- Data source
- Last synchronization timestamp
- Effective-from and effective-to dates

Address history must be retained according to policy. Do not overwrite historical addresses without an audit trail.

Home addresses and exact coordinates are highly sensitive. Mask them from users who do not need access.

### 9.2 Shift and work calendar

Support:

- Fixed shifts
- Rotational shifts
- Login/logout shifts
- Overnight shifts crossing midnight
- Flexible shifts
- Split shifts, if needed
- Holiday calendars
- Weekend policies
- Grace periods
- Pickup windows
- Office arrival deadlines
- Maximum commute time
- Minimum notice period
- Booking cut-off time
- Cancellation cut-off time
- Leave and absence states
- Hybrid-work schedules
- Work-from-home days
- Office closure days
- Shift overrides
- Effective dates

Time calculations must use timezone-aware timestamps. Test daylight-saving transitions for supported international regions.

### 9.3 Site and office master

Support:

- Site name
- Address
- Geocoordinates
- Geofence
- Entry points
- Pickup/drop zones
- Parking zones
- Accessibility information
- Operating hours
- Security contact
- Emergency contact
- Site-specific route rules
- Site-specific vehicle restrictions
- Site-specific arrival windows
- Site-specific visitor or access requirements

### 9.4 Vehicle master

Vehicle fields:

- Vehicle ID
- Registration number
- Vehicle type
- Make and model
- Year
- Passenger capacity
- Accessible capacity
- Luggage capacity, if relevant
- Fuel type
- EV status
- Battery capacity
- Current state of charge
- Estimated range
- Charging connector
- Charging location
- Vendor ownership
- Assigned operator
- GPS device ID
- SIM/device status
- Insurance status
- Permit status
- Fitness certificate
- Pollution certificate
- Registration expiry
- Maintenance status
- Current odometer
- Last inspection
- Next service due
- Active/inactive/blocked status
- Current city/site
- Cost rate
- Capabilities and restrictions

Vehicle registration numbers must be unique within the applicable jurisdiction and tenant scope.

### 9.5 Driver master

Driver fields:

- Driver ID
- Name
- Mobile number
- Vendor
- License number
- License category
- License expiry
- Background verification status
- Police verification status
- Medical fitness status
- Training status
- Alcohol-check status, if enabled
- Safety score
- Availability
- Duty limits
- Assigned vehicle
- Current location, only when permitted
- Emergency contact
- Preferred language
- Suspension or blacklist reason
- Effective dates

Never show a driver’s full personal information to passengers unless required by policy.

### 9.6 Vendor master

Support:

- Legal entity
- Tax details
- Contact persons
- Service cities
- Service zones
- Vehicle types
- Driver pool
- Rate cards
- SLA terms
- Insurance details
- Compliance documents
- Contract dates
- Payment terms
- Performance score
- Active/blocked status
- Escalation contacts
- API credentials through a secrets manager


### 9.7 Axiom Network master data

Axiom Network must use versioned, tenant-scoped records for the following objects. Do not store network requirements, quotes or awards only as unstructured notes.

#### Network program and operating region

Support:

- Network program name and display label
- Tenant and business-unit scope
- Operating cities, sites and service zones
- Enabled service types
- Approved vendor policy
- Vendor onboarding and renewal rules
- Quote response windows
- Award approval thresholds
- Safety and compliance minimums
- Data-sharing policy
- Contact and escalation policy
- Commercial and settlement model
- Currency, tax and effective dates
- Feature flags
- Active, paused and retired states

#### Transport requirement or RFP

Support:

- Requirement ID and human-readable reference
- Requesting tenant, business unit and site
- Requester and approvers
- Service type and recurring/ad-hoc pattern
- Origin zones or pickup clusters without exposing unnecessary exact home addresses
- Destination sites
- Operating city and service dates
- Shift windows and arrival deadlines
- Estimated passenger demand by day and shift
- Vehicle categories and capacities
- Accessibility, escort and safety requirements
- GPS, driver-app and reporting requirements
- Expected service levels
- Required insurance and compliance documents
- Commercial response format
- Budget or rate-card constraints, where permitted
- Vendor response deadline
- Evaluation criteria and weights
- Attachments and version history
- Status, approval history and audit trail

#### Vendor network profile

Support:

- Legal entity and verified contacts
- Approved operating regions and service zones
- Fleet capacity by vehicle category and time window
- Driver-pool capacity and eligibility
- Accessibility capability
- GPS and integration capability
- Safety and escalation capability
- Historical service metrics
- Rate cards and price validity
- Insurance, permits, tax and compliance evidence
- Contract and SLA status
- Replacement capacity
- Languages and support hours
- Bank and settlement references through protected finance workflows
- Suspension, probation, renewal and offboarding state

#### Quote, award and service order

Quotes must support structured line items for:

- Vehicle or route type
- Capacity and availability
- Base trip, route, hour, kilometre or monthly price
- Minimum guarantee
- Waiting time
- Toll and parking
- Escort or special-service charge
- Cancellation and no-show terms
- Tax and surcharge
- Replacement commitment
- SLA commitment
- Assumptions and exclusions
- Validity period
- Proposed start date
- Vendor contact and response timestamp

An award must reference the selected quote version, approver, reason, rejected alternatives, commercial terms, contract/SLA status and activation checklist. A service order must reference the award and create the operational configuration required by Axiom Fleet.

#### Scorecard and settlement configuration

Support versioned definitions for:

- On-time performance
- ETA accuracy
- GPS freshness and coverage
- Trip completion
- Incident rate and response
- Cancellation and rejection rate
- Complaint rate and resolution
- Invoice accuracy and variance
- Compliance completion
- Replacement performance
- Cost and utilization
- Minimum sample size and confidence rules
- Review period and weighting
- Corrective-action thresholds
- Suspension and renewal criteria
- Network or platform fees
- Settlement calendar and approval workflow

Do not expose exact employee addresses, sensitive safety attributes or competitor commercial terms to a vendor unless a documented operational need and policy permit it.

---

## 10. Geospatial foundation

Implement a map-provider abstraction so the product can use different providers without rewriting domain logic.

Capabilities:

- Address search
- Forward geocoding
- Reverse geocoding
- Geocode confidence score
- Manual pin correction
- Landmark handling
- Distance matrix
- Travel-time matrix
- Route geometry
- Traffic-aware ETA, where available
- Geofences
- Point-in-polygon checks
- Map matching
- Route deviation calculation
- Map tile rendering
- Pickup and drop-point clustering

Requirements:

- Cache geocoding carefully while respecting provider terms.
- Store provider, precision and timestamp for every geocode.
- Do not silently treat low-confidence geocodes as accurate.
- Let authorized users correct a geocode manually.
- Keep original address and normalized address separately.
- Maintain a route-provider fallback strategy.
- Show users when a location is approximate.
- Never expose exact home locations to other passengers without explicit policy approval.

---

## 11. Booking and rostering module

Support the following booking types:

- Login trip
- Logout trip
- Home-to-office trip
- Office-to-home trip
- Fixed-route shuttle booking
- Ad-hoc trip
- Corporate rental
- Airport transfer
- Guest trip
- Executive trip
- Inter-office trip
- Event transport
- Multi-day booking
- Recurring booking

Booking features:

- Create
- Edit
- Cancel
- Approve
- Reject
- Reschedule
- Duplicate for recurrence
- Import from HRMS
- Import from CSV
- Bulk upload
- Bulk cancellation
- Bulk shift change
- Employee self-service
- Admin booking
- Vendor booking, where authorized
- Cut-off validation
- Capacity validation
- Policy validation
- Duplicate-booking detection
- No-show status
- Waitlist status
- Manual override with reason

Every booking must show:

- Requester
- Passenger
- Source system
- Booking type
- Shift/date/time
- Origin
- Destination
- Stops
- Accessibility needs
- Vehicle type
- Safety requirements
- Approval status
- Assignment status
- Cancellation status
- Full audit trail

---

## 12. Route optimization engine

Build the routing engine as an independently testable component.

### 12.1 Inputs

The optimizer must support:

- Passenger pickup locations
- Passenger drop locations
- Shift times
- Pickup windows
- Office arrival deadlines
- Vehicle capacity
- Vehicle type
- Driver availability
- Driver duty limits
- Vendor availability
- Maximum passenger ride time
- Maximum route duration
- Maximum stop count
- Escort requirements
- Gender or safety policies only where legally and operationally appropriate
- Vehicle accessibility requirements
- Vehicle range and battery state
- Charging constraints
- Office and pickup geofences
- Traffic and travel-time estimates
- Fixed or locked stops
- Back-to-back trip requirements
- Cost rates
- Occupancy targets
- Emissions preferences
- Route fairness rules

### 12.2 Hard constraints

Hard constraints must not be violated unless an authorized emergency override is used:

- Vehicle capacity
- Pickup-before-drop precedence
- Driver and vehicle eligibility
- Safety policy requirements
- Maximum legal duty duration
- Mandatory office arrival deadline
- Required accessibility capability
- Vehicle availability
- Restricted vehicle zones
- EV range and charging feasibility
- Tenant policy restrictions

### 12.3 Soft constraints

Soft constraints may be traded off and must produce warnings:

- Preferred pickup time
- Preferred driver
- Preferred vendor
- Occupancy target
- Shorter distance
- Lower cost
- Lower emissions
- Balanced vendor utilization
- Balanced driver workload
- Reduced route changes
- Reduced passenger ride time

### 12.4 Objective function

Use a configurable weighted objective, for example:

```text
minimize:
  travel_time_weight * travel_time
+ distance_weight * distance
+ cost_weight * operating_cost
+ lateness_weight * lateness
+ ride_time_weight * passenger_ride_time
+ empty_seat_weight * empty_capacity
+ emissions_weight * estimated_emissions
+ imbalance_weight * vendor_or_driver_imbalance
+ manual_change_weight * route_disruption
```

Weights must be tenant-configurable but must not permit safety constraints to be converted into optional constraints.

### 12.5 Planning modes

Support:

- Batch planning
- Same-day planning
- Rolling-horizon planning
- Manual route editing
- Partial re-optimization
- Emergency re-routing
- Vehicle replacement
- Driver replacement
- Passenger cancellation
- New passenger insertion
- Fixed-stop preservation
- Route locking after boarding

### 12.6 Route plan versioning

Every route plan must have:

- Plan ID
- Version
- Created by
- Created at
- Input snapshot
- Optimization parameters
- Solver status
- Warnings
- Objective score
- Route list
- Stop order
- Vehicle assignments
- Driver assignments
- Manual changes
- Published status
- Superseded status
- Rollback capability

Manual changes must be validated before publication and must show the impact on:

- ETA
- Maximum ride time
- Capacity
- Cost
- Safety policy
- Driver duty
- Vendor distribution

### 12.7 Failure handling

If no feasible route exists:

- Do not silently produce an invalid route.
- Show the reason for infeasibility.
- Identify the conflicting constraints.
- Suggest controlled relaxations.
- Require authorized approval for relaxation.
- Place the case in an exception queue.
- Notify the relevant operator.

---

## 13. Dispatch and business distribution

Support:

- Automatic vehicle assignment
- Manual assignment
- Vendor assignment
- Vendor round-robin
- Cost-based assignment
- Proximity-based assignment
- Fairness-based assignment
- Capability-based assignment
- EV-aware assignment
- Backup vehicle assignment
- Driver acceptance timer
- Automatic reassignment
- Trip rejection reasons
- Business distribution audit trail
- Vendor SLA tracking
- Back-to-back trip allocation
- Replacement vehicle workflow

Every assignment must record:

- Assignment method
- Assigning user or system
- Assignment time
- Previous assignment
- New assignment
- Reason
- Vendor impact
- Cost impact
- Passenger impact


### 13.1 Axiom Network — controlled B2B transport exchange

Implement Axiom Network as a governed business workflow around Axiom Fleet operations. It must not be a public directory that sells unverified leads or a quoting screen disconnected from dispatch, safety and billing.

#### Network lifecycle

Implement a strict network-request state machine:

```text
DRAFT
SUBMITTED
PENDING_APPROVAL
UNDER_REVIEW
MATCHING
VENDORS_INVITED
QUOTING
QUOTE_WINDOW_CLOSED
COMPARISON_READY
NEGOTIATION
AWARDED
CONTRACT_PENDING
CONTRACTED
SERVICE_ACTIVATION
LIVE
SUSPENDED
COMPLETED
CANCELLED
EXPIRED
```

For each transition define:

- Allowed previous states
- Allowed roles
- Required fields and documents
- Deadline and expiry behavior
- Approval requirements
- Notification behavior
- Idempotency behavior
- Audit event
- Recovery or re-open path
- Data visibility rules

A request, match, quote, comparison, award and service order must be versioned. Submitted quotes must become immutable snapshots; a vendor revision creates a new version and preserves the prior submission. Do not silently overwrite a quote or evaluation.

#### Demand capture and requirement creation

Allow an authorized customer or Axiom operator to:

- Create a one-time, recurring or multi-site requirement
- Import demand from a template or API
- Define shifts, service windows and operating calendars
- Define passenger-volume ranges rather than exact employee PII where possible
- Define pickup zones, clusters and office destinations
- Specify vehicle categories, capacity and accessibility
- Specify escort, safety, GPS, driver-app and reporting requirements
- Specify start date, end date, ramp-up and ramp-down assumptions
- Specify service-level targets and replacement expectations
- Set a response deadline and award deadline
- Invite named vendors or use approved-network matching
- Attach policies, route examples and compliance requirements
- Route the request through approval thresholds
- Duplicate a prior requirement without copying stale dates or confidential data
- Cancel, pause, re-open or expire a requirement with a reason

Validate that the request contains enough information to produce comparable responses. Flag missing geocodes, conflicting time windows, impossible capacity, unsupported vehicle types and missing approvals before vendors are invited.

#### Vendor onboarding and governance

A vendor must not quote for or receive an awarded service until its configured minimum checks pass. Support:

- Invite-only registration
- Legal-entity verification
- Contact verification
- Service-area and capability declaration
- Fleet and driver capacity declaration
- Vehicle, driver, insurance, permit and tax evidence
- GPS and communication readiness
- Safety and incident-response contacts
- Bank and settlement verification through restricted finance workflows
- Contract and SLA acceptance
- Training or onboarding checklist
- Expiry reminders and renewal review
- Probation, suspension, blacklist and reinstatement states
- Replacement-capacity declaration
- Full audit trail

Allow Axiom or customer administrators to approve vendors by region, service type and tenant. A vendor approved for one tenant, city or capability must not automatically become approved everywhere.

#### Eligibility and vendor matching

Matching must use deterministic hard filters before any ranking score. Hard filters may include:

- Active tenant and region approval
- Required service dates and operating hours
- Available vehicle and driver capacity
- Vehicle category and accessibility capability
- Required permits, insurance and compliance validity
- GPS, driver-app or API capability
- Required safety and escalation coverage
- Maximum service distance or zone coverage
- Contract and commercial eligibility
- No active suspension or unresolved critical breach

Rank eligible vendors with an explainable, configurable score that may include:

- Service and capacity fit
- Coverage and proximity
- Historical on-time performance
- ETA accuracy and confidence quality
- GPS freshness and telemetry reliability
- Incident rate and response performance
- Cancellation and rejection rate
- Complaint rate and resolution quality
- Invoice accuracy and reconciliation variance
- Cost and total expected service cost
- Replacement capacity
- Compliance completeness
- Balanced utilization or fairness objectives

Use minimum sample sizes, recency weighting and confidence intervals. Do not penalize a new vendor as if it had poor performance when it has no evidence; label cold-start status and apply controlled exploration only with approval. Do not use protected or sensitive employee attributes as a vendor-ranking shortcut. Never allow price alone to override safety, legal, compliance or hard operational requirements.

Every match result must show:

- Included and excluded vendors
- Hard-filter failures and reasons
- Score components and weights
- Data freshness and sample size
- Conflicts or missing evidence
- Ranking timestamp and model/rules version
- Authorized override history

#### Structured quotes and comparison

Provide a vendor workspace for:

- Viewing only the requirements it is authorized to see
- Asking clarification questions without exposing competitor information
- Submitting structured quotes
- Declaring capacity and named assumptions
- Selecting available vehicle and service categories
- Committing to response, replacement and SLA terms
- Uploading evidence and documents
- Saving drafts before submission
- Revising before the deadline with version history
- Withdrawing a quote with a reason
- Receiving award or rejection status

Provide a buyer/operator comparison view that normalizes:

- Price units and billing periods
- Taxes and surcharges
- Toll, parking, waiting and escort charges
- Minimum guarantees
- Cancellation and no-show terms
- Capacity and availability
- SLA commitments
- Replacement terms
- Compliance and document status
- Estimated total cost
- Commercial exclusions and assumptions

Do not present a misleading single total when quotes contain incomparable assumptions. Highlight missing values, non-comparable units, expired documents and unusual commercial terms. Do not reveal a vendor's confidential quote or rank detail to another vendor.

#### Award, contract and service activation

An award must require the configured approval chain. On award:

1. Freeze the selected quote version and evaluation snapshot.
2. Record the award reason, approver and rejected alternatives.
3. Create or link a contract and SLA record.
4. Confirm commercial, tax, data-sharing and liability terms.
5. Complete vendor, vehicle, driver, GPS and safety readiness checks.
6. Create a service order with effective dates, service zones, routes, shifts and capacity.
7. Provision the corresponding Axiom Fleet roster, route and dispatch configuration.
8. Notify the vendor and customer with only the data each is authorized to receive.
9. Keep the service order in activation-pending state until all blocking checks pass.

If activation fails, show the exact blocking condition and keep the award auditable. Do not mark a vendor as live based only on a commercial award.

#### Operational handoff and fulfillment

Axiom Fleet remains the operational source of truth after activation. The handoff must support:

- Roster and booking generation
- Route planning and assignment
- Driver and vehicle eligibility
- GPS and telematics linkage
- ETA and delay monitoring
- Passenger communication
- Safety alerts and incident escalation
- Replacement vehicle or vendor workflow
- Trip completion evidence
- Billing and settlement reconciliation

Vendors must not bypass Axiom Fleet state transitions for trips that are under a governed service order. If an external vendor system is used, synchronize through versioned adapters, idempotent APIs and reconciliation jobs.

#### Communications, support and disputes

Implement tenant- and vendor-scoped communication threads for:

- Clarifications
- Quote questions
- Activation tasks
- Daily operations
- Delay and replacement coordination
- Incident support
- Invoice disputes
- Corrective actions

Support templates, attachments, delivery status, escalation timers, internal notes, redaction and audit history. Mask personal contact details where direct contact is not necessary. Define who owns the customer relationship, incident response and passenger communication; do not leave accountability ambiguous between Axiom, the customer and the vendor.

#### Performance scorecards and renewal

Generate scorecards from actual operational evidence, not only self-reported vendor ratings. Include:

- Completed trips and sample size
- On-time and late performance
- ETA prediction accuracy and confidence quality
- GPS freshness and missing-telemetry rate
- Cancellations, rejections and replacement response
- Incidents, severity and response time
- Complaints, satisfaction and resolution time
- Route and passenger compliance
- Invoice variance and reconciliation time
- Cost, utilization and empty capacity
- Document and SLA compliance

Show the measurement period, formulas, data sources and confidence. Allow vendor response and dispute without deleting the underlying evidence. Trigger coaching, corrective action, probation, suspension, renewal or offboarding according to configurable thresholds.

#### Commercial model and settlement

Keep the commercial model configurable and legally reviewable. Support, where approved:

- Customer subscription
- Platform or managed-service fee
- Per-request, per-award or per-service fee
- Configurable vendor or customer commission
- Operational management fee
- Contracted pass-through charges
- Tax and withholding rules
- Credit notes and adjustments

The system must not imply that it holds customer or vendor funds unless a separately approved payment architecture exists. Record who invoices whom, the currency, tax treatment, payment terms, settlement status and evidence required for payment. Use completed trip, GPS, boarding, route and approval evidence for settlement; keep forecast quotes and ETA estimates separate from final billing evidence.

#### Privacy and network boundaries

Apply least-privilege access at tenant, network program, request, vendor, quote and service-order level. In particular:

- Do not disclose exact employee home addresses during generic sourcing when zones or clusters are sufficient.
- Do not disclose passenger names or phone numbers to a vendor before an operational need exists.
- Do not disclose competitor quotes, score components or confidential commercial terms.
- Do not expose a vendor's full fleet or driver roster to other vendors.
- Log every export, download, quote view and data-share action.
- Apply retention and deletion rules to RFPs, quotes, contracts, communications and scorecards.

---

## 14. Trip lifecycle and state machine

Implement a strict trip state machine. Do not permit arbitrary state changes.

Suggested states:

```text
DRAFT
REQUESTED
PENDING_APPROVAL
APPROVED
ROUTE_PLANNED
ASSIGNED
DRIVER_ACCEPTED
DRIVER_REJECTED
DISPATCHED
DUTY_STARTED
VEHICLE_ARRIVING
VEHICLE_ARRIVED
BOARDING_OPEN
PASSENGER_BOARDED
TRIP_STARTED
IN_PROGRESS
DELAYED
ROUTE_DEVIATION
INCIDENT_ACTIVE
PASSENGER_DROPPED
TRIP_COMPLETED
DUTY_ENDED
CANCELLED
NO_SHOW
FAILED
RECONCILIATION_PENDING
RECONCILED
INVOICED
CLOSED
```

For each transition define:

- Allowed previous states
- Allowed roles
- Required data
- Idempotency behavior
- Audit event
- Notification behavior
- Time limit
- Recovery path
- Whether GPS evidence is required
- Whether passenger or driver verification is required

---

## 15. GPS and telematics ingestion

Build a provider-adapter layer.

Each provider adapter must normalize input into a common event schema:

```json
{
  "eventId": "uuid",
  "provider": "provider-name",
  "deviceId": "device-id",
  "vehicleId": "vehicle-id",
  "tripId": "trip-id-or-null",
  "timestamp": "2026-01-01T10:00:00Z",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "accuracyMeters": 8,
  "speedKph": 32,
  "bearingDegrees": 90,
  "ignition": true,
  "batteryPercent": 76,
  "fuelPercent": null,
  "source": "gps|mobile|telematics",
  "rawPayloadReference": "object-storage-key"
}
```

Required behavior:

- Authenticate provider requests.
- Validate signatures where available.
- Reject malformed coordinates.
- Detect impossible jumps.
- Deduplicate repeated events.
- Preserve raw payloads securely.
- Handle delayed events.
- Handle out-of-order events.
- Track provider health.
- Track last contact time.
- Detect stale GPS.
- Detect device mismatch.
- Support offline buffering.
- Support provider retry and dead-letter queues.
- Never expose raw provider credentials.

Tracking rules:

- Track driver location only during permitted duty/trip windows unless a customer policy explicitly requires more.
- Show GPS freshness to operators.
- Display approximate status when data is stale.
- Do not claim live tracking if the last location is old.
- Record the GPS source and accuracy.

---

## 16. ETA and route execution

ETA must be treated as an estimate with confidence, not a guaranteed fact.

Initial ETA should combine:

- Map-provider travel time
- Route geometry
- Current vehicle position
- Stop sequence
- Historical travel time
- Time of day
- Day of week
- Weather or event data, if available
- Recent route delay
- Driver or device freshness

Later add an ML ETA model using:

- Road segment
- Time of day
- Day of week
- Historical speed
- Traffic conditions
- Vehicle type
- Stop dwell time
- Weather
- Special events

Display:

- ETA
- Last updated time
- Confidence or freshness
- Delay versus plan
- Reason for delay, where known

### Network-specific ETA, evidence and supplier scoring

Use completed-trip telemetry and actual operational events as labels. Do not train or evaluate ETA only against a vendor's quoted duration or a prior prediction.

Implement ETA maturity in stages:

1. **Baseline:** map-provider travel time adjusted for route geometry, current position, stop sequence and data freshness.
2. **Historical profiles:** learn route, road segment, time-of-day, day-of-week, vehicle-type and stop-dwell patterns from completed trips.
3. **Live or model correction:** incorporate current traffic, recent delay, weather or event signals when available and legally/contractually permitted.
4. **Confidence-aware serving:** return a point estimate, range or confidence, prediction timestamp, last GPS timestamp, data-quality state and stale-data warning.
5. **Feedback loop:** compare prediction with actual arrival, dwell and completion events; monitor calibration, bias and drift; version models and features.

Persist enough metadata to audit every prediction:

- `predicted_at`
- `prediction_horizon`
- `predicted_arrival_at`
- `predicted_lower_bound_at` and `predicted_upper_bound_at`, where supported
- `confidence` or calibration band
- `route_plan_version`
- `model_or_rules_version`
- `last_gps_at`
- `gps_accuracy` and data-quality state
- `actual_arrival_at`
- `actual_boarding_at`, `actual_departure_at` and `actual_completion_at`, where applicable
- Error in seconds and error direction

Prevent label leakage. Freeze the feature snapshot available at prediction time, separate operational evidence from billing corrections, and do not allow a later actual arrival to change the historical prediction record.

Use ETA quality as one input to Axiom Network matching and supplier scorecards, together with on-time performance, incidents, GPS reliability, cancellations, complaints, invoice accuracy, compliance and replacement response. Apply minimum sample sizes, confidence intervals and cold-start handling. A vendor with insufficient data must be labelled as data-limited rather than automatically treated as best or worst.

A network-facing ETA response should include at least:

```json
{
  "predictedArrival": "2026-01-01T10:18:00Z",
  "confidence": 0.78,
  "range": {
    "earliest": "2026-01-01T10:15:00Z",
    "latest": "2026-01-01T10:24:00Z"
  },
  "lastGpsUpdate": "2026-01-01T10:07:12Z",
  "dataFreshness": "fresh",
  "status": "traffic_delay",
  "modelVersion": "eta-v1"
}
```

---

## 17. Employee application

The employee application may be web, PWA, native Android/iOS or cross-platform depending on the existing Axiom product.

Required screens:

- Sign in
- OTP or SSO
- Home
- Upcoming trips
- Current trip
- Trip history
- Roster
- Book a trip
- Cancel or modify trip
- Fixed-route shuttle discovery
- Seat booking
- Waitlist
- Live vehicle map
- ETA
- Driver and vehicle information according to policy
- Boarding QR or OTP
- Deboarding QR or OTP
- Co-passenger status according to privacy policy
- SOS/panic
- Safe-reach confirmation
- Feedback and rating
- Helpdesk
- Address management
- Privacy settings
- Notification settings
- Language settings
- Profile

Behavior requirements:

- Show clear booking status.
- Prevent accidental duplicate bookings.
- Explain why a booking cannot be created.
- Display cut-off times.
- Show cancellation penalties or policy information.
- Display stale GPS warnings.
- Provide accessible typography and contrast.
- Support poor network conditions.
- Queue safe non-critical actions offline.
- Never queue a safety alert silently.
- Display emergency contacts prominently.
- Do not expose other passengers' personal data unnecessarily.

---

## 18. Driver application

Required screens:

- Sign in and device verification
- Duty list
- Assigned trips
- Route and stop sequence
- Passenger manifest with privacy controls
- Navigation handoff
- Vehicle inspection
- Driver fitness confirmation
- Alcohol check, if enabled
- Start duty
- Arrive at pickup
- Boarding OTP/QR
- No-show workflow
- Start trip
- Route deviation warning
- Passenger drop confirmation
- End trip
- End duty
- Breakdown report
- SOS/panic
- Contact control centre
- Offline mode
- Trip history
- Earnings or payment summary, if applicable

No-show rules must require configurable time and geofence conditions. Drivers must not be able to mark a passenger as a no-show without appropriate evidence or an authorized override.

Location permissions and background tracking must be clearly explained to drivers.

---

## 19. Admin and control-centre portal

Required modules:

### Operations dashboard

- Active trips
- Upcoming trips
- Delayed trips
- Unassigned trips
- GPS-stale vehicles
- Incidents
- Driver rejections
- Vehicle breakdowns
- Capacity exceptions
- Route deviations
- No-shows
- Vendor SLA breaches
- System health

### Live map

- Vehicle markers
- Trip status colors
- Route geometry
- Planned versus actual route
- Stop sequence
- Geofences
- Incidents
- Stale GPS indicators
- Filtering by tenant/site/vendor/city/status
- Marker clustering
- Vehicle detail drawer
- Trip detail drawer
- Audit link

### Route planner

- Upload/import demand
- Filter by shift/site
- Run plan
- Show progress
- Display infeasibility explanations
- Manual edit
- Lock route or stop
- Recalculate
- Compare plan versions
- Publish
- Roll back
- Export manifests

### Assignment board

- Unassigned trips
- Driver acceptance
- Vehicle replacement
- Vendor allocation
- Capacity issues
- Exceptions
- Bulk reassignment

### Safety centre

- Active alerts
- Alert severity
- Acknowledgement
- Escalation timer
- Incident owner
- Employee and driver contact options
- Map context
- Evidence
- Timeline
- Resolution
- Root cause
- Corrective action
- Closure approval

### Axiom Network operations

- Open requirements and RFP deadlines
- Vendor eligibility and compliance exceptions
- Match-run progress and excluded-vendor reasons
- Quote response status and clarification threads
- Comparison and approval queue
- Award and contract/SLA activation blockers
- Service-order readiness
- Vendor replacement and capacity exceptions
- Network scorecard and corrective-action queue
- Settlement and dispute queue
- Network-level audit and data-sharing history

---

## 20. Safety and incident management

Build a configurable safety-policy engine.

Alert types may include:

- SOS/panic
- Route deviation
- Unauthorized stop
- Long stop
- Speeding
- Harsh driving, if telematics supports it
- GPS stale
- Vehicle breakdown
- Driver rejection
- Missed pickup
- Missed drop
- Late arrival
- Unsafe drop location
- Unverified safe reach
- Geofence violation
- Device tampering
- Passenger no-show dispute
- Vehicle compliance expiry
- Driver compliance expiry

Incident severity:

```text
P0 — Immediate safety risk
P1 — Serious operational or safety risk
P2 — Significant service issue
P3 — Informational or low-risk issue
```

For every alert define:

- Trigger
- Severity
- Notification recipients
- Acknowledgement deadline
- Escalation path
- Required evidence
- Resolution criteria
- Audit requirement
- Retention period

Safety actions must be deterministic and testable. Do not allow a generative AI system to autonomously close or downgrade a critical safety incident.

---

## 21. Notifications and communication

Implement a notification abstraction supporting:

- In-app notifications
- Push notifications
- SMS
- Email
- WhatsApp or approved messaging provider
- Voice or IVR, if required
- Admin alerts
- Driver alerts
- Employee alerts
- Vendor alerts

Features:

- Tenant-specific templates
- Localization
- Template versioning
- Delivery status
- Retry policy
- Idempotency
- Deduplication
- Quiet hours
- Emergency override
- Opt-in and opt-out where legally required
- Transactional versus marketing separation
- Delivery audit
- Provider health monitoring

Do not place sensitive data in notification text unless required.

---

## 22. Billing and reconciliation

Support flexible pricing models:

- Per trip
- Per kilometre
- Per hour
- Per vehicle
- Per passenger
- Per route
- Fixed monthly fee
- Vendor rate card
- Overtime
- Waiting time
- Toll
- Parking
- Escort
- Special vehicle
- Cancellation
- No-show
- Tax and surcharge
- Cost-centre allocation

Billing workflow:

```text
Trip completed
→ GPS and event validation
→ Distance and time calculation
→ Rate-card application
→ Exceptions and adjustments
→ Vendor invoice upload
→ Automated reconciliation
→ Human approval where required
→ Cost-centre allocation
→ Customer invoice/export
→ Payment status
→ Audit closure
```

Requirements:

- Immutable invoice versions
- Credit notes
- Manual adjustment with reason
- Approval thresholds
- Rate-card effective dates
- Tax configuration
- Currency support
- Rounding rules
- Duplicate invoice detection
- GPS-versus-invoice variance
- Export to CSV, Excel and API
- Finance-system integration
- Complete audit history

Never alter historical billing values without creating a new version or adjustment record.

### Network billing and settlement extensions

For Axiom Network, preserve the commercial chain:

```text
Requirement / RFP
→ Quote version
→ Award
→ Contract and SLA
→ Service order
→ Completed operational evidence
→ Vendor invoice or platform charge
→ Reconciliation
→ Approval
→ Settlement / customer invoice
```

Requirements:

- Link every charge to a tenant, network program, request, quote version, award, service order and operational evidence where applicable.
- Keep quoted, contracted, accrued, invoiced, approved, paid and disputed amounts separate.
- Compare vendor invoices with Axiom Fleet trip, GPS, route, boarding, cancellation and adjustment evidence.
- Apply effective-dated rate cards and contract terms; never retroactively rewrite an accepted quote.
- Support partial acceptance, disputed lines, credit notes, replacement-service charges and manual adjustments with approval.
- Show fees, commissions or managed-service charges separately from pass-through transport charges.
- Keep customer and vendor settlement views separate and role-restricted.
- Do not use predicted ETA, uncompleted bookings or unverified vendor claims as final billing evidence.
- Include network-specific reconciliation, dispute and settlement metrics in audit logs and reports.

---

## 23. Analytics and reporting

Create a shared metric-definition layer so every dashboard uses the same definitions.

Required KPIs:

- On-time arrival
- On-time departure
- Pickup punctuality
- Drop punctuality
- Vehicle utilization
- Seat utilization
- Occupancy
- Cost per trip
- Cost per passenger
- Cost per kilometre
- Empty kilometres
- Average ride time
- Maximum ride time
- Route distance
- Planned versus actual distance
- GPS freshness
- Route-deviation rate
- Driver acceptance rate
- Driver rejection rate
- No-show rate
- Cancellation rate
- Incident count
- Incident response time
- Incident resolution time
- Compliance completion
- Expired-document count
- Vendor SLA performance
- Billing variance
- Invoice reconciliation time
- Fuel consumption
- EV kilometres
- Estimated emissions
- Employee satisfaction
- Driver satisfaction

Support:

- Real-time dashboards
- Historical reports
- Date and timezone filters
- Tenant/site/city/vendor filters
- Drill-down from KPI to trip
- Scheduled reports
- CSV/XLSX/PDF export
- Role-based report visibility
- Report versioning
- Saved filters
- Report subscriptions
- Data freshness indicators

Every metric must have a documented definition and calculation formula.

### Axiom Network metrics

Add network metrics with documented formulas, data sources and freshness:

- Active requirements and RFPs
- Vendor invitation rate
- Quote response rate
- Time to first quote
- Time to comparison-ready
- Time to award
- Award conversion rate
- Requirement-to-service activation rate
- Vendor coverage by city, site, shift and vehicle type
- Match eligibility and exclusion reasons
- Quote comparability rate
- Quote spread and total-cost variance
- Service activation failure rate
- Vendor acceptance and rejection rate
- Replacement response time
- On-time performance by vendor and service order
- ETA error, calibration and stale-data rate
- GPS coverage and freshness by vendor
- Incident and complaint rate
- Invoice accuracy and reconciliation variance
- Dispute aging
- Vendor concentration and dependency risk
- Customer and vendor satisfaction
- Renewal, suspension and offboarding rate

Do not combine quote funnel metrics with completed-trip quality metrics. Dashboards must distinguish forecast, contracted, operational and financially verified values.

---

## 24. EV and sustainability module

Support optional EV operations:

- EV vehicle flag
- Battery capacity
- Current state of charge
- Estimated range
- Minimum reserve range
- Charging station
- Charging duration
- Charging availability
- Charger connector type
- Energy consumption
- Energy cost
- Green kilometres
- Fuel avoided
- Emissions estimate
- EV route eligibility
- EV route assignment
- Charging conflict detection

Do not assign an EV to a route unless the system can verify feasible range plus configured reserve and charging constraints.

---

## 25. Integrations

Use adapters and versioned contracts.

### HRMS and attendance

Support:

- Employee create/update/deactivate
- Department and manager sync
- Shift sync
- Leave and absence sync
- Work-location sync
- Hybrid-work schedule sync
- Cost-centre sync
- Full sync
- Incremental sync
- Webhook sync
- CSV/SFTP fallback
- Error reporting
- Field mapping
- Conflict resolution
- Reconciliation report

### Axiom Network and partner integrations

Support versioned adapters for:

- Approved vendor onboarding and compliance systems
- Vendor fleet, driver, GPS and dispatch systems
- Vendor quote submission and service-status APIs
- Contract, procurement and e-signature systems, where approved
- Finance, ERP and accounts-payable systems
- Customer support and case-management systems
- Communication and collaboration providers
- Document storage and verification services

Partner integrations must support scoped credentials, tenant and vendor authorization, webhook signing, idempotency, replay, reconciliation, field mapping, rate limits, schema versioning and manual retry. Never give a vendor broad access to another vendor's records or to the tenant's entire employee master.

### GPS and telematics

Support multiple providers through the normalized event model defined earlier.

### Finance and ERP

Support:

- Cost centres
- Vendor invoices
- Expense categories
- Trip charges
- Tax details
- Payment status
- Purchase orders, if applicable
- Journal or export integration

### Maps and traffic

Support provider abstraction for:

- Geocoding
- Distance matrices
- Route geometry
- Traffic ETA
- Map tiles

### Identity and workplace

Support adapters for:

- OIDC
- SAML
- Microsoft Entra ID
- Google Workspace
- Microsoft 365
- Slack
- Access-control systems
- Parking barriers

### EV charging

Support an adapter interface for:

- Charger availability
- Charging status
- Session start/end
- Energy consumption
- Vehicle state of charge

### Integration reliability

Every integration must have:

- Credentials in a secrets manager
- Health check
- Retry policy
- Exponential backoff
- Dead-letter queue
- Idempotency key
- Correlation ID
- Request and response audit metadata
- Rate-limit handling
- Schema versioning
- Alerting
- Replay capability
- Reconciliation process
- Manual retry interface

---

## 26. Public API standards

Implement versioned APIs, initially under `/api/v1`.

API requirements:

- OpenAPI specification
- Authentication and authorization
- Tenant context
- Pagination
- Filtering
- Sorting
- Search
- Field selection where useful
- Idempotency keys for writes
- Correlation IDs
- Consistent error format
- Request validation
- Rate limits
- API key or OAuth client management
- Webhook subscriptions
- Webhook signing
- Replay protection
- Deprecation policy
- Audit metadata

Suggested endpoint groups:

```text
/auth
/tenants
/users
/roles
/organizations
/sites
/departments
/cost-centres
/employees
/addresses
/shifts
/holidays
/vehicles
/drivers
/vendors
/compliance
/bookings
/rosters
/shuttles
/routes
/route-plans
/dispatch
/trips
/tracking
/geofences
/incidents
/notifications
/billing
/invoices
/reports
/integrations
/network/programs
/network/requests
/network/vendors
/network/matches
/network/quotes
/network/comparisons
/network/awards
/network/contracts
/network/service-orders
/network/communications
/network/scorecards
/network/settlements
/webhooks
/audit
```

Standard error shape:

```json
{
  "error": {
    "code": "ROUTE_CAPACITY_EXCEEDED",
    "message": "The requested route exceeds the vehicle capacity.",
    "details": {},
    "correlationId": "uuid",
    "retryable": false
  }
}
```

---

## 27. Data model standards

Every tenant-owned table should support, where applicable:

```text
id
 tenant_id
created_at
created_by
updated_at
updated_by
version
deleted_at
status
```

Additional requirements:

- Use foreign keys.
- Define unique constraints.
- Define indexes based on actual query patterns.
- Use temporal/effective dates for changing policies.
- Avoid storing derived values without a source or recalculation rule.
- Keep immutable event records for important transitions.
- Use an outbox pattern for reliable event publication.
- Use soft deletion only where legally and operationally appropriate.
- Maintain data classification.
- Separate PII from operational records where feasible.
- Encrypt especially sensitive fields.
- Redact PII in logs.
- Define retention and deletion policies.
- Define archival strategy.
- Define backup and restoration behavior.

Required documentation:

- ER diagram
- Field dictionary
- Relationship map
- State-transition diagrams
- Data-classification matrix
- Retention matrix
- Event catalog
- Migration strategy

### 27.1 Axiom Network data-model requirements

At minimum, model these entities separately rather than embedding them in a generic booking note:

- `network_program`
- `network_operating_region`
- `network_vendor_profile`
- `network_vendor_approval`
- `transport_requirement`
- `requirement_version`
- `vendor_invitation`
- `match_run`
- `match_candidate`
- `quote`
- `quote_version`
- `quote_line_item`
- `quote_evaluation`
- `comparison_snapshot`
- `award`
- `contract`
- `sla`
- `service_order`
- `service_activation_check`
- `network_message`
- `network_scorecard`
- `network_metric_observation`
- `corrective_action`
- `settlement_statement`
- `network_dispute`

Each entity must include tenant and scope checks, lifecycle status, effective dates, actor and timestamp metadata, versioning and audit linkage as appropriate. A quote evaluation must point to the exact quote version and scoring-rules version used. A scorecard metric must identify its observation window, source events, calculation version and sample size. A service order must link commercial terms to the Axiom Fleet operational objects it activated.

Define and document network events such as:

- `network_requirement_submitted`
- `network_vendor_invited`
- `network_match_completed`
- `network_quote_submitted`
- `network_quote_revised`
- `network_quote_window_closed`
- `network_award_approved`
- `network_contract_activated`
- `network_service_order_activated`
- `network_service_order_suspended`
- `network_scorecard_published`
- `network_corrective_action_opened`
- `network_settlement_approved`
- `network_dispute_opened`

Every event must include tenant, program, actor or system source, correlation ID, entity version, occurred-at time, data-classification label and idempotency or deduplication key where applicable.

Protect or isolate:

- Employee addresses and contact details
- Vendor bank and tax information
- Competitor quotes
- Internal scoring weights where disclosure creates abuse risk
- Contract documents
- Safety and incident evidence
- GPS histories

Use immutable snapshots for submitted requirements, quotes, comparisons, awards and settlement approvals. Do not derive historical commercial or performance reports from mutable current vendor profiles.

---

## 28. Security and privacy

Implement security as a product requirement, not a final audit task.

### Application security

- OWASP protections
- Input validation
- Output encoding
- SQL injection protection
- XSS protection
- CSRF protection
- SSRF protection
- Secure file uploads
- Malware scanning where appropriate
- Rate limits
- Brute-force protection
- Account lockout
- Secure headers
- CORS restrictions
- Content Security Policy
- Dependency scanning
- Secret scanning
- SAST
- DAST
- SBOM generation

### Authorization

- Server-side RBAC
- Optional ABAC
- Tenant isolation
- Site and region scope
- PII masking
- Export permission
- Bulk-operation permission
- Break-glass access with audit
- Support impersonation only with explicit approval and logging

### Encryption

- TLS in transit
- Encryption at rest
- Managed key service where available
- Key rotation
- Secret rotation
- Encrypted backups
- Secure mobile storage
- No secrets in source control
- No credentials in logs

### Privacy

Support processes for:

- Privacy notice
- Consent, where applicable
- Purpose limitation
- Data minimization
- Data access
- Data correction
- Data export
- Data deletion
- Processing restriction
- Retention and deletion
- Sub-processor management
- Cross-border transfer documentation
- Data breach response
- DPIA for high-risk features

Do not introduce facial recognition, biometrics, voice recognition or driver monitoring without an explicit product decision, consent model, legal review, security review and customer approval.

### Axiom Network security controls

In addition to general platform security:

- Enforce bid, quote, evaluation and contract confidentiality at the API and database-query layers.
- Prevent vendor-to-vendor data access, identifier enumeration and inference through response timing or error messages.
- Scope every network request, quote, award, service order, document and message to tenant, program and authorized parties.
- Require step-up authentication or explicit approval for award, suspension, settlement and bulk-export actions where configured.
- Log quote views, downloads, exports, scoring overrides, vendor approvals, data shares and commercial changes.
- Apply malware scanning, file-type validation, retention and access controls to compliance and contract documents.
- Redact personal addresses and phone numbers from logs, analytics and vendor exports.
- Treat matching and scorecard rules as configuration changes requiring review, versioning and rollback.

For India, evaluate the Digital Personal Data Protection framework and relevant transport and workplace obligations. For international customers, evaluate GDPR and applicable local requirements. This prompt is not legal advice; obtain qualified counsel before making compliance claims.

---

## 29. User experience requirements

Use the existing Axiom design system if one exists. If it does not, create a coherent design system.

Requirements:

- Responsive web experience
- Mobile-first employee and driver flows
- WCAG 2.2 AA target
- Keyboard navigation
- Screen-reader labels
- Correct focus management
- Accessible error messages
- Sufficient color contrast
- Do not use color as the only status indicator
- Clear empty states
- Clear loading states
- Clear error states
- Retry actions
- Confirmation for destructive actions
- Undo where safe
- Unsaved-change warning
- Bulk-operation progress
- Pagination or virtualization for large tables
- Search and filtering
- Saved views
- Consistent date, time and timezone display
- Localization-ready strings
- No hard-coded text in code
- en-IN and Asia/Kolkata support initially
- INR formatting initially
- Internationalization-ready architecture
- Dark mode only if it can be implemented accessibly

Do not copy the visual style, layouts or interaction patterns of Legacy Dispatch Platform, Legacy ETS Platform or another competitor pixel-for-pixel.

### Axiom Network experience

Provide separate, role-appropriate surfaces for:

- Customer requirement creation and approval
- Vendor discovery and eligibility status
- RFP invitation and response
- Structured quote entry
- Buyer comparison and evaluation
- Award and contract activation
- Service-order readiness
- Operational handoff to dispatch and control centre
- Vendor scorecard and corrective action
- Invoice and settlement dispute

Show the current network stage, owner, deadline, blocking conditions, data freshness and next action. Never make a quote look like a confirmed booking or make a commercial award look like an operationally ready service. Keep competitor information, employee PII and internal scoring detail hidden unless policy explicitly permits it.


---

## 30. Performance and reliability requirements

Use configurable targets rather than hard-coding assumptions. Establish baseline targets for:

- API p50 and p95 latency
- Login latency
- Dashboard load time
- Live-map refresh latency
- GPS-event ingestion throughput
- Notification delivery time
- Route-plan generation time
- Route re-optimization time
- Billing calculation time
- Report generation time
- Network match-run time
- Network quote-comparison time
- Network notification and deadline processing time
- Concurrent operators
- Concurrent employees
- Concurrent drivers
- Daily trips
- Daily GPS events
- Storage growth

Default engineering targets for the pilot should be documented and validated, for example:

- Most normal API reads: p95 under 500 ms under expected pilot load
- Critical state changes: p95 under 1 second excluding external provider delay
- Live-location freshness: clearly displayed and provider-dependent
- No duplicate trip events after retries
- Route generation with visible progress and timeout handling
- No silent data loss during queue or provider failure
- RPO target documented
- RTO target documented
- Backup restoration tested

Reliability features:

- Health endpoints
- Readiness and liveness checks
- Circuit breakers
- Timeouts
- Retries with backoff
- Dead-letter queues
- Idempotency
- Graceful degradation
- Queue monitoring
- Database backups
- Disaster recovery
- Feature flags
- Safe rollback
- Maintenance windows

---

## 31. Observability

Implement:

- Structured logs
- Correlation IDs
- Trace IDs
- Request metrics
- Error metrics
- Queue-lag metrics
- GPS freshness metrics
- Integration health metrics
- Notification delivery metrics
- Solver metrics
- Network match and quote-funnel metrics
- Network deadline and activation metrics
- ETA calibration and supplier-scorecard metrics
- Billing variance metrics
- Security events
- Audit events
- Admin activity logs

Create dashboards for:

- API health
- Background jobs
- GPS ingestion
- Route optimization
- Notifications
- Database health
- Queue health
- Integration health
- Security incidents
- Business KPIs

Alert on:

- High error rates
- Failed deployments
- Stale GPS across many vehicles
- Queue backlog
- Failed integrations
- Solver timeouts
- Cross-tenant authorization errors
- Unusual export volume
- Repeated login failures
- Billing discrepancies
- Notification failures

---

## 32. Testing strategy

Create automated tests at several layers.

### Unit tests

- Domain rules
- State transitions
- Permission checks
- Pricing calculations
- Timezone conversions
- Geofence calculations
- ETA calculations
- Notification selection
- Compliance expiry
- Billing reconciliation

### Integration tests

- Database
- Queue/event bus
- GPS provider adapters
- HRMS adapters
- Map providers
- Notification providers
- Finance adapters
- Authentication providers

### API contract tests

- OpenAPI validation
- Webhook signing
- Backward compatibility
- Idempotency
- Error formats
- Pagination
- Rate limits

### Route-engine tests

Create golden datasets with synthetic data and expected properties.

Test:

- Capacity overflow
- Pickup-before-drop precedence
- Maximum ride time
- Arrival windows
- Driver duty limits
- Vehicle restrictions
- Escort requirement
- Back-to-back trips
- EV range
- Charging conflict
- Route locking
- Manual edits
- Partial re-optimization
- No feasible route
- Solver timeout
- Duplicate addresses
- Low-confidence geocodes
- Overnight shifts
- Same location multiple passengers
- No-shows
- Last-minute cancellations
- New passenger insertion

Use property-based tests where possible:

- No route exceeds capacity.
- Every passenger is assigned at most once.
- Every assigned passenger is on exactly one valid route.
- Pickup occurs before drop.
- Hard constraints are never violated.
- Published routes are reproducible from their plan version.

### End-to-end tests

Test complete workflows:

1. Create tenant
2. Create site
3. Create employees
4. Import shifts
5. Geocode addresses
6. Create bookings
7. Generate route plan
8. Publish plan
9. Assign vehicle and driver
10. Start duty
11. Receive GPS events
12. Board passengers
13. Trigger delay
14. Raise SOS
15. Resolve incident
16. Complete trip
17. Reconcile invoice
18. Generate report

### Security tests

- Cross-tenant access
- Broken object-level authorization
- Privilege escalation
- Token replay
- Rate-limit bypass
- File upload abuse
- Injection attacks
- Export permission abuse
- PII leakage in logs
- Webhook forgery
- GPS event spoofing

### Other tests

- Load testing
- Soak testing
- Chaos testing
- Offline mobile testing
- Low-bandwidth testing
- Accessibility testing
- Browser compatibility
- Device compatibility
- Timezone and DST testing
- Backup restoration
- Migration rollback
- Disaster recovery

### Axiom Network tests

Test at minimum:

- Tenant and program isolation
- Vendor approval and document expiry
- Hard eligibility filters
- Explainable match ranking
- Cold-start and insufficient-sample handling
- Quote draft, submission, revision and immutability
- Quote deadline and late-submission behavior
- Incomparable quote units and missing assumptions
- Competitor-quote confidentiality
- Award approval and rejected-alternative audit
- Contract and SLA activation checks
- Service-order provisioning into Axiom Fleet
- Vendor suspension and replacement capacity
- Message authorization and redaction
- Scorecard calculation from actual trip evidence
- ETA prediction logging, calibration and actual-versus-predicted feedback
- Invoice, fee, tax and settlement reconciliation
- Dispute, credit-note and corrective-action workflows
- Network request cancellation, expiry and re-opening

Use synthetic data only. Never commit real employee names, addresses, phone numbers, GPS histories, credentials or invoice information.

---

## 33. DevOps and delivery

Create separate environments:

```text
development
staging
production
```

Use:

- Environment-specific configuration
- Secret management
- Database migrations
- Seed data
- Feature flags
- CI checks
- Automated tests
- Build artifacts
- Deployment approvals
- Rollback plan
- Database backup before migration
- Infrastructure-as-code where practical
- Containerized services where practical
- Dependency lockfiles
- Reproducible builds

CI should fail on:

- Build errors
- Type errors
- Lint errors, unless explicitly waived
- Test failures
- Security scanning failures above agreed severity
- Broken migrations
- OpenAPI mismatch
- Accessibility regression in critical flows
- Missing environment validation

Every release must produce:

- Version number
- Changelog
- Migration notes
- Rollback notes
- Test summary
- Known limitations
- Deployment status

---

## 34. Initial product priorities

### Axiom Network MVP and roadmap

The first Axiom Network release must be a closed B2B pilot, preferably in one dense operating region such as Bengaluru after validation. The MVP must prove operational fulfillment, not only marketplace demand generation.

#### Axiom Network MVP

Include:

- Tenant- and region-scoped network configuration
- Invite-only approved-vendor onboarding
- Compliance and capability checks
- Employer requirement/RFP creation and approval
- Deterministic vendor eligibility and explainable matching
- Structured quote submission and versioned comparison
- Award, contract/SLA record and activation checklist
- Service-order handoff into Axiom Fleet route, roster and dispatch workflows
- GPS, ETA, safety and incident linkage
- Replacement and exception workflow
- Evidence-backed billing and vendor settlement reconciliation
- Basic scorecard with on-time, ETA, GPS, incident, cancellation, complaint and invoice metrics
- Audit logs, role restrictions, privacy controls and operational dashboards

Defer until the controlled MVP is reliable:

- Public vendor registration
- Consumer or unmanaged marketplace flows
- Anonymous lead resale
- Autonomous pricing or award decisions
- Financial escrow or wallet features without separate legal and payment architecture
- Unbounded multi-country expansion
- Vendor ranking based only on reviews or only on price

#### Axiom Network expansion

After the MVP demonstrates fulfillment quality:

- Multi-city and multi-tenant network operations
- More vendor and telematics adapters
- Capacity forecasting and controlled replacement pools
- Advanced ETA and demand models
- Procurement and e-signature integrations
- Configurable platform and managed-service monetization
- Customer self-service renewals
- Network-wide benchmark reports with privacy protections
- EV and emissions-aware supplier selection
- Carefully governed partner ecosystem

### P0 — required for first usable pilot

- Multi-tenancy
- Authentication
- RBAC
- Organization and site setup
- Employee and shift master
- Fleet, driver and vendor master
- Geocoding
- Booking and roster management
- Fixed and dynamic trip planning
- Basic optimization
- Vehicle and driver assignment
- Driver application or driver workflow
- Employee trip visibility
- GPS ingestion
- Live operations dashboard
- SOS and incident workflow
- Basic compliance
- Basic billing
- Audit logs
- One HRMS integration
- Axiom Network closed-B2B MVP slice when enabled for the pilot: approved vendors, requirements, matching, structured quotes, award, service activation and operational handoff
- One GPS integration
- OpenAPI documentation
- Automated tests

### P1 — enterprise readiness

- Multi-city operations
- Advanced vendor distribution
- Axiom Network multi-vendor comparison, contract/SLA workflows, scorecards, replacement capacity and settlement controls
- Back-to-back optimization
- Detailed compliance workflows
- Billing reconciliation
- Cost-centre reporting
- Advanced dashboards
- Route version comparison
- Partial re-optimization
- Offline driver app
- SSO
- Data export and retention controls
- Disaster recovery
- Performance and load testing

### P2 — expansion and intelligence

- ML ETA
- Demand forecasting
- EV optimization
- Axiom Network expansion beyond the controlled pilot, with confidence-aware supplier scoring and advanced network analytics
- Emissions reporting
- Corporate rentals
- Parking management
- Metro or multimodal integration
- Workplace management
- Driver behaviour analytics
- Natural-language analytics assistant
- AI support assistant
- Advanced anomaly detection

Do not allow P2 features to delay the P0 pilot.

---

## 35. Implementation process for the coding agent

Follow this sequence.

### Step 1 — Audit

Inspect the existing project and produce the audit documents.

### Step 2 — Plan

Produce:

- Architecture proposal
- Module map
- Data model
- API map
- Event catalog
- Integration plan
- Security plan
- Test plan
- Phased delivery plan

### Step 3 — Establish foundations

Implement or validate:

- Local development
- Environment configuration
- Database migrations
- Authentication
- Tenant context
- RBAC
- Audit logging
- Error handling
- Observability
- Test harness

### Step 4 — Build vertical slices

Do not build isolated screens without backend behavior. Implement end-to-end slices such as:

1. Employee import → shift → booking → route plan
2. Route plan → assignment → driver view → GPS → live dashboard
3. Trip completion → billing calculation → reconciliation
4. SOS → command centre alert → escalation → incident closure
5. Axiom Network requirement → vendor matching → structured quotes → award → contract/SLA → service order → operational fulfillment → scorecard and settlement

### Step 5 — Validate

Run tests, load tests, security checks and manual acceptance testing.

### Step 6 — Document

Update all architecture, API, data, operational and user documentation.

### Step 7 — Report honestly

At the end of every work cycle, report:

- What was inspected
- What was implemented
- What was tested
- What passed
- What failed
- What remains incomplete
- What assumptions were made
- What risks remain
- What the next recommended action is

Never state “complete” if there are unimplemented placeholders, disabled security controls or untested critical workflows.

---

## 36. Required documentation deliverables

The final product must include:

- Product requirements document
- Architecture document
- Context and container diagrams
- Deployment diagram
- ER diagram
- Data dictionary
- API documentation
- Webhook documentation
- Event catalog
- Integration guides
- Route-engine specification
- Safety-policy specification
- Billing specification
- Axiom Network product and operating-model specification
- Axiom Network request, matching, quote, award and service-order specification
- Vendor-governance and onboarding guide
- Matching, ETA and supplier-scorecard specification
- Network commercial, dispute and settlement specification
- Network privacy and data-sharing matrix
- Security architecture
- Threat model
- Privacy and data-retention document
- Role-permission matrix
- UX flow documentation
- Mobile-app behavior guide
- Admin operations guide
- Driver operations guide
- Customer onboarding guide
- Vendor onboarding guide
- Incident-response runbook
- GPS troubleshooting runbook
- Billing-reconciliation runbook
- Backup and disaster-recovery runbook
- Deployment runbook
- Support runbook
- Test strategy
- Test evidence
- Changelog
- Known issues
- ADRs

---

## 37. Definition of done

Axiom Fleet is not ready for a pilot until all of the following are true:

- A clean checkout can install and run the project.
- Environment variables are documented.
- Database migrations work from an empty database.
- Seed data is available for a demo tenant.
- Authentication works.
- Tenant isolation is tested.
- Roles and permissions are enforced server-side.
- Employees can be created or imported.
- Vehicles, drivers and vendors can be managed.
- Shifts can be configured.
- Bookings can be created, modified and cancelled.
- Addresses can be geocoded and corrected.
- Routes can be planned.
- Hard constraints are enforced.
- Route plans are versioned.
- Manual edits are audited.
- Routes can be published.
- Vehicles and drivers can be assigned.
- Driver workflow is usable.
- Employee trip workflow is usable.
- GPS data can be ingested through an adapter.
- Live operations can see current trips.
- Stale GPS is visibly identified.
- SOS and incident escalation are functional.
- Trip completion is recorded.
- Billing can be calculated.
- Billing exceptions are visible.
- Reports can be generated.
- Notifications can be delivered and audited.
- Critical APIs are documented in OpenAPI.
- Critical workflows have automated tests.
- Cross-tenant security tests pass.
- Accessibility issues in critical workflows are addressed.
- Logs do not leak sensitive PII.
- Backups are configured.
- Restore testing is documented.
- Production deployment is repeatable.
- Known limitations are explicitly documented.

### Axiom Network definition of done

When Axiom Network is enabled for a pilot, it is not ready until:

- The module is clearly named and presented as Axiom Network within Axiom Fleet.
- Network access is feature-flagged and tenant/program scoped.
- The pilot is closed and invite-only unless a documented approval changes that policy.
- Vendor approval, capability, compliance and suspension states are enforced server-side.
- A customer can create, approve, revise, cancel and audit a transport requirement.
- Matching applies hard eligibility filters before explainable ranking.
- A buyer can compare normalized, versioned quotes without misleading totals.
- A vendor cannot see competitor quotes or unauthorized employee PII.
- Awards require configured approval and preserve the evaluation snapshot.
- A contract/SLA and service-order record can be activated into Axiom Fleet.
- Service activation blocks on missing safety, compliance, capacity or integration checks.
- Operational trips, GPS, ETA, incidents and replacements remain in Axiom Fleet source-of-truth workflows.
- ETA predictions record confidence, freshness, model/rules version and actual outcome feedback.
- Scorecards use completed-trip evidence, sample sizes and documented formulas.
- Invoices, fees, taxes, adjustments, disputes and settlements are auditable.
- Network messages, document access, exports and commercial overrides are logged.
- Network-specific automated, security, privacy and end-to-end tests pass.

---

## 38. Final instruction

Build Axiom Fleet, including the Axiom Network module when enabled, as an original, secure, configurable and operationally credible product.

Do not build a superficial dashboard that merely displays vehicles on a map. Do not build Axiom Network as a superficial lead marketplace that stops at a vendor quote.

Build the complete operational system:

```text
People
+ Shifts
+ Addresses
+ Vehicles
+ Drivers
+ Vendors
+ Axiom Network requirements and quotes
+ Contracts and service orders
+ Routes
+ Trips
+ GPS and ETA
+ Safety
+ Compliance
+ Billing and settlement
+ Analytics and scorecards
+ Integrations
+ Auditability
```

The primary success criteria are:

- Safe transportation
- Reliable trips
- Explainable route decisions
- Accurate live visibility
- Strong tenant isolation
- Correct billing
- Configurable enterprise workflows
- Controlled, accountable supplier network execution
- Operational accountability
- Measurable cost and utilization improvement
- Maintainable software
- Independent product identity

When uncertain, prefer the solution that is:

1. Safer
2. More auditable
3. More privacy-preserving
4. More configurable
5. More integration-friendly
6. Easier to test
7. Easier to operate
8. Easier to replace or extend later
