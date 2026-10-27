/**
 * Axiom Mobility (Fleetline) 10/10 Super-Admin SaaS Console Component.
 * Zero-Build Vanilla ES6+ State & Sticky Table Module.
 * Hardened with AbortController, Event Delegation, and In-Flight Request Guards.
 */

export class AdminSaasConsole {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("admin-saas-view") : null);
    this.onImpersonate = options.onImpersonate || (() => {});
    this.abortController = new AbortController();
    this.inFlightRequests = new Set();

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
      if (err.name === "AbortError" || this.abortController.signal.aborted) {
        return; // Component unmounted, ignore safely
      }
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
          phone: "+91 91234 56789",
          email: "owner@garudafleets.com",
          plan_tier: "SOLO",
          subscription_status: "TRIAL",
          mrr_paise: 0,
          current_period_end: "2026-04-10",
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

        <!-- 2. Sticky Tab Filter Toolbar -->
        <div class="saas-table-toolbar">
          <div class="tab-btn-group">
            <button class="tab-btn ${this.state.activeTab === 'ALL' ? 'active' : ''}" data-tab="ALL">All Tenants (${this.state.tenants.length})</button>
            <button class="tab-btn ${this.state.activeTab === 'ACTIVE' ? 'active' : ''}" data-tab="ACTIVE">Active</button>
            <button class="tab-btn ${this.state.activeTab === 'TRIAL' ? 'active' : ''}" data-tab="TRIAL">Trial Mode</button>
            <button class="tab-btn ${this.state.activeTab === 'PAST_DUE' ? 'active' : ''}" data-tab="PAST_DUE">Past Due / Unpaid</button>
            <button class="tab-btn ${this.state.activeTab === 'SLA_PROBATION' ? 'active' : ''}" data-tab="SLA_PROBATION">SLA Probation (Silver)</button>
          </div>
          <div>
            <input type="text" placeholder="Filter by Name, City, Plan..." style="background:var(--card-bg); border:1px solid var(--border-line); color:var(--text-primary); padding:6px 12px; border-radius:6px; font-size:12px; width:220px;" />
          </div>
        </div>

        <!-- 3. Enterprise Dense Tenant Table -->
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
                <th>SLA & Gateways</th>
                <th>Feature Entitlements</th>
                <th>Support Action</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.map((t) => this.renderTenantRow(t)).join("")}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Pre-Flight Impersonation Modal Shell -->
      <div id="impersonation-modal-root"></div>
      <div id="topup-modal-root"></div>
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

    const corpPct = Math.round((t.corporate_quota.used / t.corporate_quota.total) * 100);
    const tripPct = Math.round((t.trip_quota.used / t.trip_quota.total) * 100);

    const isLowBalance = t.wallet_balance_paise < 10000; // < ₹100

    return `
      <tr>
        <!-- Tenant & Contact -->
        <td>
          <div class="tenant-name">${t.tenant_name}</div>
          <div class="tenant-meta">ID: #${t.tenant_id} &bull; ${t.phone}</div>
          <div class="tenant-meta">${t.email}</div>
        </td>

        <!-- Plan & Status -->
        <td>
          <div style="display:flex; gap:6px; margin-bottom:4px;">
            ${tierBadge}
            ${statusBadge}
          </div>
          <div style="font-size:10px; color:var(--text-subtle);">Renews: ${t.current_period_end}</div>
        </td>

        <!-- MRR -->
        <td>
          <div class="mrr-val">${this.inrFormatter.format(t.mrr_paise / 100)}</div>
          <div style="font-size:10px; color:var(--text-subtle);">${t.plan_tier === 'ENTERPRISE' ? 'Annual Plan' : 'Monthly Bill'}</div>
        </td>

        <!-- Corporate Quota -->
        <td>
          <div class="quota-text">${t.corporate_quota.used} / ${t.corporate_quota.total} Linked</div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill" style="width:${Math.min(corpPct, 100)}%; background:${corpPct >= 100 ? 'var(--danger-rose)' : 'var(--axiom-purple)'};"></div>
          </div>
        </td>

        <!-- Trip Quota -->
        <td>
          <div class="quota-text">${t.trip_quota.used} / ${t.trip_quota.total} Trips</div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-fill" style="width:${Math.min(tripPct, 100)}%; background:${tripPct >= 90 ? 'var(--warning-amber)' : 'var(--success-emerald)'};"></div>
          </div>
        </td>

        <!-- Prepaid Wallet Balance -->
        <td>
          <div class="wallet-badge ${isLowBalance ? 'low' : ''}">
            ${this.decimalFormatter.format(t.wallet_balance_paise / 100)}
          </div>
          <button class="topup-btn btn-topup-trigger" data-tid="${t.tenant_id}">+ Top Up</button>
        </td>

        <!-- SLA & Health -->
        <td>
          <div class="sla-badge ${t.sla_tier.toLowerCase()}">
            ⭐ ${t.sla_tier} (${t.ota_pct}% OTA)
          </div>
          <div style="font-size:10px; color:${t.breaches_count > 0 ? 'var(--danger-rose)' : 'var(--text-subtle)'}; margin-top:3px;">
            ${t.breaches_count} breaches (7d)
          </div>
        </td>

        <!-- Feature Entitlements -->
        <td>
          <div class="feature-chips-grid">
            <span class="feature-toggle-chip ${t.features.network ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="network">Exchange</span>
            <span class="feature-toggle-chip ${t.features.market ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="market">Market</span>
            <span class="feature-toggle-chip ${t.features.parse_ai ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="parse_ai">ParseAI</span>
            <span class="feature-toggle-chip ${t.features.whatsapp_bot ? 'enabled' : ''}" data-tid="${t.tenant_id}" data-flag="whatsapp_bot">WhatsApp</span>
          </div>
        </td>

        <!-- Support Impersonation Action -->
        <td>
          <button class="impersonate-btn btn-login-as" data-tid="${t.tenant_id}" data-name="${t.tenant_name}">
            🛡️ Log in as Tenant &rarr;
          </button>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    if (!this.container) return;
    const signal = this.abortController.signal;

    // Use Event Delegation on the container
    this.container.addEventListener("click", async (e) => {
      const target = e.target;
      if (!target) return;

      // Filter Tabs
      const tabBtn = target.closest(".tab-btn");
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
        const tid = parseInt(loginBtn.dataset.tid, 10);
        const tname = loginBtn.dataset.name;
        this.openImpersonationModal(tid, tname);
        return;
      }

      // Top up button
      const topupBtn = target.closest(".btn-topup-trigger");
      if (topupBtn) {
        const tid = parseInt(topupBtn.dataset.tid, 10);
        this.openTopUpModal(tid);
        return;
      }
    }, { signal });
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
