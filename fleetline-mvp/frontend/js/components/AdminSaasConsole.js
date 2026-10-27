/**
 * Axiom Mobility (Fleetline) 10/10 Super-Admin SaaS & Revenue Control Plane Component.
 * Zero-Build Vanilla ES6+ State & Sticky Table Module.
 * Hardened with AbortController, Event Delegation, and In-Flight Request Guards.
 *
 * Implements:
 * 1. Executive Summary Bar (Total Users in System, Active/Blocked Tenants, Pending Leads, Total Receivables Owed to Axiom)
 * 2. Website Prospects & Sales CRM (Capture, Deduplication, Call Notes, 1-Click Onboarding)
 * 3. Axiom Receivables Ledger & Delinquent Tenant Access Control ("Kill Switch")
 * 4. Tenant Impersonation & Feature Flag Control
 */

export class AdminSaasConsole {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("admin-saas-view") : null);
    this.onImpersonate = options.onImpersonate || (() => {});
    this.abortController = new AbortController();
    this.inFlightRequests = new Set();

    this.state = {
      activeTab: "ALL",
      activeView: "TENANTS", // "TENANTS" | "RECEIVABLES" | "PROSPECTS"
      tenants: [],
      kpis: {
        active_corporates: 71,
        corporates_monthly_delta: "+4 this mo",
        active_vendor_subscriptions: 34,
        churn_risk_count: 2,
        mrr_paise: 30999700,
        gtv_platform_paise: 1830408100,
        sla_demotions_today: 2,
        pending_leads: 2,
      },
      overview: {
        total_tenants: 34,
        active_tenants: 32,
        blocked_tenants: 2,
        total_users_in_system: 6,
        total_drivers: 74,
        total_prospects_pending: 2,
        total_receivables_outstanding_paise: 45520000,
        overdue_receivables_amount_paise: 32000000,
        total_receivables_inr: 455200,
        overdue_receivables_inr: 320000,
        tenants: [
          {
            tenant_id: "org_vendor_rapid",
            tenant_name: "RapidFleet Logistics Pvt Ltd",
            user_count: 2,
            trip_count: 42,
            total_billed_paise: 48520000,
            total_paid_paise: 35000000,
            amount_owed_paise: 13520000,
            days_overdue: 12,
            account_status: "ACTIVE",
            block_reason: "",
            credit_limit_paise: 10000000,
          },
          {
            tenant_id: "org_vendor_blueline",
            tenant_name: "BlueLine Premier Cabs",
            user_count: 1,
            trip_count: 28,
            total_billed_paise: 25000000,
            total_paid_paise: 25000000,
            amount_owed_paise: 0,
            days_overdue: 0,
            account_status: "ACTIVE",
            block_reason: "",
            credit_limit_paise: 10000000,
          },
          {
            tenant_id: "org_vendor_cityfleet",
            tenant_name: "CityFleet Commercial Transport",
            user_count: 2,
            trip_count: 35,
            total_billed_paise: 62000000,
            total_paid_paise: 30000000,
            amount_owed_paise: 32000000,
            days_overdue: 45,
            account_status: "SOFT_BLOCKED",
            block_reason: "Overdue invoice > 30 days",
            credit_limit_paise: 5000000,
          },
        ],
      },
      prospects: [
        {
          id: "prsp_001",
          contact_name: "Rajesh Sharma",
          company_name: "Sharma Corporate Cabs",
          email: "rajesh@sharmacabs.in",
          mobile_number: "+919820011223",
          message: "Interested in 50-cab ETS solution for Hinjawadi IT corridor.",
          status: "QUALIFIED",
          sales_notes: [{ timestamp: new Date().toISOString(), author: "sales@axiomfleet.in", note: "Called Rajesh; qualified 40 sedans + 10 EV fleet requirement." }],
          assigned_sales_rep: "sales@axiomfleet.in",
          converted_tenant_id: null,
          created_at: new Date().toISOString(),
        },
        {
          id: "prsp_002",
          contact_name: "Vikram Malhotra",
          company_name: "Apex Shuttles Pvt Ltd",
          email: null,
          mobile_number: "+919811234567",
          message: "Need pricing for daily employee commute tracking.",
          status: "NEW",
          sales_notes: [],
          assigned_sales_rep: "",
          converted_tenant_id: null,
          created_at: new Date().toISOString(),
        },
      ],
      selectedTenantForImpersonation: null,
      topUpModalTenant: null,
    };

    this.inrFormatter = new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    });
    this.decimalFormatter = new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  destroy() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  async init() {
    await this.fetchData();
    if (this.abortController.signal.aborted) return;
    this.render();
    this.bindEvents();
  }

  async fetchData() {
    // 1. Fetch Tenant Subscriptions
    try {
      const res = await fetch("/api/v1/admin/saas/tenants", {
        signal: this.abortController.signal,
      });
      if (res.ok) {
        const data = await res.json();
        if (this.abortController.signal.aborted) return;
        if (data.tenants) this.state.tenants = data.tenants;
        if (data.kpi_strip) this.state.kpis = data.kpi_strip;
      }
    } catch (err) {
      if (err.name === "AbortError" || this.abortController.signal.aborted) return;
      console.warn("Using offline tenant fixtures for SaaS Console", err);
    }

    // 2. Fetch Axiom Company Overview & Receivables
    try {
      const res = await fetch("/api/v1/admin/company-overview", {
        signal: this.abortController.signal,
      });
      if (res.ok) {
        const data = await res.json();
        if (this.abortController.signal.aborted) return;
        this.state.overview = data;
        if (data.total_prospects_pending != null) {
          this.state.kpis.pending_leads = data.total_prospects_pending;
        }
      }
    } catch (err) {
      if (err.name === "AbortError" || this.abortController.signal.aborted) return;
      console.warn("Using offline company overview fixtures", err);
    }

    // 3. Fetch Prospects CRM
    try {
      const res = await fetch("/api/v1/admin/prospects", {
        signal: this.abortController.signal,
      });
      if (res.ok) {
        const data = await res.json();
        if (this.abortController.signal.aborted) return;
        if (data.prospects) this.state.prospects = data.prospects;
      }
    } catch (err) {
      if (err.name === "AbortError" || this.abortController.signal.aborted) return;
      console.warn("Using offline prospects fixtures", err);
    }
  }

  getFilteredTenants() {
    if (this.state.activeTab === "ACTIVE") {
      return this.state.tenants.filter((t) => t.subscription_status === "ACTIVE");
    } else if (this.state.activeTab === "TRIAL") {
      return this.state.tenants.filter((t) => t.subscription_status === "TRIAL");
    } else if (this.state.activeTab === "PAST_DUE") {
      return this.state.tenants.filter((t) => t.subscription_status === "PAST_DUE");
    } else if (this.state.activeTab === "SLA_PROBATION") {
      return this.state.tenants.filter((t) => t.subscription_status === "SLA_PROBATION" || t.sla_tier === "SILVER");
    }
    return this.state.tenants;
  }

  render() {
    if (!this.container) return;
    const ov = this.state.overview || {};
    const totalOwedInr = ov.total_receivables_inr || ((ov.total_receivables_outstanding_paise || 0) / 100);
    const overdueInr = ov.overdue_receivables_inr || ((ov.overdue_receivables_amount_paise || 0) / 100);

    this.container.innerHTML = `
      <div class="saas-console-wrapper">
        <!-- 1. Executive Summary Bar (Commercial Census & Revenue Ledger) -->
        <div class="executive-kpi-strip">
          <div class="kpi-card">
            <div>
              <div class="kpi-title">Total People in System</div>
              <div class="kpi-value">${ov.total_users_in_system || 6} Users</div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-pos">${ov.total_drivers || 74} Active Drivers</span>
              <span style="color:var(--text-subtle);">system census</span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">Active vs Blocked Tenants</div>
              <div class="kpi-value" style="color:${(ov.blocked_tenants || 0) > 0 ? 'var(--danger-rose)' : 'var(--success-emerald)'};">
                ${ov.active_tenants || 0} / ${(ov.total_tenants || this.state.tenants.length)} Active
              </div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-alert" style="background:${(ov.blocked_tenants || 0) > 0 ? '#fee2e2' : '#f1f5f9'}; color:${(ov.blocked_tenants || 0) > 0 ? '#b91c1c' : '#475569'};">
                ${ov.blocked_tenants || 0} Suspended / Blocked
              </span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">Website Inquiries (CRM)</div>
              <div class="kpi-value" style="color:var(--axiom-purple);">${ov.total_prospects_pending || this.state.prospects.length} Leads</div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-pos">1-Click Onboarding Ready</span>
            </div>
          </div>

          <div class="kpi-card" style="border:1.5px solid ${(ov.overdue_receivables_amount_paise || 0) > 0 ? 'var(--danger-rose)' : 'var(--border-line)'};">
            <div>
              <div class="kpi-title">Money Owed to Axiom Mobility</div>
              <div class="kpi-value" style="color:${totalOwedInr > 0 ? 'var(--danger-rose)' : 'var(--text-primary)'};">
                ${this.inrFormatter.format(totalOwedInr)}
              </div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-alert" style="background:#fee2e2; color:#b91c1c;">
                ${this.inrFormatter.format(overdueInr)} Overdue
              </span>
              <span style="color:var(--text-subtle);">SaaS ledger</span>
            </div>
          </div>
        </div>

        <!-- 2. Commercial Control Plane Primary Navigation Tabs -->
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border-line); padding-bottom:10px;">
          <div class="tab-btn-group">
            <button class="tab-btn ${this.state.activeView === 'TENANTS' ? 'active' : ''}" data-view="TENANTS">
              🏢 Tenants & Subscriptions
            </button>
            <button class="tab-btn ${this.state.activeView === 'RECEIVABLES' ? 'active' : ''}" data-view="RECEIVABLES">
              💰 Receivables & Kill Switch (${(ov.tenants || []).length})
            </button>
            <button class="tab-btn ${this.state.activeView === 'PROSPECTS' ? 'active' : ''}" data-view="PROSPECTS">
              📋 Website Prospects & Sales CRM (${this.state.prospects.length})
            </button>
          </div>
          <div style="font-size:11px; color:var(--text-secondary); font-weight:700;">
            Axiom HQ Commercial Governance &bull; Strict IDOR Enforced
          </div>
        </div>

        <!-- 3. Dynamic View Content -->
        ${this.state.activeView === 'RECEIVABLES' ? this.renderReceivablesView() : (this.state.activeView === 'PROSPECTS' ? this.renderProspectsView() : this.renderTenantsView())}
      </div>

      <!-- Modals -->
      <div id="impersonation-modal-root"></div>
      <div id="topup-modal-root"></div>
      <div id="action-modal-root"></div>
    `;
  }

  renderTenantsView() {
    const filtered = this.getFilteredTenants();
    return `
      <div class="saas-table-toolbar">
        <div class="tab-btn-group">
          <button class="tab-btn ${this.state.activeTab === 'ALL' ? 'active' : ''}" data-tab="ALL">All Tenants (${this.state.tenants.length})</button>
          <button class="tab-btn ${this.state.activeTab === 'ACTIVE' ? 'active' : ''}" data-tab="ACTIVE">Active</button>
          <button class="tab-btn ${this.state.activeTab === 'TRIAL' ? 'active' : ''}" data-tab="TRIAL">Trial Mode</button>
          <button class="tab-btn ${this.state.activeTab === 'PAST_DUE' ? 'active' : ''}" data-tab="PAST_DUE">Past Due / Unpaid</button>
          <button class="tab-btn ${this.state.activeTab === 'SLA_PROBATION' ? 'active' : ''}" data-tab="SLA_PROBATION">SLA Probation (Silver)</button>
        </div>
      </div>
      <div class="saas-table-container">
        <table class="saas-table">
          <thead>
            <tr>
              <th>Tenant & Contact</th>
              <th>Plan & Status</th>
              <th>MRR / Cycle</th>
              <th>Corporate Quota</th>
              <th>Trip Quota (Mo)</th>
              <th>Prepaid Wallet</th>
              <th>Feature Entitlements</th>
              <th>Support Action</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.map((t) => this.renderTenantRow(t)).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderReceivablesView() {
    const ovTenants = (this.state.overview && this.state.overview.tenants) || [];
    return `
      <div class="saas-table-container">
        <table class="saas-table">
          <thead>
            <tr>
              <th>Tenant & Organization</th>
              <th>Users & Trips</th>
              <th>Total Billed (₹)</th>
              <th>Total Paid (₹)</th>
              <th>Amount Owed to Axiom (₹)</th>
              <th>Aging / Overdue</th>
              <th>Access Status</th>
              <th>Kill-Switch & Payment Actions</th>
            </tr>
          </thead>
          <tbody>
            ${ovTenants.length === 0 ? `<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--text-subtle);">No tenant billing records found.</td></tr>` : ovTenants.map((t) => {
              const isBlocked = t.account_status === "HARD_BLOCKED" || t.account_status === "SOFT_BLOCKED";
              const isOverdue = t.days_overdue > 0 && t.amount_owed_paise > 0;
              return `
                <tr>
                  <td>
                    <div style="font-weight:750; color:var(--text-primary); font-size:12px;">${t.tenant_name}</div>
                    <div style="font-size:10px; color:var(--text-subtle);">${t.tenant_id}</div>
                  </td>
                  <td>
                    <div style="font-size:11px; font-weight:700;">${t.user_count || 0} Users</div>
                    <div style="font-size:10px; color:var(--text-subtle);">${t.trip_count || 0} Total Duties</div>
                  </td>
                  <td>${this.inrFormatter.format((t.total_billed_paise || 0) / 100)}</td>
                  <td style="color:var(--success-emerald); font-weight:700;">${this.inrFormatter.format((t.total_paid_paise || 0) / 100)}</td>
                  <td>
                    <div style="font-weight:800; font-size:13px; color:${t.amount_owed_paise > 0 ? 'var(--danger-rose)' : 'var(--text-primary)'};">
                      ${this.inrFormatter.format((t.amount_owed_paise || 0) / 100)}
                    </div>
                  </td>
                  <td>
                    ${isOverdue ? `<span class="status-pill status-pastdue">${t.days_overdue} Days Overdue</span>` : `<span class="status-pill status-active">Current / Paid</span>`}
                  </td>
                  <td>
                    ${t.account_status === 'ACTIVE' ? `<span class="status-pill status-active">ACTIVE</span>` : (t.account_status === 'SOFT_BLOCKED' ? `<span class="status-pill status-probation">SOFT BLOCKED</span>` : `<span class="status-pill status-pastdue">HARD BLOCKED</span>`)}
                    ${t.block_reason ? `<div style="font-size:9.5px; color:var(--danger-rose); margin-top:2px;">${t.block_reason}</div>` : ''}
                  </td>
                  <td>
                    <div style="display:flex; gap:6px; align-items:center;">
                      ${isBlocked ? `
                        <button class="tab-btn" data-action="unblock-tenant" data-tid="${t.tenant_id}" style="padding:4px 8px; font-size:10.5px; background:var(--success-subtle); color:#065f46; border:1px solid #a7f3d0; font-weight:750;">
                          ✓ Unblock
                        </button>
                      ` : `
                        <button class="tab-btn" data-action="block-tenant" data-tid="${t.tenant_id}" style="padding:4px 8px; font-size:10.5px; background:#fee2e2; color:#b91c1c; border:1px solid #fecaca; font-weight:750;">
                          ⛔ Block (Kill Switch)
                        </button>
                      `}
                      <button class="tab-btn" data-action="record-payment" data-tid="${t.tenant_id}" data-name="${t.tenant_name}" data-owed="${t.amount_owed_paise}" style="padding:4px 8px; font-size:10.5px; background:var(--card-bg); border:1px solid var(--border-line); font-weight:750;">
                        💳 Record Payment
                      </button>
                    </div>
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderProspectsView() {
    return `
      <div class="saas-table-container">
        <table class="saas-table">
          <thead>
            <tr>
              <th>Contact & Company</th>
              <th>Contact Channels</th>
              <th>Status Badge</th>
              <th>Inquiry Note & Call Log History</th>
              <th>Sales Actions</th>
            </tr>
          </thead>
          <tbody>
            ${this.state.prospects.length === 0 ? `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-subtle);">No website prospects captured yet.</td></tr>` : this.state.prospects.map((p) => {
              const notes = Array.isArray(p.sales_notes) ? p.sales_notes : [];
              const latestNote = notes.length > 0 ? notes[notes.length - 1] : null;
              const isOnboarded = p.status === "ONBOARDED" || !!p.converted_tenant_id;
              return `
                <tr>
                  <td>
                    <div style="font-weight:750; color:var(--text-primary); font-size:12px;">${p.contact_name || "Anonymous Prospect"}</div>
                    <div style="font-size:10px; color:var(--text-secondary); font-weight:600;">${p.company_name || "Direct Inquiry"}</div>
                    <div style="font-size:9.5px; color:var(--text-subtle); margin-top:2px;">Captured: ${p.created_at ? new Date(p.created_at).toLocaleDateString() : 'Recent'} &bull; Source: ${p.source || 'WEBSITE'}</div>
                  </td>
                  <td>
                    <div style="font-size:11px; font-weight:600;">📧 ${p.email || `<span style="color:var(--text-subtle);">(None)</span>`}</div>
                    <div style="font-size:11px; font-weight:600; margin-top:2px;">📱 ${p.mobile_number || `<span style="color:var(--text-subtle);">(None)</span>`}</div>
                  </td>
                  <td>
                    ${p.status === 'NEW' ? `<span class="status-pill status-trial">NEW LEAD</span>` : (p.status === 'QUALIFIED' ? `<span class="status-pill status-active">QUALIFIED</span>` : (p.status === 'ONBOARDED' ? `<span class="status-pill tier-enterprise">ONBOARDED</span>` : `<span class="status-pill status-probation">${p.status}</span>`))}
                  </td>
                  <td style="max-width:320px;">
                    ${p.message ? `<div style="font-size:11px; color:var(--text-secondary); margin-bottom:4px; font-style:italic;">"${p.message}"</div>` : ''}
                    ${latestNote ? `
                      <div style="font-size:10px; background:var(--surface-soft); padding:4px 8px; border-radius:6px; border:1px solid var(--border-line);">
                        <strong>📞 Latest Note:</strong> ${latestNote.note}
                        <div style="font-size:9px; color:var(--text-subtle); margin-top:1px;">by ${latestNote.author} &bull; ${new Date(latestNote.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                      </div>
                    ` : `<span style="font-size:10px; color:var(--text-subtle);">No call logs recorded.</span>`}
                  </td>
                  <td>
                    <div style="display:flex; gap:6px; align-items:center;">
                      <button class="tab-btn" data-action="log-call-note" data-pid="${p.id}" data-name="${p.contact_name}" style="padding:4px 8px; font-size:10.5px; background:var(--card-bg); border:1px solid var(--border-line); font-weight:750;">
                        📝 Log Call Note
                      </button>
                      ${isOnboarded ? `
                        <span style="font-size:10px; font-weight:750; color:var(--axiom-purple); padding:4px 8px; background:var(--blue-soft); border-radius:6px;">
                          ✓ Converted: ${p.converted_tenant_id}
                        </span>
                      ` : `
                        <button class="tab-btn" data-action="onboard-prospect" data-pid="${p.id}" style="padding:4px 8px; font-size:10.5px; background:var(--axiom-purple); color:#fff; border:none; font-weight:750;">
                          🚀 1-Click Onboard
                        </button>
                      `}
                    </div>
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderTenantRow(t) {
    const isPastDue = t.subscription_status === "PAST_DUE";
    const isProbation = t.subscription_status === "SLA_PROBATION" || t.sla_tier === "SILVER";
    const isTrial = t.subscription_status === "TRIAL";

    let statusBadge = `<span class="status-pill status-active">ACTIVE</span>`;
    if (isPastDue) statusBadge = `<span class="status-pill status-pastdue">PAST DUE</span>`;
    if (isProbation) statusBadge = `<span class="status-pill status-probation">SLA PROBATION</span>`;
    if (isTrial) statusBadge = `<span class="status-pill status-trial">TRIAL</span>`;

    let tierBadge = `<span class="status-pill tier-growth">${t.plan_tier}</span>`;
    if (t.plan_tier === "ENTERPRISE") tierBadge = `<span class="status-pill tier-enterprise">ENTERPRISE</span>`;
    if (t.plan_tier === "SOLO") tierBadge = `<span class="status-pill tier-solo">SOLO</span>`;

    const corpUsed = (t.corporate_quota && t.corporate_quota.used) || 0;
    const corpTotal = (t.corporate_quota && t.corporate_quota.total) || 1;
    const tripUsed = (t.trip_quota && t.trip_quota.used) || 0;
    const tripTotal = (t.trip_quota && t.trip_quota.total) || 1;

    const corpPct = Math.round((corpUsed / corpTotal) * 100);
    const tripPct = Math.round((tripUsed / tripTotal) * 100);

    return `
      <tr>
        <td>
          <div class="tenant-name">${t.tenant_name}</div>
          <div class="tenant-meta">ID: #${t.tenant_id} &bull; ${t.phone}</div>
          <div class="tenant-meta">${t.email}</div>
        </td>
        <td>
          <div style="display:flex; gap:6px; margin-bottom:4px;">
            ${tierBadge}
            ${statusBadge}
          </div>
          <div style="font-size:10px; color:var(--text-subtle);">Renews: ${t.current_period_end || 'End of Month'}</div>
        </td>
        <td>
          <div class="mrr-val">${this.inrFormatter.format((t.mrr_paise || 0) / 100)}</div>
          <div style="font-size:10px; color:var(--text-subtle);">${t.plan_tier === 'ENTERPRISE' ? 'Annual Plan' : 'Monthly Bill'}</div>
        </td>
        <td>
          <div class="quota-text">${corpUsed} / ${corpTotal} Linked</div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill" style="width:${Math.min(corpPct, 100)}%; background:${corpPct >= 100 ? 'var(--danger-rose)' : 'var(--axiom-purple)'};"></div>
          </div>
        </td>
        <td>
          <div class="quota-text">${tripUsed} / ${tripTotal} Trips</div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill" style="width:${Math.min(tripPct, 100)}%; background:${tripPct >= 90 ? 'var(--warning-amber)' : 'var(--success-emerald)'};"></div>
          </div>
        </td>
        <td>
          <div class="quota-text" style="font-weight:700;">${this.decimalFormatter.format((t.wallet_balance_paise || 0) / 100)}</div>
          <button class="topup-btn btn-topup-trigger" data-tid="${t.tenant_id}" style="margin-top:4px;">+ Instant Top-Up</button>
        </td>
        <td>
          <div class="feature-chips-wrap">
            <span class="feature-toggle-chip ${t.features && t.features.network ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="network">Network</span>
            <span class="feature-toggle-chip ${t.features && t.features.market ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="market">Market</span>
            <span class="feature-toggle-chip ${t.features && t.features.whatsapp_bot ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="whatsapp_bot">WA Bot</span>
          </div>
        </td>
        <td>
          <button class="btn-login-as" data-tid="${t.tenant_id}" data-name="${t.tenant_name}">
            🛡️ Shadow Login
          </button>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    if (!this.container) return;
    const signal = this.abortController.signal;

    this.container.addEventListener("click", async (e) => {
      const target = e.target;
      if (!target) return;

      // View Switcher (TENANTS | RECEIVABLES | PROSPECTS)
      const viewBtn = target.closest("[data-view]");
      if (viewBtn) {
        this.state.activeView = viewBtn.dataset.view;
        this.render();
        return;
      }

      // Filter Tabs inside Tenants View
      const tabBtn = target.closest(".tab-btn[data-tab]");
      if (tabBtn) {
        this.state.activeTab = tabBtn.dataset.tab;
        this.render();
        return;
      }

      // Feature Flag Toggle Chips
      const chip = target.closest(".feature-toggle-chip");
      if (chip) {
        const tid = parseInt(chip.dataset.tid, 10);
        const flag = chip.dataset.flag;
        const tenant = this.state.tenants.find((x) => x.tenant_id === tid);
        if (!tenant) return;

        const newState = !tenant.features[flag];
        tenant.features[flag] = newState;
        chip.classList.toggle("enabled", newState);

        try {
          await fetch(`/api/v1/admin/saas/tenants/${tid}/flags`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ flag_key: flag, enabled: newState }),
            signal,
          });
        } catch (err) {
          console.warn("Flag update sync error", err);
        }
        return;
      }

      // Login As Vendor Button
      const loginBtn = target.closest(".btn-login-as");
      if (loginBtn) {
        const tid = loginBtn.dataset.tid;
        const tname = loginBtn.dataset.name;
        this.openImpersonationModal(tid, tname);
        return;
      }

      // Top up button
      const topupBtn = target.closest(".btn-topup-trigger");
      if (topupBtn) {
        const tid = topupBtn.dataset.tid;
        this.openTopUpModal(tid);
        return;
      }

      // Commercial: Log Call Note Button
      const noteBtn = target.closest("[data-action='log-call-note']");
      if (noteBtn) {
        const pid = noteBtn.dataset.pid;
        const pname = noteBtn.dataset.name;
        this.openCallNoteModal(pid, pname);
        return;
      }

      // Commercial: 1-Click Onboard Button
      const onboardBtn = target.closest("[data-action='onboard-prospect']");
      if (onboardBtn) {
        const pid = onboardBtn.dataset.pid;
        await this.onboardProspect(pid);
        return;
      }

      // Commercial: Block Tenant (Kill Switch)
      const blockBtn = target.closest("[data-action='block-tenant']");
      if (blockBtn) {
        const tid = blockBtn.dataset.tid;
        this.openBlockModal(tid);
        return;
      }

      // Commercial: Unblock Tenant
      const unblockBtn = target.closest("[data-action='unblock-tenant']");
      if (unblockBtn) {
        const tid = unblockBtn.dataset.tid;
        await this.setTenantBlockStatus(tid, "ACTIVE", "Unblocked by Super-Admin");
        return;
      }

      // Commercial: Record Payment
      const payBtn = target.closest("[data-action='record-payment']");
      if (payBtn) {
        const tid = payBtn.dataset.tid;
        const tname = payBtn.dataset.name;
        const owed = parseInt(payBtn.dataset.owed, 10) || 0;
        this.openPaymentModal(tid, tname, owed);
        return;
      }
    }, { signal });
  }

  async onboardProspect(prospectId) {
    if (this.inFlightRequests.has(`onboard_${prospectId}`)) return;
    this.inFlightRequests.add(`onboard_${prospectId}`);

    try {
      const res = await fetch(`/api/v1/admin/prospects/${prospectId}/onboard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Success! Onboarded tenant '${data.tenant_name}' (#${data.tenant_id}).\n\nLogin Email: ${data.credentials.email}\nTemporary Password: ${data.credentials.temp_password}`);
        await this.fetchData();
        this.render();
      } else {
        alert(`Onboarding failed: ${data.message || data.error || 'Server error'}`);
      }
    } catch (err) {
      console.warn("Onboard error:", err);
      alert("Network error while onboarding prospect.");
    } finally {
      this.inFlightRequests.delete(`onboard_${prospectId}`);
    }
  }

  async setTenantBlockStatus(tenantId, mode, reason) {
    try {
      const res = await fetch(`/api/v1/admin/tenants/${tenantId}/block`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, reason }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        await this.fetchData();
        this.render();
      } else {
        alert(`Block update failed: ${data.message || data.error}`);
      }
    } catch (err) {
      console.warn("Block status update failed:", err);
    }
  }

  openCallNoteModal(prospectId, prospectName) {
    const modalRoot = document.getElementById("action-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="audit-modal-backdrop">
        <div class="audit-modal-box" style="max-width:440px;">
          <div class="audit-modal-header">
            <div>
              <div class="audit-modal-title">📞 Log Sales Call Note</div>
              <div class="audit-modal-subtitle">Prospect: <strong>${prospectName}</strong></div>
            </div>
            <button class="drawer-close-btn" id="btn-close-action">&times;</button>
          </div>
          <div class="audit-modal-body">
            <div class="form-group">
              <label class="form-label">Update Pipeline Status:</label>
              <select id="action-prospect-status" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;">
                <option value="CONTACTED">CONTACTED - Call Completed</option>
                <option value="QUALIFIED" selected>QUALIFIED - Demo Scheduled</option>
                <option value="LOST">LOST - Not Interested</option>
              </select>
            </div>
            <div class="form-group" style="margin-top:10px;">
              <label class="form-label">Sales Note Details:</label>
              <textarea id="action-call-note" placeholder="Enter notes from discovery call, fleet requirements, pricing discussed..." style="width:100%; height:80px; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;"></textarea>
            </div>
          </div>
          <div class="audit-modal-footer">
            <button class="btn-cancel" id="btn-cancel-action">Cancel</button>
            <button class="btn-confirm-imp" id="btn-save-note">Save Sales Note</button>
          </div>
        </div>
      </div>
    `;

    const closeModal = () => (modalRoot.innerHTML = "");
    document.getElementById("btn-close-action")?.addEventListener("click", closeModal);
    document.getElementById("btn-cancel-action")?.addEventListener("click", closeModal);

    document.getElementById("btn-save-note")?.addEventListener("click", async () => {
      const status = document.getElementById("action-prospect-status")?.value;
      const note = document.getElementById("action-call-note")?.value;
      if (!note) {
        alert("Please enter a call note.");
        return;
      }

      try {
        await fetch(`/api/v1/admin/prospects/${prospectId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, note }),
          signal: this.abortController.signal,
        });
        closeModal();
        await this.fetchData();
        this.render();
      } catch (err) {
        console.warn("Failed to save note:", err);
        closeModal();
      }
    });
  }

  openBlockModal(tenantId) {
    const modalRoot = document.getElementById("action-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="audit-modal-backdrop">
        <div class="audit-modal-box" style="max-width:440px;">
          <div class="audit-modal-header">
            <div>
              <div class="audit-modal-title">⛔ Tenant Access Suspension (Kill Switch)</div>
              <div class="audit-modal-subtitle">Target Tenant: <strong>${tenantId}</strong></div>
            </div>
            <button class="drawer-close-btn" id="btn-close-action">&times;</button>
          </div>
          <div class="audit-modal-body">
            <div class="audit-security-warning" style="margin-bottom:12px;">
              <strong>SUSPENSION POLICY NOTICE:</strong> Blocked tenants are prevented from creating new bookings and dispatches.
            </div>
            <div class="form-group">
              <label class="form-label">Select Suspension Enforcement Mode:</label>
              <select id="action-block-mode" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;">
                <option value="SOFT_BLOCKED" selected>SOFT BLOCKED - Disallow new trips; allow in-flight trips to close</option>
                <option value="HARD_BLOCKED">HARD BLOCKED - Full lock out (HTTP 402 on all endpoints)</option>
              </select>
            </div>
            <div class="form-group" style="margin-top:10px;">
              <label class="form-label">Mandatory Suspension Reason:</label>
              <input type="text" id="action-block-reason" value="Overdue platform receivables balance" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;" />
            </div>
          </div>
          <div class="audit-modal-footer">
            <button class="btn-cancel" id="btn-cancel-action">Cancel</button>
            <button class="btn-confirm-imp" id="btn-confirm-block" style="background:var(--danger-rose);">Confirm & Suspend Tenant</button>
          </div>
        </div>
      </div>
    `;

    const closeModal = () => (modalRoot.innerHTML = "");
    document.getElementById("btn-close-action")?.addEventListener("click", closeModal);
    document.getElementById("btn-cancel-action")?.addEventListener("click", closeModal);

    document.getElementById("btn-confirm-block")?.addEventListener("click", async () => {
      const mode = document.getElementById("action-block-mode")?.value;
      const reason = document.getElementById("action-block-reason")?.value;
      await this.setTenantBlockStatus(tenantId, mode, reason);
      closeModal();
    });
  }

  openPaymentModal(tenantId, tenantName, amountOwedPaise) {
    const modalRoot = document.getElementById("action-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="audit-modal-backdrop">
        <div class="audit-modal-box" style="max-width:440px;">
          <div class="audit-modal-header">
            <div>
              <div class="audit-modal-title">💳 Record Tenant Payment</div>
              <div class="audit-modal-subtitle">${tenantName} &bull; Outstanding: ${this.inrFormatter.format(amountOwedPaise / 100)}</div>
            </div>
            <button class="drawer-close-btn" id="btn-close-action">&times;</button>
          </div>
          <div class="audit-modal-body">
            <div class="form-group">
              <label class="form-label">Settlement Amount (₹):</label>
              <input type="number" id="action-payment-inr" value="${amountOwedPaise > 0 ? (amountOwedPaise / 100) : 10000}" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:13px; font-weight:700;" />
            </div>
            <div class="form-group" style="margin-top:10px;">
              <label class="form-label">Payment Channel / Reference ID:</label>
              <input type="text" id="action-payment-ref" value="NEFT-UTR-${Date.now().toString().slice(-6)}" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;" />
            </div>
            <div style="font-size:11px; color:var(--text-secondary); margin-top:8px;">
              <em>Note: Settling full overdue balance will automatically unblock this tenant.</em>
            </div>
          </div>
          <div class="audit-modal-footer">
            <button class="btn-cancel" id="btn-cancel-action">Cancel</button>
            <button class="btn-confirm-imp" id="btn-confirm-payment">Record Payment & Update Ledger</button>
          </div>
        </div>
      </div>
    `;

    const closeModal = () => (modalRoot.innerHTML = "");
    document.getElementById("btn-close-action")?.addEventListener("click", closeModal);
    document.getElementById("btn-cancel-action")?.addEventListener("click", closeModal);

    document.getElementById("btn-confirm-payment")?.addEventListener("click", async () => {
      const inrVal = parseFloat(document.getElementById("action-payment-inr")?.value || 0);
      const ref = document.getElementById("action-payment-ref")?.value || "BANK_TRANSFER";
      const paise = Math.round(inrVal * 100);

      try {
        const res = await fetch(`/api/v1/admin/tenants/${tenantId}/payment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ amount_paise: paise, reference_id: ref }),
          signal: this.abortController.signal,
        });
        const data = await res.json();
        closeModal();
        if (data.ok) {
          alert(`Payment recorded! New balance: ${this.inrFormatter.format(data.new_amount_owed_paise / 100)}. Status: ${data.account_status}`);
          await this.fetchData();
          this.render();
        } else {
          alert(`Payment error: ${data.message || data.error}`);
        }
      } catch (err) {
        console.warn("Payment recording failed:", err);
        closeModal();
      }
    });
  }

  openImpersonationModal(tenantId, tenantName) {
    const modalRoot = document.getElementById("impersonation-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="audit-modal-backdrop" id="audit-modal-backdrop">
        <div class="audit-modal-box">
          <div class="audit-modal-header">
            <div>
              <div class="audit-modal-title">🛡️ Initiate Support Shadow Session</div>
              <div class="audit-modal-subtitle">Target: <strong>${tenantName} (#${tenantId})</strong></div>
            </div>
            <button class="drawer-close-btn" id="btn-close-modal">&times;</button>
          </div>
          <div class="audit-modal-body">
            <div class="audit-security-warning">
              <strong>CRITICAL AUDIT NOTICE:</strong>
              You are accessing tenant data under Axiom HQ Governance. All page views, searches, and mutations are immutably signed and timestamped in <code>admin_impersonation_audit_logs</code>.
            </div>
            <div class="form-group">
              <label class="form-label">Select Session Mode:</label>
              <div class="mode-radio-card selected">
                <input type="radio" name="imp_mode" id="mode_ro" value="READ_ONLY" checked />
                <label for="mode_ro" style="cursor:pointer; margin-bottom:0;">
                  <strong>🔒 Read-Only Shadow (Recommended)</strong>
                  <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">
                    Safe browsing. All POST/PATCH/DELETE mutations are strictly blocked at API layer.
                  </div>
                </label>
              </div>
              <div class="mode-radio-card" style="margin-top:8px;">
                <input type="radio" name="imp_mode" id="mode_rw" value="READ_WRITE" />
                <label for="mode_rw" style="cursor:pointer; margin-bottom:0;">
                  <strong>✍️ Read-Write Mode (Emergency Action Required)</strong>
                  <div style="font-size:11px; color:var(--text-secondary); margin-top:2px;">
                    Permits live updates, dispatch reassignment, or manual invoice sync on tenant's behalf.
                  </div>
                </label>
              </div>
            </div>
            <div class="form-group" id="reason-code-wrap" style="display:none;">
              <label class="form-label">Mandatory Support Reason Code:</label>
              <select id="imp-reason-code" style="width:100%; padding:8px; background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); border-radius:6px; font-size:12px;">
                <option value="TICKET_DISPATCH_FAILURE">Ticket #9912 - Unallotted Duty Dispatch Emergency</option>
                <option value="CORP_BILLING_INVOICE_SYNC">Ticket #8841 - Corporate Proforma Audit Reconcile</option>
                <option value="SLA_DEMOTION_DISPUTE">Ticket #7712 - Force Majeure Review</option>
                <option value="ONBOARDING_ASSISTANCE">New Tenant Corporate Roster Walkthrough</option>
              </select>
            </div>
          </div>
          <div class="audit-modal-footer">
            <button class="btn-cancel" id="btn-cancel-imp">Cancel</button>
            <button class="btn-confirm-imp" id="btn-start-shadow-session">
              Authenticate & Launch Shadow Session &rarr;
            </button>
          </div>
        </div>
      </div>
    `;

    const radioModes = modalRoot.querySelectorAll('input[name="imp_mode"]');
    const reasonWrap = document.getElementById("reason-code-wrap");
    radioModes.forEach((r) => {
      r.addEventListener("change", () => {
        reasonWrap.style.display = r.value === "READ_WRITE" ? "block" : "none";
      });
    });

    const closeModal = () => (modalRoot.innerHTML = "");
    document.getElementById("btn-close-modal")?.addEventListener("click", closeModal);
    document.getElementById("btn-cancel-imp")?.addEventListener("click", closeModal);

    document.getElementById("btn-start-shadow-session")?.addEventListener("click", async () => {
      if (this.inFlightRequests.has("impersonate")) return;
      this.inFlightRequests.add("impersonate");

      const mode = modalRoot.querySelector('input[name="imp_mode"]:checked')?.value || "READ_ONLY";
      const reason = document.getElementById("imp-reason-code")?.value || "Standard Support Investigation";

      try {
        const res = await fetch("/api/v1/admin/impersonate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenant_id: tenantId,
            impersonation_mode: mode,
            reason_code: reason,
          }),
          signal: this.abortController.signal,
        });

        const data = await res.json();
        closeModal();

        if (data.ok) {
          sessionStorage.setItem("axiom_parent_admin_token", "admin_session_token_persist");
          sessionStorage.setItem("axiom_shadow_token", data.shadow_token);
          sessionStorage.setItem("axiom_shadow_expires_at", data.expires_at);

          this.onImpersonate({
            tenant_id: tenantId,
            tenant_name: tenantName,
            session_id: data.session_id,
            impersonation_mode: mode,
            shadow_token: data.shadow_token,
          });
        }
      } catch (err) {
        console.error("Impersonation handoff failed", err);
        closeModal();
        this.onImpersonate({
          tenant_id: tenantId,
          tenant_name: tenantName,
          session_id: `imp_local_fallback_${tenantId}`,
          impersonation_mode: mode,
        });
      } finally {
        this.inFlightRequests.delete("impersonate");
      }
    });
  }

  openTopUpModal(tenantId) {
    const modalRoot = document.getElementById("topup-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="audit-modal-backdrop">
        <div class="audit-modal-box" style="max-width:380px;">
          <div class="audit-modal-header">
            <div>
              <div class="audit-modal-title">Prepaid Wallet Top-Up</div>
              <div class="audit-modal-subtitle">Tenant #${tenantId}</div>
            </div>
            <button class="drawer-close-btn" id="btn-close-topup">&times;</button>
          </div>
          <div class="audit-modal-body">
            <div style="font-size:12px; color:var(--text-secondary); margin-bottom:12px;">
              Select instant top-up amount for gateway / API billing:
            </div>
            <div style="display:flex; gap:8px;">
              <button class="topup-btn btn-amount-preset" data-amount="100000" style="padding:10px; flex:1;">+₹1,000</button>
              <button class="topup-btn btn-amount-preset" data-amount="500000" style="padding:10px; flex:1;">+₹5,000</button>
              <button class="topup-btn btn-amount-preset" data-amount="2000000" style="padding:10px; flex:1;">+₹20,000</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("btn-close-topup")?.addEventListener("click", () => {
      modalRoot.innerHTML = "";
    });

    modalRoot.querySelectorAll(".btn-amount-preset").forEach((b) => {
      b.addEventListener("click", async (e) => {
        if (this.inFlightRequests.has("topup")) return;
        this.inFlightRequests.add("topup");

        const amt = parseInt(e.currentTarget.dataset.amount, 10);
        try {
          await fetch(`/api/v1/admin/saas/tenants/${tenantId}/topup`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ amount_paise: amt }),
            signal: this.abortController.signal,
          });
          modalRoot.innerHTML = "";
          await this.fetchData();
          this.render();
        } catch (err) {
          console.warn("Topup error:", err);
          modalRoot.innerHTML = "";
        } finally {
          this.inFlightRequests.delete("topup");
        }
      });
    });
  }
}
