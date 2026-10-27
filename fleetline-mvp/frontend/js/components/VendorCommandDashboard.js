/**
 * Axiom Mobility (Fleetline) 10/10 Vendor Command & Dual-Ledger Dashboard Component.
 * Zero-Build Vanilla ES6+ State Store, Morphing Grid & Slide-Over Drawer Module.
 */

export class VendorCommandDashboard {
  constructor(options = {}) {
    this.container = options.container || document.getElementById("vendor-command-view");
    this.impersonationSession = options.impersonationSession || null;
    this.onEndImpersonation = options.onEndImpersonation || (() => {});

    this.state = {
      dashboardLens: "OPERATIONAL", // "OPERATIONAL" | "REVENUE"
      businessLine: "RAC", // "RAC" | "ETS"
      dateRange: "TODAY",
      activeDrawer: null, // null | { type: string, title: string, items: Array }
      spotlightOpen: false,
      spotlightQuery: "",
      spotlightIndex: 0,
      shadowSecondsRemaining: 1800,
      shadowMode: this.impersonationSession ? this.impersonationSession.impersonation_mode : "READ_ONLY",

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

      // Dual-Ledger Financials
      financials: {
        client_receivable_paise: 48520000, // ₹4,85,200
        supplier_payable_paise: 36290000,   // ₹3,62,900
        gross_margin_paise: 12230000,       // ₹1,22,300
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

    this.timerInterval = null;
  }

  init() {
    this.render();
    this.bindEvents();
    this.startSupportCountdown();
    this.setupSpotlightShortcut();
  }

  destroy() {
    if (this.timerInterval) clearInterval(this.timerInterval);
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
        alert("Shadow session has expired. Returning to Super-Admin console.");
        this.onEndImpersonation();
      }
    }, 1000);
  }

  setupSpotlightShortcut() {
    window.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        this.openSpotlight();
      }
      if (e.key === "Escape") {
        this.closeSpotlight();
        this.closeDrawer();
      }
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
            <kbd class="kbd-shortcut">ESC</kbd>
          </div>
          <div class="spotlight-results" id="spotlight-results-box">
            <div class="spotlight-category-header">Recent Duties & Actions</div>
            <div class="spotlight-result-item" data-action="duty" data-id="DT-8821">
              <div>
                <strong>Duty #DT-8821</strong> &bull; Infosys BPM &bull; KA-01-MJ-4491
                <div style="font-size:11px; color:var(--text-muted);">Toyota Innova &bull; Ramesh Kumar</div>
              </div>
              <span class="margin-pill">IN PROGRESS</span>
            </div>
            <div class="spotlight-result-item" data-action="audit" data-id="DT-8819">
              <div>
                <strong>Duty #DT-8819</strong> &bull; Distance Audit Hold (Odo 88km > GPS 72km)
                <div style="font-size:11px; color:var(--danger-rose);">+22.2% variance held for review</div>
              </div>
              <span class="margin-pill danger">AUDIT HOLD</span>
            </div>
            <div class="spotlight-category-header">Vehicles & Drivers</div>
            <div class="spotlight-result-item" data-action="driver" data-id="DRV-401">
              <div>
                <strong>Suresh Gowda</strong> &bull; +91 98450 44332 &bull; KA-04-E-1002
                <div style="font-size:11px; color:var(--text-muted);">Commercial Badge Expiring in 4 days</div>
              </div>
              <span class="margin-pill warn">RENEWAL</span>
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("spotlight-overlay").addEventListener("click", (e) => {
      if (e.target.id === "spotlight-overlay") this.closeSpotlight();
    });

    const input = document.getElementById("spotlight-search-input");
    input.focus();
    input.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase();
      const items = document.querySelectorAll(".spotlight-result-item");
      items.forEach((it) => {
        const text = it.textContent.toLowerCase();
        it.style.display = text.includes(q) ? "flex" : "none";
      });
    });

    document.querySelectorAll(".spotlight-result-item").forEach((it) => {
      it.addEventListener("click", () => {
        const act = it.dataset.action;
        const id = it.dataset.id;
        this.closeSpotlight();
        this.openDrawerForAction(act, id);
      });
    });
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
      <!-- Persistent Top Purple Support Banner (Rendered when in Shadow Session) -->
      ${this.renderSupportBanner()}

      <!-- Global Top Header -->
      <header class="global-header">
        <div class="global-header-brand">
          <div class="brand-badge"><span class="brand-dot"></span> AXIOM MOBILITY</div>
        </div>

        <div class="spotlight-search-trigger" id="spotlight-btn-trigger">
          <span>Search Vehicle (KA-01...), Duty #ID, Driver Phone, Corporate...</span>
          <kbd class="kbd-shortcut">⌘K</kbd>
        </div>

        <div class="global-header-controls">
          <div class="telemetry-pill">
            <span class="pulse-dot" style="width:6px; height:6px;"></span> All Gateways Healthy
          </div>
          <div class="branch-select-pill">
            Bengaluru HQ (GSTIN 29...)
          </div>
          <div class="role-view-toggle">
            <button class="role-toggle-btn active" id="btn-toggle-vendor">Vendor Portal</button>
            <button class="role-toggle-btn" id="btn-toggle-admin">Super-Admin</button>
          </div>
        </div>
      </header>

      <!-- Dashboard Layout: 4-Group Left Sidebar + Main Viewport -->
      <div class="dashboard-layout-container">
        <!-- 4-Group Left Sidebar -->
        <aside class="sidebar-4group">
          <div>
            <div class="sidebar-nav-group">
              <div class="sidebar-group-title">LIVE OPS</div>
              <div class="sidebar-nav-item active">⚡ Command Dashboard</div>
              <div class="sidebar-nav-item">🗺️ Dispatch & Roster Grid</div>
              <div class="sidebar-nav-item">📄 Parse AI Intake</div>
            </div>

            <div class="sidebar-nav-group">
              <div class="sidebar-group-title">NETWORK & SLA</div>
              <div class="sidebar-nav-item">🔄 Partner Exchange</div>
              <div class="sidebar-nav-item">🏆 Sub-Vendor Scorecard</div>
            </div>

            <div class="sidebar-nav-group">
              <div class="sidebar-group-title">FINANCE (DUAL-LEDGER)</div>
              <div class="sidebar-nav-item">📊 Proforma & Audit Hold</div>
              <div class="sidebar-nav-item">🧾 GST Invoices & Tally XML</div>
              <div class="sidebar-nav-item">💳 Supplier Payouts</div>
            </div>

            <div class="sidebar-nav-group">
              <div class="sidebar-group-title">FLEET & GOVERNANCE</div>
              <div class="sidebar-nav-item">🏢 Corporates & Rate Cards</div>
              <div class="sidebar-nav-item">🚗 Vehicles & Drivers</div>
              <div class="sidebar-nav-item">🛡️ Webhook & Audit Logs</div>
            </div>
          </div>

          <!-- Bottom Plan Usage Progress Card -->
          <div class="plan-usage-card">
            <div class="plan-usage-title">
              <span>GROWTH PLAN</span>
              <span style="color:var(--primary-indigo);">ACTIVE</span>
            </div>
            <div class="usage-metric-row">
              <div class="usage-label-strip">
                <span>OWN CORPORATES</span>
                <span>1/1 (100%)</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill warn" style="width:100%;"></div>
              </div>
            </div>
            <div class="usage-metric-row">
              <div class="usage-label-strip">
                <span>MONTHLY TRIPS</span>
                <span>42/100</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill" style="width:42%;"></div>
              </div>
            </div>
            <button class="btn-upgrade-plan">UPGRADE PLAN &rarr;</button>
          </div>
        </aside>

        <!-- Main Viewport -->
        <main class="main-viewport">
          <!-- Control Sub-Header -->
          <div class="control-subheader">
            <!-- Left: Dashboard Lens -->
            <div class="segmented-control">
              <button class="segmented-btn ${this.state.dashboardLens === 'OPERATIONAL' ? 'active' : ''}" id="btn-lens-ops">
                ⚡ Operational Dashboard
              </button>
              <button class="segmented-btn ${this.state.dashboardLens === 'REVENUE' ? 'active' : ''}" id="btn-lens-rev">
                💰 Revenue & Dual-Ledger P&L
              </button>
            </div>

            <!-- Center: RAC vs ETS Morph Switcher -->
            <div class="mode-morph-control">
              <span class="morph-pill ${!isETS ? 'active' : ''}" id="btn-mode-rac">🚕 RAC (Spot Rental)</span>
              <span class="morph-pill ${isETS ? 'active' : ''}" id="btn-mode-ets">🚌 ETS (Shift Transport)</span>
            </div>

            <!-- Right: Date Range Picker -->
            <div class="date-filter-control">
              <button class="quick-pill active">Today</button>
              <button class="quick-pill">This Week</button>
              <button class="quick-pill">This Month</button>
            </div>
          </div>

          ${this.state.dashboardLens === 'OPERATIONAL' ? this.renderOperationalView(data, isETS, fin) : this.renderRevenueView(fin)}
        </main>
      </div>

      <!-- Slide-Over Drawer Container -->
      <div id="drawer-root"></div>

      <!-- Spotlight Search Root -->
      <div id="spotlight-modal-root"></div>
    `;
  }

  renderSupportBanner() {
    if (!this.impersonationSession) return "";
    const s = this.impersonationSession;
    const m = Math.floor(this.state.shadowSecondsRemaining / 60);
    const sec = this.state.shadowSecondsRemaining % 60;

    return `
      <div class="support-mode-banner">
        <div class="support-banner-left">
          <span>🛡️</span>
          <span>SUPPORT MODE &mdash; VIEWING PORTAL AS <strong>${s.tenant_name.toUpperCase()} (#${s.tenant_id})</strong> | EVERY ACTION IS AUDIT-LOGGED</span>
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
      <!-- Top 4 Hero Execution Cards -->
      <div class="hero-exec-strip">
        <div class="hero-exec-card">
          <div class="hero-title">TOTAL DUTIES / TRIPS</div>
          <div class="hero-number">${data.hero.total}</div>
        </div>
        <div class="hero-exec-card live-pulse">
          <div class="hero-title">IN PROGRESS (LIVE)</div>
          <div class="hero-number">
            <span class="pulse-dot"></span> ${data.hero.in_progress}
          </div>
        </div>
        <div class="hero-exec-card upcoming">
          <div class="hero-title">UPCOMING (NEXT 4 HRS)</div>
          <div class="hero-number">${data.hero.upcoming}</div>
        </div>
        <div class="hero-exec-card at-risk" id="hero-card-unallotted">
          <div class="hero-title">UNALLOTTED / AT RISK</div>
          <div class="hero-number" style="color:${data.hero.unallotted > 0 ? 'var(--danger-rose)' : 'var(--text-primary)'};">
            ${data.hero.unallotted}
          </div>
        </div>
      </div>

      <!-- 12-Box Status & Compliance Matrix (4x3 Grid) -->
      <div class="matrix-12box-grid">
        ${!isETS ? this.renderRACMatrix(data.matrix) : this.renderETSMatrix(data.matrix)}
      </div>

      <!-- Bottom Split Row: Volume Chart (60%) + Dual-Ledger Card (40%) -->
      <div class="bottom-split-row">
        <!-- Left: Trip Trend & Margin SVG Chart Area -->
        <div class="chart-panel">
          <div class="chart-header">
            <div class="chart-title">Daily Trip Execution & On-Time Performance (OTA %)</div>
            <span style="font-size:12px; color:var(--text-muted);">Last 7 Days</span>
          </div>
          <div class="chart-canvas-area">
            <svg viewBox="0 0 500 200" style="width:100%; height:100%;">
              <defs>
                <linearGradient id="gradTrip" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#4F46E5" stop-opacity="0.3"/>
                  <stop offset="100%" stop-color="#4F46E5" stop-opacity="0.0"/>
                </linearGradient>
              </defs>
              <line x1="40" y1="160" x2="480" y2="160" stroke="#E2E8F0" stroke-width="1"/>
              <line x1="40" y1="110" x2="480" y2="110" stroke="#E2E8F0" stroke-width="1" stroke-dasharray="3,3"/>
              <line x1="40" y1="60" x2="480" y2="60" stroke="#E2E8F0" stroke-width="1" stroke-dasharray="3,3"/>
              
              <!-- Sparkline Bars -->
              <rect x="70" y="80" width="24" height="80" fill="#4F46E5" rx="3"/>
              <rect x="130" y="60" width="24" height="100" fill="#4F46E5" rx="3"/>
              <rect x="190" y="90" width="24" height="70" fill="#4F46E5" rx="3"/>
              <rect x="250" y="50" width="24" height="110" fill="#4F46E5" rx="3"/>
              <rect x="310" y="40" width="24" height="120" fill="#4F46E5" rx="3"/>
              <rect x="370" y="70" width="24" height="90" fill="#4F46E5" rx="3"/>
              <rect x="430" y="45" width="24" height="115" fill="#10B981" rx="3"/>
              
              <!-- Trend Line -->
              <polyline fill="none" stroke="#10B981" stroke-width="3" points="82,75 142,55 202,80 262,45 322,35 382,60 442,40"/>
              
              <!-- X Axis Labels -->
              <text x="75" y="180" font-size="10" fill="#94A3B8">21 Oct</text>
              <text x="135" y="180" font-size="10" fill="#94A3B8">22 Oct</text>
              <text x="195" y="180" font-size="10" fill="#94A3B8">23 Oct</text>
              <text x="255" y="180" font-size="10" fill="#94A3B8">24 Oct</text>
              <text x="315" y="180" font-size="10" fill="#94A3B8">25 Oct</text>
              <text x="375" y="180" font-size="10" fill="#94A3B8">26 Oct</text>
              <text x="435" y="180" font-size="10" fill="#10B981" font-weight="700">Today</text>
            </svg>
          </div>
        </div>

        <!-- Right: Axiom Dual-Ledger P&L Command Card -->
        <div class="dual-ledger-card">
          <div>
            <div class="dual-ledger-header">
              <div class="dual-ledger-title">DUAL-LEDGER P&L &amp; PAYOUTS</div>
              <button class="callout-btn" id="btn-view-ledger">View Ledger &rarr;</button>
            </div>

            <!-- 3-Column Financial Strip -->
            <div class="financial-strip-3col">
              <div>
                <div class="fin-col-label">Client Receivable</div>
                <div class="fin-col-value">${this.inrFormatter.format(fin.client_receivable_paise / 100)}</div>
              </div>
              <div>
                <div class="fin-col-label">Supplier Payable</div>
                <div class="fin-col-value">${this.inrFormatter.format(fin.supplier_payable_paise / 100)}</div>
              </div>
              <div>
                <div class="fin-col-label">Net Margin</div>
                <div class="fin-col-value" style="color:var(--success-emerald);">
                  ${this.inrFormatter.format(fin.gross_margin_paise / 100)}
                </div>
                <span class="margin-pill" style="margin-top:2px;">${fin.margin_pct}% 🟢</span>
              </div>
            </div>

            <!-- 3 Axiom Intelligence Callouts -->
            <div class="intelligence-callouts-box">
              <div class="callout-row">
                <div class="callout-desc">
                  <span>✨</span>
                  <span><strong>Auto-Slab Optimizer:</strong> Upgraded ${fin.auto_slab_upgraded_count} duties &bull; Protected ${this.inrFormatter.format(fin.auto_slab_savings_paise / 100)} margin</span>
                </div>
              </div>

              <div class="callout-row" style="border-color:#FDE68A; background:#FFFDF0;">
                <div class="callout-desc">
                  <span>🛑</span>
                  <span><strong>3-Way Distance Audit Hold:</strong> ${fin.distance_hold_count} duties locked (Odo > Road by >10%) &bull; ${this.inrFormatter.format(fin.distance_hold_held_paise / 100)} held</span>
                </div>
                <button class="callout-btn btn-open-drawer" data-drawer-type="distance_hold">Review Diff</button>
              </div>

              <div class="callout-row">
                <div class="callout-desc">
                  <span>📉</span>
                  <span><strong>SLA Penalty Debits:</strong> ${this.inrFormatter.format(fin.sla_penalties_deducted_paise / 100)} auto-deducted from demoted sub-vendors</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  renderRACMatrix(m) {
    const card = (label, count, isAlert, isWarn, drawerType) => {
      const isZero = count === 0 || count === "0";
      const cls = isZero ? "zero-muted" : isAlert ? "actionable alert-pulse" : isWarn ? "actionable warn-pulse" : "actionable";
      return `
        <div class="matrix-box-card ${cls} ${drawerType ? 'btn-open-drawer' : ''}" data-drawer-type="${drawerType || ''}">
          <span class="matrix-label">${label}</span>
          <span class="matrix-count">${count}</span>
        </div>
      `;
    };

    return `
      ${card("Allotted Duties", m.allotted, false, false, "allotted")}
      ${card("Completed Duties", m.completed, false, false, "completed")}
      ${card("Cancelled Duties", m.cancelled, false, false, "cancelled")}
      ${card("Driver Rejected", m.driver_rejected, true, false, "driver_rejected")}

      ${card("Pending Proforma Bills", m.pending_proforma, false, true, "proforma")}
      ${card("Distance Audit Hold (Odo > GPS)", m.distance_audit_hold, false, true, "distance_hold")}
      ${card("Auto-Slab Upgraded Trips", m.auto_slab_upgraded, false, false, "auto_slab")}
      ${card("Partner Overflow Trips", m.partner_overflow, false, false, "overflow")}

      ${card("SOS Alerts", m.sos_alerts, true, false, "sos")}
      ${card("Expired Vehicles", m.expired_vehicles, true, false, "expired_veh")}
      ${card("Expired Drivers", m.expired_drivers, false, true, "expired_drv")}
      ${card("Flight Delays Tracked", m.flight_delay_tracked, false, false, "flight_delay")}
    `;
  }

  renderETSMatrix(m) {
    const card = (label, count, isAlert, isWarn, drawerType) => {
      const isZero = count === 0 || count === "0";
      const cls = isZero ? "zero-muted" : isAlert ? "actionable alert-pulse" : isWarn ? "actionable warn-pulse" : "actionable";
      return `
        <div class="matrix-box-card ${cls} ${drawerType ? 'btn-open-drawer' : ''}" data-drawer-type="${drawerType || ''}">
          <span class="matrix-label">${label}</span>
          <span class="matrix-count">${count}</span>
        </div>
      `;
    };

    return `
      ${card("Shift Routes Generated", m.shift_routes_generated, false, false, "routes")}
      ${card("On-Time Arrival (OTA)", m.ota_pct, false, false, "ota")}
      ${card("Passenger No-Shows", m.passenger_no_shows, false, false, "no_shows")}
      ${card("Ad-Hoc Seat Insertions", m.adhoc_seat_insertions, false, false, "seat_insert")}

      ${card("Women Night-Shift Routes", m.women_night_shift_routes, false, false, "night_shift")}
      ${card("Guard Escort Verified (POSH)", m.guard_escort_verified, false, false, "posh_guard")}
      ${card("Pending Safe-Drop IVR", m.pending_safe_drop_ivr, false, true, "safe_drop")}
      ${card("Route Deviation Alerts", m.route_deviation_alerts, true, false, "deviation")}

      ${card("SOS Alerts", m.sos_alerts, true, false, "sos")}
      ${card("Expired Vehicles", m.expired_vehicles, true, false, "expired_veh")}
      ${card("Expired Drivers", m.expired_drivers, true, false, "expired_drv")}
      ${card("Vendor SLA Breaches", m.vendor_sla_breaches, true, false, "sla_breach")}
    `;
  }

  renderRevenueView(fin) {
    return `
      <div class="table-panel" style="margin-bottom:24px;">
        <div class="table-filter-bar">
          <div style="font-weight:700; font-size:15px;">Corporate-Wise Profitability & Dual-Ledger Margins</div>
          <button class="callout-btn" id="btn-export-all-tally">Export All Tally Prime XML &rarr;</button>
        </div>
        <table class="enterprise-table">
          <thead>
            <tr>
              <th>Corporate Account</th>
              <th>Duties</th>
              <th>Client Billing (Receivable)</th>
              <th>Vendor Cost (Payable)</th>
              <th>Gross Margin ₹</th>
              <th>Margin %</th>
              <th>Proforma Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${this.state.corporate_pnl.map((c) => `
              <tr>
                <td style="font-weight:700;">${c.name}</td>
                <td>${c.duties}</td>
                <td>${this.inrFormatter.format(c.client_billing / 100)}</td>
                <td>${this.inrFormatter.format(c.vendor_cost / 100)}</td>
                <td style="color:var(--success-emerald); font-weight:700;">${this.inrFormatter.format(c.margin_paise / 100)}</td>
                <td><span class="margin-pill">${c.margin_pct}%</span></td>
                <td>
                  <span style="font-size:11px; padding:2px 6px; border-radius:4px; font-weight:700; background:${c.proforma === 'APPROVED' ? 'var(--success-subtle)' : 'var(--warning-subtle)'}; color:${c.proforma === 'APPROVED' ? '#065F46' : '#B45309'};">
                    ${c.proforma}
                  </span>
                </td>
                <td>
                  <button class="callout-btn btn-export-tally" data-corp="${c.name}">[Export Tally XML]</button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  bindEvents() {
    if (!this.container) return;

    document.getElementById("spotlight-btn-trigger")?.addEventListener("click", () => this.openSpotlight());

    document.getElementById("btn-lens-ops")?.addEventListener("click", () => {
      this.state.dashboardLens = "OPERATIONAL";
      this.render();
      this.bindEvents();
    });

    document.getElementById("btn-lens-rev")?.addEventListener("click", () => {
      this.state.dashboardLens = "REVENUE";
      this.render();
      this.bindEvents();
    });

    document.getElementById("btn-mode-rac")?.addEventListener("click", () => {
      this.state.businessLine = "RAC";
      this.render();
      this.bindEvents();
    });

    document.getElementById("btn-mode-ets")?.addEventListener("click", () => {
      this.state.businessLine = "ETS";
      this.render();
      this.bindEvents();
    });

    document.getElementById("btn-end-shadow-session")?.addEventListener("click", async () => {
      if (this.impersonationSession) {
        await fetch("/api/v1/admin/impersonate/end", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: this.impersonationSession.session_id }),
        });
      }
      this.onEndImpersonation();
    });

    document.getElementById("btn-toggle-shadow-mode")?.addEventListener("click", async () => {
      const newMode = this.state.shadowMode === "READ_ONLY" ? "READ_WRITE" : "READ_ONLY";
      const reason = prompt("Enter mandatory reason code to toggle support session mode:", "Dispatcher Emergency Override");
      if (!reason) return;

      this.state.shadowMode = newMode;
      if (this.impersonationSession) {
        await fetch("/api/v1/admin/impersonate/mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: this.impersonationSession.session_id,
            impersonation_mode: newMode,
            reason_code: reason,
          }),
        });
      }
      this.render();
      this.bindEvents();
    });

    this.container.querySelectorAll(".btn-open-drawer").forEach((b) => {
      b.addEventListener("click", (e) => {
        const type = e.currentTarget.dataset.drawerType;
        this.openDrawerForType(type);
      });
    });

    document.getElementById("hero-card-unallotted")?.addEventListener("click", () => {
      this.openDrawerForType("unallotted");
    });

    document.getElementById("btn-toggle-admin")?.addEventListener("click", () => {
      this.onEndImpersonation();
    });
  }

  openDrawerForType(type) {
    let title = "Action Drawer";
    let contentHtml = "";

    if (type === "distance_hold") {
      title = "🛑 3-Way Distance Audit Hold Queue";
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
          <div style="display:flex; gap:8px;">
            <button class="callout-btn" style="background:var(--success-subtle); color:#065F46; border-color:#A7F3D0;">[Approve Odo Variance]</button>
            <button class="callout-btn">[Clamp to Snapped 71.8km]</button>
          </div>
        </div>
      `;
    } else if (type === "unallotted") {
      title = "🚨 Quick Dispatch: Unallotted Duties";
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
          <button class="callout-btn" style="background:var(--primary-indigo); color:#FFF; border:none; padding:6px 12px;">[Auto-Allot Nearest Vendor]</button>
        </div>
      `;
    } else if (type === "expired_drv") {
      title = "⚠️ Driver Compliance & Expired Permits";
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
          <div style="display:flex; gap:8px;">
            <button class="callout-btn">[Masked Call Driver]</button>
            <button class="callout-btn">[Upload Renewed Permit]</button>
          </div>
        </div>
      `;
    } else {
      title = `Records: ${type.toUpperCase()}`;
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

    document.getElementById("drawer-backdrop").addEventListener("click", () => this.closeDrawer());
    document.getElementById("btn-close-drawer").addEventListener("click", () => this.closeDrawer());
  }

  openDrawerForAction(action, id) {
    if (action === "audit") this.openDrawerForType("distance_hold");
    else if (action === "driver") this.openDrawerForType("expired_drv");
    else this.openDrawerForType("unallotted");
  }

  closeDrawer() {
    const drawerRoot = document.getElementById("drawer-root");
    if (drawerRoot) drawerRoot.innerHTML = "";
  }
}
