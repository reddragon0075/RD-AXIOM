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
      tenantBlockedState: null, // null | { account_status: string, amount_owed_paise: number, block_reason: string }

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

  setTenantBlockedState(statusData) {
    this.state.tenantBlockedState = statusData;
    this.render();
  }

  renderSuspensionBanner() {
    const block = this.state.tenantBlockedState;
    if (!block || block.account_status === "ACTIVE") return "";

    const isHard = block.account_status === "HARD_BLOCKED";
    const amountOwed = block.amount_owed_paise != null ? this.inrFormatter.format(block.amount_owed_paise / 100) : "₹3,20,000";
    const reason = block.block_reason || "Overdue platform receivables balance past due date.";

    if (isHard) {
      return `
        <div class="tenant-suspended-lock-screen" style="position:fixed; inset:0; z-index:99999; background:rgba(17,28,32,0.92); display:flex; align-items:center; justify-content:center; backdrop-filter:blur(6px); padding:20px;">
          <div style="background:#fff; border-radius:18px; padding:36px; max-width:500px; width:100%; text-align:center; box-shadow:0 24px 60px rgba(0,0,0,0.5); border:1px solid #fee2e2;">
            <div style="width:54px; height:54px; border-radius:50%; background:#fee2e2; color:#dc2626; display:grid; place-items:center; margin:0 auto 18px; font-size:26px; font-weight:800;">⛔</div>
            <h2 style="margin:0 0 10px; color:#111c20; font-size:22px; font-weight:800; letter-spacing:-0.02em;">Account Suspended — Payment Overdue</h2>
            <p style="color:#64748b; font-size:13.5px; line-height:1.55; margin:0 0 20px;">
              Your organization's access to Axiom Mobility has been temporarily suspended due to an outstanding balance of <strong style="color:#b91c1c;">${amountOwed}</strong>.<br>
              <span style="font-size:12px; color:#94a3b8; display:inline-block; margin-top:4px;">Reason: ${reason}</span>
            </p>
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; font-size:12px; color:#334155; margin-bottom:22px; line-height:1.6;">
              New dispatches, bookings, and telematics streams are locked. Please contact <strong>billing@axiomfleet.in</strong> or call <strong>+91 80 6900 8800</strong> to complete settlement and immediately unblock your fleet.
            </div>
            <div>
              <button class="tab-btn" data-action="self-settle-dues" style="background:#16a34a; color:#fff; border:none; padding:10px 20px; border-radius:8px; font-size:13px; font-weight:800; cursor:pointer; box-shadow:0 4px 12px rgba(22,163,74,0.3);">
                ⚡ Self-Serve Instant Settlement &amp; Unblock
              </button>
            </div>
          </div>
        </div>
      `;
    }

    return `
      <div class="tenant-soft-block-banner" style="background:#fef2f2; border-bottom:1.5px solid #fecaca; color:#991b1b; padding:12px 24px; font-size:13px; display:flex; align-items:center; justify-content:space-between; box-shadow:0 2px 8px rgba(220,38,38,0.08);">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="font-size:18px;">⚠️</span>
          <div>
            <strong>Account Restricted — Payment Overdue:</strong>
            New bookings and dispatches are paused due to an outstanding balance of <strong>${amountOwed}</strong>. Active in-flight trips may still be safely concluded.
            <span style="font-size:11.5px; color:#b91c1c; margin-left:6px;">(${reason})</span>
          </div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <button class="tab-btn" data-action="self-settle-dues" style="background:#16a34a; color:#fff; border:none; padding:6px 14px; border-radius:6px; font-size:12px; font-weight:800; cursor:pointer;">
            ⚡ Self-Serve Settle
          </button>
          <a href="mailto:billing@axiomfleet.in" style="background:#dc2626; color:#fff; padding:6px 14px; border-radius:6px; font-size:12px; font-weight:750; text-decoration:none; white-space:nowrap;">
            Billing Help ↗
          </a>
        </div>
      </div>
    `;
  }

  render() {
    if (!this.container) return;
    const isETS = this.state.businessLine === "ETS";
    const data = isETS ? this.state.ets : this.state.rac;
    const fin = this.state.financials;

    this.container.innerHTML = `
      ${this.renderSuspensionBanner()}
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

  renderSLARadarStrip() {
    const radar = this.state.slaRadar || {
      high_risk_count: 1,
      critical_trips: [
        {
          duty_id: "DT-9104",
          booking_id: "BK-4421",
          sla_risk_level: "CRITICAL",
          risk_reason: "Vehicle KA-05-AB-1200 stationary 6.2km away in high congestion",
          minutes_to_pickup: 14,
          suggested_backups: [
            { driver_name: "Kiran R.", vehicle_no: "KA-01-EQ-9021", eta_minutes: 6 }
          ]
        }
      ],
      night_safety_alerts: [
        {
          duty_id: "DT-9104",
          type: "NIGHT_SAFETY_UNESCORTED",
          passenger_type: "FEMALE_SOLO",
          alert: "Night Drop (21:15) requires active Geofence tracking & Escort verification"
        }
      ]
    };

    const criticals = radar.critical_trips || [];
    const nightAlerts = radar.night_safety_alerts || [];
    if (!criticals.length && !nightAlerts.length) return "";

    return `
      <div class="sla-radar-strip" style="background:linear-gradient(135deg, #1e1b4b 0%, #312e81 100%); color:#fff; border-radius:12px; padding:16px 20px; margin-bottom:20px; box-shadow:0 8px 24px rgba(49, 46, 129, 0.25); border:1px solid #4338ca;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:18px;">📡</span>
            <strong style="font-size:14px; letter-spacing:-0.01em;">Autonomous SLA Breach Radar &amp; Night Safety Guardian</strong>
            <span style="font-size:10px; background:rgba(239,68,68,0.3); color:#fca5a5; padding:3px 8px; border-radius:6px; font-weight:800; border:1px solid #ef4444;">
              ${criticals.length} AT-RISK
            </span>
          </div>
          <button data-action="refresh-sla-radar" style="background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.25); color:#fff; padding:5px 12px; font-size:11px; font-weight:700; border-radius:6px; cursor:pointer;">
            ↻ Scan Radar
          </button>
        </div>

        <div style="display:grid; grid-template-columns:${criticals.length && nightAlerts.length ? '1fr 1fr' : '1fr'}; gap:14px;">
          ${criticals.length ? `
            <div style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:12px;">
              <div style="font-size:11px; font-weight:750; color:#fbbf24; text-transform:uppercase; margin-bottom:6px;">⚠️ Imminent SLA Breach Alert</div>
              ${criticals.map(t => `
                <div style="font-size:12px; line-height:1.5;">
                  <strong>${t.duty_id}</strong> &bull; Pickup within ${t.minutes_to_pickup || 15}m<br/>
                  <span style="color:#fca5a5;">${t.risk_reason || 'High delay probability'}</span>
                  ${t.suggested_backups && t.suggested_backups.length ? `
                    <div style="margin-top:6px; font-size:11px; color:#c7d2fe; display:flex; align-items:center; gap:6px;">
                      <span>Suggested Fast Backup:</span>
                      <strong style="color:#fff;">${t.suggested_backups[0].driver_name} (${t.suggested_backups[0].vehicle_no}) &bull; ${t.suggested_backups[0].eta_minutes}m ETA</strong>
                    </div>
                  ` : ''}
                </div>
              `).join('')}
            </div>
          ` : ''}

          ${nightAlerts.length ? `
            <div style="background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:12px;">
              <div style="font-size:11px; font-weight:750; color:#c084fc; text-transform:uppercase; margin-bottom:6px;">🛡️ Night Safety Guardian Active (20:00 - 06:00)</div>
              ${nightAlerts.map(a => `
                <div style="font-size:12px; line-height:1.5; color:#e0e7ff;">
                  <strong>${a.duty_id}</strong>: ${a.alert}
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  renderOperationalView(data, isETS, fin) {
    return `
      ${this.renderSLARadarStrip()}
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
            <button class="drawer-card-btn btn-open-drawer" data-drawer-type="factoring_cashout">
              <div class="drawer-card-top">
                <span class="drawer-badge success" style="background:#dcfce7; color:#15803d;">T+0 CLEARING</span>
                <span class="drawer-count">₹3,782</span>
              </div>
              <div class="drawer-card-title">Instant Factoring</div>
              <div class="drawer-card-sub">1.75% fee immediate payout</div>
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

      // 7. Autonomous: Refresh SLA Radar
      if (target.closest("[data-action='refresh-sla-radar']")) {
        await this.fetchSLARadar();
        return;
      }

      // 8. Autonomous: Resolve Discrepancy Audit
      const resolveBtn = target.closest("[data-action='resolve-audit']");
      if (resolveBtn) {
        const dutyId = resolveBtn.dataset.dutyId;
        const resolution = resolveBtn.dataset.resolution;
        await this.handleResolveAudit(dutyId, resolution);
        return;
      }

      // 9. Autonomous: Self-Serve Dunning Unblock
      if (target.closest("[data-action='self-settle-dues']")) {
        await this.handleSelfSettleDues();
        return;
      }

      // 10. Autonomous: Instant T+0 Factoring Cashout
      const cashoutBtn = target.closest("[data-action='instant-cashout']");
      if (cashoutBtn) {
        const dutyId = cashoutBtn.dataset.dutyId;
        await this.handleInstantCashout(dutyId);
        return;
      }
    }, { signal });
  }

  async handleInstantCashout(dutyId) {
    if (this.inFlightRequests.has(`cashout_${dutyId}`)) return;
    this.inFlightRequests.add(`cashout_${dutyId}`);
    try {
      const res = await fetch("/api/v1/network/factoring/instant-cashout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duty_id: dutyId }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Success! T+0 Factoring Disbursed: ₹${data.instant_net_disbursement_inr} credited to withdrawable wallet.`);
        this.closeDrawer();
      } else {
        alert(`Cash-out failed: ${data.message || data.error || 'Server error'}`);
      }
    } catch (err) {
      console.warn("Cashout error:", err);
      alert("Network error processing instant factoring.");
    } finally {
      this.inFlightRequests.delete(`cashout_${dutyId}`);
    }
  }

  async fetchSLARadar() {
    try {
      const res = await fetch("/api/v1/ops/sla-radar", { signal: this.abortController.signal });
      const data = await res.json();
      if (data.ok) {
        this.state.slaRadar = data;
        this.render();
      }
    } catch (err) {
      console.warn("SLA Radar fetch error:", err);
    }
  }

  async handleResolveAudit(dutyId, action) {
    if (this.inFlightRequests.has(`resolve_${dutyId}`)) return;
    this.inFlightRequests.add(`resolve_${dutyId}`);

    try {
      const res = await fetch(`/api/v1/duties/${dutyId}/resolve-audit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: action,
          reason: "Dispatcher 1-click resolution from command center",
        }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Audit resolved for ${dutyId}: ${action === 'snap_gps_distance' ? 'Snapped to GPS distance' : 'Approved as-is'}. Duty slip ready for billing!`);
        const actionsEl = document.getElementById(`resolver-actions-${dutyId}`);
        if (actionsEl) {
          actionsEl.innerHTML = `<span style="font-size:11px; font-weight:800; color:#16a34a;">✓ Audit Resolved (${action})</span>`;
        }
      } else {
        alert("Resolve error: " + (data.error || "Failed to resolve discrepancy"));
      }
    } catch (err) {
      console.warn("Resolve audit error:", err);
      alert("Network error resolving audit discrepancy.");
    } finally {
      this.inFlightRequests.delete(`resolve_${dutyId}`);
    }
  }

  async handleSelfSettleDues() {
    if (this.inFlightRequests.has("self_settle")) return;
    this.inFlightRequests.add("self_settle");

    try {
      const res = await fetch("/api/v1/tenant/self-settle-payment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          payment_method: "UPI_INSTANT",
          reference_id: "SETTLE_" + Date.now(),
        }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert("Payment settled successfully! Account status restored to ACTIVE.");
        this.state.tenantBlockedState = { account_status: "ACTIVE", amount_owed_paise: 0 };
        this.render();
      } else {
        alert("Settlement failed: " + (data.error || "Please contact billing support."));
      }
    } catch (err) {
      console.warn("Self settle error:", err);
      alert("Network error processing settlement.");
    } finally {
      this.inFlightRequests.delete("self_settle");
    }
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
          <div style="display:flex; gap:8px; margin-top:10px;" id="resolver-actions-DT-8819">
            <button class="tab-btn" data-action="resolve-audit" data-duty-id="DT-8819" data-resolution="snap_gps_distance" style="background:#2563eb; color:#fff; border:none; padding:6px 12px; font-size:11px; font-weight:750; border-radius:6px; cursor:pointer;">
              🎯 Snap to GPS (71.8 km)
            </button>
            <button class="tab-btn" data-action="resolve-audit" data-duty-id="DT-8819" data-resolution="approve_as_is" style="background:var(--surface-soft); color:var(--text-primary); border:1px solid var(--border-line); padding:6px 12px; font-size:11px; font-weight:750; border-radius:6px; cursor:pointer;">
              ✓ Approve Driver Odo (88 km)
            </button>
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
    } else if (type === "factoring_cashout") {
      title = "T+0 Instant Factoring Clearinghouse";
      contentHtml = `
        <div class="drawer-action-card">
          <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <strong>Duty #DT-8819 &bull; Verified Completed</strong>
            <span class="margin-pill success" style="background:#dcfce7; color:#15803d; font-weight:800;">AUDIT PASSED</span>
          </div>
          <div style="font-size:12px; color:var(--text-secondary); line-height:1.6; margin-bottom:12px;">
            Route: Infosys BPM -> Whitefield ITPL &bull; 48.0 km<br/>
            <strong>Gross Payable:</strong> ₹3,850.00 &bull; <strong>Platform Factoring Fee (1.75%):</strong> -₹67.38<br/>
            <strong style="color:#15803d; font-size:13px;">Net Instant Disbursement: ₹3,782.62</strong>
          </div>
          <div>
            <button class="tab-btn" data-action="instant-cashout" data-duty-id="DT-8819" style="background:#16a34a; color:#fff; border:none; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:800; cursor:pointer; box-shadow:0 4px 12px rgba(22,163,74,0.3);">
              ⚡ Instant Cash-Out to Wallet (T+0)
            </button>
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
