/**
 * Axiom Mobility (Fleetline) 10/10 Super-Admin SaaS Console Component.
 * Zero-Build Vanilla ES6+ State & Sticky Table Module.
 */

export class AdminSaasConsole {
  constructor(options = {}) {
    this.container = options.container || document.getElementById("admin-saas-view");
    this.onImpersonate = options.onImpersonate || (() => {});
    this.state = {
      activeTab: "ALL",
      tenants: [],
      kpis: {
        active_corporates: 71,
        corporates_monthly_delta: "+4 this mo",
        active_vendor_subscriptions: 34,
        churn_risk_count: 2,
        mrr_paise: 30999700,
        gtv_platform_paise: 1830408100,
        sla_demotions_today: 2,
        pending_leads: 0,
      },
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

  async init() {
    await this.fetchData();
    this.render();
    this.bindEvents();
  }

  async fetchData() {
    try {
      const res = await fetch("/api/v1/admin/saas/tenants");
      if (res.ok) {
        const data = await res.json();
        if (data.tenants) this.state.tenants = data.tenants;
        if (data.kpi_strip) this.state.kpis = data.kpi_strip;
      }
    } catch (err) {
      console.warn("Using offline tenant fixtures for SaaS Console", err);
      this.state.tenants = [
        {
          tenant_id: 169,
          tenant_name: "Zion Travels",
          phone: "+91 98450 11223",
          email: "ops@ziontravels.in",
          plan_tier: "GROWTH",
          subscription_status: "ACTIVE",
          mrr_paise: 500000,
          current_period_end: "2026-04-23",
          corporate_quota: { total: 5, used: 1 },
          trip_quota: { total: 100, used: 14 },
          wallet_balance_paise: 500, // ₹5.00
          sla_tier: "PLATINUM",
          ota_pct: 98.4,
          breaches_count: 0,
          features: { network: true, market: true, parse_ai: true, whatsapp_bot: false },
        },
        {
          tenant_id: 170,
          tenant_name: "Apex Cabs & Logistics",
          phone: "+91 97110 88231",
          email: "dispatch@apexcabs.in",
          plan_tier: "ENTERPRISE",
          subscription_status: "ACTIVE",
          mrr_paise: 2500000,
          current_period_end: "2026-12-31",
          corporate_quota: { total: 25, used: 18 },
          trip_quota: { total: 1500, used: 1120 },
          wallet_balance_paise: 425000, // ₹4,250.00
          sla_tier: "PLATINUM",
          ota_pct: 99.1,
          breaches_count: 0,
          features: { network: true, market: true, parse_ai: true, whatsapp_bot: true },
        },
        {
          tenant_id: 171,
          tenant_name: "BlueStar Mobility",
          phone: "+91 99881 22334",
          email: "fleet@bluestar.in",
          plan_tier: "GROWTH",
          subscription_status: "SLA_PROBATION",
          mrr_paise: 500000,
          current_period_end: "2026-05-15",
          corporate_quota: { total: 5, used: 2 },
          trip_quota: { total: 100, used: 42 },
          wallet_balance_paise: 120000, // ₹1,200.00
          sla_tier: "SILVER",
          ota_pct: 86.2,
          breaches_count: 3,
          features: { network: false, market: true, parse_ai: true, whatsapp_bot: false },
        },
        {
          tenant_id: 172,
          tenant_name: "Garuda City Fleets",
          phone: "+91 94432 55667",
          email: "admin@garudafleets.in",
          plan_tier: "SOLO",
          subscription_status: "TRIAL",
          mrr_paise: 0,
          current_period_end: "2026-05-02",
          corporate_quota: { total: 1, used: 1 },
          trip_quota: { total: 20, used: 19 },
          wallet_balance_paise: 0,
          sla_tier: "GOLD",
          ota_pct: 94.1,
          breaches_count: 1,
          features: { network: false, market: false, parse_ai: true, whatsapp_bot: false },
        },
        {
          tenant_id: 173,
          tenant_name: "Royal Executive Rentals",
          phone: "+91 96654 33221",
          email: "accounts@royalrentals.in",
          plan_tier: "GROWTH",
          subscription_status: "PAST_DUE",
          mrr_paise: 500000,
          current_period_end: "2026-04-18",
          corporate_quota: { total: 5, used: 3 },
          trip_quota: { total: 100, used: 88 },
          wallet_balance_paise: 25000,
          sla_tier: "GOLD",
          ota_pct: 93.5,
          breaches_count: 1,
          features: { network: true, market: true, parse_ai: false, whatsapp_bot: false },
        },
      ];
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
    const kpis = this.state.kpis;
    const filtered = this.getFilteredTenants();

    this.container.innerHTML = `
      <div class="saas-console-wrapper">
        <!-- 1. Top Executive KPI Strip (5 Cards in 1 Row) -->
        <div class="executive-kpi-strip">
          <div class="kpi-card">
            <div>
              <div class="kpi-title">Active Corporates</div>
              <div class="kpi-value">${kpis.active_corporates}</div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-pos">${kpis.corporates_monthly_delta}</span>
              <span style="color:var(--text-subtle);">across all vendors</span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">Active Subscriptions</div>
              <div class="kpi-value">${kpis.active_vendor_subscriptions}</div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-alert">${kpis.churn_risk_count} churn risk</span>
              <span style="color:var(--text-subtle);">past due</span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">Monthly MRR</div>
              <div class="kpi-value">${this.inrFormatter.format(kpis.mrr_paise / 100)}</div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-pos">+12.4% ARR</span>
              <span style="color:var(--text-subtle);">healthy</span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">Gross Platform GTV</div>
              <div class="kpi-value">${this.inrFormatter.format(kpis.gtv_platform_paise / 100)}</div>
            </div>
            <div class="kpi-meta-strip">
              <span style="color:var(--text-secondary);">Dual-Ledger Volume</span>
            </div>
          </div>

          <div class="kpi-card">
            <div>
              <div class="kpi-title">SLA & Webhook Health</div>
              <div class="kpi-value" style="color:${kpis.sla_demotions_today > 0 ? 'var(--danger-rose)' : 'var(--text-primary)'}">
                ${kpis.sla_demotions_today} Demoted
              </div>
            </div>
            <div class="kpi-meta-strip">
              <span class="delta-badge-pos">Gateways 100%</span>
              <span style="color:var(--text-subtle);">0 Leads</span>
            </div>
          </div>
        </div>

        <!-- 2. Multi-Tenant Vendor Management Table Panel -->
        <div class="table-panel">
          <div class="table-filter-bar">
            <div class="tab-group">
              <button class="tab-btn ${this.state.activeTab === 'ALL' ? 'active' : ''}" data-tab="ALL">All (34)</button>
              <button class="tab-btn ${this.state.activeTab === 'ACTIVE' ? 'active' : ''}" data-tab="ACTIVE">Active (22)</button>
              <button class="tab-btn ${this.state.activeTab === 'TRIAL' ? 'active' : ''}" data-tab="TRIAL">Trial (6)</button>
              <button class="tab-btn ${this.state.activeTab === 'PAST_DUE' ? 'active' : ''}" data-tab="PAST_DUE">Past Due (4)</button>
              <button class="tab-btn ${this.state.activeTab === 'SLA_PROBATION' ? 'active' : ''}" data-tab="SLA_PROBATION">SLA Probation / Demoted (2)</button>
            </div>
            <div style="font-size:12px; color:var(--text-muted); font-weight:500;">
              Showing ${filtered.length} of ${this.state.tenants.length} Fleet Vendors
            </div>
          </div>

          <div class="sticky-table-wrapper">
            <table class="enterprise-table">
              <thead>
                <tr>
                  <th class="col-sticky-left" style="width:240px;">Vendor ID & Name</th>
                  <th>Plan & Billing</th>
                  <th>Axiom SLA Tier</th>
                  <th>Usage Quotas</th>
                  <th>Pre-Paid Wallet</th>
                  <th>Period End</th>
                  <th>Feature Entitlements</th>
                  <th class="col-sticky-right" style="width:140px;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${filtered.map((t) => this.renderTableRow(t)).join("")}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Impersonation Confirmation Modal -->
      <div id="impersonation-modal-root"></div>

      <!-- Top Up Modal -->
      <div id="topup-modal-root"></div>
    `;
  }

  renderTableRow(t) {
    const corpPct = Math.min(100, Math.round((t.corporate_quota.used / t.corporate_quota.total) * 100));
    const tripPct = Math.min(100, Math.round((t.trip_quota.used / t.trip_quota.total) * 100));
    const walletFmt = this.decimalFormatter.format(t.wallet_balance_paise / 100);

    let slaClass = "sla-platinum";
    let slaIcon = "🏆";
    if (t.sla_tier === "GOLD") {
      slaClass = "sla-gold";
      slaIcon = "🥇";
    } else if (t.sla_tier === "SILVER") {
      slaClass = "sla-silver";
      slaIcon = "⚠️";
    }

    return `
      <tr data-tenant-id="${t.tenant_id}">
        <td class="col-sticky-left">
          <div style="font-weight:700; color:var(--text-primary); font-size:14px;">#${t.tenant_id} ${t.tenant_name}</div>
          <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">${t.phone} &bull; ${t.email}</div>
        </td>

        <td>
          <div style="font-weight:600; color:var(--text-secondary);">${t.plan_tier} &bull; ${t.mrr_paise > 0 ? this.inrFormatter.format(t.mrr_paise / 100) + '/mo' : 'Free Trial'}</div>
          <span style="display:inline-block; margin-top:4px; font-size:11px; padding:2px 6px; border-radius:4px; background:${t.subscription_status === 'ACTIVE' ? 'var(--success-subtle)' : t.subscription_status === 'TRIAL' ? 'var(--info-subtle)' : 'var(--danger-subtle)'}; color:${t.subscription_status === 'ACTIVE' ? '#065F46' : t.subscription_status === 'TRIAL' ? '#0369A1' : '#991B1B'}; font-weight:700;">
            ${t.subscription_status}
          </span>
        </td>

        <td>
          <div class="sla-badge ${slaClass}" title="Click to view SLA breach logs">
            ${slaIcon} ${t.sla_tier} (${t.ota_pct}% OTA)
          </div>
          ${t.breaches_count > 0 ? `<div style="font-size:11px; color:var(--danger-rose); font-weight:600; margin-top:3px;">${t.breaches_count} Breaches in 14d</div>` : ''}
        </td>

        <td style="min-width:160px;">
          <div style="font-size:11px; font-weight:600; display:flex; justify-content:space-between; margin-bottom:2px;">
            <span>Corps: ${t.corporate_quota.used}/${t.corporate_quota.total}</span>
            <span>Trips: ${t.trip_quota.used}/${t.trip_quota.total}</span>
          </div>
          <div class="progress-track" style="margin-bottom:4px;">
            <div class="progress-fill ${tripPct > 80 ? 'warn' : ''}" style="width:${tripPct}%;"></div>
          </div>
        </td>

        <td>
          <div style="font-weight:700; font-family:ui-monospace, monospace; color:${t.wallet_balance_paise < 1000 ? 'var(--danger-rose)' : 'var(--text-primary)'};">
            ${walletFmt}
          </div>
          <button class="callout-btn btn-topup-trigger" data-tid="${t.tenant_id}" style="margin-top:4px; font-size:10px;">+ Top Up</button>
        </td>

        <td style="color:var(--text-secondary); font-size:12px;">
          ${t.current_period_end}
        </td>

        <td>
          <div class="feature-pill-strip">
            <span class="feature-toggle-chip ${t.features.network ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="network">Network</span>
            <span class="feature-toggle-chip ${t.features.market ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="market">Market</span>
            <span class="feature-toggle-chip ${t.features.parse_ai ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="parse_ai">Parse AI</span>
            <span class="feature-toggle-chip ${t.features.whatsapp_bot ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="whatsapp_bot">WA Bot</span>
          </div>
        </td>

        <td class="col-sticky-right">
          <button class="btn-login-as" data-tid="${t.tenant_id}" data-name="${t.tenant_name}">[Login as]</button>
          <button class="callout-btn" style="border:none; padding:4px 6px; font-size:14px; color:var(--text-muted);">&bull;&bull;&bull;</button>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    if (!this.container) return;

    // Filter Tab Buttons
    this.container.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        this.state.activeTab = e.currentTarget.dataset.tab;
        this.render();
        this.bindEvents();
      });
    });

    // Feature Flag Toggle Chips
    this.container.querySelectorAll(".feature-toggle-chip").forEach((chip) => {
      chip.addEventListener("click", async (e) => {
        const tid = parseInt(e.currentTarget.dataset.tid, 10);
        const flag = e.currentTarget.dataset.flag;
        const tenant = this.state.tenants.find((x) => x.tenant_id === tid);
        if (!tenant) return;

        const newState = !tenant.features[flag];
        tenant.features[flag] = newState;
        e.currentTarget.classList.toggle("enabled", newState);

        try {
          await fetch(`/api/v1/admin/saas/tenants/${tid}/flags`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ flag_key: flag, enabled: newState }),
          });
        } catch (err) {
          console.warn("Flag update sync error", err);
        }
      });
    });

    // Login as Vendor buttons (triggers pre-flight audit modal)
    this.container.querySelectorAll(".btn-login-as").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const tid = parseInt(e.currentTarget.dataset.tid, 10);
        const tname = e.currentTarget.dataset.name;
        this.openImpersonationModal(tid, tname);
      });
    });

    // Top up trigger
    this.container.querySelectorAll(".btn-topup-trigger").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const tid = parseInt(e.currentTarget.dataset.tid, 10);
        this.openTopUpModal(tid);
      });
    });
  }

  openImpersonationModal(tenantId, tenantName) {
    const modalRoot = document.getElementById("impersonation-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="spotlight-modal-overlay open" id="imp-modal-overlay">
        <div class="spotlight-modal-box" style="padding:24px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div style="font-size:18px; font-weight:800; color:var(--text-primary);">
              Impersonate ${tenantName} (#${tenantId})?
            </div>
            <button id="btn-close-imp-modal" style="background:none; border:none; font-size:20px; cursor:pointer; color:var(--text-muted);">&times;</button>
          </div>

          <p style="font-size:13px; color:var(--text-secondary); line-height:1.5; margin-bottom:18px;">
            You are entering a <strong>30-minute audit-logged shadow session</strong>. Every view and mutation is recorded under your admin ID with client IP, headers, and precise timestamp.
          </p>

          <div style="background:var(--bg-subtle); border:1px solid var(--border-subtle); border-radius:var(--radius-md); padding:14px; margin-bottom:20px;">
            <div style="font-size:12px; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:10px;">Select Safety Mode:</div>
            
            <label style="display:flex; align-items:flex-start; gap:10px; margin-bottom:12px; cursor:pointer;">
              <input type="radio" name="imp_mode" value="READ_ONLY" checked style="margin-top:3px;" />
              <div>
                <div style="font-weight:700; font-size:13px; color:var(--text-primary);">🔒 Read-Only Shadow Mode (Safe - Recommended)</div>
                <div style="font-size:12px; color:var(--text-muted);">Inspect all dispatch grids, bills, and drivers. All POST/PUT/DELETE mutations are strictly blocked.</div>
              </div>
            </label>

            <label style="display:flex; align-items:flex-start; gap:10px; cursor:pointer;">
              <input type="radio" name="imp_mode" value="READ_WRITE" style="margin-top:3px;" />
              <div>
                <div style="font-weight:700; font-size:13px; color:#B45309;">✍️ Read-Write Support Mode (Requires Reason Code)</div>
                <div style="font-size:12px; color:var(--text-muted);">Enables manual emergency fixes on live duties. Every mutation increment is counted in audit logs.</div>
              </div>
            </label>
          </div>

          <div id="reason-code-wrap" style="display:none; margin-bottom:18px;">
            <label style="font-size:12px; font-weight:600; color:var(--text-secondary); display:block; margin-bottom:4px;">Mandatory Support Ticket / Reason:</label>
            <input type="text" id="imp-reason-code" placeholder="e.g. TICKET-9921: Emergency dispatch reroute" style="width:100%; padding:8px 12px; font-size:13px; border:1px solid var(--border-strong); border-radius:6px;" />
          </div>

          <div style="display:flex; justify-content:flex-end; gap:10px;">
            <button id="btn-cancel-imp" class="callout-btn" style="padding:8px 16px; font-size:13px;">Cancel</button>
            <button id="btn-start-imp" class="btn-login-as" style="padding:8px 18px; font-size:13px; font-weight:700; background:var(--purple-gradient);">
              Start 30-Min Shadow Session &rarr;
            </button>
          </div>
        </div>
      </div>
    `;

    const overlay = document.getElementById("imp-modal-overlay");
    const closeBtn = document.getElementById("btn-close-imp-modal");
    const cancelBtn = document.getElementById("btn-cancel-imp");
    const startBtn = document.getElementById("btn-start-imp");
    const radioModes = modalRoot.querySelectorAll('input[name="imp_mode"]');
    const reasonWrap = document.getElementById("reason-code-wrap");

    radioModes.forEach((r) => {
      r.addEventListener("change", () => {
        reasonWrap.style.display = r.value === "READ_WRITE" ? "block" : "none";
      });
    });

    const closeModal = () => (modalRoot.innerHTML = "");
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);

    startBtn.addEventListener("click", async () => {
      const mode = modalRoot.querySelector('input[name="imp_mode"]:checked').value;
      const reason = document.getElementById("imp-reason-code")?.value || "Standard Support Investigation";

      startBtn.disabled = true;
      startBtn.textContent = "Minting Shadow Token...";

      try {
        const res = await fetch("/api/v1/admin/impersonate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenant_id: tenantId,
            impersonation_mode: mode,
            reason_code: reason,
          }),
        });

        const data = await res.json();
        closeModal();

        if (data.ok) {
          // Store token & handoff
          sessionStorage.setItem("axiom_parent_admin_token", "admin_session_token_persist");
          sessionStorage.setItem("axiom_shadow_token", data.shadow_token);
          sessionStorage.setItem("axiom_shadow_expires_at", data.expires_at);
          sessionStorage.setItem("axiom_shadow_mode", data.impersonation_mode);

          this.onImpersonate({
            tenant_id: tenantId,
            tenant_name: tenantName,
            shadow_token: data.shadow_token,
            expires_at: data.expires_at,
            impersonation_mode: data.impersonation_mode,
            session_id: data.session_id,
          });
        }
      } catch (err) {
        console.error("Impersonation handoff failed", err);
        // Fallback simulation for local dev
        closeModal();
        this.onImpersonate({
          tenant_id: tenantId,
          tenant_name: tenantName,
          shadow_token: "simulated_shadow_jwt_token",
          expires_at: new Date(Date.now() + 30 * 60000).toISOString(),
          impersonation_mode: mode,
          session_id: "imp_local_sim",
        });
      }
    });
  }

  openTopUpModal(tenantId) {
    const modalRoot = document.getElementById("topup-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="spotlight-modal-overlay open">
        <div class="spotlight-modal-box" style="padding:24px;">
          <div style="font-size:16px; font-weight:700; margin-bottom:10px;">Top Up Pre-Paid Wallet (Tenant #${tenantId})</div>
          <p style="font-size:13px; color:var(--text-muted); margin-bottom:14px;">Credit immediate balance for SMS, GPS pings, and WhatsApp Bot consumption.</p>
          <div style="display:flex; gap:8px; margin-bottom:16px;">
            <button class="callout-btn btn-amount-preset" data-amount="50000">+ ₹500</button>
            <button class="callout-btn btn-amount-preset" data-amount="100000">+ ₹1,000</button>
            <button class="callout-btn btn-amount-preset" data-amount="500000">+ ₹5,000</button>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:10px;">
            <button id="btn-close-topup" class="callout-btn">Cancel</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById("btn-close-topup").addEventListener("click", () => {
      modalRoot.innerHTML = "";
    });

    modalRoot.querySelectorAll(".btn-amount-preset").forEach((b) => {
      b.addEventListener("click", async (e) => {
        const amt = parseInt(e.currentTarget.dataset.amount, 10);
        await fetch(`/api/v1/admin/saas/tenants/${tenantId}/topup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ amount_paise: amt }),
        });
        modalRoot.innerHTML = "";
        await this.fetchData();
        this.render();
        this.bindEvents();
      });
    });
  }
}
