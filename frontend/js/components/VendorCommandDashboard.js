/**
 * Axiom Mobility (Fleetline) 10/10 Vendor Command & Dual-Ledger Dashboard Component.
 * Zero-Build Vanilla ES6+ State Store, Morphing Grid & Slide-Over Drawer Module.
 * Hardened with Event Delegation, AbortController Lifecycle, and Mutability Locks.
 */

export class VendorCommandDashboard {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("vendor-command-view") : null);
    this.impersonationSession = options.impersonationSession || null;
    this.onEndImpersonation = options.onEndImpersonation || (() => {});

    this.abortController = new AbortController();
    this.inFlightRequests = new Set();
    this.timerInterval = null;

    this.state = {
      isLocked: false,
      dashboardLens: "OPERATIONAL", // "OPERATIONAL" | "REVENUE"
      businessLine: "RAC", // "RAC" | "ETS"
      dateRange: "TODAY",
      activeDrawer: null, // null | { type: string, title: string, items: Array }
      spotlightOpen: false,
      spotlightQuery: "",
      spotlightIndex: 0,
      shadowSecondsRemaining: 1800,
      shadowMode: this.impersonationSession ? (this.impersonationSession.impersonation_mode || "READ_ONLY") : "READ_ONLY",

      // RAC Data State
      rac: {
        hero: { total: 42, in_progress: 14, upcoming: 18, unallotted: 2 },
        matrix: {
          allotted: 26,
          completed: 18,
          cancelled: 1,
          driver_rejected: 0,
          pending_proforma: 3,
          distance_audit_hold: 2, // 3-way variance hold
          auto_slab_upgraded: 14, // auto slab optimizer
          partner_overflow: 4,
          sos_alerts: 0,
          expired_vehicles: 0,
          expired_drivers: 1,
          flight_delay_tracked: 2,
        },
      },

      // ETS Data State
      ets: {
        hero: { total: 128, in_progress: 46, upcoming: 54, unallotted: 0 },
        matrix: {
          shift_routes_generated: 16,
          ota_pct: "98.4%",
          passenger_no_shows: 4,
          adhoc_seat_insertions: 2,
          women_night_shift_routes: 8,
          guard_escort_verified: 8, // POSH compliance
          pending_safe_drop_ivr: 1,
          route_deviation_alerts: 0,
          sos_alerts: 0,
          expired_vehicles: 0,
          expired_drivers: 0,
          vendor_sla_breaches: 2,
        },
      },

      // Dual-Ledger Financials (with normalized contract aliases)
      financials: {
        client_receivable_paise: 48520000, // ₹4,85,200
        client_billing_paise: 48520000,
        supplier_payable_paise: 36290000,   // ₹3,62,900
        supplier_cost_paise: 36290000,
        gross_margin_paise: 12230000,       // ₹1,22,300
        gross_margin_percentage: 25.2,
        margin_pct: 25.2,
        auto_slab_savings_paise: 1140000,   // ₹11,400
        auto_slab_upgraded_count: 14,
        distance_hold_count: 2,
        distance_hold_held_paise: 385000,   // ₹3,850
        sla_penalties_deducted_paise: 150000, // ₹1,500
      },

      // Mock Corporate Profitability Table
      corporate_pnl: [
        { name: "Infosys BPM", duties: 24, client_billing: 24000000, vendor_cost: 17500000, margin_paise: 6500000, margin_pct: 27.1, proforma: "APPROVED" },
        { name: "Wipro Technologies", duties: 12, client_billing: 14500000, vendor_cost: 11000000, margin_paise: 3500000, margin_pct: 24.1, proforma: "PENDING_AUDIT" },
        { name: "Deloitte USI", duties: 6, client_billing: 10020000, vendor_cost: 7790000, margin_paise: 2230000, margin_pct: 22.3, proforma: "READY" },
      ],
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

  mutateState(fn) {
    if (this.state.isLocked) {
      throw new Error("LOCKED: State is immutable during locked operational cycles.");
    }
    if (this.state.activeDuty && ["invoiced", "completed", "locked", "billed"].includes(this.state.activeDuty.status)) {
      throw new Error("LOCKED: Cannot mutate finalized or invoiced duty state.");
    }
    fn(this.state);
  }

  appendTelemetryPing(ping) {
    if (!this.state.telemetryStream) this.state.telemetryStream = [];
    this.state.telemetryStream.push({ ...ping, timestamp: Date.now() });
    if (this.state.telemetryStream.length > 500) {
      this.state.telemetryStream = this.state.telemetryStream.slice(-500);
    }
  }

  appendAuditLog(log) {
    if (!this.state.auditLogs) this.state.auditLogs = [];
    this.state.auditLogs.unshift({ ...log, timestamp: Date.now() });
    if (this.state.auditLogs.length > 500) {
      this.state.auditLogs = this.state.auditLogs.slice(0, 500);
    }
  }

  init() {
    this.render();
    this.bindEvents();
    this.startSupportCountdown();
    this.setupSpotlightShortcut();
  }

  destroy() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
    if (this.abortController) {
      this.abortController.abort();
    }
    if (typeof window !== "undefined" && this._keydownHandler) {
      window.removeEventListener("keydown", this._keydownHandler);
      this._keydownHandler = null;
    }
  }

  startSupportCountdown() {
    if (!this.impersonationSession) return;
    this.timerInterval = setInterval(() => {
      if (this.state.shadowSecondsRemaining > 0) {
        this.state.shadowSecondsRemaining -= 1;
        const pill = document.getElementById("support-timer-display");
        if (pill) {
          const m = Math.floor(this.state.shadowSecondsRemaining / 60);
          const s = this.state.shadowSecondsRemaining % 60;
          pill.textContent = `⏱️ ${m}:${s < 10 ? '0' : ''}${s} remaining`;
        }
      } else {
        clearInterval(this.timerInterval);
        this.timerInterval = null;
        if (typeof alert === "function") {
          alert("Shadow session has expired. Returning to Super-Admin console.");
        }
        this.onEndImpersonation();
      }
    }, 1000);
  }

  setupSpotlightShortcut() {
    if (typeof window === "undefined") return;
    this._keydownHandler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key && e.key.toLowerCase() === "k") {
        if (typeof e.preventDefault === "function") e.preventDefault();
        this.openSpotlight();
      }
      if (e.key === "Escape") {
        this.closeSpotlight();
        this.closeDrawer();
      }
    };
    window.addEventListener("keydown", this._keydownHandler, {
      signal: this.abortController.signal,
    });
  }

  openSpotlight() {
    this.state.spotlightOpen = true;
    const modalRoot = document.getElementById("spotlight-modal-root");
    if (!modalRoot) return;

    modalRoot.innerHTML = `
      <div class="spotlight-modal-overlay open" id="spotlight-overlay">
        <div class="spotlight-modal-box">
          <div class="spotlight-input-wrap">
            <span style="font-size:16px;">🔍</span>
            <input type="text" id="spotlight-search-input" class="spotlight-input" placeholder="Search Vehicle (KA-01...), Duty #ID, Driver Phone, Corporate... [⌘K]" autofocus />
            <button class="drawer-close-btn" id="spotlight-close-btn">&times;</button>
          </div>
          <div class="spotlight-results-container">
            <div class="spotlight-category-header">Recent Duties</div>
            <div class="spotlight-result-item" data-action="duty" data-id="DT-9012">
              <div>
                <strong>Duty #DT-9012</strong> &bull; Infosys BPM &bull; KA-01-MJ-4491 (Ramesh Kumar)
                <div style="font-size:11px; color:var(--text-secondary);">Airport T2 Pickup &bull; Reporting 09:30 AM</div>
              </div>
              <span class="margin-pill">IN PROGRESS</span>
            </div>
            <div class="spotlight-result-item" data-action="audit" data-id="DT-8819">
              <div>
                <strong>Duty #DT-8819</strong> &bull; Wipro Technologies &bull; Distance Audit Hold
                <div style="font-size:11px; color:var(--text-secondary);">+22.2% GPS vs Odometer discrepancy &bull; Held ₹3,850</div>
              </div>
              <span class="margin-pill danger">AUDIT HOLD</span>
            </div>
            <div class="spotlight-category-header">Vehicles & Drivers</div>
            <div class="spotlight-result-item" data-action="driver" data-id="DRV-401">
              <div>
                <strong>Suresh Gowda</strong> &bull; Driver #DRV-401 &bull; +91 98450 44332
                <div style="font-size:11px; color:var(--text-secondary);">Commercial Badge Expired &bull; 0 Active Duties</div>
              </div>
              <span class="margin-pill warn">RENEWAL</span>
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("spotlight-overlay")?.addEventListener("click", (e) => {
      if (e.target && e.target.id === "spotlight-overlay") this.closeSpotlight();
    });
    document.getElementById("spotlight-close-btn")?.addEventListener("click", () => this.closeSpotlight());
  }

  closeSpotlight() {
    this.state.spotlightOpen = false;
    const modalRoot = document.getElementById("spotlight-modal-root");
    if (modalRoot) modalRoot.innerHTML = "";
  }

  render() {
    if (!this.container) return;
    const isETS = this.state.businessLine === "ETS";
    const data = isETS ? this.state.ets : this.state.rac;
    const fin = this.state.financials;

    this.container.innerHTML = `
      ${this.renderSupportBanner()}
      <div class="command-container">
        <!-- Persistent Top Header -->
        <header class="command-top-bar">
          <div class="brand-cluster">
            <div class="command-logo">AXIOM<span>COMMAND</span></div>
            <div class="mode-toggle-group">
              <button class="mode-btn ${!isETS ? 'active' : ''}" id="btn-mode-rac">RAC SPOT RENTALS</button>
              <button class="mode-btn ${isETS ? 'active' : ''}" id="btn-mode-ets">ETS EMPLOYEE TRANSPORT</button>
            </div>
          </div>
          <div class="lens-switcher-wrap">
            <span style="font-size:11px; font-weight:700; color:var(--text-subtle); margin-right:8px;">COMMAND LENS:</span>
            <div class="lens-segmented">
              <button class="lens-btn ${this.state.dashboardLens === 'OPERATIONAL' ? 'active' : ''}" id="btn-lens-ops">
                ⚡ 24/7 Operations Lens
              </button>
              <button class="lens-btn ${this.state.dashboardLens === 'REVENUE' ? 'active' : ''}" id="btn-lens-rev">
                📈 Dual-Ledger Financial Lens
              </button>
            </div>
            <button class="spotlight-quick-btn" id="spotlight-btn-trigger">
              🔍 ⌘K
            </button>
          </div>
        </header>

        <!-- Dynamic Main Content Grid -->
        <main class="dashboard-body">
          ${this.state.dashboardLens === 'OPERATIONAL'
            ? this.renderOperationalView(data, isETS, fin)
            : this.renderRevenueView(fin)}
        </main>
      </div>

      <!-- Slide-Over Drawer Shell -->
      <div id="drawer-root"></div>
      <div id="spotlight-modal-root"></div>
    `;

    // Re-bind support banner buttons if present directly in document
    this.bindDirectButtons();
  }

  renderSupportBanner() {
    if (!this.impersonationSession) return "";
    const s = this.impersonationSession;
    const tenantTitle = String(s.tenant_name || `Tenant #${s.tenant_id || "Active"}`).toUpperCase();
    const m = Math.floor(this.state.shadowSecondsRemaining / 60);
    const sec = this.state.shadowSecondsRemaining % 60;

    return `
      <div class="support-mode-banner">
        <div class="support-banner-left">
          <span>🛡️</span>
          <span>SUPPORT MODE &mdash; VIEWING PORTAL AS <strong>${tenantTitle} (#${s.tenant_id || 169})</strong> | EVERY ACTION IS AUDIT-LOGGED</span>
        </div>
        <div class="support-banner-center">
          <span class="support-timer-pill" id="support-timer-display">⏱️ ${m}:${sec < 10 ? '0' : ''}${sec} remaining</span>
          <button class="support-mode-toggle" id="btn-toggle-shadow-mode">
            ${this.state.shadowMode === 'READ_ONLY' ? '🔒 Read-Only Lock: ON' : '✍️ Read-Write: ON'}
          </button>
          <button class="btn-end-shadow" id="btn-end-shadow-session">
            END SESSION & RETURN TO ADMIN &rarr;
          </button>
        </div>
      </div>
    `;
  }

  renderOperationalView(data, isETS, fin) {
    return `
      <div class="hero-stats-row">
        <div class="hero-stat-card">
          <div class="hero-title">Total Active Roster Today</div>
          <div class="hero-val">${data.hero.total} Duties</div>
          <div class="hero-meta"><span class="delta-pos">+8.2%</span> vs 7-day average</div>
        </div>
        <div class="hero-stat-card">
          <div class="hero-title">Live in Execution</div>
          <div class="hero-val text-info">${data.hero.in_progress}</div>
          <div class="hero-meta">Vehicles actively on road</div>
        </div>
        <div class="hero-stat-card">
          <div class="hero-title">Upcoming Dispatches</div>
          <div class="hero-val text-warning">${data.hero.upcoming}</div>
          <div class="hero-meta">Next 3 hours</div>
        </div>
        <div class="hero-stat-card unallotted-action-card" id="hero-card-unallotted">
          <div class="hero-title">Unallotted Emergency Queue</div>
          <div class="hero-val text-danger">${data.hero.unallotted}</div>
          <div class="hero-meta" style="color:var(--danger-rose);">⚠️ Requires Immediate Dispatch</div>
        </div>
      </div>

      <div class="bottom-split-row">
        <div class="chart-panel">
          <div class="chart-header">
            <div class="chart-title">Daily Trip Execution & On-Time Performance</div>
            <span class="margin-pill">OTA: 98.4%</span>
          </div>
          <div class="sparkline-wrapper">
            <svg class="sparkline-svg" viewBox="0 0 500 120" preserveAspectRatio="none">
              <path class="sparkline-fill" d="M0,90 Q125,50 250,70 T500,30 L500,120 L0,120 Z"></path>
              <path class="sparkline-path" d="M0,90 Q125,50 250,70 T500,30"></path>
            </svg>
          </div>
        </div>

        <div class="drawer-trigger-panel">
          <div class="chart-header">
            <div class="chart-title">Action Center Drawers</div>
            <span style="font-size:11px; color:var(--text-subtle);">Click to inspect</span>
          </div>
          <div class="drawer-grid">
            <button class="drawer-card-btn btn-open-drawer" data-drawer-type="unallotted">
              <div class="drawer-card-top">
                <span class="drawer-badge danger">URGENT</span>
                <span class="drawer-count">${data.hero.unallotted}</span>
              </div>
              <div class="drawer-card-title">Unallotted Duties</div>
              <div class="drawer-card-sub">Immediate fleet dispatch required</div>
            </button>
            <button class="drawer-card-btn btn-open-drawer" data-drawer-type="distance_hold">
              <div class="drawer-card-top">
                <span class="drawer-badge danger">3-WAY AUDIT</span>
                <span class="drawer-count">${fin.distance_hold_count}</span>
              </div>
              <div class="drawer-card-title">Distance Fraud Holds</div>
              <div class="drawer-card-sub">${this.inrFormatter.format(fin.distance_hold_held_paise / 100)} billing protected</div>
            </button>
            <button class="drawer-card-btn btn-open-drawer" data-drawer-type="expired_drv">
              <div class="drawer-card-top">
                <span class="drawer-badge warn">COMPLIANCE</span>
                <span class="drawer-count">${isETS ? data.matrix.vendor_sla_breaches : data.matrix.expired_drivers}</span>
              </div>
              <div class="drawer-card-title">${isETS ? 'SLA Demotions' : 'Expired Badges'}</div>
              <div class="drawer-card-sub">Statutory compliance flags</div>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  renderRevenueView(fin) {
    return `
      <div class="hero-stats-row">
        <div class="hero-stat-card">
          <div class="hero-title">Gross Client Receivable</div>
          <div class="hero-val text-success">${this.inrFormatter.format(fin.client_receivable_paise / 100)}</div>
          <div class="hero-meta"><span class="delta-pos">+14.2%</span> verified proforma</div>
        </div>
        <div class="hero-stat-card">
          <div class="hero-title">Supplier Payable & DCO Cost</div>
          <div class="hero-val text-secondary">${this.inrFormatter.format(fin.supplier_payable_paise / 100)}</div>
          <div class="hero-meta">Settlement ledger cost</div>
        </div>
        <div class="hero-stat-card">
          <div class="hero-title">Net Gross Margin</div>
          <div class="hero-val text-success">${this.inrFormatter.format(fin.gross_margin_paise / 100)}</div>
          <div class="hero-meta"><span class="margin-pill">${fin.margin_pct}% Realized Margin</span></div>
        </div>
        <div class="hero-stat-card">
          <div class="hero-title">Auto-Slab Optimizer Gain</div>
          <div class="hero-val text-info">${this.inrFormatter.format(fin.auto_slab_savings_paise / 100)}</div>
          <div class="hero-meta">${fin.auto_slab_upgraded_count} package upgrades</div>
        </div>
      </div>

      <div class="pnl-table-card">
        <div class="chart-header">
          <div class="chart-title">Client-Wise Profitability Ledger (Dual-Ledger Reconciliation)</div>
          <span style="font-size:12px; color:var(--text-secondary);">Maker-Checker Dual Verification Active</span>
        </div>
        <table class="saas-table" style="margin-top:12px;">
          <thead>
            <tr>
              <th>Corporate Account</th>
              <th>Duties</th>
              <th>Client Billing (INR)</th>
              <th>Vendor Cost (INR)</th>
              <th>Gross Margin (INR)</th>
              <th>Margin %</th>
              <th>Proforma Status</th>
            </tr>
          </thead>
          <tbody>
            ${this.state.corporate_pnl.map((c) => {
              const billing = c.client_billing || c.client_billing_paise || 0;
              const cost = c.vendor_cost || c.supplier_cost_paise || 0;
              const margin = c.margin_paise != null ? c.margin_paise : (billing - cost);
              const pct = c.margin_pct != null ? c.margin_pct : (c.gross_margin_percentage || 0);
              return `
                <tr>
                  <td><strong>${c.name}</strong></td>
                  <td>${c.duties}</td>
                  <td>${this.inrFormatter.format(billing / 100)}</td>
                  <td>${this.inrFormatter.format(cost / 100)}</td>
                  <td style="color:var(--success-emerald); font-weight:700;">${this.inrFormatter.format(margin / 100)}</td>
                  <td><span class="margin-pill">${pct}%</span></td>
                  <td>
                    <span style="font-size:11px; padding:2px 6px; border-radius:4px; font-weight:700; background:${c.proforma === 'APPROVED' ? 'var(--success-subtle)' : 'var(--warning-subtle)'}; color:${c.proforma === 'APPROVED' ? '#065F46' : '#B45309'};">
                      ${c.proforma}
                    </span>
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  bindEvents() {
    if (!this.container) return;
    const signal = this.abortController.signal;

    // Use Event Delegation on the root container: Zero stacked listener leaks
    this.container.addEventListener("click", async (e) => {
      const target = e.target;
      if (!target) return;

      // 1. Lens Switchers
      if (target.closest("#btn-lens-ops")) {
        this.mutateState((draft) => { draft.dashboardLens = "OPERATIONAL"; });
        this.render();
        return;
      }
      if (target.closest("#btn-lens-rev")) {
        this.mutateState((draft) => { draft.dashboardLens = "REVENUE"; });
        this.render();
        return;
      }

      // 2. Business Line Switchers
      if (target.closest("#btn-mode-rac")) {
        this.mutateState((draft) => { draft.businessLine = "RAC"; });
        this.render();
        return;
      }
      if (target.closest("#btn-mode-ets")) {
        this.mutateState((draft) => { draft.businessLine = "ETS"; });
        this.render();
        return;
      }

      // 3. Spotlight Trigger
      if (target.closest("#spotlight-btn-trigger")) {
        this.openSpotlight();
        return;
      }

      // 4. Hero unallotted card
      if (target.closest("#hero-card-unallotted")) {
        this.openDrawerForType("unallotted");
        return;
      }

      // 5. Drawer buttons
      const drawerBtn = target.closest(".btn-open-drawer");
      if (drawerBtn) {
        const type = drawerBtn.dataset.drawerType;
        this.openDrawerForType(type);
        return;
      }

      // 6. Support Mode actions
      if (target.closest("#btn-end-shadow-session")) {
        await this.handleEndShadowSession();
        return;
      }
      if (target.closest("#btn-toggle-shadow-mode")) {
        await this.handleToggleShadowMode();
        return;
      }
      if (target.closest("#btn-toggle-admin")) {
        this.onEndImpersonation();
        return;
      }
    }, { signal });
  }

  bindDirectButtons() {
    // Fallback direct bindings for buttons outside container or in document
    const endBtn = document.getElementById("btn-end-shadow-session");
    if (endBtn && !endBtn._hasDirectListener) {
      endBtn._hasDirectListener = true;
      endBtn.addEventListener("click", () => this.handleEndShadowSession(), { signal: this.abortController.signal });
    }
  }

  async handleEndShadowSession() {
    if (this.inFlightRequests.has("end_shadow")) return;
    this.inFlightRequests.add("end_shadow");
    try {
      if (this.impersonationSession) {
        await fetch("/api/v1/admin/impersonate/end", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.impersonationSession.session_id }),
          signal: this.abortController.signal,
        });
      }
      this.onEndImpersonation();
    } catch (err) {
      console.warn("Impersonation end warning:", err);
      this.onEndImpersonation();
    } finally {
      this.inFlightRequests.delete("end_shadow");
    }
  }

  async handleToggleShadowMode() {
    if (this.inFlightRequests.has("toggle_mode")) return;
    this.inFlightRequests.add("toggle_mode");
    try {
      const newMode = this.state.shadowMode === "READ_ONLY" ? "READ_WRITE" : "READ_ONLY";
      const reason = typeof prompt === "function" ? prompt("Enter mandatory reason code to toggle support session mode:", "Dispatcher Emergency Override") : "Emergency Support Mode Switch";
      if (!reason) return;

      this.mutateState((draft) => { draft.shadowMode = newMode; });
      if (this.impersonationSession) {
        await fetch("/api/v1/admin/impersonate/mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: this.impersonationSession.session_id,
            impersonation_mode: newMode,
            reason_code: reason,
          }),
          signal: this.abortController.signal,
        });
      }
      this.render();
    } finally {
      this.inFlightRequests.delete("toggle_mode");
    }
  }

  openDrawerForType(type) {
    let title = "Action Center";
    let contentHtml = "";

    if (type === "distance_hold") {
      title = "3-Way Distance Audit Discrepancies";
      contentHtml = `
        <div class="drawer-action-card">
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <strong>Duty #DT-8819 &bull; Infosys BPM</strong>
            <span class="margin-pill danger">+22.2% VARIANCE</span>
          </div>
          <div style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:10px;">
            Driver: Ramesh Kumar &bull; Vehicle: KA-01-MJ-4491<br/>
            <strong>Odometer:</strong> 88.0 km &bull; <strong>Raw GPS:</strong> 72.0 km &bull; <strong>Road Snapped:</strong> 71.8 km<br/>
            Discrepancy: +16.0 km exceeds 10% &amp; 5km gate &bull; Held Amount: ₹3,850
          </div>
        </div>
      `;
    } else if (type === "unallotted") {
      title = "Emergency Unallotted Queue";
      contentHtml = `
        <div class="drawer-action-card">
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <strong>Duty #DT-9002 &bull; Wipro Tech</strong>
            <span class="margin-pill warn">DEPARTS IN 45 MIN</span>
          </div>
          <div style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:10px;">
            Pickup: Koramangala 4th Block &bull; Drop: Airport T2<br/>
            Vehicle Class: Sedan (Dzire / Etios)
          </div>
        </div>
      `;
    } else if (type === "expired_drv") {
      title = "Compliance Exceptions";
      contentHtml = `
        <div class="drawer-action-card">
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <strong>Suresh Gowda (+91 98450 44332)</strong>
            <span class="margin-pill warn">BADGE EXPIRED</span>
          </div>
          <div style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:10px;">
            Commercial Transport Badge expired on 24-Oct-2026.<br/>
            Cannot be allotted to airport or corporate duties.
          </div>
        </div>
      `;
    } else {
      title = `Records: ${String(type || "UNKNOWN").toUpperCase()}`;
      contentHtml = `<p style="font-size:13px; color:var(--text-muted);">No urgent action required for this bucket.</p>`;
    }

    const drawerRoot = document.getElementById("drawer-root");
    if (!drawerRoot) return;

    drawerRoot.innerHTML = `
      <div class="drawer-backdrop open" id="drawer-backdrop"></div>
      <div class="slide-over-drawer open">
        <div class="drawer-header">
          <div class="drawer-title">${title}</div>
          <button class="drawer-close-btn" id="btn-close-drawer">&times;</button>
        </div>
        <div class="drawer-content">
          ${contentHtml}
        </div>
      </div>
    `;

    document.getElementById("drawer-backdrop")?.addEventListener("click", () => this.closeDrawer());
    document.getElementById("btn-close-drawer")?.addEventListener("click", () => this.closeDrawer());
  }

  closeDrawer() {
    const drawerRoot = document.getElementById("drawer-root");
    if (drawerRoot) drawerRoot.innerHTML = "";
  }
}
