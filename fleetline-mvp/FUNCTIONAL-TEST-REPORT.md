# Axiom Fleet functional and performance test report

Date: 1 October 2026

## Scope

The local fallback product was exercised through the complete checked-in smoke,
contract, calculation, security, driver, domain, finance, network, corporate,
enterprise, Phase 1/2 and Phase 3 test surface. Tests used isolated temporary
SQLite databases unless they explicitly checked the normal local runtime.

## Results

- **35/35 test programs passed**.
- `regression_check.py`: **139/139 checks passed**.
- Golden calculation suite: **1,000/1,000 cases passed**.
- Supabase parity contract checks passed.
- Driver PWA/native replay and contract checks passed.
- Production-boundary security smoke passed.
- Normal local runtime database verified empty of legacy/demo users and
  organizations.

The suite included all checked-in `*_test.py` programs, including the added
`phase3_concurrency_test.py` and the extended enterprise booking-control GET
coverage.

## Performance checks

Measured against an isolated local server with a fresh SQLite database and an
authenticated tenant:

| Surface | Load | Result |
|---|---:|---:|
| Health endpoint | 100 concurrent requests | p95 9.0 ms; 100/100 HTTP 200 |
| Authenticated identity | 100 concurrent requests | p95 238.9 ms; 100/100 HTTP 200 |
| Enterprise booking-control list | 50 concurrent requests | p95 206.8 ms; 50/50 HTTP 200 |
| Full dashboard hydration GET inventory | 117 concurrent GET requests | 0.697 s wall time; p95 228.8 ms; no 5xx responses |
| Phase 3 first-load burst | 48 concurrent requests | 48/48 HTTP 200 |
| Driver signup writes | 5 sequential signups | approximately 46 ms median, 48 ms maximum |

The 409 responses in the full dashboard inventory were intentional
`corporate_account_required` responses for vendor accounts requesting corporate
account-only collections; they were not server errors and are already handled
by the dashboard's `Promise.allSettled` loading path.

## Issues found and fixed

1. **Enterprise booking controls GET returned HTTP 500**
   - Cause: the local handler called `_list()` without its required organization
     argument.
   - Fix: pass the authenticated organization to `_list()`.
   - Regression coverage: enterprise smoke test now creates a rule and reads it
     back through `GET /api/enterprise/booking-controls`.

2. **Concurrent first-load Phase 3 requests could return HTTP 409**
   - Cause: multiple dashboard requests could race while creating the default
     region under the organization/region unique constraint.
   - Fix: make default-region creation idempotent with `INSERT OR IGNORE` and
     return the row that wins the race.
   - Regression coverage: `phase3_concurrency_test.py` verifies 48 concurrent
     requests and exactly one default region.

3. **Connection backlog caused avoidable latency under request bursts**
   - Cause: the standard threaded HTTP server inherited a very small accept
     queue.
   - Fix: add `AxiomFleetHTTPServer` with address reuse and a 128-request
     backlog.
   - Result: health p95 improved from approximately 1.2 seconds under the
     initial burst test to 9 ms.

## Remaining boundary

Remote Supabase execution, external provider credentials, and production
infrastructure were not live-tested because no project credentials are
configured in the workspace. Local and contract coverage for those boundaries
passed without claiming production connectivity.
