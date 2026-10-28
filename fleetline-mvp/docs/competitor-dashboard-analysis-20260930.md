# Corporate dashboard and partner-network review

**Review date:** 30 September 2026  
**Scope:** Axiom Fleet corporate console, Axiom Network, Legacy Rental Platform corporate positioning and public product walkthroughs.

## Executive conclusion

The supplied screenshot is a recovery state, not a credible corporate control room. It has a strong shell—brand, workspace selector, search, branch context and a compact navigation rail—but the main surface becomes one oversized error card with a large amount of unused space. The visible sidebar counters (`24`, `P0`, `6`, `12`) are especially damaging when the data request has failed: they read as demo records rather than trustworthy tenant metrics. A corporate operator should either see a dense, action-oriented control room or a deliberate tenant-access state; never a half-populated dashboard.

Axiom Fleet should keep its own visual language and not copy Legacy Rental Platform's interface. The improvement is to make the first screen an operational cockpit: approval queue, upcoming movements, supplier/network health, invoice state, policy readiness and audit activity, all sourced from the current tenant APIs. Empty states must explain the next action and unavailable measurements must stay as `—`.

## What the Legacy Rental Platform corporate page communicates well

The corporate page emphasizes five workflows that must be visible in a corporate product:

1. **Employee self-service and booking for others** — employees can request/manage trips, while travel desks can book for colleagues.
2. **Supplier and booking control** — a centralized booking surface, configurable approval workflows, supplier allotment and real-time supplier updates.
3. **Operational proof and safety** — digital duty slips, route/timing transparency, live tracking and SOS/panic support.
4. **Finance confidence** — centralized invoice intake, automated validation, reports, expense prediction, duty-level evidence and environmental reporting.
5. **Enterprise readiness** — regional admin capabilities, integrations and SSO/security positioning.

Source: [Legacy Rental Platform for Corporates](https://legacyfleet.example.com/for-corporates).

### What is useful versus what Axiom Fleet can improve

| Area | Legacy Rental Platform signal | Axiom Fleet response |
|---|---|---|
| First screen | Centralized booking and administration | Make approvals, upcoming trips and unresolved decisions the first view, not a generic KPI wall |
| Supplier operations | Allotment, SLAs and supplier updates | Add supplier state and partner actions to the corporate overview, linked to the invite-only Network |
| Finance | Invoice verification, duty-slip evidence and predictions | Keep source-linked bills, proof and audit references visible; never show a financial number without tenant data |
| Regional operations | Regional admin controls | Keep tenant/branch scope explicit in the shell and filter every card by that scope |
| Safety | Live tracking and SOS | Surface active safety signals and the recovery path without inventing live locations |
| Employee experience | Self-service booking and booking for others | Make “Request a booking” and “Book for someone else” first-class actions |

## Legacy Rental Platform Network walkthrough findings

The 4:15 public walkthrough is an older, simple partner workflow. Its visible sequence is:

1. Open Network and find a listed, verified car-rental company.
2. Add the company as an associate or accept an association request.
3. Contact the associate to discuss rates/capabilities.
4. Send and receive booking requests and duty slips through the network.
5. Receive notifications for new requests, acceptance, allotment and duty-slip updates.
6. Send driver/vehicle and completed-duty information back to the associate.
7. Review changes in a duty activity section; unread events can also produce email/SMS alerts.

Source: [Legacy Rental Platform Network — An introduction](https://www.youtube.com/watch?v=OTTmH-f6O8Y).

The driver walkthrough reinforces the expected execution loop: accept a duty, view reporting details, start/stop the duty with meter readings, collect a passenger signature, add billable items and attach receipt evidence. Source: [How to use the Legacy Rental Platform Go Driver app](https://www.youtube.com/watch?v=UfExvakMqgY).

### Network comparison

| Capability | Legacy Rental Platform Network evidence | Axiom Fleet current foundation | Product decision |
|---|---|---|---|
| Partner discovery | Listed verified companies and associate relationships | Invite-only vendor profiles and partner invites | Keep closed B2B; add a clearer partner directory and connection status |
| Request exchange | Booking requests, accept/decline and notifications | Versioned requirements, matching and vendor quotes | Present the lifecycle as `Invite → qualify → request → quote → approve → Fleet service order` |
| Data exchange | Booking requests, duty slips and invoices | Fleet-linked service orders and canonical duties/finance | Do not create a second trip ledger; show the handoff and source record explicitly |
| Privacy | Contact details are shared only after association | Confidential quotes and buyer-scoped comparison are already modeled | Make the access boundary visible in the UI |
| Quality control | Vendor SLAs/delivery rules are advertised on the corporate page | Capability/compliance filters, scorecards, evidence and audit contracts exist | Expose SLA health, rejection reasons and corrective actions in the Network page |
| Financial closure | Duty slips/invoices pass through the network | Finance, bill review, payout and reconciliation foundations exist | Add a visible rate-check/discrepancy/settlement stage, without autonomous payment |
| Auditability | Activity/notifications are described | Axiom Fleet has audit references, idempotency and tenant RLS | Make each Network event traceable to an audit reference and canonical Fleet record |

**Conclusion:** Axiom Fleet's backend contract is broader than the public Network walkthrough, but the current UI hides that advantage. The redesign should improve information architecture and state visibility rather than copy Legacy Rental Platform's older visual treatment.

## Additional benchmark signals

A current Indian car-rental operations benchmark, Caarzoo, presents the complete operating chain as booking → car/driver allocation → documents → trip execution → invoice. It also makes vendor dispatch, digital acceptance, rate verification, live updates and a vendor scorecard explicit. This is a useful information-architecture benchmark, not a design to copy. Source: [Caarzoo](https://caarzoo.com/).

## Changes applied to Axiom Fleet

- Corporate overview redesigned around live approvals, upcoming movements, tenant invoice state, supplier/network coverage, policy readiness and recent audit activity.
- Dashboard metrics distinguish collection counts (`0`) from unavailable measurements (`—`).
- Recovery state now explains organization-linked access failures and provides a sign-in path instead of leaving a blank workspace.
- Static sidebar/demo counters were not introduced; shell counts remain API/state-derived.
- Network overview retains invite-only B2B scope and exposes the stronger Axiom lifecycle instead of pretending to be an open marketplace.
- No third-party proprietary copy, code or visual assets were copied.
