from pathlib import Path
import gzip
import re, struct, sys, json, urllib.request
from bs4 import BeautifulSoup

ROOT = Path('/home/user/fleetline-mvp')
HTML_PATH = ROOT / 'index.html'
html = HTML_PATH.read_text()
soup = BeautifulSoup(html, 'html.parser')
checks = []
def check(name, ok, detail=''):
    checks.append((name, bool(ok), detail))

# HTTP / delivery checks
for url, expected_type in [
    ('http://127.0.0.1:4173/', 'text/html'),
    ('http://127.0.0.1:4173/axiom-fleet-logo.png', 'image/png'),
    ('http://127.0.0.1:4173/api/health', 'application/json'),
]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read()
            ctype = r.headers.get_content_type()
            check(f'HTTP {url}', r.status == 200 and ctype == expected_type,
                  f'status={r.status}, type={ctype}, bytes={len(body)}')
    except Exception as e:
        check(f'HTTP {url}', False, repr(e))

# Optimized delivery checks
try:
    request = urllib.request.Request('http://127.0.0.1:4173/', headers={'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(request, timeout=5) as response:
        compressed = response.read()
        decoded = gzip.decompress(compressed)
        check('gzip delivery for HTML', response.headers.get('Content-Encoding') == 'gzip' and decoded == html.encode(),
              f'encoding={response.headers.get("Content-Encoding")}, compressed={len(compressed)}, raw={len(decoded)}')
except Exception as e:
    check('gzip delivery for HTML', False, repr(e))

# Document structure
check('HTML doctype', html.lstrip().lower().startswith('<!doctype html>'))
check('document language', soup.html and soup.html.get('lang') == 'en')
check('viewport meta', bool(soup.find('meta', attrs={'name':'viewport'})))
check('single title', len(soup.find_all('title')) == 1 and 'AXIOM FLEET' in soup.title.get_text())
ids = [x.get('id') for x in soup.find_all(attrs={'id': True})]
dups = sorted({i for i in ids if ids.count(i) > 1})
check('unique static IDs', not dups, ', '.join(dups))

# Required application surfaces
required_ids = ['public-site','public-pages','public-page-content','auth-screen','app-shell','login-form','login-email','login-password','toggle-password','forgot-password','signup-form','signup-role','signup-name','signup-email','signup-phone','signup-city','signup-organization','signup-gstin','signup-size','signup-license','signup-password','impact-range','demo-form','demo-form-note','drawerBackdrop','modalBackdrop','mobileMenu','notificationsBtn','helpBtn','profileBtn','logoutBtn','globalSearch']
missing = [i for i in required_ids if soup.find(id=i) is None]
check('required static IDs present', not missing, ', '.join(missing))

# Logo integration and local assets
logo_imgs = soup.find_all('img', src='axiom-fleet-logo.png')
check('official logo used in six surfaces', len(logo_imgs) == 6, f'found={len(logo_imgs)}')
check('logo images have alt text', all(i.get('alt','').strip() for i in logo_imgs))
logo_path = ROOT / 'axiom-fleet-logo.png'
check('logo asset exists', logo_path.is_file(), '')
check('logo asset non-trivial', logo_path.stat().st_size > 10000, str(logo_path.stat().st_size))
if logo_path.is_file():
    png_header = logo_path.read_bytes()[:24]
    png_width, png_height = struct.unpack('>II', png_header[16:24])
    check('optimized logo dimensions', (png_width, png_height) == (640, 184), f'{png_width}x{png_height}')
    check('optimized logo under 100KB', logo_path.stat().st_size < 100000, str(logo_path.stat().st_size))

# Route model
required_routes = ['about-us','blogs','newsroom','careers','contact-us','success-stories','terms','privacy','disclaimer','refund']
template_keys = re.findall(r"^\s*'([^']+)': `", html, re.M)
check('all requested public templates declared', all(r in template_keys for r in required_routes), f'missing={[r for r in required_routes if r not in template_keys]}')
check('template count is 10', len(template_keys) == 10, f'count={len(template_keys)}')
# Main nav/footer references should expose every route.
public_refs = set(re.findall(r'data-public-page="([^"]+)"', html))
check('all requested routes linked from public UI', set(required_routes).issubset(public_refs), f'missing={sorted(set(required_routes)-public_refs)}')

# Routing / auth guards present in source
check('backend API health route is wired', 'route == "/api/health"' in Path(ROOT / 'server.py').read_text())
check('app route is protected by backend session', "if (!currentUser && !(await restoreSession())) { showLogin(updateHash); return; }" in html)
check('hashchange route handling', "window.addEventListener('hashchange'" in html and "else if (publicPageTemplates[route]) showPublicPage(route, false);" in html)
check('all three signup roles are available', all(role in html for role in ('value=\"vendor\"','value=\"driver\"','value=\"corporate\"')))
check('signup exposes a complete timezone selector', 'id=\"signup-timezone\"' in html and 'Intl.supportedValuesOf' in html and 'IANA_TIMEZONE_FALLBACK' in html)
check('dashboard greeting uses the authenticated name and timezone', 'workspaceGreeting()' in html and 'currentUser?.full_name' in html and 'timeZone: userTimeZone()' in html)
check('driver surfaces use authenticated profile identity', 'state.user?.full_name' in (ROOT / 'driver-app/index.html').read_text() and 'Airport transfer</h2>' not in (ROOT / 'driver-app/index.html').read_text())
server_source = Path(ROOT / 'server.py').read_text()
check('server validates and persists profile timezone', 'available_timezones' in server_source and 'profile_timezone' in server_source and 'validate_timezone' in server_source)
check('normal runtime purges legacy fixture records', 'purge_demo_records' in server_source and 'if not test_fixtures_enabled()' in server_source)
check('prototype credentials are not rendered publicly', 'admin@blueorbit.in' not in html and 'motion2026' not in html)
check('httpOnly session cookie is implemented', 'HttpOnly' in server_source)
check('static serving uses an explicit public allowlist', 'PUBLIC_FILES' in server_source and 'Directory listing is disabled' in server_source and 'raw_path.relative_to(ROOT.resolve())' in server_source)
check('password reset has hashed expiring one-time tokens', 'token_hash(raw_token)' in server_source and 'expires_at > ?' in server_source and 'used_at IS NULL' in server_source)
check('mock payments are disabled in production by default', 'AXIOM_ALLOW_MOCK_PAYMENTS' in server_source and 'payment_provider_required' in server_source)
check('payment webhooks require HMAC and replay protection', 'hmac.compare_digest' in server_source and 'handle_verified_payment_webhook' in (ROOT / 'backend_extended.py').read_text() and 'invalid_webhook_signature' in server_source)
edge_sources = [p.read_text() for p in (ROOT / 'supabase/functions').glob('*/index.ts')]
check('Supabase Edge CORS is configured rather than wildcard', all('Access-Control-Allow-Origin": "*"' not in source for source in edge_sources) and all('AXIOM_ALLOWED_ORIGIN' in source for source in edge_sources if 'Access-Control-Allow-Methods' in source))

# Interaction bindings / key source contracts
source_contracts = {
    'login submit binding': "document.getElementById('login-form').addEventListener('submit'",
    'signup submit binding': "document.getElementById('signup-form').addEventListener('submit'",
    'backend request helper': "async function apiRequest(path, options = {})",
    'password visibility toggle': "document.getElementById('toggle-password').addEventListener('click'",
    'forgot password feedback': "document.getElementById('forgot-password').addEventListener('click'",
    'calculator input update': "impactRange.addEventListener('input', updateImpact)",
    'demo form submission': "document.getElementById('demo-form').addEventListener('submit'",
    'public page interaction binding': 'function bindPublicPageInteractions(scope = document)',
    'logout clears backend session': "apiRequest('/api/auth/logout', { method: 'POST' })",
    'dashboard render path': 'function render()'
}
for name, needle in source_contracts.items():
    check(name, needle in html)

# Static images and anchors
all_local_img_src = []
for img in soup.find_all('img'):
    src = img.get('src','')
    if src and not src.startswith(('data:', 'http:', 'https:')):
        all_local_img_src.append(src)
missing_img = [src for src in all_local_img_src if not (ROOT/src).is_file()]
check('all local image sources resolve', not missing_img, ', '.join(missing_img))
local_script_srcs = [script.get('src') for script in soup.find_all('script', src=True) if script.get('src') and not script.get('src').startswith(('http:', 'https:'))]
missing_scripts = [src for src in local_script_srcs if not (ROOT / src).is_file()]
check('all local scripts resolve', not missing_scripts, ', '.join(missing_scripts))
migration_path = ROOT / 'supabase/migrations/20260919000000_axiom_fleet_foundation.sql'
check('Supabase migration is present', migration_path.is_file())
openapi_path = ROOT / 'openapi.yaml'
check('OpenAPI contract is present', openapi_path.is_file() and 'openapi: 3.1.0' in openapi_path.read_text() and '/api/bookings/recurring:' in openapi_path.read_text() and '/api/security/2fa/setup:' in openapi_path.read_text())
mobile_contract_path = ROOT / 'mobile_driver_contract_test.py'
check('Driver mobile vertical slice is present', mobile_contract_path.is_file() and (ROOT / 'driver-app' / 'index.html').is_file() and (ROOT / 'mobile-driver' / 'App.tsx').is_file())
if migration_path.is_file():
    migration = migration_path.read_text()
    required_domain_contracts = ('create policy customers_member_select', 'create policy sync_operations_user_access', 'create or replace function public.transition_duty', 'create or replace function public.issue_invoice', 'create or replace function public.record_payment', 'create or replace function public.record_expense', 'create or replace function public.enqueue_sync_operation', 'create or replace function public.create_invitation', 'create or replace function public.accept_invitation', 'create table if not exists public.employees', 'create table if not exists public.support_tickets', 'create table if not exists public.einvoice_records', 'create table if not exists public.collection_actions', 'create table if not exists public.onboarding_states', 'create table if not exists public.supplier_bills', 'create table if not exists public.cost_entries', 'create table if not exists public.approval_steps', 'create table if not exists public.network_edges', 'create table if not exists public.report_exports', 'create table if not exists public.retention_locks', 'create policy einvoice_records_billing_write', 'create policy collection_actions_billing_write')
    check('Supabase domain/RLS/RPC contracts are present', all(contract in migration for contract in required_domain_contracts))
network_migration_path = ROOT / 'supabase/migrations/20260922000000_axiom_network_mvp.sql'
check('Axiom Network migration is present', network_migration_path.is_file())
if network_migration_path.is_file():
    network_migration = network_migration_path.read_text()
    network_contracts = (
        'create table if not exists public.network_programs',
        'create table if not exists public.network_requirements',
        'create table if not exists public.network_requirement_versions',
        'create table if not exists public.network_vendor_profiles',
        'create table if not exists public.network_match_runs',
        'create table if not exists public.network_quote_versions',
        'create table if not exists public.network_comparisons',
        'create table if not exists public.network_awards',
        'create table if not exists public.network_activation_checks',
        'create table if not exists public.network_service_orders',
        'create table if not exists public.network_scorecards',
        'create table if not exists public.network_settlements',
        'create or replace function public.network_activate_award',
        'network_quote_versions_tenant_access',
        'network_requirements_tenant_access'
    )
    check('Axiom Network Supabase/RLS/RPC contracts are present', all(contract in network_migration for contract in network_contracts))
network_backend_path = ROOT / 'backend_network.py'
check('local Axiom Network handler is present', network_backend_path.is_file() and 'def handle_network' in network_backend_path.read_text())
check('Network smoke contract test is present', (ROOT / 'network_mvp_smoke_test.py').is_file())
check('Supabase adapter exposes Network v1 boundary', 'supabaseNetworkRequest' in (ROOT / 'supabase/client.js').read_text() and "path.startsWith('/api/network/v1')" in (ROOT / 'supabase/client.js').read_text())
network_collaboration_migration = ROOT / 'supabase/migrations/20260930090000_network_exchange_feedback_delivery.sql'
network_collaboration_sql = network_collaboration_migration.read_text() if network_collaboration_migration.is_file() else ''
network_edge = ROOT / 'supabase/functions/network-orchestrator/index.ts'
network_markers = ('public.network_partner_directory', 'public.network_associates', 'public.network_contract_versions', 'public.network_rate_cards', 'public.network_exchange_envelopes', 'public.network_sla_observations', 'public.network_supplier_issues', 'public.network_rate_discrepancies', 'public.network_settlement_resolutions')
check('Network collaboration migration covers directory, contracts, exchanges and resolution workflows', network_collaboration_migration.is_file() and all(marker in network_collaboration_sql for marker in network_markers) and 'enable row level security' in network_collaboration_sql and 'network_invites_vendor_access' in network_collaboration_sql)
check('Network production orchestrator and mock exchange adapter are present', network_edge.is_file() and 'network-orchestrator' in (ROOT / 'supabase/client.js').read_text() and all(marker in network_edge.read_text() for marker in ('partner-directory', 'network_exchange_envelopes', 'sla-observations', 'rate-discrepancies', 'settlement-resolutions')))
check('Network collaboration smoke coverage is present', (ROOT / 'network_mvp_smoke_test.py').is_file() and all(marker in (ROOT / 'network_mvp_smoke_test.py').read_text() for marker in ('verified partner directory', 'exchange envelope', 'supplier SLA breach', 'settlement resolution')))
p0_backend_path = ROOT / 'backend_p0.py'
p0_migration_path = ROOT / 'supabase/migrations/20260923000000_axiom_p0_foundations.sql'
p0_client = (ROOT / 'supabase/client.js').read_text()
check('P0 local handler is wired', p0_backend_path.is_file() and 'def handle_p0' in p0_backend_path.read_text() and 'handle_p0(conn' in (ROOT / 'server.py').read_text())
check('P0 Supabase migration is present', p0_migration_path.is_file() and 'create table if not exists public.p0_route_plans' in p0_migration_path.read_text() and 'p0_audit_row' in p0_migration_path.read_text())
check('P0 Supabase adapter mappings are present', 'supabaseP0Request' in p0_client and 'p0-orchestrator' in p0_client and '/api/permissions' in p0_client)
check('P0 Planning/Safety UI wiring is present', 'handlePlanningAction' in html and 'handleSafetyAction' in html and 'data-planning-action' in html and 'data-safety-action' in html)
check('P0 smoke coverage is present', (ROOT / 'p0_smoke_test.py').is_file())
check('focused uncovered smoke coverage is present', (ROOT / 'uncovered_smoke_test.py').is_file())
check('security regression smoke coverage is present', (ROOT / 'security_smoke_test.py').is_file() and 'RESULT security smoke test passed' in (ROOT / 'security_smoke_test.py').read_text())
security_sql_path = ROOT / 'supabase/migrations/20260930000000_axiom_security_hardening.sql'
security_sql = security_sql_path.read_text() if security_sql_path.is_file() else ''
webhook_function_path = ROOT / 'supabase/functions/webhook-gateway/index.ts'
webhook_function = webhook_function_path.read_text() if webhook_function_path.is_file() else ''
vercel_path = ROOT / 'vercel.json'
vercel_json = vercel_path.read_text() if vercel_path.is_file() else ''
check('security hardening parity contracts are present', security_sql_path.is_file() and all(marker in security_sql for marker in ('mfa_satisfied_for_role', 'trg_prevent_direct_calculation_snapshot_mutation', 'expenses_amount_business_limit', 'duty_proofs_otp_format')))
check('Supabase privileged MFA uses native Auth AAL2', 'supabase_auth_mfa' in (ROOT / 'supabase/client.js').read_text() and '/factors/' in (ROOT / 'supabase/client.js').read_text() and 'mock_verification_code' not in (ROOT / 'supabase/client.js').read_text())
check('multi-provider webhook signing boundary is present', webhook_function_path.is_file() and all(marker in webhook_function for marker in ('payment', 'sms', 'whatsapp', 'telephony', 'crypto.subtle', 'constantTimeEqual', 'webhook_events')))
check('deployment clickjacking and CSP headers are declared', vercel_path.is_file() and all(marker in vercel_json for marker in ('Content-Security-Policy', 'frame-ancestors', 'X-Frame-Options', 'DENY', 'Strict-Transport-Security')))
phase12_backend = ROOT / 'backend_phase12.py'
phase12_migration = ROOT / 'supabase/migrations/20260924000000_axiom_phase12_foundations.sql'
phase12_client = (ROOT / 'supabase/client.js').read_text()
check('Phase 1/2 local handler is wired', phase12_backend.is_file() and 'def handle_phase12' in phase12_backend.read_text() and 'handle_phase12(conn' in (ROOT / 'server.py').read_text())
phase12_sql = phase12_migration.read_text() if phase12_migration.is_file() else ''
check('Phase 1/2 migration is present', phase12_migration.is_file() and 'create table if not exists public.phase12_master_records' in phase12_sql and 'phase12_master_records' in phase12_sql and 'organization_id is not null' in phase12_sql and 'is_platform_user()' in phase12_sql)
phase12_function = ROOT / 'supabase/functions/phase12-orchestrator/index.ts'
check('Phase 1/2 Supabase boundary mappings are present', 'phase12-orchestrator' in phase12_client and '/api/mobile/home' in phase12_client and '/api/operations/live-board' in phase12_client and phase12_function.is_file() and 'RLS' in phase12_function.read_text() and 'idempotency_key' in phase12_function.read_text())
check('Phase 1/2 UI state and workflows are present', 'state.phase12Data' in html and 'renderLoadingState' in html and 'openSavedViewModal' in html and 'Mobile operations home' in html)
check('Phase 1/2 smoke coverage is present', (ROOT / 'phase12_smoke_test.py').is_file())
phase3_backend = ROOT / 'backend_phase3.py'
phase3_migration = ROOT / 'supabase/migrations/20260925000000_axiom_phase3_moat.sql'
phase3_function = ROOT / 'supabase/functions/phase3-orchestrator/index.ts'
phase3_client = (ROOT / 'supabase/client.js').read_text()
phase3_sql = phase3_migration.read_text() if phase3_migration.is_file() else ''
phase3_contracts = ('phase3_predictive_alerts', 'phase3_vendor_quality_snapshots', 'phase3_simulations', 'phase3_variance_findings', 'phase3_sustainability_trips', 'phase3_regions', 'phase3_exchange_rates')
phase3_routes = ('/api/phase3/predictive-alerts', '/api/phase3/vendor-quality/graph', '/api/phase3/simulations', '/api/phase3/variance/findings', '/api/phase3/sustainability/summary', '/api/phase3/regions')
check('Phase 3 local handler is wired', phase3_backend.is_file() and 'def handle_phase3' in phase3_backend.read_text() and 'handle_phase3(conn' in (ROOT / 'server.py').read_text())
check('Phase 3 migration and tenant RLS are present', phase3_migration.is_file() and all(f'public.{name}' in phase3_sql for name in phase3_contracts) and 'has_permission' in phase3_sql and 'p0_audit_row' in phase3_sql)
check('Phase 3 authenticated Edge/browser boundary is present', phase3_function.is_file() and 'phase3-orchestrator' in phase3_client and 'supabasePhase3Request' in phase3_client and 'getUser' in phase3_function.read_text() and all(route in phase3_function.read_text() for route in phase3_routes))
check('Phase 3 UI intelligence surface is present', 'data-page="phase3"' in html and 'function renderPhase3()' in html and 'state.phase3Data' in html and 'handlePhase3Action' in html)
check('Phase 3 OpenAPI routes are declared', openapi_path.is_file() and all(route in openapi_path.read_text() for route in phase3_routes))
check('Phase 3 smoke coverage is present', (ROOT / 'phase3_smoke_test.py').is_file() and 'RESULT Phase 3 smoke test passed' in (ROOT / 'phase3_smoke_test.py').read_text())
check('Phase 3 documentation and production gates are present', (ROOT / 'docs/phase3-moat.md').is_file() and 'Supabase production boundary' in (ROOT / 'docs/phase3-moat.md').read_text() and 'physical Android' in (ROOT / 'docs/phase3-moat.md').read_text())
bill_backend = ROOT / 'backend_bill_intelligence.py'
bill_migration_path = ROOT / 'supabase/migrations/20260929000000_axiom_bill_intelligence.sql'
bill_function_path = ROOT / 'supabase/functions/bill-intelligence-orchestrator/index.ts'
bill_client = (ROOT / 'supabase/client.js').read_text()
bill_sql = bill_migration_path.read_text() if bill_migration_path.is_file() else ''
bill_function = bill_function_path.read_text() if bill_function_path.is_file() else ''
check('Bill intelligence local handler is wired', bill_backend.is_file() and 'def handle_bill_intelligence' in bill_backend.read_text() and 'handle_bill_intelligence(conn' in (ROOT / 'server.py').read_text() and (ROOT / 'bill_intelligence_smoke_test.py').is_file())
check('Bill intelligence additive schema and RLS are present', bill_migration_path.is_file() and all(f'public.{name}' in bill_sql for name in ('bill_intelligence_records','bill_intelligence_postings','bill_intelligence_fuel_entries','bill_intelligence_timeline')) and 'bill_intelligence.read' in bill_sql and 'organization_id is not null' in bill_sql)
check('Bill intelligence Supabase Edge/browser boundary is present', bill_function_path.is_file() and 'bill-intelligence-orchestrator' in bill_client and 'supabaseBillIntelligenceRequest' in bill_client and 'getUser' in bill_function and 'supplier_bills' in bill_function)
check('Bill intelligence protected Finance UI is present', 'AI bill reading' in html and 'openBillUploadModal' in html and 'openBillReviewModal' in html and 'state.billData' in html and 'data-page="finance"' in html)
check('Bill intelligence OpenAPI and parity docs are present', openapi_path.is_file() and '/api/bill-intelligence/summary:' in openapi_path.read_text() and (ROOT / 'docs/bill-intelligence.md').is_file() and 'Supabase production parity' in (ROOT / 'docs/bill-intelligence.md').read_text())
operations_backend = ROOT / 'backend_operations_parity.py'
operations_migration = ROOT / 'supabase/migrations/20260930020000_operations_parity_slice.sql'
operations_function = ROOT / 'supabase/functions/operations-orchestrator/index.ts'
operations_client = (ROOT / 'supabase/client.js').read_text()
check('Operations parity local handler is wired', operations_backend.is_file() and 'def handle_operations_parity' in operations_backend.read_text() and 'handle_operations_parity(conn' in (ROOT / 'server.py').read_text())
check('Operations parity migration and RLS are present', operations_migration.is_file() and all(f'public.{name}' in operations_migration.read_text() for name in ('booking_batches','booking_batch_rows','allotment_decisions','duty_closures','closure_evidence')) and 'submit_duty_closure' in operations_migration.read_text())
check('Operations parity Edge/browser boundary is present', operations_function.is_file() and 'operations-orchestrator' in operations_client and 'createBatch' in operations_function.read_text() and 'deterministic' in operations_function.read_text())
check('Operations parity OpenAPI/docs/smoke coverage is present', all(token in openapi_path.read_text() for token in ('/api/bookings/batches:', '/api/availability/evaluate:', '/api/bookings/{booking_id}/allot:', '/api/duties/{duty_id}/close:')) and (ROOT / 'docs/operations-parity-slice.md').is_file() and (ROOT / 'operations_parity_smoke_test.py').is_file())
booking_backend = ROOT / 'backend_booking_parity.py'
booking_migration = ROOT / 'supabase/migrations/20260930100000_booking_allotment_pricing_parity.sql'
booking_invoice_migration = ROOT / 'supabase/migrations/20260930101000_booking_invoice_fuel_surcharge.sql'
booking_function = ROOT / 'supabase/functions/booking-orchestrator/index.ts'
booking_client = (ROOT / 'supabase/client.js').read_text()
booking_sql = booking_migration.read_text() if booking_migration.is_file() else ''
check('Booking/allotment/pricing local handler is wired', booking_backend.is_file() and 'def handle_booking_parity' in booking_backend.read_text() and 'handle_booking_parity(conn' in (ROOT / 'server.py').read_text() and (ROOT / 'booking_allotment_smoke_test.py').is_file())
check('Booking/allotment/pricing additive schema and RLS are present', booking_migration.is_file() and booking_invoice_migration.is_file() and all(name in booking_sql for name in ('booking_request_keys','booking_action_events','booking_dispatches','network_vendor_profile_id','temporary_passengers','temporary_allotments','booking_pricing_contracts','booking_pricing_rules','customer_fuel_surcharge_rules','fuel_rate_history')) and 'enable row level security' in booking_sql and 'bookings.lifecycle' in booking_sql)
check('Booking/allotment/pricing Edge/browser boundary is present', booking_function.is_file() and 'booking-orchestrator' in booking_client and all(marker in booking_function.read_text() for marker in ('booking_request_keys','booking_action_events','allotment_mode','network_vendor_profiles','contractType','customer_fuel_surcharge_rules','temporary_allotments')))
check('Booking/allotment/pricing OpenAPI/docs/UI coverage is present', all(token in openapi_path.read_text() for token in ('/api/bookings/import:', '/api/bookings/{bookingId}/allot-all:', '/api/pricing/contracts:', '/api/fuel-surcharge-rules:', '/api/duties/{dutyId}/arrival:')) and (ROOT / 'docs/booking-allotment-pricing-parity.md').is_file() and all(token in html for token in ('openBookingActionsModal','openPricingContractModal','data-booking-field="booking_type"','/api/bookings/import')))
finance_backend = ROOT / 'backend_finance_parity.py'
finance_migration = ROOT / 'supabase/migrations/20260930030000_finance_reporting_parity_slice.sql'
finance_function = ROOT / 'supabase/functions/finance-reporting-orchestrator/index.ts'
finance_client = (ROOT / 'supabase/client.js').read_text()
check('Finance/reporting local handler is wired', finance_backend.is_file() and 'def handle_finance_parity' in finance_backend.read_text() and 'handle_finance_parity(conn' in (ROOT / 'server.py').read_text())
check('Finance/reporting migration and RLS/RPC are present', finance_migration.is_file() and all(f'public.{name}' in finance_migration.read_text() for name in ('invoice_runs','dunning_actions','report_definitions','export_profiles')) and 'generate_invoice_run' in finance_migration.read_text() and 'run_dunning_run' in finance_migration.read_text())
check('Finance/reporting Edge/browser boundary is present', finance_function.is_file() and 'finance-reporting-orchestrator' in finance_client and 'generate_invoice_run' in finance_function.read_text() and 'ageing' in finance_function.read_text())
check('Finance/reporting OpenAPI/docs/smoke coverage is present', all(token in openapi_path.read_text() for token in ('/api/invoices/generate:', '/api/reports/ageing:', '/api/reports/definitions:', '/api/export-profiles:')) and (ROOT / 'docs/finance-reporting-parity-slice.md').is_file() and (ROOT / 'finance_reporting_smoke_test.py').is_file())
followon_migration = ROOT / 'supabase/migrations/20260930080000_finance_reporting_feedback_followon.sql'
followon_finance_function = ROOT / 'supabase/functions/finance-controls-orchestrator/index.ts'
followon_feedback_function = ROOT / 'supabase/functions/feedback-orchestrator/index.ts'
followon_public_function = ROOT / 'supabase/functions/feedback-public/index.ts'
check('Follow-on finance/reporting/feedback production slice is present', followon_migration.is_file() and all(f'public.{name}' in followon_migration.read_text() for name in ('finance_supplier_payment_requests','finance_payroll_exports','finance_fuel_stations','report_builder_configs','finance_import_jobs','feedback_public_links')) and followon_finance_function.is_file() and '/api/reports/profitability' in followon_finance_function.read_text() and followon_feedback_function.is_file() and '/api/feedback/notifications/run' in followon_feedback_function.read_text() and followon_public_function.is_file() and 'submit_public_feedback' in followon_public_function.read_text())
check('Follow-on Finance UI exposes import preview/correction and reconciliation controls', all(token in html for token in ('finance-import','openFinanceImportModal','data-import-correction','finance-reconciliation','fuel-station')) and all(token in openapi_path.read_text() for token in ('/api/imports/preview:', '/api/feedback/v1/{token}:', '/api/duties/{duty_id}/evidence-bundle:')) and (ROOT / 'finance_feedback_smoke_test.py').is_file())
communications_backend = ROOT / 'backend_communications.py'
communications_migration = ROOT / 'supabase/migrations/20260930040000_communications_parity_slice.sql'
communications_function = ROOT / 'supabase/functions/communications-orchestrator/index.ts'
communications_client = (ROOT / 'supabase/client.js').read_text()
check('Communications local handler is wired', communications_backend.is_file() and 'def handle_communications' in communications_backend.read_text() and 'handle_communications(conn' in (ROOT / 'server.py').read_text())
check('Communications migration and RLS/RPC are present', communications_migration.is_file() and all(f'public.{name}' in communications_migration.read_text() for name in ('communication_templates','communication_suppressions','communication_dispatches','communication_webhook_events')) and 'queue_communication_dispatch' in communications_migration.read_text() and 'record_communication_delivery' in communications_migration.read_text())
check('Communications Edge/browser boundary is present', communications_function.is_file() and 'communications-orchestrator' in communications_client and 'queue_communication_dispatch' in communications_function.read_text() and 'suppression' in communications_function.read_text())
check('Communications OpenAPI/docs/smoke coverage is present', all(token in openapi_path.read_text() for token in ('/api/communications/templates:', '/api/communications/dispatch:', '/api/communications/suppressions:')) and (ROOT / 'docs/communications-parity-slice.md').is_file() and (ROOT / 'communications_smoke_test.py').is_file())
supplier_finance_backend = ROOT / 'backend_supplier_finance.py'
supplier_finance_migration = ROOT / 'supabase/migrations/20260930050000_supplier_fleet_finance_slice.sql'
supplier_finance_function = ROOT / 'supabase/functions/supplier-fleet-finance-orchestrator/index.ts'
supplier_finance_client = (ROOT / 'supabase/client.js').read_text()
check('Supplier/fleet finance local handler is wired', supplier_finance_backend.is_file() and 'def handle_supplier_finance' in supplier_finance_backend.read_text() and 'handle_supplier_finance(conn' in (ROOT / 'server.py').read_text())
check('Supplier/fleet finance migration and RLS/RPC are present', supplier_finance_migration.is_file() and all(f'public.{name}' in supplier_finance_migration.read_text() for name in ('purchase_orders','fuel_entries','petty_cash_entries','driver_allowances','payroll_runs','payroll_lines','supplier_settlements')) and 'generate_payroll_run' in supplier_finance_migration.read_text() and 'generate_supplier_settlement' in supplier_finance_migration.read_text())
check('Supplier/fleet finance Edge/browser boundary is present', supplier_finance_function.is_file() and 'supplier-fleet-finance-orchestrator' in supplier_finance_client and 'generate_payroll_run' in supplier_finance_function.read_text() and 'supplier-ageing' in supplier_finance_function.read_text())
check('Supplier/fleet finance OpenAPI/docs/smoke coverage is present', all(token in openapi_path.read_text() for token in ('/api/supplier-purchases:', '/api/fuel-entries:', '/api/driver-allowances:', '/api/payroll/runs:')) and (ROOT / 'docs/supplier-fleet-finance-slice.md').is_file() and (ROOT / 'supplier_finance_smoke_test.py').is_file())
feedback_backend = ROOT / 'backend_feedback.py'
feedback_migration = ROOT / 'supabase/migrations/20260930060000_feedback_recovery_slice.sql'
feedback_function = ROOT / 'supabase/functions/feedback-orchestrator/index.ts'
feedback_client = (ROOT / 'supabase/client.js').read_text()
check('Feedback/recovery local handler is wired', feedback_backend.is_file() and 'def handle_feedback' in feedback_backend.read_text() and 'handle_feedback(conn' in (ROOT / 'server.py').read_text())
check('Feedback/recovery migration and RLS/RPC are present', feedback_migration.is_file() and all(f'public.{name}' in feedback_migration.read_text() for name in ('feedback_forms','feedback_requests','feedback_responses','service_recovery_actions')) and 'create_feedback_form' in feedback_migration.read_text() and 'submit_feedback_response' in feedback_migration.read_text())
check('Feedback/recovery Edge/browser boundary is present', feedback_function.is_file() and 'feedback-orchestrator' in feedback_client and 'submit_feedback_response' in feedback_function.read_text() and 'sentiment' in feedback_function.read_text())
check('Feedback/recovery OpenAPI/docs/smoke coverage is present', all(token in openapi_path.read_text() for token in ('/api/feedback/forms:', '/api/feedback/requests:', '/api/feedback/recovery:')) and (ROOT / 'docs/feedback-recovery-slice.md').is_file() and (ROOT / 'feedback_smoke_test.py').is_file())
feedback_delivery_sql = network_collaboration_sql
feedback_delivery_function = ROOT / 'supabase/functions/feedback-delivery-webhook/index.ts'
feedback_orchestrator = feedback_function.read_text() if feedback_function.is_file() else ''
check('Feedback delivery policies, attempts, receipts and webhook boundary are present', network_collaboration_migration.is_file() and all(marker in feedback_delivery_sql for marker in ('public.feedback_delivery_policies', 'public.feedback_escalation_policies', 'public.feedback_delivery_attempts', 'public.feedback_provider_events')) and feedback_delivery_function.is_file() and 'SUPABASE_SERVICE_ROLE_KEY' in feedback_delivery_function.read_text() and 'feedback_delivery_attempts' in feedback_orchestrator and 'mock_sms_email_whatsapp_adapter' in feedback_orchestrator)
feedback_webhook_source = feedback_delivery_function.read_text() if feedback_delivery_function.is_file() else ''
check('Feedback provider callbacks require signed, replay-bounded, idempotent receipts', all(marker in feedback_webhook_source for marker in ('AXIOM_SMS_WEBHOOK_SECRET', 'AXIOM_EMAIL_WEBHOOK_SECRET', 'AXIOM_WHATSAPP_WEBHOOK_SECRET', 'constantTimeEqual', 'REPLAY_WINDOW_SECONDS', 'processed_at', 'retry_scheduled')) and all(marker in (ROOT / 'supabase/functions/webhook-gateway/index.ts').read_text() for marker in ('email:', 'AXIOM_EMAIL_WEBHOOK_SECRET', 'x-email-signature')))
check('Feedback relationship RLS prevents cross-tenant attachments', all(marker in feedback_delivery_sql for marker in ('feedback_requests_manage', 'feedback_public_links_operator_write', 'feedback_notifications_delivery_write', 'organization_memberships', 'c.id=feedback_delivery_policies.customer_id', 'feedback_responses r where r.id=service_recovery_actions.response_id')))
check('Feedback delivery UI and smoke coverage are present', all(marker in html for marker in ('feedback-policy', 'feedback-escalation', 'deliveryAttempts')) and all(marker in (ROOT / 'finance_feedback_smoke_test.py').read_text() for marker in ('customer-specific feedback delivery policy', 'provider delivery receipt', 'provider attempts', 'transient feedback delivery schedules a retry', 'hard-bounced feedback delivery is terminal', 'exhausted feedback delivery enters dead letter')))
# Product acceptance criteria contracts: these are intentionally source-level guards
# in addition to browser/WCAG testing at the release gate.
acceptance_contracts = {
    'loading skeleton and recovery': 'function renderLoadingState()' in html and 'data-action="retry-hydration"' in html,
    'empty states explain next action': 'class="table-empty"' in html and 'Add the first' in html,
    'sticky long-form save actions': '.modal-footer { position: sticky' in html and 'settings-save-bar' in html and 'master-form-section' in html,
    'field-level accessible validation': 'function validateFields' in html and 'aria-invalid' in html and 'inline-error' in html,
    'search result count and selection': 'result${list.length' in html and 'selected' in html and 'result_count' in (ROOT / 'backend_phase3.py').read_text(),
    'mobile table card equivalents': 'mobile-card-table' in html and 'decorateResponsiveTables' in html,
    'bulk edit assign archive workflows': 'bulk-duty-edit' in html and 'bulk-duty-archive' in html and 'bulk_assign' in (ROOT / 'backend_phase12.py').read_text(),
    'saved views persist and reapply': '/api/views' in html and 'data-saved-view' in html and 'Saved view applied' in html,
    'keyboard shortcuts and command palette': 'ctrlKey' in html and 'openCommandPalette' in html and 'commandPaletteInput' in html,
    'mutation audit references': 'audit_reference' in html and 'toastAudit' in html,
    'error recovery action': 'toastRecovery' in html and 'recoveryAction' in html,
    'regionalized labels and formatting': 'regionalSettings' in html and 'formatDateTime' in html and 'regionalTaxLabel' in html and 'formatAmount' in html,
    'sustainability intelligence surface': all(token in html for token in ('ev-eligibility','charging-stations','total_avoided_emissions_kg','emissions_per_passenger_km_g','sustainability-report-v2')),
}
for name, ok in acceptance_contracts.items():
    check(f'Acceptance · {name}', ok)
check('domain calculation engine is present', (ROOT / 'domain_engine.py').is_file())
driver_app = (ROOT / 'driver-app/index.html').read_text() if (ROOT / 'driver-app/index.html').is_file() else ''
calculation_edge = (ROOT / 'supabase/functions/calculate-duty/index.ts').read_text() if (ROOT / 'supabase/functions/calculate-duty/index.ts').is_file() else ''
check('Driver PWA input bounds and allowlists are present', all(marker in driver_app for marker in ('EXPENSE_CATEGORIES', 'MAX_EXPENSE_RUPEES', 'MAX_NOTE_LENGTH', 'pattern="[0-9]{4,6}"', 'Number.isFinite')))
check('calculation ceilings are shared across local and Edge engines', all(marker in (ROOT / 'domain_engine.py').read_text() for marker in ('MAX_CALCULATION_PAISE', 'INPUT_LIMITS', '_safe_product')) and all(marker in calculation_edge for marker in ('MAX_CALCULATION_PAISE', 'INPUT_LIMITS', 'safeProduct', 'percentageBps')))
check('driver execution hardening smoke assertions are present', 'driver expense ceiling is enforced server-side' in (ROOT / 'execution_smoke_test.py').read_text() and 'driver OTP format is enforced server-side' in (ROOT / 'execution_smoke_test.py').read_text())
check('driver offline shell manifest is present', (ROOT / 'driver-manifest.json').is_file() and (ROOT / 'driver-sw.js').is_file())
check('service worker registration is wired', "navigator.serviceWorker.register('/driver-sw.js')" in html)
# Any local href should point to an in-file route, page anchor, or existing asset.
local_hrefs = [a.get('href') for a in soup.find_all('a') if a.get('href') and not a.get('href').startswith(('http:', 'https:', 'mailto:', 'tel:', 'javascript:'))]
allowed_hashes = {'#', '#home', '#login', '#app'} | {f'#{r}' for r in required_routes}
unknown_hashes = sorted({h for h in local_hrefs if h.startswith('#') and h not in allowed_hashes and not re.match(r'^#[A-Za-z][\w-]*$', h)})
check('local anchor syntax', not unknown_hashes, ', '.join(unknown_hashes))

# Form accessibility baseline
forms = soup.find_all('form')
inputs_without_label = []
for el in soup.find_all(['input','select','textarea']):
    if el.get('type') == 'hidden':
        continue
    eid = el.get('id')
    has_label = bool(el.get('aria-label','').strip()) or bool(eid and soup.find('label', attrs={'for': eid})) or bool(el.find_parent('label'))
    if not has_label:
        inputs_without_label.append(eid or el.name)
check('static form controls have labels', not inputs_without_label, ', '.join(inputs_without_label))

# CSS / logo sizing contract after requested reduction
size_contracts = ['width:140px', 'width:130px', 'width:150px', 'width:160px', 'width:112px']
check('reduced logo sizing rules present', all(x in html for x in size_contracts))

# Print results
passed = sum(ok for _,ok,_ in checks)
failed = len(checks) - passed
for name, ok, detail in checks:
    print(('PASS' if ok else 'FAIL').ljust(4), name, ('— ' + detail) if detail else '')
print(f'RESULT {passed}/{len(checks)} passed; {failed} failed')
sys.exit(1 if failed else 0)
