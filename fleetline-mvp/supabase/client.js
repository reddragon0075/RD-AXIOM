/* Axiom Fleet Supabase browser adapter.
 * The app falls back to the local /api backend when config.enabled is false.
 * Do not put the Supabase service-role key in this file or any browser bundle.
 */
(() => {
  const config = window.AXIOM_SUPABASE_CONFIG || {};
  const enabled = Boolean(
    config.enabled &&
    config.url &&
    config.anonKey &&
    !String(config.url).includes('YOUR_PROJECT_REF') &&
    !String(config.anonKey).includes('YOUR_SUPABASE')
  );
  const baseUrl = String(config.url || '').replace(/\/$/, '');
  const storageKey = 'axiomfleet_supabase_session';
  const mfaPendingKey = 'axiomfleet_supabase_mfa_pending_factor';
  const REQUEST_TIMEOUT_MS = 15000;

  async function fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try { return await fetch(url, { ...options, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  }

  function readSession() {
    try { return JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch (_) { return null; }
  }
  let cachedCurrentUser = null;
  function invalidateUserCache() {
    cachedCurrentUser = null;
  }
  function writeSession(session) {
    invalidateUserCache();
    if (session) localStorage.setItem(storageKey, JSON.stringify(session));
    else localStorage.removeItem(storageKey);
  }
  function authHeaders(token) {
    return {
      apikey: config.anonKey,
      Authorization: `Bearer ${token || config.anonKey}`,
      'Content-Type': 'application/json'
    };
  }
  async function sha256(value) {
    if (globalThis.crypto?.subtle) {
      const bytes = new TextEncoder().encode(String(value));
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      return Array.from(new Uint8Array(digest)).map(byte => byte.toString(16).padStart(2, '0')).join('');
    }
    return String(value);
  }
  async function parseResponse(response) {
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
      throw new Error(payload.error_description || payload.msg || payload.message || payload.error || 'Supabase request failed.');
    }
    return payload;
  }
  async function authRequest(path, options = {}, token = '') {
    const headers = { ...authHeaders(token), ...(options.headers || {}) };
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetchWithTimeout(`${baseUrl}/auth/v1${path}`, {
      ...options,
      headers
    });
    return parseResponse(response);
  }
  async function dataRequest(path, options = {}, token = '') {
    const headers = {
      ...authHeaders(token),
      Prefer: 'return=representation',
      ...(options.headers || {})
    };
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetchWithTimeout(`${baseUrl}/rest/v1/${path}`, {
      ...options,
      headers
    });
    return parseResponse(response);
  }
  async function rpc(name, body, token) {
    const response = await fetchWithTimeout(`${baseUrl}/rest/v1/rpc/${name}`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    return parseResponse(response);
  }
  async function edgeFunction(name, body, token) {
    const response = await fetchWithTimeout(`${baseUrl}/functions/v1/${name}`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    return parseResponse(response);
  }
  async function refreshIfNeeded() {
    const session = readSession();
    if (!session) return null;
    if (!session.expires_at || Number(session.expires_at) - Math.floor(Date.now() / 1000) > 60) return session;
    if (!session.refresh_token) { writeSession(null); return null; }
    try {
      const refreshed = await authRequest('/token?grant_type=refresh_token', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: session.refresh_token })
      });
      const next = {
        access_token: refreshed.access_token,
        refresh_token: refreshed.refresh_token || session.refresh_token,
        expires_at: refreshed.expires_at || Math.floor(Date.now() / 1000) + (refreshed.expires_in || 3600),
        user: refreshed.user || session.user
      };
      writeSession(next);
      return next;
    } catch (err) {
      if (String(err?.message || '').toLowerCase().includes('invalid') || String(err?.message || '').toLowerCase().includes('grant')) {
        writeSession(null);
        return null;
      }
      return session;
    }
  }
  function roleFrom(profile, membership) {
    const membershipRole = membership?.role || '';
    if (membershipRole.startsWith('corporate')) return 'corporate';
    if (membershipRole.startsWith('vendor')) return 'vendor';
    if (membershipRole === 'driver') return 'driver';
    return profile?.account_type || 'vendor';
  }
  async function currentUser(forceRefresh = false) {
    if (!forceRefresh && cachedCurrentUser) return cachedCurrentUser;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const user = await authRequest('/user', {}, session.access_token);
    const profiles = await dataRequest(`profiles?id=eq.${encodeURIComponent(user.id)}&select=*`, {}, session.access_token);
    const memberships = await dataRequest(`organization_memberships?user_id=eq.${encodeURIComponent(user.id)}&status=eq.active&select=organization_id,role,branch_id,organizations(*)`, {}, session.access_token);
    const profile = profiles[0] || {};
    let membership = memberships[0] || null;
    let organization = membership?.organizations || null;
    if (!organization && membership?.organization_id) {
      try {
        const orgRows = await dataRequest(`organizations?id=eq.${encodeURIComponent(membership.organization_id)}&select=*`, {}, session.access_token);
        if (orgRows?.[0]) organization = orgRows[0];
      } catch (_) {}
    }
    if (!organization) {
      try {
        const ownedOrgs = await dataRequest(`organizations?owner_user_id=eq.${encodeURIComponent(user.id)}&select=*`, {}, session.access_token);
        if (ownedOrgs?.[0]) {
          organization = ownedOrgs[0];
          if (!membership) {
            membership = { organization_id: organization.id, role: organization.kind === 'corporate' ? 'corporate_admin' : 'vendor_owner' };
          }
        }
      } catch (_) {}
    }
    if (!organization && (profile.account_type === 'corporate' || user.user_metadata?.account_type === 'corporate')) {
      try {
        const corpMemberships = await dataRequest(`corporate_account_users?user_id=eq.${encodeURIComponent(user.id)}&select=organization_id,account_type,status`, {}, session.access_token);
        if (corpMemberships?.[0]?.organization_id) {
          const orgRows = await dataRequest(`organizations?id=eq.${encodeURIComponent(corpMemberships[0].organization_id)}&select=*`, {}, session.access_token);
          if (orgRows?.[0]) {
            organization = orgRows[0];
            if (!membership) {
              membership = { organization_id: organization.id, role: 'corporate_admin' };
            }
          }
        }
      } catch (_) {}
    }
    const driverRows = profile.account_type === 'driver'
      ? await dataRequest(`drivers?user_id=eq.${encodeURIComponent(user.id)}&select=*`, {}, session.access_token)
      : [];
    const driver = driverRows[0] || {};
    const resolved = {
      ok: true,
      user: {
        id: user.id,
        email: user.email,
        role: roleFrom(profile, membership),
        full_name: profile.full_name || user.user_metadata?.full_name || '',
        phone: profile.phone || user.user_metadata?.phone || '',
        status: 'active',
        created_at: user.created_at,
        last_login_at: null,
        organization: organization ? {
          id: organization.id,
          type: organization.kind,
          name: organization.name,
          phone: organization.phone || '',
          city: organization.city || '',
          gstin: organization.gstin || ''
        } : null,
        profile: {
          city: driver.city || organization?.city || '',
          timezone: profile.timezone || organization?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
          license_number: driver.license_number || '',
          fleet_size: organization?.fleet_size ?? null,
          employee_count: organization?.employee_count ?? null
        }
      }
    };
    cachedCurrentUser = resolved;
    return resolved;
  }
  async function signUp(payload) {
    const authData = await authRequest('/signup', {
      method: 'POST',
      body: JSON.stringify({
        email: payload.email,
        password: payload.password,
        data: {
          full_name: payload.full_name,
          phone: payload.phone,
          account_type: payload.role,
          timezone: payload.timezone || 'UTC'
        }
      })
    });
    if (!authData.access_token) {
      return { ok: true, needs_confirmation: true, user: { email: payload.email, full_name: payload.full_name, role: payload.role } };
    }
    writeSession({
      access_token: authData.access_token,
      refresh_token: authData.refresh_token,
      expires_at: authData.expires_at || Math.floor(Date.now() / 1000) + (authData.expires_in || 3600),
      user: authData.user
    });
    const token = authData.access_token;
    if (payload.role === 'driver') {
      await rpc('create_driver_profile', {
        p_full_name: payload.full_name,
        p_phone: payload.phone || '',
        p_city: payload.city || '',
        p_license_number: payload.license_number || ''
      }, token);
    } else {
      const orgRes = await rpc('create_organization', {
        p_kind: payload.role,
        p_name: payload.organization_name,
        p_city: payload.city || '',
        p_phone: payload.phone || '',
        p_gstin: payload.gstin || '',
        p_fleet_size: payload.role === 'vendor' && payload.fleet_size ? Number(payload.fleet_size) : null,
        p_employee_count: payload.role === 'corporate' && payload.employee_count ? Number(payload.employee_count) : null
      }, token);
      if (payload.role === 'corporate') {
        try {
          const orgId = orgRes?.id || orgRes?.organization_id;
          if (orgId) {
            const corpAccount = await dataRequest('corporate_accounts', {
              method: 'POST',
              body: JSON.stringify({
                organization_id: orgId,
                name: payload.organization_name || 'Corporate Account',
                connection_type: 'manual',
                status: 'active',
                created_by: authData.user?.id || null
              })
            }, token);
            const accountId = Array.isArray(corpAccount) ? corpAccount[0]?.id : corpAccount?.id;
            if (accountId) {
              await dataRequest('corporate_account_users', {
                method: 'POST',
                body: JSON.stringify({
                  organization_id: orgId,
                  account_id: accountId,
                  user_id: authData.user?.id,
                  email: payload.email,
                  full_name: payload.full_name || '',
                  account_type: 'admin',
                  permission_profile: 'admin',
                  status: 'active',
                  invited_by: authData.user?.id,
                  activated_at: new Date().toISOString()
                })
              }, token);
            }
          }
        } catch (_) {
          // If direct table writes are restricted by edge policies, orchestrator will connect gracefully
        }
      }
    }
    if (payload.timezone) {
      await dataRequest(`profiles?id=eq.${encodeURIComponent(authData.user?.id || '')}`, {
        method: 'PATCH',
        body: JSON.stringify({ timezone: payload.timezone })
      }, token);
    }
    return currentUser();
  }
  async function signIn(payload) {
    const authData = await authRequest('/token?grant_type=password', {
      method: 'POST',
      body: JSON.stringify({ email: payload.email, password: payload.password })
    });
    writeSession({
      access_token: authData.access_token,
      refresh_token: authData.refresh_token,
      expires_at: authData.expires_at || Math.floor(Date.now() / 1000) + (authData.expires_in || 3600),
      user: authData.user
    });
    return currentUser();
  }
  async function signOut() {
    const session = await refreshIfNeeded();
    if (session?.access_token) {
      try { await authRequest('/logout', { method: 'POST' }, session.access_token); } catch (_) { /* local session still clears */ }
    }
    writeSession(null);
    return { ok: true };
  }
  async function activeOrganizationId() {
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id;
    if (!organizationId) throw new Error('An organization-linked account is required.');
    return organizationId;
  }
  function locationValue(value) {
    if (value && typeof value === 'object' && !Array.isArray(value)) return value;
    return { label: value || '' };
  }
  function normalizedBooking(payload, organizationId) {
    return {
      organization_id: organizationId,
      branch_id: payload.branch_id || null,
      customer_id: payload.customer_id || null,
      customer_entity_id: payload.customer_entity_id || null,
      sister_company_id: payload.sister_company_id || null,
      company_id: payload.company_id || null,
      vehicle_group_code: payload.vehicle_group_code || null,
      duty_type_code: payload.duty_type_code || payload.duty_type || 'local',
      requesting_organization_id: payload.requesting_organization_id || null,
      vendor_organization_id: payload.vendor_organization_id || null,
      status: payload.status || 'requested',
      booking_reference: payload.booking_reference || `BK-${new Date().toISOString().slice(0, 7).replace('-', '')}-${Math.random().toString(36).slice(2, 8).toUpperCase()}`,
      passenger_name: payload.passenger_name || null,
      passenger_phone: payload.passenger_phone || null,
      passenger_email: payload.passenger_email || null,
      pickup: locationValue(payload.pickup),
      dropoff: locationValue(payload.dropoff),
      stops: Array.isArray(payload.stops) ? payload.stops : [],
      scheduled_at: payload.scheduled_at || null,
      duty_type: payload.duty_type || 'local',
      policy_context: payload.policy_context || {},
      source: payload.source || 'web',
      notes: payload.notes || null
    };
  }
  async function supabasePhase3Request(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    if (!route.startsWith('/api/phase3')) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    let organizationId = identity.user.organization?.id || null;
    if (!organizationId) organizationId = await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('phase3-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }
  async function supabaseCorporateRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    if (!route.startsWith('/api/corporate')) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('corporate-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }
  async function supabaseOperationsRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/bookings/batches' || route.startsWith('/api/bookings/batches/') || route === '/api/availability' || route === '/api/availability/evaluate' || route === '/api/allotment/decisions' || /^\/api\/bookings\/[^/]+\/allot$/.test(route) || /^\/api\/duties\/[^/]+\/close$/.test(route) || /^\/api\/duties\/[^/]+\/closure(?:\/evidence)?$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('operations-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }
  async function supabaseBookingRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = (route === '/api/bookings' && (options.method || 'GET') === 'POST') || ((options.method || 'GET') === 'GET' && /^\/api\/bookings\/[^/]+$/.test(route)) || ((options.method || 'GET') === 'PATCH' && /^\/api\/bookings\/[^/]+$/.test(route)) || route === '/api/bookings/import' || route === '/api/bookings/imports' || route === '/api/pricing/contracts' || route === '/api/pricing/quote' || route === '/api/fuel-rates' || route === '/api/fuel-surcharge-rules' || route === '/api/booking-dispatches' || route === '/api/temporary-passengers' || route === '/api/temporary-allotments' || /^\/api\/bookings\/[^/]+\/(children|split|confirm|confirmation|unconfirm|delete|restore|print|briefing|advance|attachments|export|allot-all|reallot|re-allot|dispatch|supplier-dispatch|dispatches|temporary-passenger|temporary-allotment|pricing|actions)$/.test(route) || /^\/api\/pricing\/contracts\/[^/]+\/rules$/.test(route) || /^\/api\/booking-dispatches\/[^/]+\/respond$/.test(route) || /^\/api\/duties\/[^/]+\/arrival$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('booking-orchestrator', { path: route, method: options.method || 'GET', organization_id: organizationId, query: Object.fromEntries(url.searchParams.entries()), body }, session.access_token);
  }
  async function supabaseP0Request(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const phase12Boundary = route === '/api/masters/registry' || route.startsWith('/api/masters/registry/') || route === '/api/mobile/home' || route === '/api/views' || route.startsWith('/api/views/') || route === '/api/operations/rosters' || route === '/api/operations/live-board' || /^\/api\/operations\/duties\/[^/]+\/eta$/.test(route) || route === '/api/operations/bulk' || route === '/api/safety/monitor' || route === '/api/safety/monitor/evaluate' || /^\/api\/safety\/incidents\/[^/]+\/(evidence|closure-approval)/.test(route) || route === '/api/network/v1/scorecard-formulas' || route === '/api/network/v1/scorecard-formulas/active' || route === '/api/network/v1/scorecard-disputes' || /^\/api\/network\/v1\/service-orders\/[^/]+\/(activation|replacements|scorecard|reconciliation)/.test(route) || route === '/api/permissions/bundles' || route === '/api/integrations/catalog' || route === '/api/integrations/config' || route === '/api/integrations/sync' || route === '/api/integrations/events';
    if (phase12Boundary) {
      const phaseSession = await refreshIfNeeded();
      if (!phaseSession?.access_token) throw new Error('Sign in required.');
      const phaseIdentity = await currentUser();
      let phaseOrganizationId = phaseIdentity.user.organization?.id || null;
      if (!phaseOrganizationId) { try { phaseOrganizationId = await activeOrganizationId(); } catch (_) { /* independent drivers can be resolved by the edge boundary */ } }
      let phaseBody = {};
      try { phaseBody = JSON.parse(options.body || '{}'); } catch (_) { phaseBody = {}; }
      return edgeFunction('phase12-orchestrator', { path: route, method: options.method || 'GET', organization_id: phaseOrganizationId, query: Object.fromEntries(url.searchParams.entries()), body: phaseBody }, phaseSession.access_token);
    }
    const isP0 = route.startsWith('/api/masters') || route.startsWith('/api/operations/') || route.startsWith('/api/safety/') || route.startsWith('/api/permissions') || route.startsWith('/api/network/v1/regions') || route.startsWith('/api/network/v1/vendor-approvals') || route.startsWith('/api/network/v1/requirements/') || route.startsWith('/api/network/v1/messages') || route.startsWith('/api/network/v1/service-orders/') || route.startsWith('/api/network/v1/disputes') || route.startsWith('/api/network/v1/corrective-actions');
    if (!isP0) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const method = options.method || 'GET';
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    const limit = Math.min(Number(url.searchParams.get('limit') || 100), 100);
    const list = async (table, extra = '') => {
      const rows = await dataRequest(`${table}?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=${limit}${extra}`, {}, session.access_token);
      return { ok: true, items: rows, count: rows.length };
    };
    const insert = async (table, value, headers = {}) => {
      const rows = await dataRequest(table, { method: 'POST', headers, body: JSON.stringify({ ...value, organization_id: organizationId }) }, session.access_token);
      return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
    };
    const orchestrate = (command, value = body) => edgeFunction('p0-orchestrator', { command, path: route, method, organization_id: organizationId, body: value }, session.access_token);
    const decode = (rows, jsonKeys = []) => rows.map(row => {
      const item = { ...row };
      jsonKeys.forEach(key => { if (typeof item[key] === 'string') { try { item[key] = JSON.parse(item[key]); } catch (_) {} } });
      return item;
    });

    if (route === '/api/masters' && method === 'GET') {
      const rows = await dataRequest(`p0_master_records?organization_id=eq.${encodeURIComponent(organizationId)}&select=kind,status`, {}, session.access_token);
      const kinds = ['billing_items','duty_types','feedback_forms','labels','operating_regions','taxes','vehicle_groups'];
      const counts = Object.fromEntries(kinds.map(kind => [kind, rows.filter(row => row.kind === kind && row.status !== 'archived').length]));
      return { ok: true, counts, kinds };
    }
    const master = route.match(/^\/api\/masters\/([^/]+)(?:\/([^/]+)(?:\/(archive|restore))?)?$/);
    if (master) {
      const [, kind, id, action] = master;
      if (!id && method === 'GET') {
        const q = url.searchParams.get('q');
        const statusValue = url.searchParams.get('status') || 'active';
        let query = `p0_master_records?organization_id=eq.${encodeURIComponent(organizationId)}&kind=eq.${encodeURIComponent(kind)}&select=*&order=name.asc&limit=${limit}`;
        if (statusValue !== 'all') query += `&status=eq.${encodeURIComponent(statusValue)}`;
        if (q) query += `&or=(code.ilike.*${encodeURIComponent(q)}*,name.ilike.*${encodeURIComponent(q)}*)`;
        return { ok: true, items: decode(await dataRequest(query, {}, session.access_token), ['config']) };
      }
      if (!id && method === 'POST') return insert('p0_master_records', { kind, code: String(body.code || '').toUpperCase(), name: body.name, status: body.status || 'active', version: 1, effective_from: body.effective_from || null, effective_to: body.effective_to || null, config: body.config || {}, created_by: session.user?.id || null });
      if (id && method === 'GET') {
        const rows = await dataRequest(`p0_master_records?id=eq.${encodeURIComponent(id)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
        const versions = await dataRequest(`p0_master_versions?master_id=eq.${encodeURIComponent(id)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=version.desc`, {}, session.access_token);
        const item = decode(rows, ['config'])[0] || null;
        if (item) item.versions = decode(versions, ['snapshot']);
        return { ok: true, item };
      }
      if (id && action && method === 'POST') return orchestrate(`master.${action}`, { ...body, master_id: id, kind });
      if (id && method === 'PATCH') return orchestrate('master.update', { ...body, master_id: id, kind });
    }

    if (route === '/api/operations/sites' && method === 'GET') return list('p0_sites');
    if (route === '/api/operations/sites' && method === 'POST') return insert('p0_sites', { code: String(body.code || '').toUpperCase(), name: body.name, city: body.city || '', address: body.address || {}, status: body.status || 'active', created_by: session.user?.id || null });
    if (route === '/api/operations/shifts' && method === 'GET') return list('p0_shifts', '&order=starts_at.asc');
    if (route === '/api/operations/shifts' && method === 'POST') return insert('p0_shifts', { site_id: body.site_id || null, code: String(body.code || '').toUpperCase(), name: body.name, starts_at: body.starts_at, ends_at: body.ends_at, demand: body.demand || {}, status: body.status || 'active', created_by: session.user?.id || null });
    if (route === '/api/operations/dispatch-board' && method === 'GET') return list('p0_roster_assignments', '&order=response_deadline.asc');

    const plan = route.match(/^\/api\/operations\/route-plans(?:\/([^/]+)(?:\/(publish))?)?$/);
    if (plan) {
      const [, planId, planAction] = plan;
      if (!planId && method === 'GET') return list('p0_route_plans', '&order=plan_date.desc,version.desc');
      if (!planId && method === 'POST') return orchestrate('route_plan.create');
      if (planId && planAction === 'publish' && method === 'POST') return orchestrate('route_plan.publish', { ...body, route_plan_id: planId });
      if (planId && method === 'GET') {
        const rows = await dataRequest(`p0_route_plans?id=eq.${encodeURIComponent(planId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
        const stops = await dataRequest(`p0_route_stops?route_plan_id=eq.${encodeURIComponent(planId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=sequence.asc`, {}, session.access_token);
        const assignments = await dataRequest(`p0_roster_assignments?route_plan_id=eq.${encodeURIComponent(planId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=offered_at.asc`, {}, session.access_token);
        const item = decode(rows, ['constraints','feasibility'])[0] || null;
        if (item) { item.stops = decode(stops, ['pickup','dropoff']); item.assignments = assignments; }
        return { ok: true, item };
      }
    }
    const assignment = route.match(/^\/api\/operations\/assignments(?:\/([^/]+)(?:\/(accept|reject|expire))?)?$/);
    if (assignment) {
      const [, assignmentId, assignmentAction] = assignment;
      if (!assignmentId && method === 'GET') return list('p0_roster_assignments', '&order=offered_at.desc');
      if (!assignmentId && method === 'POST') return orchestrate('assignment.offer');
      if (assignmentId && assignmentAction && method === 'POST') return orchestrate(`assignment.${assignmentAction}`, { ...body, assignment_id: assignmentId });
      if (assignmentId && method === 'GET') { const rows = await dataRequest(`p0_roster_assignments?id=eq.${encodeURIComponent(assignmentId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token); return { ok: true, item: rows[0] || null }; }
    }
    const replacement = route.match(/^\/api\/operations\/replacements(?:\/([^/]+))?$/);
    if (replacement) {
      const [, replacementId] = replacement;
      if (!replacementId && method === 'GET') return list('p0_replacements');
      if (!replacementId && method === 'POST') return insert('p0_replacements', { duty_id: body.duty_id, reason: body.reason || 'capacity_exception', status: 'open', replacement_driver_id: body.replacement_driver_id || null, replacement_vehicle_id: body.replacement_vehicle_id || null, due_at: body.due_at || null, created_by: session.user?.id || null });
      if (replacementId && method === 'PATCH') return orchestrate('replacement.update', { ...body, replacement_id: replacementId });
      if (replacementId && method === 'GET') { const rows = await dataRequest(`p0_replacements?id=eq.${encodeURIComponent(replacementId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token); return { ok: true, item: rows[0] || null }; }
    }

    if (route === '/api/safety/policies' && method === 'GET') return list('p0_safety_policies', '&order=created_at.desc');
    if (route === '/api/safety/policies' && method === 'POST') return insert('p0_safety_policies', { code: body.code, name: body.name, version: Number(body.version || 1), rules: body.rules || {}, status: body.status || 'active', created_by: session.user?.id || null });
    if (route === '/api/safety/alerts' && method === 'POST') return orchestrate('safety.alert');
    const incident = route.match(/^\/api\/safety\/incidents(?:\/([^/]+)(?:\/(acknowledge|investigate|contain|resolve|close))?)?$/);
    if (incident) {
      const [, incidentId, incidentAction] = incident;
      if (!incidentId && method === 'GET') return list('p0_safety_incidents', '&order=opened_at.desc');
      if (!incidentId && method === 'POST') return insert('p0_safety_incidents', { duty_id: body.duty_id || null, alert_type: body.alert_type || 'manual', severity: body.severity || 'medium', status: 'open', title: body.title, description: body.description || '', due_at: body.due_at || null, evidence: body.evidence || {}, opened_at: new Date().toISOString() });
      if (incidentId && incidentAction && method === 'POST') return orchestrate(`safety.incident.${incidentAction}`, { ...body, incident_id: incidentId });
      if (incidentId && method === 'GET') { const rows = await dataRequest(`p0_safety_incidents?id=eq.${encodeURIComponent(incidentId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token); return { ok: true, item: rows[0] || null }; }
    }
    const safetyAction = route.match(/^\/api\/safety\/incidents\/([^/]+)\/actions(?:\/([^/]+))?$/);
    if (safetyAction && method === 'GET') return list('p0_safety_actions', `&incident_id=eq.${encodeURIComponent(safetyAction[1])}`);
    if (safetyAction && method === 'POST') return orchestrate('safety.corrective_action', { ...body, incident_id: safetyAction[1], action_id: safetyAction[2] || null });
    if (route === '/api/safety/evaluate' && method === 'POST') return orchestrate('safety.evaluate');

    if (route === '/api/permissions' && method === 'GET') {
      const rows = await dataRequest(`p0_role_permissions?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=role.asc,permission_key.asc`, {}, session.access_token);
      const permissions = ['masters.read','masters.write','route_plans.read','route_plans.write','dispatch.read','dispatch.write','dispatch.respond','replacements.manage','safety.read','safety.incidents.create','safety.incidents.manage','network.regions.read','network.regions.write','network.vendor_approvals.read','network.vendor_approvals.write','network.lifecycle.write','network.messages.write','network.evaluations.write','network.metrics.write','network.scorecards.write','network.settlements.write','network.disputes.write','network.corrective_actions.write','permissions.read','permissions.write'];
      return { ok: true, items: rows, permissions };
    }
    if (route === '/api/permissions/check' && method === 'POST') {
      const memberships = await dataRequest(`organization_memberships?organization_id=eq.${encodeURIComponent(organizationId)}&user_id=eq.${encodeURIComponent(session.user?.id || '')}&status=eq.active&select=role`, {}, session.access_token);
      const role = memberships[0]?.role || '';
      const grants = await dataRequest(`p0_role_permissions?organization_id=eq.${encodeURIComponent(organizationId)}&role=eq.${encodeURIComponent(role)}&permission_key=eq.${encodeURIComponent(body.permission || '')}&select=allowed`, {}, session.access_token);
      const defaults = grants.length ? Boolean(grants[0].allowed) : (await dataRequest(`role_permissions?role=eq.${encodeURIComponent(role)}&permission_key=eq.${encodeURIComponent(body.permission || '')}&select=permission_key`, {}, session.access_token)).length > 0;
      return { ok: true, permission: body.permission || '', allowed: defaults, role };
    }
    const grant = route.match(/^\/api\/permissions\/grants(?:\/([^/]+))?$/);
    if (grant && (method === 'POST' || method === 'PATCH')) {
      const roleMap = { vendor: 'vendor_owner', corporate: 'corporate_admin', driver: 'driver' };
      const value = { organization_id: organizationId, role: roleMap[body.role] || body.role, permission_key: body.permission, allowed: body.allowed !== false, created_by: session.user?.id || null, updated_at: new Date().toISOString() };
      const rows = await dataRequest('p0_role_permissions', { method: 'POST', headers: { Prefer: 'resolution=merge-duplicates,return=representation' }, body: JSON.stringify(value) }, session.access_token);
      return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
    }

    // Network P0 records share the invite-only Network auth context but use
    // additive tables so legacy network collections remain untouched.
    const suffix = route.replace('/api/network/v1', '') || '/';
    const networkTable = {
      '/regions': 'p0_network_regions',
      '/vendor-approvals': 'p0_network_vendor_approvals',
      '/messages': 'p0_network_messages',
      '/disputes': 'p0_network_disputes',
      '/corrective-actions': 'p0_network_corrective_actions'
    }[suffix];
    if (networkTable && method === 'GET') return list(networkTable);
    if (networkTable && method === 'POST') return insert(networkTable, body);
    if (route.match(/^\/api\/network\/v1\/regions\/[^/]+$/) && method === 'PATCH') return orchestrate('network.region.update');
    const lifecycle = route.match(/^\/api\/network\/v1\/requirements\/([^/]+)\/lifecycle$/);
    if (lifecycle && method === 'GET') return orchestrate('network.requirement.lifecycle', { requirement_id: lifecycle[1] });
    if (lifecycle && method === 'POST') return orchestrate('network.requirement.transition', { ...body, requirement_id: lifecycle[1] });
    const evaluation = route.match(/^\/api\/network\/v1\/requirements\/([^/]+)\/evaluations(?:\/([^/]+))?$/);
    if (evaluation && method === 'GET') return list('p0_network_quote_evaluations', `&requirement_id=eq.${encodeURIComponent(evaluation[1])}`);
    if (evaluation && method === 'POST') return insert('p0_network_quote_evaluations', { requirement_id: evaluation[1], quote_id: body.quote_id, version: Number(body.version || 1), commercial_score: Number(body.commercial_score || 0), quality_score: Number(body.quality_score || 0), risk_score: Number(body.risk_score || 0), total_score: Number(body.total_score || 0), sample_size: Number(body.sample_size || 0), confidence: body.confidence || 'cold_start', comments: body.comments || '', status: body.status || 'draft', created_by: session.user?.id || null });
    const metric = route.match(/^\/api\/network\/v1\/service-orders\/([^/]+)\/metric-observations$/);
    if (metric && method === 'GET') return list('p0_network_metric_observations', `&service_order_id=eq.${encodeURIComponent(metric[1])}`);
    if (metric && method === 'POST') return insert('p0_network_metric_observations', { service_order_id: metric[1], vendor_profile_id: body.vendor_profile_id || null, metric_key: body.metric_key, value: Number(body.value || 0), unit: body.unit || '', sample_size: Number(body.sample_size || 0), source_event_ids: body.source_event_ids || [], formula_version: body.formula_version || 'v1', observed_at: body.observed_at || new Date().toISOString(), created_by: session.user?.id || null });
    const score = route.match(/^\/api\/network\/v1\/service-orders\/([^/]+)\/scorecard-runs$/);
    if (score && method === 'GET') return list('p0_network_scorecard_runs', `&service_order_id=eq.${encodeURIComponent(score[1])}`);
    if (score && method === 'POST') return insert('p0_network_scorecard_runs', { service_order_id: score[1], period_start: body.period_start, period_end: body.period_end, formula_version: body.formula_version || 'v1', sample_size: Number(body.sample_size || 0), confidence: body.confidence || 'cold_start', score: Number(body.score || 0), metrics: body.metrics || {}, status: body.status || 'computed', created_by: session.user?.id || null });
    const statement = route.match(/^\/api\/network\/v1\/service-orders\/([^/]+)\/settlement-statements(?:\/([^/]+)\/(approve))?$/);
    if (statement && method === 'GET') return list('p0_network_settlement_statements', `&service_order_id=eq.${encodeURIComponent(statement[1])}`);
    if (statement && method === 'POST' && statement[3]) return orchestrate('network.settlement.approve', { ...body, statement_id: statement[2] });
    if (statement && method === 'POST') return insert('p0_network_settlement_statements', { service_order_id: statement[1], scorecard_run_id: body.scorecard_run_id || null, period_start: body.period_start, period_end: body.period_end, subtotal_paise: Number(body.subtotal_paise || 0), tax_paise: Number(body.tax_paise || 0), fee_paise: Number(body.fee_paise || 0), deduction_paise: Number(body.deduction_paise || 0), net_paise: Number(body.net_paise || 0), status: body.status || 'draft', reconciliation: body.reconciliation || {}, created_by: session.user?.id || null });
    const readiness = route.match(/^\/api\/network\/v1\/service-orders\/([^/]+)\/readiness$/);
    if (readiness && method === 'GET') return orchestrate('network.service_order.readiness', { service_order_id: readiness[1] });

    return undefined;
  }

  async function supabaseNetworkRequest(path, options = {}) {
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const method = options.method || 'GET';
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const suffix = route.replace('/api/network/v1', '') || '/';
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    const governedNetwork = route === '/api/network/v1/partner-directory' || route === '/api/network/v1/associates' || route === '/api/network/v1/invites' || /^\/api\/network\/v1\/(associates|invites)\/[^/]+\/(accept|reject|revoke)$/.test(route) || route === '/api/network/v1/contracts' || /^\/api\/network\/v1\/contracts\/[^/]+(?:\/(versions|sync|sign))?$/.test(route) || /^\/api\/network\/v1\/service-orders\/[^/]+\/(exchanges|sla-observations|issues|rate-discrepancies|settlement-resolutions)$/.test(route) || /^\/api\/network\/v1\/(exchanges|issues|rate-discrepancies|settlement-resolutions)\/[^/]+\/(acknowledge|reject|process|resolve|decide)$/.test(route);
    if (governedNetwork || (route === '/api/network/v1/invites' && method === 'POST')) {
      return edgeFunction('network-orchestrator', { path: route, method, organization_id: organizationId, query: Object.fromEntries(url.searchParams.entries()), body }, session.access_token);
    }
    const list = async (table, filter = '') => {
      const rows = await dataRequest(`${table}?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=100${filter}`, {}, session.access_token);
      return { ok: true, items: rows, count: rows.length };
    };
    const insert = async (table, value) => {
      const rows = await dataRequest(table, { method: 'POST', body: JSON.stringify({ ...value, organization_id: organizationId }) }, session.access_token);
      return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
    };
    if (suffix === '/feature-flag' && method === 'GET') {
      const rows = await dataRequest(`network_feature_flags?organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      return { ok: true, flag: rows[0] || { organization_id: organizationId, enabled: true, mode: 'closed_invite_only' } };
    }
    if (suffix === '/feature-flag' && method === 'POST') {
      const current = await dataRequest(`network_feature_flags?organization_id=eq.${encodeURIComponent(organizationId)}&select=organization_id`, {}, session.access_token);
      const result = current[0]
        ? await dataRequest(`network_feature_flags?organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ enabled: Boolean(body.enabled), updated_by: session.user?.id || null, updated_at: new Date().toISOString() }) }, session.access_token)
        : await dataRequest('network_feature_flags', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, enabled: Boolean(body.enabled), mode: 'closed_invite_only', updated_by: session.user?.id || null }) }, session.access_token);
      return { ok: true, enabled: Boolean(body.enabled), flag: Array.isArray(result) ? result[0] : result };
    }
    const collection = suffix.match(/^\/(invites|vendor-profiles|programs|service-orders|events)$/);
    if (collection && method === 'GET') {
      const table = { invites: 'network_invites', 'vendor-profiles': 'network_vendor_profiles', programs: 'network_programs', 'service-orders': 'network_service_orders', events: 'network_events' }[collection[1]];
      return list(table);
    }
    if (collection && method === 'POST' && collection[1] !== 'events' && collection[1] !== 'service-orders') {
      const table = { invites: 'network_invites', 'vendor-profiles': 'network_vendor_profiles', programs: 'network_programs' }[collection[1]];
      return insert(table, body);
    }
    const requirementCollection = suffix.match(/^\/programs\/([^/]+)\/requirements$/);
    if (requirementCollection && method === 'GET') return list('network_requirements', `&program_id=eq.${encodeURIComponent(requirementCollection[1])}`);
    if (requirementCollection && method === 'POST') {
      const created = await insert('network_requirements', { program_id: requirementCollection[1], reference: body.reference, status: 'draft', current_version: 1, created_by: session.user?.id || null });
      const requirement = created.item;
      const versions = await dataRequest('network_requirement_versions', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, requirement_id: requirement.id, version: 1, status: 'draft', payload: body.spec || {}, change_note: body.change_note || '', created_by: session.user?.id || null }) }, session.access_token);
      const version = Array.isArray(versions) ? versions[0] : versions;
      const updated = await dataRequest(`network_requirements?id=eq.${encodeURIComponent(requirement.id)}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ current_version_id: version.id }) }, session.access_token);
      return { ok: true, item: Array.isArray(updated) ? updated[0] : updated };
    }
    const reqRoute = suffix.match(/^\/requirements\/([^/]+)(?:\/(.*))?$/);
    if (reqRoute && (!reqRoute[2] || reqRoute[2] === '') && method === 'GET') {
      if (identity.user.role === 'vendor') return edgeFunction('network-orchestrator', { path: route, method, body, organization_id: organizationId }, session.access_token);
      const rows = await dataRequest(`network_requirements?id=eq.${encodeURIComponent(reqRoute[1])}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      return { ok: true, item: rows[0] || null };
    }
    if (suffix === '/requirements' && method === 'GET' && identity.user.role === 'vendor') {
      return edgeFunction('network-orchestrator', { path: route, method, body, organization_id: organizationId }, session.access_token);
    }
    const directTables = {
      '/requirements': 'network_requirements',
      '/comparisons': 'network_comparisons',
      '/awards': 'network_awards'
    };
    for (const [prefix, table] of Object.entries(directTables)) {
      if (suffix === prefix && method === 'GET') return list(table);
    }
    const activate = suffix.match(/^\/awards\/([^/]+)\/activate$/);
    if (activate && method === 'POST') {
      const result = await rpc('network_activate_award', { p_award_id: activate[1], p_idempotency_key: body.idempotency_key || null }, session.access_token);
      return { ok: true, item: result, fleet: result };
    }
    // Matching, comparison, award approval and evidence transitions are kept
    // behind a deployed Supabase orchestration adapter so they remain atomic
    // and do not devolve into a browser-side multi-write workflow.
    if (route.startsWith('/api/network/v1/')) {
      return edgeFunction('network-orchestrator', { path: route, method, body, organization_id: organizationId }, session.access_token);
    }
    throw new Error(`Supabase Network route not implemented: ${method} ${path}`);
  }

  async function supabaseBillIntelligenceRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    if (!route.startsWith('/api/bill-intelligence')) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('bill-intelligence-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseFinanceReportingRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/invoices/generate' || route === '/api/invoice-runs' || route === '/api/collections/dunning' || route === '/api/collections/dunning/run' || route === '/api/reports/ageing' || route === '/api/finance/ageing' || route === '/api/reports/definitions' || route.startsWith('/api/reports/definitions/') || route === '/api/export-profiles' || route.startsWith('/api/export-profiles/');
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('finance-reporting-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseCommunicationsRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/communications/templates' || route === '/api/communications/dispatch' || route === '/api/communications/deliveries' || route.startsWith('/api/communications/deliveries/') || route === '/api/communications/suppressions';
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('communications-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseSupplierFinanceRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/supplier-purchases' || route === '/api/supplier-ageing' || route === '/api/supplier-settlements' || route === '/api/supplier-settlements/generate' || route === '/api/fuel-entries' || route === '/api/petty-cash/entries' || route === '/api/driver-allowances' || route === '/api/payroll/runs' || /^\/api\/payroll\/runs\/[^/]+\/lines$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('supplier-fleet-finance-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseFinanceControlsRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/supplier-payment-requests' || /^\/api\/supplier-payment-requests\/[^/]+\/(approve|reject|execute)$/.test(route) || route === '/api/supplier-advances' || /^\/api\/supplier-advances\/[^/]+\/(approve|reject)$/.test(route) || route === '/api/driver-payouts/requests' || /^\/api\/driver-payouts\/[^/]+\/(approve|reject|disburse)$/.test(route) || route === '/api/supplier-settlement-approvals' || /^\/api\/supplier-settlement-approvals\/[^/]+\/(approve|reject)$/.test(route) || route === '/api/fuel-stations' || route === '/api/fuel-prices' || route === '/api/fuel-analytics' || route === '/api/petty-cash/reconciliations' || route === '/api/finance/reconciliations' || route === '/api/payroll/exports' || /^\/api\/payroll\/exports\/[^/]+\/download$/.test(route) || route === '/api/payroll/compliance' || route === '/api/reports/profitability' || route === '/api/reports/exports' || /^\/api\/reports\/exports\/[^/]+(?:\/download)?$/.test(route) || route === '/api/reports/builder' || /^\/api\/reports\/builder\/[^/]+\/run$/.test(route) || route === '/api/reports/favorites' || /^\/api\/reports\/favorites\/[^/]+\/refresh$/.test(route) || route === '/api/reporting/import-templates' || route === '/api/imports/preview' || /^\/api\/imports\/[^/]+\/(corrections|commit)$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('finance-controls-orchestrator', { path: route, method: options.method || 'GET', organization_id: organizationId, query: Object.fromEntries(url.searchParams.entries()), body }, session.access_token);
  }

  async function supabaseFeedbackRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/feedback/forms' || route.startsWith('/api/feedback/forms/') || route === '/api/feedback/requests' || /^\/api\/feedback\/requests\/[^/]+\/submit$/.test(route) || route === '/api/feedback/responses' || route === '/api/feedback/summary' || route === '/api/feedback/public-links' || route === '/api/feedback/analytics' || route === '/api/feedback/corrective-actions' || route === '/api/feedback/recovery' || route === '/api/feedback/notifications' || route === '/api/feedback/notifications/run' || /^\/api\/feedback\/notifications\/[^/]+\/receipt$/.test(route) || route === '/api/feedback/delivery-policies' || /^\/api\/feedback\/delivery-policies\/[^/]+\/(archive|pause|activate)$/.test(route) || route === '/api/feedback/escalation-policies' || /^\/api\/feedback\/escalation-policies\/[^/]+\/(archive|pause|activate)$/.test(route) || route === '/api/feedback/delivery-attempts' || /^\/api\/feedback\/recovery\/[^/]+\/resolve$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('feedback-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseEnterpriseRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route.startsWith('/api/enterprise') || route === '/api/passenger/portal-links' || route === '/api/availability/calendar' || /^\/api\/bookings\/[^/]+\/quote$/.test(route) || /^\/api\/bookings\/[^/]+\/allotment-requests$/.test(route) || /^\/api\/allotment-requests\/[^/]+\/respond$/.test(route) || route === '/api/allotment-exceptions' || route === '/api/duty-closure-jobs' || route === '/api/duty-closure-jobs/run' || /^\/api\/duties\/[^/]+\/(execution-profile|otp|otp\/verify|media|evidence-bundle|slip|adjustments|sms-close|network-execution|dco|attached-driver|garage-transfer)$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    const organizationId = identity.user.organization?.id || await activeOrganizationId();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('enterprise-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: organizationId,
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseWorkspaceRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/workspace/next-actions' || /^\/api\/workspace\/next-actions\/[^/]+\/status$/.test(route);
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('workspace-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: identity.user.organization?.id || await activeOrganizationId(),
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseGapRequest(path, options = {}) {
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    const supported = route === '/api/passenger/booking-requests' || route === '/api/passenger/book-for-others' || /^\/api\/passenger\/booking-requests\/[^/]+\/(approve|reject|cancel)$/.test(route) || route === '/api/availability/optimize' || /^\/api\/duties\/[^/]+\/(route-log(?:\/(start|stop))?|location-share|driver-alerts(?:\/(acknowledge|resolve))?)$/.test(route) || route === '/api/driver-alert-policies' || route === '/api/driver/device-readiness' || route === '/api/provider-connections' || /^\/api\/provider-connections\/[^/]+\/test$/.test(route) || route === '/api/maps/places' || route === '/api/maps/navigation' || route === '/api/communications/click-to-call' || route === '/api/payment-authorizations' || /^\/api\/invoices\/[^/]+\/auto-collect$/.test(route) || route === '/api/auto-collect/runs' || route === '/api/invoice-automation/policies' || route === '/api/invoice-automation/run' || route === '/api/enterprise/custom-field-values' || route === '/api/integrations/sync' || route === '/api/network/supplier-exchange' || route === '/api/finance/budgets' || route === '/api/finance/expense-forecast';
    if (!supported) return undefined;
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const identity = await currentUser();
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    return edgeFunction('gap-completion-orchestrator', {
      path: route,
      method: options.method || 'GET',
      organization_id: identity.user.organization?.id || await activeOrganizationId(),
      query: Object.fromEntries(url.searchParams.entries()),
      body
    }, session.access_token);
  }

  async function supabaseDomainRequest(path, options = {}) {
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const method = options.method || 'GET';
    const url = new URL(path, window.location.origin);
    const route = url.pathname;
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    const operationsResult = await supabaseOperationsRequest(path, options);
    if (operationsResult !== undefined) return operationsResult;
    const corporateBookingEvaluation = async (requestBody, action = 'book') => {
      const accountResponse = await supabaseCorporateRequest('/api/corporate/account');
      const account = accountResponse?.account;
      if (!account || account.status !== 'active') return null;
      const evaluation = await supabaseCorporateRequest('/api/corporate/policies/evaluate', { method: 'POST', body: JSON.stringify({ ...requestBody, action }) });
      if (evaluation?.outcome === 'block') { const error = new Error('Corporate booking policy blocked this request.'); error.details = evaluation; throw error; }
      return evaluation;
    };
    const persistCorporateApproval = async (bookingId, evaluation) => {
      if (!evaluation || evaluation.outcome !== 'needs_approval') return;
      // The production booking trigger creates this row atomically with the
      // pending booking.  Read first so the browser adapter remains compatible
      // with the older Edge-only deployment without duplicating approvals.
      let pending;
      try {
        pending = await dataRequest(`booking_approvals?booking_id=eq.${encodeURIComponent(bookingId)}&status=eq.pending&approver_id=is.null&select=id&order=created_at.asc&limit=1`, {}, session.access_token);
      } catch (_) {
        // A booker without approval-read permission cannot repair or duplicate
        // the server-created row; the transaction above is authoritative.
        return null;
      }
      if (pending[0]) return pending[0];
      const route = evaluation.reasons?.find(item => item.code === 'approval_required')?.approval_route || [];
      return dataRequest('booking_approvals', { method: 'POST', body: JSON.stringify({ organization_id: await activeOrganizationId(), booking_id: bookingId, approver_id: null, status: 'pending', comment: JSON.stringify({ source: 'corporate_policy', policy_id: evaluation.policy_id, policy_version: evaluation.policy_version, approval_route: route }) }) }, session.access_token);
    };
    if (route === '/api/bookings' && method === 'POST') {
      const evaluation = await corporateBookingEvaluation(body, 'book');
      const bookingBody = { ...body, status: evaluation?.outcome === 'needs_approval' ? 'pending_approval' : body.status, policy_context: evaluation || body.policy_context || {} };
      const result = await supabaseBookingRequest(path, { ...options, body: JSON.stringify(bookingBody) });
      if (result?.item?.id) await persistCorporateApproval(result.item.id, evaluation);
      return { ...result, corporate_evaluation: evaluation };
    }
    const corporateLegacyAction = route.match(/^\/api\/bookings\/[^/]+\/(approve|reject|cancel|assign)$/);
    const bookingConfirm = route.match(/^\/api\/bookings\/([^/]+)\/confirm$/);
    if (!corporateLegacyAction && !bookingConfirm && !(route === '/api/bookings/import' && method === 'POST')) {
      const bookingActionResult = await supabaseBookingRequest(path, options);
      if (bookingActionResult !== undefined) return bookingActionResult;
    }
    if (bookingConfirm && method === 'POST') {
      const accountResponse = await supabaseCorporateRequest('/api/corporate/account');
      if (accountResponse?.account?.status === 'active') {
        const access = await supabaseCorporateRequest('/api/corporate/permissions/evaluate', { method: 'POST', body: JSON.stringify({ permission: 'booking.approve' }) });
        if (!access?.allowed) throw new Error('Corporate booking approval permission is required.');
      }
      const confirmed = await supabaseBookingRequest(path, options);
      if (confirmed !== undefined) return confirmed;
    }
    const bookingImport = route === '/api/bookings/import' && method === 'POST';
    if (bookingImport) {
      const durableImport = await supabaseBookingRequest(path, options);
      if (durableImport !== undefined) return durableImport;
      const organizationId = await activeOrganizationId();
      const sourceRows = Array.isArray(body.bookings) ? body.bookings : [];
      const rows = [];
      for (const [index, source] of sourceRows.entries()) {
        try {
          const evaluation = await corporateBookingEvaluation(source || {}, 'book');
          const bookingPayload = normalizedBooking({ ...(source || {}), status: evaluation?.outcome === 'needs_approval' ? 'pending_approval' : (source || {}).status, policy_context: evaluation || {} }, organizationId);
          const inserted = await dataRequest('bookings', { method: 'POST', body: JSON.stringify(bookingPayload) }, session.access_token);
          const item = Array.isArray(inserted) ? inserted[0] : inserted;
          await persistCorporateApproval(item.id, evaluation);
          rows.push({ row: index + 1, status: 'imported', item, corporate_evaluation: evaluation });
        } catch (error) {
          rows.push({ row: index + 1, status: 'error', error: error.message, code: 'import_error' });
        }
      }
      return { ok: true, imported: rows.filter(row => row.status === 'imported').length, failed: rows.filter(row => row.status === 'error').length, rows };
    }
    const bookingAction = route.match(/^\/api\/bookings\/([^/]+)\/(approve|confirm|reject|cancel|assign)$/);
    if (bookingAction && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const bookingId = bookingAction[1];
      const action = bookingAction[2];
      const selected = await dataRequest(`bookings?id=eq.${encodeURIComponent(bookingId)}&select=*`, {}, session.access_token);
      const booking = selected[0];
      if (!booking) throw new Error('Booking not found.');
      if (action === 'cancel') await corporateBookingEvaluation({ ...booking, ...body, scheduled_at: booking.scheduled_at }, 'cancel');
      if (['approve', 'confirm', 'reject'].includes(action)) {
        const accountResponse = await supabaseCorporateRequest('/api/corporate/account');
        if (accountResponse?.account?.status === 'active') {
          const access = await supabaseCorporateRequest('/api/corporate/permissions/evaluate', { method: 'POST', body: JSON.stringify({ permission: 'booking.approve' }) });
          if (!access?.allowed) throw new Error('Corporate booking approval permission is required.');
        }
      }
      if (action === 'assign' && booking.status === 'pending_approval') throw new Error('Booking approval is required before a duty can be assigned.');
      if (action === 'assign') {
        const dutyPayload = {
          organization_id: organizationId,
          booking_id: bookingId,
          driver_id: body.driver_id || null,
          vehicle_id: body.vehicle_id || null,
          reporting_at: body.reporting_at || null,
          status: 'assigned'
        };
        const createdDuty = await dataRequest('duties', { method: 'POST', body: JSON.stringify(dutyPayload) }, session.access_token);
        const duty = Array.isArray(createdDuty) ? createdDuty[0] : createdDuty;
        const updated = await dataRequest(`bookings?id=eq.${encodeURIComponent(bookingId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'assigned' }) }, session.access_token);
        return { ok: true, booking: Array.isArray(updated) ? updated[0] : updated, duty };
      }
      const nextStatus = { approve: 'approved', confirm: 'confirmed', reject: 'disputed', cancel: 'cancelled' }[action];
      const updated = await dataRequest(`bookings?id=eq.${encodeURIComponent(bookingId)}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus }) }, session.access_token);
      const item = Array.isArray(updated) ? updated[0] : updated;
      if (action === 'approve' || action === 'confirm' || action === 'reject') {
        const decisionStatus = action === 'reject' ? 'rejected' : 'approved';
        const pendingRows = await dataRequest(`booking_approvals?booking_id=eq.${encodeURIComponent(bookingId)}&status=eq.pending&approver_id=is.null&select=id&order=created_at.asc&limit=1`, {}, session.access_token);
        if (pendingRows[0]) {
          await dataRequest(`booking_approvals?id=eq.${encodeURIComponent(pendingRows[0].id)}`, { method: 'PATCH', body: JSON.stringify({ approver_id: session.user?.id || null, status: decisionStatus, comment: body.comment || '' }) }, session.access_token);
        } else {
          await dataRequest('booking_approvals', {
            method: 'POST',
            body: JSON.stringify({ organization_id: organizationId, booking_id: bookingId, approver_id: session.user?.id || null, status: decisionStatus, comment: body.comment || '' })
          }, session.access_token);
        }
      }
      return { ok: true, item, status: nextStatus };
    }
    if (route === '/api/branches' && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const { code, address, ...branchBody } = body;
      const inserted = await dataRequest('branches', { method: 'POST', body: JSON.stringify({ ...branchBody, organization_id: organizationId, numbering_series: { ...(body.numbering_series || {}), ...(code ? { code } : {}) }, tax_registration: body.tax_registration || {} }) }, session.access_token);
      return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    if (route === '/api/drivers' && method === 'POST') {
      const { vehicle_type: ignoredVehicleType, ...driverBody } = body;
      const inserted = await dataRequest('drivers', { method: 'POST', body: JSON.stringify({ ...driverBody, organization_id: await activeOrganizationId() }) }, session.access_token);
      return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    const priceItemRoute = route.match(/^\/api\/price-books\/([^/]+)\/items$/);
    if (priceItemRoute && method === 'POST') {
      const { tax_rate_bps: ignoredTaxRateBps, ...priceItemBody } = body;
      const inserted = await dataRequest('price_book_items', { method: 'POST', body: JSON.stringify({ ...priceItemBody, price_book_id: priceItemRoute[1], tax_rate: body.tax_rate ?? (Number(ignoredTaxRateBps || 0) / 100) }) }, session.access_token);
      return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    const invoiceCreate = route === '/api/invoices' && method === 'POST';
    if (invoiceCreate && body.duty_id) {
      const organizationId = await activeOrganizationId();
      const duties = await dataRequest(`duties?id=eq.${encodeURIComponent(body.duty_id)}&select=*`, {}, session.access_token);
      const duty = duties[0];
      if (!duty) throw new Error('Duty not found.');
      const snapshot = duty.calculation_snapshot || {};
      const bookingRows = duty.booking_id ? await dataRequest(`bookings?id=eq.${encodeURIComponent(duty.booking_id)}&select=customer_id`, {}, session.access_token) : [];
      const invoicePayload = {
        organization_id: organizationId,
        customer_id: bookingRows[0]?.customer_id || null,
        booking_id: duty.booking_id,
        invoice_number: body.invoice_number || `INV-${new Date().getUTCFullYear()}-${Date.now().toString().slice(-6)}`,
        status: 'draft',
        subtotal_paise: Number(snapshot.subtotal_paise || 0),
        tax_paise: Number(snapshot.tax_paise || 0),
        total_paise: Number(snapshot.total_paise || 0),
        currency: 'INR'
      };
      const inserted = await dataRequest('invoices', { method: 'POST', body: JSON.stringify(invoicePayload) }, session.access_token);
      const invoice = Array.isArray(inserted) ? inserted[0] : inserted;
      if (Array.isArray(snapshot.lines) && snapshot.lines.length) {
        await dataRequest('invoice_lines', { method: 'POST', body: JSON.stringify(snapshot.lines.map(line => ({ invoice_id: invoice.id, description: line.label || line.code || 'Duty line', quantity: line.quantity || 1, unit_paise: line.unit_paise || 0, tax_rate: 0, amount_paise: line.amount_paise || 0, source_entity_type: 'duty', source_entity_id: duty.id }))) }, session.access_token);
      }
      return { ok: true, item: invoice };
    }
    const dutyTransition = route.match(/^\/api\/duties\/([^/]+)$/);
    if (dutyTransition && method === 'PATCH' && body.status) {
      const result = await rpc('transition_duty', {
        p_duty_id: dutyTransition[1],
        p_next_status: body.status,
        p_payload: { ...(body.payload || { source: 'web' }), idempotency_key: body.idempotency_key || body.payload?.idempotency_key || null }
      }, session.access_token);
      return { ok: true, item: result };
    }
    const dutyException = route.match(/^\/api\/duties\/([^/]+)\/(reassign|sos)$/);
    if (dutyException && method === 'POST') {
      const dutyId = dutyException[1];
      const action = dutyException[2];
      if (action === 'reassign') {
        const organizationId = await activeOrganizationId();
        const updates = { status: 'assigned', updated_at: new Date().toISOString() };
        for (const key of ['driver_id', 'vehicle_id', 'reporting_at']) if (Object.prototype.hasOwnProperty.call(body, key)) updates[key] = body[key] || null;
        const updated = await dataRequest(`duties?id=eq.${encodeURIComponent(dutyId)}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify(updates) }, session.access_token);
        return { ok: true, item: Array.isArray(updated) ? updated[0] : updated };
      }
      const result = await rpc('raise_sos', {
        p_duty_id: dutyId,
        p_latitude: body.latitude == null ? null : Number(body.latitude),
        p_longitude: body.longitude == null ? null : Number(body.longitude),
        p_payload: { ...body, idempotency_key: body.idempotency_key || null }
      }, session.access_token);
      return { ok: true, item: result };
    }
    const invoiceIssue = route.match(/^\/api\/invoices\/([^/]+)\/issue$/);
    if (invoiceIssue && method === 'POST') {
      const result = await rpc('issue_invoice', { p_invoice_id: invoiceIssue[1] }, session.access_token);
      return { ok: true, item: result };
    }
    const invoiceEInvoice = route.match(/^\/api\/invoices\/([^/]+)\/e-invoice$/);
    if (invoiceEInvoice && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const existingRows = await dataRequest(`einvoice_records?invoice_id=eq.${encodeURIComponent(invoiceEInvoice[1])}&select=*`, {}, session.access_token);
      if (existingRows[0]) return { ok: true, item: { ...existingRows[0], reference: existingRows[0].irn }, idempotent: true };
      const invoiceRows = await dataRequest(`invoices?id=eq.${encodeURIComponent(invoiceEInvoice[1])}&select=id,invoice_number,total_paise`, {}, session.access_token);
      const invoice = invoiceRows[0];
      if (!invoice) throw new Error('Invoice not found.');
      const irn = `mock_irn_${invoice.id}`;
      const inserted = await dataRequest('einvoice_records', {
        method: 'POST',
        body: JSON.stringify({ organization_id: organizationId, invoice_id: invoice.id, provider: 'mock_einvoice', status: 'issued', irn, qr_payload: `mock_qr_${invoice.invoice_number}`, payload: { invoice_number: invoice.invoice_number, total_paise: invoice.total_paise, mode: 'mock' } })
      }, session.access_token);
      const record = Array.isArray(inserted) ? inserted[0] : inserted;
      return { ok: true, item: { ...record, reference: record.irn } };
    }
    const invoiceDispatch = route.match(/^\/api\/invoices\/([^/]+)\/dispatch$/);
    if (invoiceDispatch && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const invoiceRows = await dataRequest(`invoices?id=eq.${encodeURIComponent(invoiceDispatch[1])}&select=id,invoice_number,total_paise`, {}, session.access_token);
      const invoice = invoiceRows[0];
      if (!invoice) throw new Error('Invoice not found.');
      const reference = `mock_msg_${invoice.id}_${body.channel || 'email'}`;
      const inserted = await dataRequest('collection_actions', {
        method: 'POST',
        body: JSON.stringify({ organization_id: organizationId, invoice_id: invoice.id, action_type: 'dispatch', channel: body.channel || 'email', status: 'queued', provider_reference: reference, scheduled_at: body.scheduled_at || null })
      }, session.access_token);
      const action = Array.isArray(inserted) ? inserted[0] : inserted;
      return { ok: true, invoice, dispatch: { ...action, reference, status: action.status } };
    }
    if (route === '/api/invitations' && method === 'POST') {
      const result = await rpc('create_invitation', { p_email: body.email, p_role: body.role === 'corporate' ? 'corporate_travel' : (body.role || 'driver'), p_branch_id: body.branch_id || null, p_expires_days: Number(body.expires_days || 7) }, session.access_token);
      return { ok: true, item: result.invitation, invite_token: result.invite_token };
    }
    if (route === '/api/invitations/accept' && method === 'POST') {
      const result = await rpc('accept_invitation', { p_token: body.token }, session.access_token);
      return { ok: true, item: result };
    }
    if (route === '/api/payments' && method === 'POST') {
      const result = await rpc('record_payment', {
        p_invoice_id: body.invoice_id,
        p_amount_paise: Number(body.amount_paise),
        p_mode: body.mode || 'other',
        p_idempotency_key: body.idempotency_key || null
      }, session.access_token);
      return { ok: true, item: result };
    }
    const expenseRoute = route.match(/^\/api\/duties\/([^/]+)\/expenses$/);
    if (expenseRoute && method === 'POST') {
      const result = await rpc('record_expense', { p_duty_id: expenseRoute[1], p_category: body.category || 'other', p_amount_paise: Number(body.amount_paise), p_note: body.note || '', p_attachment: body.attachment || {}, p_idempotency_key: body.idempotency_key || null }, session.access_token);
      return { ok: true, item: result };
    }
    const proofRoute = route.match(/^\/api\/duties\/([^/]+)\/proof$/);
    if (proofRoute && method === 'POST') {
      const result = await rpc('capture_duty_proof', {
        p_duty_id: proofRoute[1],
        p_proof_type: body.proof_type,
        p_proof_data: body.proof_data || body,
        p_storage_path: body.storage_path || null,
        p_idempotency_key: body.idempotency_key || null
      }, session.access_token);
      return { ok: true, item: result };
    }
    const trackRoute = route.match(/^\/api\/duties\/([^/]+)\/track$/);
    if (trackRoute && method === 'POST') {
      const result = await rpc('record_track_point', {
        p_duty_id: trackRoute[1],
        p_recorded_at: body.recorded_at || null,
        p_latitude: Number(body.latitude),
        p_longitude: Number(body.longitude),
        p_accuracy_m: body.accuracy_m == null ? null : Number(body.accuracy_m),
        p_battery_pct: body.battery_pct == null ? null : Number(body.battery_pct),
        p_source: body.source || 'driver_app',
        p_idempotency_key: body.idempotency_key || null
      }, session.access_token);
      return { ok: true, item: result };
    }
    if (route === '/api/sync/replay' && method === 'POST') {
      const operations = Array.isArray(body.operations) ? body.operations : [];
      const results = await Promise.all(operations.map(async operation => {
        const result = await rpc('enqueue_sync_operation', {
          p_device_id: body.device_id || 'browser',
          p_idempotency_key: operation.idempotency_key,
          p_entity_type: operation.entity_type,
          p_entity_id: operation.entity_id || null,
          p_operation: operation.operation,
          p_payload: operation.payload || {},
          p_client_created_at: operation.client_created_at || null
        }, session.access_token);
        return { idempotency_key: operation.idempotency_key, status: result.status || 'queued', result };
      }));
      return { ok: true, device_id: body.device_id || 'browser', accepted: results.length, failed: 0, results };
    }
    const calculateRoute = route.match(/^\/api\/duties\/([^/]+)\/calculate$/);
    if (calculateRoute && method === 'POST') {
      const result = await edgeFunction('calculate-duty', { duty_id: calculateRoute[1], inputs: body }, session.access_token);
      return result;
    }
    if ((route === '/api/onboarding' || route === '/api/setup') && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const rows = await dataRequest(`onboarding_states?organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      const steps = rows[0]?.steps || {};
      const definitions = [['organization_profile', 'Complete company profile'], ['default_branch', 'Set up a default branch'], ['tax_profile', 'Add GST and tax settings'], ['team_access', 'Invite the operating team'], ['masters', 'Add customer, driver and vehicle masters'], ['price_book', 'Publish a price book'], ['first_booking', 'Create the first booking'], ['driver_readiness', 'Enable driver field readiness']];
      const items = definitions.map(([key, label]) => ({ key, label, complete: steps[key]?.status === 'complete', status: steps[key]?.status || 'pending' }));
      return { ok: true, completed: items.filter(item => item.complete).length, total: items.length, progress_pct: Math.round(items.filter(item => item.complete).length * 100 / items.length), completed_at: rows[0]?.completed_at || null, items, metadata: rows[0]?.metadata || {} };
    }
    if (route === '/api/onboarding' && method === 'PATCH') {
      const organizationId = await activeOrganizationId();
      const currentRows = await dataRequest(`onboarding_states?organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      const steps = { ...(currentRows[0]?.steps || {}), [body.step]: { status: body.status || 'complete', updated_at: new Date().toISOString() } };
      const metadata = { ...(currentRows[0]?.metadata || {}), ...(body.metadata || {}) };
      const payload = { organization_id: organizationId, steps, metadata, completed_at: null };
      if (currentRows.length) await dataRequest(`onboarding_states?organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ steps, metadata }) }, session.access_token);
      else await dataRequest('onboarding_states', { method: 'POST', body: JSON.stringify(payload) }, session.access_token);
      return { ok: true, step: body.step, status: body.status || 'complete' };
    }
    if (route === '/api/onboarding/provision' && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const profile = body.organization || body;
      const organizationPatch = {};
      ['name', 'city', 'phone', 'gstin'].forEach(key => { if (profile[key] !== undefined) organizationPatch[key] = profile[key]; });
      if (Object.keys(organizationPatch).length) await dataRequest(`organizations?id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify(organizationPatch) }, session.access_token);
      if (body.branch) await dataRequest('branches', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, name: body.branch.name || 'Main branch', city: body.branch.city || profile.city || '', numbering_series: { code: body.branch.code || 'HQ' } }) }, session.access_token);
      return { ok: true, organization_id: organizationId, provisioned: true };
    }
    if (route === '/api/organization' && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const rows = await dataRequest(`organizations?id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      return { ok: true, item: rows[0] || null };
    }
    if (route === '/api/settings' && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const rows = await dataRequest(`organization_settings?organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
      return { ok: true, item: { organization_id: organizationId, settings: rows[0]?.settings || {} } };
    }
    if (route === '/api/settings' && method === 'PATCH') {
      const organizationId = await activeOrganizationId();
      const currentRows = await dataRequest(`organization_settings?organization_id=eq.${encodeURIComponent(organizationId)}&select=settings`, {}, session.access_token);
      const settings = { ...(currentRows[0]?.settings || {}), ...(body.settings || body) };
      const settingsPayload = { organization_id: organizationId, settings, updated_by: session.user?.id || null };
      if (currentRows.length) {
        const updated = await dataRequest(`organization_settings?organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ settings, updated_by: settingsPayload.updated_by }) }, session.access_token);
        return { ok: true, item: { organization_id: organizationId, settings: (Array.isArray(updated) ? updated[0]?.settings : updated?.settings) || settings } };
      }
      const inserted = await dataRequest('organization_settings', { method: 'POST', body: JSON.stringify(settingsPayload) }, session.access_token);
      return { ok: true, item: { organization_id: organizationId, settings: (Array.isArray(inserted) ? inserted[0]?.settings : inserted?.settings) || settings } };
    }
    if (route === '/api/audit' && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const limit = Math.min(Number(url.searchParams.get('limit') || 100), 100);
      const rows = await dataRequest(`audit_events?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=${limit}`, {}, session.access_token);
      return { ok: true, items: rows, count: rows.length };
    }
    if (route === '/api/integrations' && method === 'GET') {
      return { ok: true, items: [
        { key: 'payments', provider: 'Mock Payment', mode: 'mock', status: 'available', credentials_configured: false },
        { key: 'messaging', provider: 'Mock Messaging', mode: 'mock', status: 'available', credentials_configured: false },
        { key: 'telephony', provider: 'Mock Telephony', mode: 'mock', status: 'available', credentials_configured: false },
        { key: 'maps', provider: 'Mock Maps', mode: 'mock', status: 'available', credentials_configured: false },
        { key: 'einvoice', provider: 'Mock E-Invoice', mode: 'mock', status: 'available', credentials_configured: false },
        { key: 'storage', provider: 'Mock Storage', mode: 'mock', status: 'available', credentials_configured: false }
      ] };
    }
    const recurringRoute = route === '/api/bookings/recurring';
    if (recurringRoute && method === 'GET') {
      const organizationId = await activeOrganizationId(); const rows = await dataRequest(`recurring_bookings?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=100`, {}, session.access_token); return { ok: true, items: rows, count: rows.length };
    }
    if (recurringRoute && method === 'POST') {
      const organizationId = await activeOrganizationId(); const template = body.template || {}; const inserted = await dataRequest('recurring_bookings', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, customer_id: template.customer_id || null, cadence: body.cadence || 'weekly', start_at: body.start_at, end_at: body.end_at || null, occurrences: Number(body.occurrences || 1), template }) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted, generated: [] };
    }
    const stopsRoute = route.match(/^\/api\/bookings\/([^/]+)\/stops$/);
    if (stopsRoute && method === 'GET') {
      const organizationId = await activeOrganizationId(); const rows = await dataRequest(`booking_stops?organization_id=eq.${encodeURIComponent(organizationId)}&booking_id=eq.${encodeURIComponent(stopsRoute[1])}&select=*&order=stop_index.asc`, {}, session.access_token); return { ok: true, items: rows };
    }
    if (stopsRoute && method === 'POST') {
      const organizationId = await activeOrganizationId(); const stops = Array.isArray(body.stops) ? body.stops : [body]; const rows = stops.map((stop, index) => ({ organization_id: organizationId, booking_id: stopsRoute[1], stop_index: index + 1, label: stop.label || `Stop ${index + 1}`, address: stop.address || stop, arrival_at: stop.arrival_at || null, departure_at: stop.departure_at || null, status: stop.status || 'planned' })); const inserted = await dataRequest('booking_stops', { method: 'POST', body: JSON.stringify(rows) }, session.access_token); return { ok: true, items: inserted };
    }
    const capacityRoute = route.match(/^\/api\/capacity\/locks(?:\/([^/]+)\/release)?$/);
    if (capacityRoute && method === 'GET') { const organizationId = await activeOrganizationId(); const rows = await dataRequest(`capacity_locks?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=starts_at.asc`, {}, session.access_token); return { ok: true, items: rows }; }
    if (capacityRoute && capacityRoute[1] && method === 'POST') { const organizationId = await activeOrganizationId(); await dataRequest(`capacity_locks?id=eq.${encodeURIComponent(capacityRoute[1])}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'released', released_at: new Date().toISOString() }) }, session.access_token); return { ok: true, status: 'released' }; }
    if (route === '/api/capacity/locks' && method === 'POST') { const organizationId = await activeOrganizationId(); const inserted = await dataRequest('capacity_locks', { method: 'POST', body: JSON.stringify({ ...body, organization_id: organizationId }) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted }; }
    const paymentCapture = route.match(/^\/api\/payment-links\/([^/]+)\/capture$/);
    if (paymentCapture && method === 'POST') { const organizationId = await activeOrganizationId(); await dataRequest(`payment_links?id=eq.${encodeURIComponent(paymentCapture[1])}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'paid', paid_at: new Date().toISOString(), provider_reference: `mock_payment_${paymentCapture[1]}` }) }, session.access_token); return { ok: true, status: 'paid', reference: `mock_payment_${paymentCapture[1]}` }; }
    const financialDecision = route.match(/^\/api\/financial-actions\/([^/]+)\/(approve|reject)$/);
    if (financialDecision && method === 'POST') { const organizationId = await activeOrganizationId(); const status = financialDecision[2] === 'approve' ? 'approved' : 'rejected'; const updated = await dataRequest(`financial_actions?id=eq.${encodeURIComponent(financialDecision[1])}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status, reviewed_by: session.user?.id || null, review_comment: body.comment || '', reviewed_at: new Date().toISOString() }) }, session.access_token); return { ok: true, item: Array.isArray(updated) ? updated[0] : updated }; }
    const networkAccept = route === '/api/network/edges/accept' && method === 'POST';
    if (networkAccept) { const organizationId = await activeOrganizationId(); const updated = await dataRequest(`network_edges?id=eq.${encodeURIComponent(body.edge_id)}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'active', accepted_at: new Date().toISOString() }) }, session.access_token); return { ok: true, item: Array.isArray(updated) ? updated[0] : updated }; }
    const remainingResource = route.match(/^\/api\/(billing-notes|payment-links|jobs)$/);
    if (remainingResource && method === 'GET') { const organizationId = await activeOrganizationId(); const table = { 'billing-notes': 'billing_notes', 'payment-links': 'payment_links', jobs: 'jobs' }[remainingResource[1]]; const rows = await dataRequest(`${table}?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=100`, {}, session.access_token); return { ok: true, items: rows, count: rows.length }; }
    if (remainingResource && method === 'POST') { const organizationId = await activeOrganizationId(); const table = { 'billing-notes': 'billing_notes', 'payment-links': 'payment_links', jobs: 'jobs' }[remainingResource[1]]; const write = { ...body, organization_id: organizationId, created_by: session.user?.id || null }; if (remainingResource[1] === 'payment-links') { const raw = `afpay_${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`; write.token_hash = await sha256(raw); write.short_code = raw.slice(-10).toUpperCase(); write.expires_at = body.expires_at || new Date(Date.now() + 7 * 86400000).toISOString(); const inserted = await dataRequest(table, { method: 'POST', body: JSON.stringify(write) }, session.access_token); const item = Array.isArray(inserted) ? inserted[0] : inserted; return { ok: true, item: { ...item, token: raw, url: `/pay/${item.short_code}` } }; } const inserted = await dataRequest(table, { method: 'POST', body: JSON.stringify(write) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted }; }
    const jobRun = route.match(/^\/api\/jobs\/([^/]+)\/run$/);
    if (jobRun && method === 'POST') { const organizationId = await activeOrganizationId(); await dataRequest(`jobs?id=eq.${encodeURIComponent(jobRun[1])}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'completed', attempts: 1, completed_at: new Date().toISOString(), result: { mode: 'supabase_mock_worker', processed_at: new Date().toISOString() } }) }, session.access_token); return { ok: true, status: 'completed' }; }
    if (route === '/api/devices' && method === 'GET') { const rows = await dataRequest(`device_bindings?user_id=eq.${encodeURIComponent(session.user.id)}&select=*&order=last_seen_at.desc`, {}, session.access_token); return { ok: true, items: rows }; }
    if (route === '/api/devices' && method === 'POST') { const organizationId = await activeOrganizationId(); const deviceId = body.device_id || `device-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`; const write = { organization_id: organizationId, user_id: session.user.id, device_id: deviceId, platform: body.platform || 'mobile', push_token: body.push_token || '', status: 'active', last_seen_at: new Date().toISOString() }; const existing = await dataRequest(`device_bindings?user_id=eq.${encodeURIComponent(session.user.id)}&device_id=eq.${encodeURIComponent(deviceId)}&select=id`, {}, session.access_token); const result = existing[0] ? await dataRequest(`device_bindings?id=eq.${encodeURIComponent(existing[0].id)}`, { method: 'PATCH', body: JSON.stringify(write) }, session.access_token) : await dataRequest('device_bindings', { method: 'POST', body: JSON.stringify(write) }, session.access_token); return { ok: true, item: Array.isArray(result) ? result[0] : result }; }
    if (route === '/api/security/2fa' && method === 'GET') { const factorResponse = await authRequest('/factors', {}, session.access_token); const factors = Array.isArray(factorResponse) ? factorResponse : (factorResponse.all || factorResponse.totp || []); const factor = factors.find(item => item.factor_type === 'totp' || item.type === 'totp') || null; return { ok: true, provider: 'supabase_auth_mfa', enabled: factors.some(item => item.status === 'verified' && (item.factor_type === 'totp' || item.type === 'totp')), factor }; }
    if (route === '/api/security/2fa/setup' && method === 'POST') { const factor = await authRequest('/factors', { method: 'POST', body: JSON.stringify({ factor_type: 'totp', friendly_name: 'Axiom Fleet operator' }) }, session.access_token); if (!factor?.id) throw new Error('Supabase Auth did not return an MFA factor.'); localStorage.setItem(mfaPendingKey, factor.id); return { ok: true, provider: 'supabase_auth_mfa', factor_id: factor.id, factor_type: 'totp', otpauth_url: factor.totp?.uri || '', qr_code: factor.totp?.qr_code || '', secret: factor.totp?.secret || '' }; }
    if (route === '/api/security/2fa/verify' && method === 'POST') { const factorId = body.factor_id || localStorage.getItem(mfaPendingKey); const code = String(body.code || '').trim(); if (!factorId || !/^[0-9]{6}$/.test(code)) throw new Error('A six digit authenticator code and pending factor are required.'); const challenge = await authRequest(`/factors/${encodeURIComponent(factorId)}/challenge`, { method: 'POST', body: '{}' }, session.access_token); await authRequest(`/factors/${encodeURIComponent(factorId)}/verify`, { method: 'POST', body: JSON.stringify({ code, challenge_id: challenge.id }) }, session.access_token); localStorage.removeItem(mfaPendingKey); if (session.refresh_token) { const refreshed = await authRequest('/token?grant_type=refresh_token', { method: 'POST', body: JSON.stringify({ refresh_token: session.refresh_token }) }); writeSession({ access_token: refreshed.access_token, refresh_token: refreshed.refresh_token || session.refresh_token, expires_at: refreshed.expires_at || Math.floor(Date.now() / 1000) + (refreshed.expires_in || 3600), user: refreshed.user || session.user }); } return { ok: true, provider: 'supabase_auth_mfa', enabled: true, aal: 'aal2' }; }
    if (route === '/api/security/2fa/disable' && method === 'POST') { const factorId = body.factor_id || localStorage.getItem(mfaPendingKey); if (!factorId) throw new Error('No Supabase Auth MFA factor is enrolled.'); await authRequest(`/factors/${encodeURIComponent(factorId)}`, { method: 'DELETE' }, session.access_token); localStorage.removeItem(mfaPendingKey); return { ok: true, provider: 'supabase_auth_mfa', enabled: false }; }
    const apiKeyRoute = route.match(/^\/api\/security\/api-keys(?:\/([^/]+)\/revoke)?$/);
    if (apiKeyRoute && method === 'GET') { const organizationId = await activeOrganizationId(); const rows = await dataRequest(`api_keys?organization_id=eq.${encodeURIComponent(organizationId)}&select=id,name,key_prefix,scopes,status,last_used_at,created_by,created_at,revoked_at&order=created_at.desc`, {}, session.access_token); return { ok: true, items: rows }; }
    if (apiKeyRoute && method === 'POST' && apiKeyRoute[1]) { const organizationId = await activeOrganizationId(); await dataRequest(`api_keys?id=eq.${encodeURIComponent(apiKeyRoute[1])}&organization_id=eq.${encodeURIComponent(organizationId)}`, { method: 'PATCH', body: JSON.stringify({ status: 'revoked', revoked_at: new Date().toISOString() }) }, session.access_token); return { ok: true, status: 'revoked' }; }
    if (apiKeyRoute && method === 'POST') { const raw = `af_live_${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`; const organizationId = await activeOrganizationId(); const inserted = await dataRequest('api_keys', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, name: body.name || 'API key', key_hash: await sha256(raw), key_prefix: raw.slice(0, 12), scopes: body.scopes || ['bookings:read'], created_by: session.user?.id || null }) }, session.access_token); const item = Array.isArray(inserted) ? inserted[0] : inserted; return { ok: true, item: { ...item, key: raw } }; }
    const privacyFulfill = route.match(/^\/api\/privacy\/requests\/([^/]+)\/fulfill$/);
    if (privacyFulfill && method === 'POST') { await dataRequest(`privacy_requests?id=eq.${encodeURIComponent(privacyFulfill[1])}`, { method: 'PATCH', body: JSON.stringify({ status: 'completed', completed_at: new Date().toISOString() }) }, session.access_token); return { ok: true, status: 'completed' }; }
    const employeeLifecycle = route.match(/^\/api\/employees\/([^/]+)\/(deactivate|reactivate)$/);
    if (employeeLifecycle && method === 'POST') { const status = employeeLifecycle[2] === 'deactivate' ? 'inactive' : 'active'; const updated = await dataRequest(`employees?id=eq.${encodeURIComponent(employeeLifecycle[1])}`, { method: 'PATCH', body: JSON.stringify({ status, updated_at: new Date().toISOString() }) }, session.access_token); return { ok: true, status, item: Array.isArray(updated) ? updated[0] : updated }; }
    const extendedRoute = route.match(/^\/api\/(supplier-bills|costs|vehicle-costs|driver-payouts|supplier-payouts|alerts|geofences|sla)$/);
    if (extendedRoute && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const table = { 'supplier-bills': 'supplier_bills', costs: 'cost_entries', 'vehicle-costs': 'cost_entries', 'driver-payouts': 'payouts', 'supplier-payouts': 'payouts', alerts: 'alerts', geofences: 'geofences', sla: 'sla_events' }[extendedRoute[1]];
      const rows = await dataRequest(`${table}?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=100`, {}, session.access_token);
      return { ok: true, items: rows, count: rows.length };
    }
    if (extendedRoute && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const kind = extendedRoute[1];
      const table = { 'supplier-bills': 'supplier_bills', costs: 'cost_entries', 'vehicle-costs': 'cost_entries', 'driver-payouts': 'payouts', 'supplier-payouts': 'payouts', alerts: 'alerts', geofences: 'geofences', sla: 'sla_events' }[kind];
      const write = { ...body, organization_id: organizationId };
      if (['supplier-bills', 'costs', 'vehicle-costs', 'driver-payouts', 'supplier-payouts'].includes(kind)) write.created_by = body.created_by || session.user?.id || null;
      if (kind === 'driver-payouts' || kind === 'supplier-payouts') write.recipient_type = body.recipient_type || (kind === 'driver-payouts' ? 'driver' : 'supplier');
      if (kind === 'sla') write.status = body.status || 'open';
      const inserted = await dataRequest(table, { method: 'POST', body: JSON.stringify(write) }, session.access_token);
      return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    const networkRoute = route.match(/^\/api\/network\/(edges|offers|settlements)$/);
    if (networkRoute && method === 'GET') {
      const organizationId = await activeOrganizationId(); const table = { edges: 'network_edges', offers: 'network_offers', settlements: 'settlements' }[networkRoute[1]]; const rows = await dataRequest(`${table}?organization_id=eq.${encodeURIComponent(organizationId)}&select=*&order=created_at.desc&limit=100`, {}, session.access_token); return { ok: true, items: rows, count: rows.length };
    }
    if (networkRoute && method === 'POST') {
      const organizationId = await activeOrganizationId(); const table = { edges: 'network_edges', offers: 'network_offers', settlements: 'settlements' }[networkRoute[1]]; const inserted = await dataRequest(table, { method: 'POST', body: JSON.stringify({ ...body, organization_id: organizationId }) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    if (route === '/api/financial-actions' && method === 'POST') {
      const organizationId = await activeOrganizationId(); const inserted = await dataRequest('financial_actions', { method: 'POST', body: JSON.stringify({ ...body, organization_id: organizationId, requested_by: session.user?.id || null }) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    if (route === '/api/tax/calculate' && method === 'POST') {
      const taxable = Number(body.taxable_paise || 0); const rate = Number(body.tax_rate_bps || 1800); const tax = Math.round(taxable * rate / 10000); const intra = String(body.origin_state || '').trim().toLowerCase() === String(body.destination_state || body.origin_state || '').trim().toLowerCase();
      return { ok: true, tax: { taxable_paise: taxable, rate_bps: rate, supply_type: intra ? 'intra_state' : 'inter_state', cgst_paise: intra ? Math.floor(tax / 2) : 0, sgst_paise: intra ? tax - Math.floor(tax / 2) : 0, igst_paise: intra ? 0 : tax, total_paise: taxable + tax } };
    }
    if (route === '/api/updates' && method === 'GET') {
      const organizationId = await activeOrganizationId();
      const [duties, alerts] = await Promise.all([dataRequest(`duties?organization_id=eq.${encodeURIComponent(organizationId)}&select=id,status,driver_id,vehicle_id,updated_at&order=updated_at.desc&limit=100`, {}, session.access_token), dataRequest(`alerts?organization_id=eq.${encodeURIComponent(organizationId)}&select=id,alert_type,severity,status,created_at&order=created_at.desc&limit=100`, {}, session.access_token)]);
      return { ok: true, cursor: new Date().toISOString(), events: duties.map(item => ({ type: 'duty.changed', ...item })).concat(alerts.map(item => ({ type: 'alert.created', ...item }))) };
    }
    if (route === '/api/reports/export' && method === 'POST') {
      const organizationId = await activeOrganizationId(); const token = crypto.randomUUID ? crypto.randomUUID() : `export-${Date.now()}`; const inserted = await dataRequest('report_exports', { method: 'POST', body: JSON.stringify({ organization_id: organizationId, report_type: body.report_type || 'operations', filters: body.filters || {}, download_token: token, content: 'Axiom Fleet,report_type\n' + (body.report_type || 'operations'), expires_at: new Date(Date.now() + 7 * 86400000).toISOString(), created_by: session.user?.id || null }) }, session.access_token); const item = Array.isArray(inserted) ? inserted[0] : inserted; return { ok: true, item: { ...item, download_url: `/api/reports/exports/${item.id}` } };
    }
    if (route === '/api/privacy/retention' && method === 'POST') {
      const organizationId = await activeOrganizationId(); const entityId = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(body.entity_id || '')) ? body.entity_id : (crypto.randomUUID ? crypto.randomUUID() : '00000000-0000-4000-8000-000000000000'); const inserted = await dataRequest('retention_locks', { method: 'POST', body: JSON.stringify({ ...body, entity_id: entityId, organization_id: organizationId, created_by: session.user?.id || null }) }, session.access_token); return { ok: true, item: Array.isArray(inserted) ? inserted[0] : inserted };
    }
    if (route === '/api/admin/kpis' && method === 'GET') {
      const [organizations, users, bookings, duties, alerts] = await Promise.all([dataRequest('organizations?select=id&limit=1000', {}, session.access_token), dataRequest('profiles?select=id&limit=1000', {}, session.access_token), dataRequest('bookings?select=id&limit=1000', {}, session.access_token), dataRequest('duties?select=id&limit=1000', {}, session.access_token), dataRequest('alerts?status=eq.open&select=id&limit=1000', {}, session.access_token)]);
      return { ok: true, kpis: { organizations: organizations.length, users: users.length, bookings: bookings.length, duties: duties.length, open_alerts: alerts.length } };
    }
    const resourceMap = {
      '/api/customers': 'customers',
      '/api/drivers': 'drivers',
      '/api/vehicles': 'vehicles',
      '/api/bookings': 'bookings',
      '/api/duties': 'duties',
      '/api/invoices': 'invoices',
      '/api/branches': 'branches',
      '/api/suppliers': 'suppliers',
      '/api/price-books': 'price_books',
      '/api/documents': 'documents',
      '/api/invitations': 'invitations',
      '/api/employees': 'employees',
      '/api/policies': 'travel_policies',
      '/api/approvals': 'booking_approvals',
      '/api/notifications': 'notifications',
      '/api/tickets': 'support_tickets',
      '/api/privacy/requests': 'privacy_requests',
      '/api/settings': 'organization_settings'
    };
    if (route === '/api/overview' && method === 'GET') {
      const [duties, invoices] = await Promise.all([
        dataRequest('duties?select=status', {}, session.access_token),
        dataRequest('invoices?select=status,total_paise', {}, session.access_token)
      ]);
      const dutySummary = {};
      duties.forEach(item => { dutySummary[item.status] = (dutySummary[item.status] || 0) + 1; });
      const invoiceSummary = {};
      invoices.forEach(item => {
        invoiceSummary[item.status] ||= { count: 0, total_paise: 0 };
        invoiceSummary[item.status].count += 1;
        invoiceSummary[item.status].total_paise += Number(item.total_paise || 0);
      });
      return { ok: true, duties: dutySummary, invoices: invoiceSummary };
    }
    if (route === '/api/organization/checklist' && method === 'GET') {
      const [branches, customers, drivers, vehicles, priceBooks, bookings] = await Promise.all([
        dataRequest('branches?select=id&limit=1', {}, session.access_token),
        dataRequest('customers?select=id&limit=1', {}, session.access_token),
        dataRequest('drivers?select=id&limit=1', {}, session.access_token),
        dataRequest('vehicles?select=id&limit=1', {}, session.access_token),
        dataRequest('price_books?select=id&status=eq.active&limit=1', {}, session.access_token),
        dataRequest('bookings?select=id&limit=1', {}, session.access_token)
      ]);
      const checks = [['branch', 'Add a branch', branches], ['customer', 'Add a customer', customers], ['driver', 'Add a driver', drivers], ['vehicle', 'Add a vehicle', vehicles], ['price_book', 'Publish a price book', priceBooks], ['booking', 'Create the first booking', bookings]];
      const items = checks.map(([key, label, rows]) => ({ key, label, complete: rows.length > 0 }));
      return { ok: true, completed: items.filter(item => item.complete).length, total: items.length, items };
    }
    if (route === '/api/reports/summary' && method === 'GET') {
      const [customers, duties, invoices, payments] = await Promise.all([
        dataRequest('customers?select=id&status=eq.active', {}, session.access_token),
        dataRequest('duties?select=status', {}, session.access_token),
        dataRequest('invoices?select=status,total_paise', {}, session.access_token),
        dataRequest('payments?select=status,amount_paise&status=eq.succeeded', {}, session.access_token)
      ]);
      const dutySummary = {}; duties.forEach(item => { dutySummary[item.status] = (dutySummary[item.status] || 0) + 1; });
      const invoiceSummary = {}; invoices.forEach(item => { invoiceSummary[item.status] ||= { count: 0, total_paise: 0 }; invoiceSummary[item.status].count += 1; invoiceSummary[item.status].total_paise += Number(item.total_paise || 0); });
      return { ok: true, period: url.searchParams.get('period') || 'current', summary: { customers: customers.length, duties: dutySummary, invoices: invoiceSummary, payments: { count: payments.length, total_paise: payments.reduce((sum, item) => sum + Number(item.amount_paise || 0), 0) } } };
    }
    if (route === '/api/bookings' && method === 'POST') {
      const organizationId = await activeOrganizationId();
      const evaluation = await corporateBookingEvaluation(body, 'book');
      const bookingPayload = normalizedBooking({ ...body, status: evaluation?.outcome === 'needs_approval' ? 'pending_approval' : body.status, policy_context: evaluation || body.policy_context || {} }, organizationId);
      const inserted = await dataRequest('bookings', { method: 'POST', body: JSON.stringify(bookingPayload) }, session.access_token);
      const item = Array.isArray(inserted) ? inserted[0] : inserted;
      await persistCorporateApproval(item.id, evaluation);
      return { ok: true, item, corporate_evaluation: evaluation };
    }
    const singleResourceMatch = route.match(/^\/api\/(customers|drivers|vehicles|branches|suppliers|price-books|documents|employees|policies)\/([^/]+)$/);
    if (singleResourceMatch) {
      const pluralRoute = `/api/${singleResourceMatch[1]}`;
      const singleTable = resourceMap[pluralRoute];
      const entityId = singleResourceMatch[2];
      if (singleTable) {
        const organizationId = await activeOrganizationId();
        if (method === 'PATCH') {
          let patchBody = { ...body };
          if (singleTable === 'vehicles') {
            const {
              id: _id, created_at: _cat, updated_at: _uat, organization_id: _oid,
              registration_number, vehicle_type, vehicle_group, make_model, year, city, status,
              compliance,
              ...rest
            } = patchBody;
            patchBody = {};
            if (registration_number !== undefined) patchBody.registration_number = registration_number;
            if (vehicle_type !== undefined) patchBody.vehicle_type = vehicle_type;
            if (vehicle_group !== undefined) patchBody.vehicle_group = vehicle_group;
            if (make_model !== undefined) patchBody.make_model = make_model;
            if (year !== undefined) patchBody.year = year ? Number(year) : null;
            if (city !== undefined) patchBody.city = city;
            if (status !== undefined) patchBody.status = status;
            if (compliance !== undefined || Object.keys(rest).length > 0) {
              patchBody.compliance = { ...(compliance || {}), ...rest };
            }
          }
          const rows = await dataRequest(`${singleTable}?id=eq.${encodeURIComponent(entityId)}&organization_id=eq.${encodeURIComponent(organizationId)}`, {
            method: 'PATCH',
            body: JSON.stringify(patchBody)
          }, session.access_token);
          return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
        }
        if (method === 'GET') {
          const rows = await dataRequest(`${singleTable}?id=eq.${encodeURIComponent(entityId)}&organization_id=eq.${encodeURIComponent(organizationId)}&select=*`, {}, session.access_token);
          return { ok: true, item: rows[0] || null };
        }
        if (method === 'DELETE') {
          await dataRequest(`${singleTable}?id=eq.${encodeURIComponent(entityId)}&organization_id=eq.${encodeURIComponent(organizationId)}`, {
            method: 'DELETE'
          }, session.access_token);
          return { ok: true, deleted: true };
        }
      }
    }
    const table = resourceMap[route];
    if (!table) throw new Error(`Supabase adapter route not implemented: ${method} ${path}`);
    if (method === 'GET') {
      const limit = Math.min(Number(url.searchParams.get('limit') || 100), 100);
      const order = table === 'bookings' ? 'scheduled_at.asc' : table === 'duties' ? 'reporting_at.asc' : table === 'organization_settings' ? 'updated_at.desc' : 'created_at.desc';
      const rows = await dataRequest(`${table}?select=*&order=${order}&limit=${limit}`, {}, session.access_token);
      return { ok: true, items: rows, count: rows.length };
    }
    const organizationScopedTables = new Set(['customers', 'drivers', 'vehicles', 'bookings', 'duties', 'invoices', 'branches', 'suppliers', 'price_books', 'documents', 'invitations', 'employees', 'travel_policies', 'booking_approvals', 'notifications', 'support_tickets', 'privacy_requests']);
    const writeBody = organizationScopedTables.has(table) ? { ...body, organization_id: await activeOrganizationId() } : body;
    if (table === 'notifications' && writeBody.recipient !== undefined) {
      writeBody.payload = { ...(writeBody.payload || {}), recipient: writeBody.recipient, variables: writeBody.variables || {} };
      delete writeBody.recipient;
      delete writeBody.variables;
    }
    if (table === 'vehicles') {
      const {
        id: _id, created_at: _cat, updated_at: _uat,
        registration_number, vehicle_type = 'sedan', vehicle_group, make_model, year, city = '', status = 'active',
        compliance,
        ...rest
      } = writeBody;
      const combinedCompliance = { ...(compliance || {}), ...rest };
      const normalizedVehicle = {
        organization_id: writeBody.organization_id,
        registration_number,
        vehicle_type,
        vehicle_group: vehicle_group || null,
        make_model: make_model || null,
        year: year ? Number(year) : null,
        city: city || '',
        status: status || 'active',
        compliance: combinedCompliance
      };
      const rows = await dataRequest(table, { method, body: JSON.stringify(normalizedVehicle) }, session.access_token);
      return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
    }
    const rows = await dataRequest(table, { method, body: JSON.stringify(writeBody) }, session.access_token);
    return { ok: true, item: Array.isArray(rows) ? rows[0] : rows };
  }
  async function updateMe(payload) {
    const session = await refreshIfNeeded();
    if (!session?.access_token) throw new Error('Sign in required.');
    const current = await currentUser();
    const profilePatch = {};
    if (payload.full_name !== undefined) profilePatch.full_name = payload.full_name;
    if (payload.phone !== undefined) profilePatch.phone = payload.phone;
    if (payload.timezone !== undefined) profilePatch.timezone = payload.timezone;
    if (Object.keys(profilePatch).length) {
      await dataRequest(`profiles?id=eq.${encodeURIComponent(current.user.id)}`, {
        method: 'PATCH',
        body: JSON.stringify(profilePatch)
      }, session.access_token);
    }
    if (current.user.organization?.id) {
      const organizationPatch = {};
      if (payload.organization_name !== undefined) organizationPatch.name = payload.organization_name;
      if (payload.organization_city !== undefined) organizationPatch.city = payload.organization_city;
      if (payload.gstin !== undefined) organizationPatch.gstin = payload.gstin;
      if (Object.keys(organizationPatch).length) {
        await dataRequest(`organizations?id=eq.${encodeURIComponent(current.user.organization.id)}`, {
          method: 'PATCH',
          body: JSON.stringify(organizationPatch)
        }, session.access_token);
      }
    }
    return currentUser();
  }
  async function publicRequest(path, options = {}) {
    if (!enabled) throw new Error('Supabase is not configured.');
    const url = new URL(path, window.location.origin);
    const route = url.pathname.replace(/\/$/, '') || '/';
    let body = {};
    try { body = JSON.parse(options.body || '{}'); } catch (_) { body = {}; }
    const functionName = route.startsWith('/api/feedback/v1/') ? 'feedback-public' : route.startsWith('/api/location-shares/') ? 'gap-completion-orchestrator' : 'enterprise-orchestrator';
    return edgeFunction(functionName, { path: route, method: options.method || 'GET', query: Object.fromEntries(url.searchParams.entries()), body }, config.anonKey);
  }
  async function request(path, options = {}) {
    if (!enabled) throw new Error('Supabase is not configured.');
    const method = options.method || 'GET';
    let payload = {};
    if (options.body) {
      try { payload = JSON.parse(options.body); } catch (_) { payload = {}; }
    }
    if (path === '/api/auth/signup' && method === 'POST') return signUp(payload);
    if (path === '/api/auth/login' && method === 'POST') return signIn(payload);
    if (path === '/api/auth/password-reset' && method === 'POST') { await authRequest('/recover', { method: 'POST', body: JSON.stringify({ email: payload.email }) }); return { ok: true, message: 'If that address exists, a reset link will be sent shortly.' }; }
    if (path === '/api/auth/me' && method === 'GET') return currentUser();
    if (path === '/api/auth/me' && method === 'PATCH') return updateMe(payload);
    if (path === '/api/auth/logout' && method === 'POST') return signOut();
    const billIntelligenceResult = await supabaseBillIntelligenceRequest(path, options);
    if (billIntelligenceResult !== undefined) return billIntelligenceResult;
    const financeReportingResult = await supabaseFinanceReportingRequest(path, options);
    if (financeReportingResult !== undefined) return financeReportingResult;
    const communicationsResult = await supabaseCommunicationsRequest(path, options);
    if (communicationsResult !== undefined) return communicationsResult;
    const supplierFinanceResult = await supabaseSupplierFinanceRequest(path, options);
    if (supplierFinanceResult !== undefined) return supplierFinanceResult;
    const financeControlsResult = await supabaseFinanceControlsRequest(path, options);
    if (financeControlsResult !== undefined) return financeControlsResult;
    const feedbackResult = await supabaseFeedbackRequest(path, options);
    if (feedbackResult !== undefined) return feedbackResult;
    const gapResult = await supabaseGapRequest(path, options);
    if (gapResult !== undefined) return gapResult;
    const workspaceResult = await supabaseWorkspaceRequest(path, options);
    if (workspaceResult !== undefined) return workspaceResult;
    const enterpriseResult = await supabaseEnterpriseRequest(path, options);
    if (enterpriseResult !== undefined) return enterpriseResult;
    const phase3Result = await supabasePhase3Request(path, options);
    if (phase3Result !== undefined) return phase3Result;
    const corporateResult = await supabaseCorporateRequest(path, options);
    if (corporateResult !== undefined) return corporateResult;
    const p0Result = await supabaseP0Request(path, options);
    if (p0Result !== undefined) return p0Result;
    if (path.startsWith('/api/network/v1')) return supabaseNetworkRequest(path, options);
    if (path.startsWith('/api/overview') || /^\/api\/(customers|drivers|vehicles|bookings|duties|invoices|payments|sync|branches|suppliers|price-books|documents|invitations|employees|policies|approvals|notifications|devices|reports|audit|tickets|privacy|integrations|organization|settings|onboarding|setup|network|supplier-bills|costs|vehicle-costs|driver-payouts|supplier-payouts|financial-actions|alerts|geofences|sla|tax|admin|capacity|availability|allotment|billing-notes|payment-links|jobs|security)/.test(path)) return supabaseDomainRequest(path, options);
    throw new Error(`Supabase adapter route not implemented: ${method} ${path}`);
  }
  window.AxiomSupabaseAdapter = { enabled, request, publicRequest };
})();
