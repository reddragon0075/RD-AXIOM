/**
 * Axiom Mobility (Fleetline) 10/10 Partner Network Exchange & Autonomous Clearinghouse View.
 * Zero-Build Vanilla ES6+ State Store, Morphing Feed & Real-Time Clearinghouse Console.
 * Hardened with Event Delegation, AbortController Lifecycle, and Mutability Locks.
 */

export class PartnerExchangeView {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("partner-exchange-view") : null);
    this.abortController = new AbortController();
    this.inFlightRequests = new Set();
    this.timerInterval = null;

    this.state = {
      activeTab: "EXCHANGE_FEED", // "EXCHANGE_FEED" | "EMPTY_LEGS" | "DEMAND_SWARM" | "FACTORING_PAYOUTS"
      vendorTier: "TIER_1_PLATINUM",
      surgeModalListing: null,
      surgeSliderValue: 10.0,
      overrideMarginFloor: false,
      listings: [
        {
          id: "net_demo_001",
          duty_id: "DT-9104",
          origin_vendor_name: "BlueLine Mobility",
          client_display_name: "Originating Partner: BlueLine Mobility",
          trip_class: "Executive Sedan",
          pickup_address: "Silk Board Junction / HSR",
          dropoff_address: "Embassy GolfLinks (EGL) Dome",
          reporting_time: "18:30 IST",
          estimated_distance_km: 28.5,
          supplier_payout_inr: 1950.0,
          current_wave: 1,
          eligible_tier: "TIER_1_PLATINUM",
          wave_seconds_remaining: 184,
          prefer_ev_green_corridor: true,
          status: "BROADCASTING",
          compliance_status: "PASSED_VERIFIED",
        },
        {
          id: "net_demo_002",
          duty_id: "DT-9103",
          origin_vendor_name: "AeroShuttle Express",
          client_display_name: "Originating Partner: AeroShuttle Express",
          trip_class: "Airport Transfer Zone Ring",
          pickup_address: "Electronic City Phase 1",
          dropoff_address: "BLR Airport Terminal 2",
          reporting_time: "19:15 IST",
          estimated_distance_km: 52.0,
          supplier_payout_inr: 2850.0,
          current_wave: 2,
          eligible_tier: "TIER_2_GOLD",
          wave_seconds_remaining: 260,
          prefer_ev_green_corridor: false,
          status: "BROADCASTING",
          compliance_status: "PASSED_VERIFIED",
        },
      ],
      emptyLegs: [
        {
          id: "el_demo_001",
          vendor_name: "MetroFleet Cabs",
          origin_city: "Mysuru",
          destination_city: "Bengaluru",
          corridor_name: "Mysuru -> Bengaluru Expressway Deadhead",
          vehicle_category: "Sedan (Dzire / Etios)",
          discounted_partner_rate_per_km: 12.6,
          standard_rate_per_km: 18.0,
          discount_pct: 30.0,
          status: "AVAILABLE",
        },
      ],
      demandSwarm: [
        { zone: "Electronic City Phase 1 & 2", predicted_duties: 48, active_partner_idle_vehicles: 34, deficit: 14, surge_eligible: true, surge_boost_pct: 10.0 },
        { zone: "Whitefield & ITPL Corridor", predicted_duties: 62, active_partner_idle_vehicles: 48, deficit: 14, surge_eligible: true, surge_boost_pct: 15.0 },
        { zone: "Airport / Hebbal Corridor", predicted_duties: 55, active_partner_idle_vehicles: 42, deficit: 13, surge_eligible: true, surge_boost_pct: 10.0 },
      ],
      factoringDuties: [
        {
          duty_id: "DT-8819",
          route_label: "Infosys BPM -> Whitefield ITPL",
          gross_payable_inr: 3850.0,
          factoring_fee_pct: 1.75,
          platform_fee_inr: 67.38,
          net_disbursement_inr: 3782.62,
          status: "VERIFIED_AUDITED",
        },
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

  mount() {
    this.init();
  }

  unmount() {
    this.destroy();
  }

  init() {
    this.render();
    this.bindEvents();
    this.startCountdownTimer();
  }

  destroy() {
    if (this.abortController) {
      this.abortController.abort();
    }
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
    }
  }

  startCountdownTimer() {
    this.timerInterval = setInterval(() => {
      let changed = false;
      this.state.listings.forEach((l) => {
        if (l.wave_seconds_remaining > 0) {
          l.wave_seconds_remaining -= 1;
          changed = true;
        }
      });
      if (changed && this.state.activeTab === "EXCHANGE_FEED") {
        this.updateCountdownElements();
      }
    }, 1000);
  }

  updateCountdownElements() {
    if (!this.container) return;
    this.state.listings.forEach((l) => {
      const el = this.container.querySelector(`#timer-${l.id}`);
      if (el) {
        const m = Math.floor(l.wave_seconds_remaining / 60);
        const s = l.wave_seconds_remaining % 60;
        el.textContent = `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
      }
    });
  }

  openSurgeModal(listing) {
    this.state.surgeModalListing = listing;
    this.render();
  }

  closeSurgeModal() {
    this.state.surgeModalListing = null;
    this.render();
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="partner-exchange-container" style="padding:24px; max-width:1400px; margin:0 auto; font-family:Inter,system-ui,sans-serif;">
        <!-- Header Banner -->
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; background:linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); color:#fff; padding:20px 24px; border-radius:14px; box-shadow:0 8px 30px rgba(15,23,42,0.4); border:1px solid #312e81;">
          <div>
            <div style="display:flex; align-items:center; gap:10px;">
              <span style="font-size:24px;">🌐</span>
              <h1 style="margin:0; font-size:20px; font-weight:800; letter-spacing:-0.02em;">Axiom Hyper-Network Exchange &amp; Autonomous Clearinghouse</h1>
              <span class="status-pill tier-enterprise" style="font-size:10.5px; background:#4338ca; color:#e0e7ff; padding:3px 8px; border-radius:6px; font-weight:750;">
                ⭐ ${this.state.vendorTier}
              </span>
            </div>
            <p style="margin:6px 0 0; font-size:12.5px; color:#94a3b8;">
              Double-Blind White-Label Ghost Mode &bull; Timed Waterfall Cascades &bull; Pre-Authorized Escrow &bull; T+0 Factoring
            </p>
          </div>
          <div style="display:flex; gap:10px;">
            <button data-action="broadcast-trip-prompt" style="background:#2563eb; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-size:12px; font-weight:750; cursor:pointer;">
              + Broadcast Overflow Trip
            </button>
            <button data-action="publish-empty-leg-prompt" style="background:#10b981; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-size:12px; font-weight:750; cursor:pointer;">
              ⚡ List Deadhead Return
            </button>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <div style="display:flex; gap:8px; margin-bottom:20px; border-bottom:1.5px solid var(--border-line); padding-bottom:12px;">
          <button class="tab-btn ${this.state.activeTab === 'EXCHANGE_FEED' ? 'active' : ''}" data-view-tab="EXCHANGE_FEED" style="padding:8px 16px; border-radius:8px; font-size:12.5px; font-weight:750; cursor:pointer; border:none;">
            📡 Live Waterfall Feed (${(this.state.listings || []).length})
          </button>
          <button class="tab-btn ${this.state.activeTab === 'EMPTY_LEGS' ? 'active' : ''}" data-view-tab="EMPTY_LEGS" style="padding:8px 16px; border-radius:8px; font-size:12.5px; font-weight:750; cursor:pointer; border:none;">
            🔄 Empty-Leg Return Radar (${(this.state.emptyLegs || []).length})
          </button>
          <button class="tab-btn ${this.state.activeTab === 'DEMAND_SWARM' ? 'active' : ''}" data-view-tab="DEMAND_SWARM" style="padding:8px 16px; border-radius:8px; font-size:12.5px; font-weight:750; cursor:pointer; border:none;">
            🔥 City Demand Swarm Heatmap
          </button>
          <button class="tab-btn ${this.state.activeTab === 'FACTORING_PAYOUTS' ? 'active' : ''}" data-view-tab="FACTORING_PAYOUTS" style="padding:8px 16px; border-radius:8px; font-size:12.5px; font-weight:750; cursor:pointer; border:none;">
            ⚡ Instant T+0 Factoring (${(this.state.factoringDuties || []).length})
          </button>
          <button class="tab-btn ${this.state.activeTab === 'SHADOW_MODE' ? 'active' : ''}" data-view-tab="SHADOW_MODE" style="padding:8px 16px; border-radius:8px; font-size:12.5px; font-weight:750; cursor:pointer; border:none;">
            🛡️ Shadow Mode (Vendor Audit)
          </button>
        </div>

        <!-- Active Tab Content -->
        ${this.renderActiveTabContent()}

        <!-- Smart Surge Slider Modal -->
        ${this.renderSurgeSliderModal()}
      </div>
    `;
  }

  renderActiveTabContent() {
    switch (this.state.activeTab) {
      case "EMPTY_LEGS":
        return this.renderEmptyLegsView();
      case "DEMAND_SWARM":
        return this.renderDemandSwarmView();
      case "FACTORING_PAYOUTS":
        return this.renderFactoringPayoutsView();
      case "SHADOW_MODE":
        return this.renderShadowModeView();
      case "EXCHANGE_FEED":
      default:
        return this.renderExchangeFeedView();
    }
  }

  renderExchangeFeedView() {
    return `
      <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(420px, 1fr)); gap:18px;">
        ${this.state.listings.map((l) => {
          const m = Math.floor(l.wave_seconds_remaining / 60);
          const s = l.wave_seconds_remaining % 60;
          const timeStr = `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
          return `
            <div style="background:var(--card-bg, #fff); border:1px solid var(--border-line, #e2e8f0); border-radius:12px; padding:18px; box-shadow:0 2px 10px rgba(0,0,0,0.04); display:flex; flex-direction:column; justify-content:space-between;">
              <div>
                <!-- Top Badge Row -->
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                  <span class="status-pill" style="background:#ede9fe; color:#6d28d9; font-weight:800; font-size:10.5px; padding:3px 8px; border-radius:6px;">
                    WAVE ${l.current_wave} &bull; ${l.eligible_tier}
                  </span>
                  <div style="display:flex; align-items:center; gap:6px;">
                    <span style="font-size:12px; color:#dc2626;">⏳</span>
                    <strong id="timer-${l.id}" style="font-size:12px; font-family:monospace; color:#dc2626;">${timeStr}</strong>
                  </div>
                </div>

                <!-- Client Masked Brand -->
                <div style="margin-bottom:8px;">
                  <h3 style="margin:0 0 2px; font-size:15px; font-weight:800; color:var(--text-primary, #0f172a);">
                    ${l.client_display_name}
                  </h3>
                  <div style="display:flex; align-items:center; gap:6px; font-size:11.5px; color:var(--text-secondary, #64748b);">
                    <span>${l.duty_id ? `#${l.duty_id} &bull; ` : ''}${l.trip_class}</span>
                    &bull;
                    <span>${l.estimated_distance_km} km</span>
                    ${l.prefer_ev_green_corridor ? `<span style="background:#dcfce7; color:#15803d; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:800;">🌿 EV GREEN PRIORITY</span>` : ''}
                  </div>
                </div>

                <!-- Routing -->
                <div style="background:var(--surface-soft, #f8fafc); border:1px solid var(--border-line, #e2e8f0); border-radius:8px; padding:10px 12px; margin-bottom:14px; font-size:12px; line-height:1.5;">
                  <div><strong style="color:#059669;">● Pickup:</strong> ${l.pickup_address}</div>
                  <div style="margin-top:4px;"><strong style="color:#dc2626;">■ Drop:</strong> ${l.dropoff_address}</div>
                  <div style="margin-top:4px; font-size:10.5px; color:var(--text-subtle, #94a3b8);">⏰ Reporting: ${l.reporting_time}</div>
                </div>
              </div>

              <!-- Action & Payout Footer -->
              <div style="border-top:1px solid var(--border-line, #e2e8f0); padding-top:12px; display:flex; justify-content:space-between; align-items:center;">
                <div>
                  <div style="font-size:10.5px; color:var(--text-secondary, #64748b); text-transform:uppercase; font-weight:750;">Supplier Payout</div>
                  <div style="font-size:18px; font-weight:800; color:#1e1b4b;">₹${this.inrFormatter.format(l.supplier_payout_inr).replace('₹', '')}</div>
                </div>
                <div style="display:flex; gap:8px;">
                  <button class="tab-btn" data-action="open-surge-slider" data-listing-id="${l.id}" style="background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; padding:6px 12px; font-size:11px; font-weight:750; border-radius:6px; cursor:pointer;">
                    ⚡ Surge
                  </button>
                  <button class="tab-btn" data-action="claim-listing" data-listing-id="${l.id}" style="background:#2563eb; color:#fff; border:none; padding:8px 16px; font-size:12px; font-weight:800; border-radius:6px; cursor:pointer; box-shadow:0 4px 12px rgba(37,99,235,0.3);">
                    Claim Duty ↗
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  renderEmptyLegsView() {
    return `
      <div style="background:var(--card-bg, #fff); border:1px solid var(--border-line, #e2e8f0); border-radius:12px; padding:20px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <div>
            <h3 style="margin:0 0 4px; font-size:16px; font-weight:800; color:var(--text-primary, #0f172a);">🔄 Empty-Leg Deadhead Return Matchmaker</h3>
            <p style="margin:0; font-size:12px; color:var(--text-secondary, #64748b);">Unlocking pure profit on empty returning outstation vehicles with 25%–40% partner discounts.</p>
          </div>
          <button data-action="publish-empty-leg-prompt" style="background:#10b981; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-size:12px; font-weight:750; cursor:pointer;">
            + List Available Deadhead
          </button>
        </div>

        <table class="saas-table" style="width:100%; border-collapse:collapse; font-size:12px;">
          <thead>
            <tr style="border-bottom:1.5px solid #e2e8f0; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">
              <th style="padding:10px;">Corridor Route</th>
              <th style="padding:10px;">Fulfilling Vendor</th>
              <th style="padding:10px;">Vehicle Category</th>
              <th style="padding:10px;">Discounted Partner Rate</th>
              <th style="padding:10px;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${this.state.emptyLegs.map((el) => `
              <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:12px 10px; font-weight:750; color:#1e293b;">
                  ${el.corridor_name}
                  <div style="font-size:10px; color:#059669; font-weight:700;">-${el.discount_pct}% below standard tariff</div>
                </td>
                <td style="padding:12px 10px; color:#475569;">${el.vendor_name}</td>
                <td style="padding:12px 10px; color:#475569;">${el.vehicle_category}</td>
                <td style="padding:12px 10px; font-weight:800; color:#0f172a;">
                  ₹${el.discounted_partner_rate_per_km} / km
                  <span style="font-size:10px; text-decoration:line-through; color:#94a3b8; margin-left:4px;">₹${el.standard_rate_per_km}</span>
                </td>
                <td style="padding:12px 10px;">
                  <button data-action="match-empty-leg" data-corridor-id="${el.id}" style="background:#059669; color:#fff; border:none; padding:6px 14px; border-radius:6px; font-size:11.5px; font-weight:750; cursor:pointer;">
                    Match Booking 🎯
                  </button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderDemandSwarmView() {
    return `
      <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(360px, 1fr)); gap:16px;">
        ${this.state.demandSwarm.map((z) => `
          <div style="background:var(--card-bg, #fff); border:1px solid ${z.surge_eligible ? '#fecaca' : '#e2e8f0'}; border-radius:12px; padding:18px; box-shadow:0 2px 10px rgba(0,0,0,0.04);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
              <strong style="font-size:13.5px; color:#0f172a;">${z.zone}</strong>
              ${z.surge_eligible ? `
                <span class="status-pill status-danger" style="font-size:10px; background:#fee2e2; color:#dc2626; font-weight:800; padding:3px 8px; border-radius:6px;">
                  +${z.surge_boost_pct}% SURGE ELIGIBLE
                </span>
              ` : `
                <span class="status-pill status-active" style="font-size:10px; background:#f0fdf4; color:#16a34a; font-weight:750; padding:3px 8px; border-radius:6px;">
                  BALANCED
                </span>
              `}
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#64748b; margin-bottom:8px;">
              <span>Predicted Shift Duties (Next 6h):</span>
              <strong style="color:#0f172a;">${z.predicted_duties}</strong>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#64748b; margin-bottom:12px;">
              <span>Active Idle Partner Vehicles:</span>
              <strong style="color:#0f172a;">${z.active_partner_idle_vehicles}</strong>
            </div>
            <div style="background:#f8fafc; border-radius:8px; padding:8px 12px; font-size:11px; color:#334155; font-weight:600;">
              Supply Deficit: <span style="color:#dc2626; font-weight:800;">${z.deficit} vehicles</span>. Pre-position your idle fleet here to earn surge multipliers.
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  renderFactoringPayoutsView() {
    return `
      <div style="background:var(--card-bg, #fff); border:1px solid var(--border-line, #e2e8f0); border-radius:12px; padding:20px;">
        <div style="margin-bottom:16px;">
          <h3 style="margin:0 0 4px; font-size:16px; font-weight:800; color:var(--text-primary, #0f172a);">⚡ T+0 Instant Factoring Clearinghouse</h3>
          <p style="margin:0; font-size:12px; color:var(--text-secondary, #64748b);">Cash out verified completed network duties immediately instead of waiting for Net-30/45 corporate payment cycles (Platform Fee: 1.75%).</p>
        </div>

        <table class="saas-table" style="width:100%; border-collapse:collapse; font-size:12px;">
          <thead>
            <tr style="border-bottom:1.5px solid #e2e8f0; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">
              <th style="padding:10px;">Duty Reference</th>
              <th style="padding:10px;">Gross Receivable</th>
              <th style="padding:10px;">Factoring Fee (1.75%)</th>
              <th style="padding:10px;">Instant Net Payout</th>
              <th style="padding:10px;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${this.state.factoringDues.map((f) => `
              <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:12px 10px;">
                  <strong style="color:#1e293b;">${f.duty_id}</strong>
                  <div style="font-size:10.5px; color:#64748b;">${f.route_label}</div>
                </td>
                <td style="padding:12px 10px; font-weight:750; color:#0f172a;">₹${this.decimalFormatter.format(f.gross_payable_inr).replace('₹', '')}</td>
                <td style="padding:12px 10px; color:#dc2626; font-weight:750;">-₹${this.decimalFormatter.format(f.platform_fee_inr).replace('₹', '')}</td>
                <td style="padding:12px 10px; font-weight:800; color:#15803d; font-size:13.5px;">₹${this.decimalFormatter.format(f.net_disbursement_inr).replace('₹', '')}</td>
                <td style="padding:12px 10px;">
                  <button data-action="instant-cashout" data-duty-id="${f.duty_id}" style="background:#16a34a; color:#fff; border:none; padding:8px 16px; border-radius:6px; font-size:11.5px; font-weight:800; cursor:pointer; box-shadow:0 4px 12px rgba(22,163,74,0.3);">
                    ⚡ Instant Cash-Out (T+0)
                  </button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderShadowModeView() {
    const shadowItems = this.state.shadowEvaluations || [
      { id: "shd_01", route: "Whitefield to BLR Airport T2", vendor_billed: 2850.0, axiom_audited: 2180.0, leakage: 670.0, reason: "Excess Deadhead KMs (18km claimed vs 6km actual GPS)" },
      { id: "shd_02", route: "Electronic City to Manyata Tech Park", vendor_billed: 1650.0, axiom_audited: 1290.0, leakage: 360.0, reason: "Inflated Waiting Time (45 min charged vs 12 min stopped)" },
      { id: "shd_03", route: "Koramangala to Outer Ring Road Bellandur", vendor_billed: 980.0, axiom_audited: 820.0, leakage: 160.0, reason: "Non-existent Toll Tagging (Double-counted toll plaza)" },
      { id: "shd_04", route: "Indiranagar to Kempegowda Bus Station", vendor_billed: 1150.0, axiom_audited: 920.0, leakage: 230.0, reason: "Standard Sedan billed under Premium SUV Tier" },
    ];
    const totalBilled = shadowItems.reduce((acc, it) => acc + it.vendor_billed, 0);
    const totalAudited = shadowItems.reduce((acc, it) => acc + it.axiom_audited, 0);
    const totalLeakage = shadowItems.reduce((acc, it) => acc + it.leakage, 0);
    const savingsPct = Math.round((totalLeakage / totalBilled) * 1000) / 10;

    return `
      <div style="background:#fff; border-radius:12px; border:1px solid #e2e8f0; padding:20px; box-shadow:0 4px 14px rgba(0,0,0,0.03);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <div>
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:18px;">🛡️</span>
              <h2 style="margin:0; font-size:16px; font-weight:800; color:#0f172a;">Shadow Evaluation Mode &bull; Zero-Disruption Vendor Audit</h2>
              <span style="font-size:10.5px; background:#dcfce7; color:#15803d; padding:3px 8px; border-radius:6px; font-weight:800;">
                ACTIVE &bull; 0% CONTRACT DISRUPTION
              </span>
            </div>
            <p style="margin:4px 0 0; font-size:12px; color:#64748b;">
              Audits existing contracted fleet vendor invoices side-by-side using Algorithmic GPS Trust telemetry without requiring immediate vendor migration.
            </p>
          </div>
          <button data-action="run-shadow-audit" style="background:#0f172a; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-size:12px; font-weight:750; cursor:pointer;">
            + Run Trip Audit
          </button>
        </div>

        <!-- 4-Pillar Summary Strip -->
        <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px;">
          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px 14px;">
            <div style="font-size:11px; color:#64748b; font-weight:600;">Audited External Billed</div>
            <div style="font-size:18px; font-weight:900; color:#0f172a; margin-top:4px;">₹${this.decimalFormatter.format(totalBilled).replace('₹', '')}</div>
          </div>
          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px 14px;">
            <div style="font-size:11px; color:#64748b; font-weight:600;">Axiom Algorithmic Cost</div>
            <div style="font-size:18px; font-weight:900; color:#2563eb; margin-top:4px;">₹${this.decimalFormatter.format(totalAudited).replace('₹', '')}</div>
          </div>
          <div style="background:#ecfdf5; border:1px solid #a7f3d0; border-radius:10px; padding:12px 14px;">
            <div style="font-size:11px; color:#047857; font-weight:600;">Billing Leakage Prevented</div>
            <div style="font-size:18px; font-weight:900; color:#059669; margin-top:4px;">₹${this.decimalFormatter.format(totalLeakage).replace('₹', '')} <span style="font-size:12px; font-weight:700;">(${savingsPct}%)</span></div>
          </div>
          <div style="background:#faf5ff; border:1px solid #e9d5ff; border-radius:10px; padding:12px 14px;">
            <div style="font-size:11px; color:#7e22ce; font-weight:600;">Corporate Migration Risk</div>
            <div style="font-size:18px; font-weight:900; color:#6b21a8; margin-top:4px;">0.0% <span style="font-size:11px; font-weight:700;">(Parallel Shadow)</span></div>
          </div>
        </div>

        <!-- Detail Table -->
        <table style="width:100%; border-collapse:collapse; font-size:12px;">
          <thead>
            <tr style="background:#f1f5f9; text-align:left; color:#475569; font-size:11px; font-weight:750; text-transform:uppercase; letter-spacing:0.04em;">
              <th style="padding:10px 12px; border-radius:6px 0 0 6px;">Trip / Route</th>
              <th style="padding:10px;">Contracted Vendor Billed</th>
              <th style="padding:10px;">Axiom Algorithmic Tariff</th>
              <th style="padding:10px;">Billing Leakage</th>
              <th style="padding:10px; border-radius:0 6px 6px 0;">Audit Anomaly Reason</th>
            </tr>
          </thead>
          <tbody>
            ${shadowItems.map(it => `
              <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:12px 10px; font-weight:700; color:#1e293b;">
                  <div>${it.route}</div>
                  <div style="font-size:10px; color:#64748b;">Audit ID: ${it.id} &bull; Cryptographically Verified</div>
                </td>
                <td style="padding:12px 10px; font-weight:700; color:#0f172a;">₹${this.decimalFormatter.format(it.vendor_billed).replace('₹', '')}</td>
                <td style="padding:12px 10px; font-weight:700; color:#2563eb;">₹${this.decimalFormatter.format(it.axiom_audited).replace('₹', '')}</td>
                <td style="padding:12px 10px; font-weight:800; color:#15803d;">₹${this.decimalFormatter.format(it.leakage).replace('₹', '')}</td>
                <td style="padding:12px 10px; color:#b45309; font-size:11.5px; font-weight:600;">${it.reason}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  renderSurgeSliderModal() {
    const l = this.state.surgeModalListing;
    if (!l) return "";

    const boostPct = this.state.surgeSliderValue;
    const basePayout = l.supplier_payout_inr || 1950.0;
    const boostedPayout = basePayout * (1 + (boostPct / 100.0));
    const clientRec = 2500.0; // Benchmark client receivable
    const netMargin = clientRec - boostedPayout;
    const netMarginPct = Math.round((netMargin / clientRec) * 1000) / 10;
    const isFloorBreached = netMarginPct < 12.0;

    return `
      <div class="surge-modal-backdrop" style="position:fixed; inset:0; background:rgba(15,23,42,0.8); z-index:99999; display:flex; align-items:center; justify-content:center; backdrop-filter:blur(4px); padding:20px;">
        <div style="background:#fff; border-radius:16px; padding:28px; max-width:480px; width:100%; box-shadow:0 24px 60px rgba(0,0,0,0.4); border:1px solid #e2e8f0;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <h3 style="margin:0; font-size:17px; font-weight:800; color:#0f172a;">⚡ Smart Clearing Surge Slider</h3>
            <button data-action="close-surge-modal" style="background:none; border:none; font-size:20px; cursor:pointer; color:#94a3b8;">&times;</button>
          </div>
          <p style="font-size:12px; color:#64748b; margin:0 0 16px; line-height:1.5;">
            Accelerate partner acceptance by applying a spot surge payout boost with real-time Margin-Floor Guardrail enforcement.
          </p>

          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:12px;">
              <span>Base Supplier Payout:</span>
              <strong>₹${this.decimalFormatter.format(basePayout).replace('₹', '')}</strong>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:12px;">
              <span>Boost Multiplier:</span>
              <strong style="color:#2563eb;">+${boostPct}%</strong>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:13.5px; border-top:1px solid #e2e8f0; padding-top:6px;">
              <span>New Supplier Payout:</span>
              <strong style="color:#0f172a;">₹${this.decimalFormatter.format(boostedPayout).replace('₹', '')}</strong>
            </div>
          </div>

          <!-- Slider Input -->
          <div style="margin-bottom:18px;">
            <label style="display:flex; justify-content:space-between; font-size:11.5px; font-weight:750; color:#475569; margin-bottom:6px;">
              <span>Surge Payout Boost</span>
              <span>+${boostPct}%</span>
            </label>
            <input type="range" id="surge-slider-input" min="0" max="30" step="5" value="${boostPct}" style="width:100%; cursor:pointer;" />
          </div>

          <!-- Margin Guardrail Indicator -->
          <div style="background:${isFloorBreached ? '#fef2f2' : '#f0fdf4'}; border:1px solid ${isFloorBreached ? '#fecaca' : '#bbf7d0'}; border-radius:10px; padding:12px; margin-bottom:20px; font-size:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:750; color:${isFloorBreached ? '#b91c1c' : '#15803d'};">
                ${isFloorBreached ? '⚠️ Margin Floor Breached (< 12%)' : '✓ Margin Safe (Floor >= 12%)'}
              </span>
              <strong style="color:${isFloorBreached ? '#b91c1c' : '#15803d'};">${netMarginPct}% Net Margin</strong>
            </div>
          </div>

          <div style="display:flex; gap:10px; justify-content:flex-end;">
            <button data-action="close-surge-modal" style="background:#f1f5f9; color:#475569; border:none; padding:8px 16px; border-radius:8px; font-size:12px; font-weight:750; cursor:pointer;">
              Cancel
            </button>
            <button data-action="apply-surge-boost" data-listing-id="${l.id}" style="background:${isFloorBreached ? '#dc2626' : '#2563eb'}; color:#fff; border:none; padding:8px 18px; border-radius:8px; font-size:12px; font-weight:800; cursor:pointer;">
              Apply +${boostPct}% Surge
            </button>
          </div>
        </div>
      </div>
    `;
  }

  bindEvents() {
    if (!this.container) return;
    const signal = this.abortController.signal;

    this.container.addEventListener("click", async (e) => {
      const target = e.target;
      if (!target) return;

      // 1. Tab Navigation
      const tabBtn = target.closest("[data-view-tab]");
      if (tabBtn) {
        this.state.activeTab = tabBtn.dataset.viewTab;
        this.render();
        return;
      }

      // 2. Claim Listing
      const claimBtn = target.closest("[data-action='claim-listing']");
      if (claimBtn) {
        const lid = claimBtn.dataset.listingId;
        await this.handleClaimListing(lid);
        return;
      }

      // 3. Open Surge Modal
      const surgeBtn = target.closest("[data-action='open-surge-slider']");
      if (surgeBtn) {
        const lid = surgeBtn.dataset.listingId;
        const listing = this.state.listings.find((x) => x.id === lid);
        if (listing) {
          this.state.surgeModalListing = listing;
          this.render();
        }
        return;
      }

      // 4. Close Surge Modal
      if (target.closest("[data-action='close-surge-modal']")) {
        this.state.surgeModalListing = null;
        this.render();
        return;
      }

      // 5. Apply Surge Boost
      const applySurgeBtn = target.closest("[data-action='apply-surge-boost']");
      if (applySurgeBtn) {
        const lid = applySurgeBtn.dataset.listingId;
        await this.handleApplySurgeBoost(lid, this.state.surgeSliderValue);
        return;
      }

      // 6. Instant T+0 Cash-Out
      const cashoutBtn = target.closest("[data-action='instant-cashout']");
      if (cashoutBtn) {
        const did = cashoutBtn.dataset.dutyId;
        await this.handleInstantCashout(did);
        return;
      }

      // 7. Prompt Modals
      if (target.closest("[data-action='broadcast-trip-prompt']")) {
        alert("Broadcast Overflow Trip:\nSelect any unallotted duty from your command roster to farm out with pre-authorized escrow.");
        return;
      }

      if (target.closest("[data-action='publish-empty-leg-prompt']")) {
        alert("Publish Empty-Leg Deadhead:\nSelect returning outstation vehicle to list on partner corridor with 25%–40% discount.");
        return;
      }
    }, { signal });

    // Slider input change delegation
    this.container.addEventListener("input", (e) => {
      if (e.target && e.target.id === "surge-slider-input") {
        this.state.surgeSliderValue = parseFloat(e.target.value);
        this.render();
      }
    }, { signal });
  }

  async handleClaimListing(listingId) {
    if (this.inFlightRequests.has(`claim_${listingId}`)) return;
    this.inFlightRequests.add(`claim_${listingId}`);

    try {
      const res = await fetch(`/api/v1/network/exchange/${listingId}/claim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Success! Duty claimed on Partner Exchange. ${data.message}`);
        this.state.listings = this.state.listings.filter((l) => l.id !== listingId);
        this.render();
      } else {
        alert(`Claim rejected: ${data.message || data.error || 'Server error'}`);
      }
    } catch (err) {
      console.warn("Claim error:", err);
      alert("Network error claiming duty.");
    } finally {
      this.inFlightRequests.delete(`claim_${listingId}`);
    }
  }

  async handleApplySurgeBoost(listingId, boostPct) {
    try {
      const res = await fetch(`/api/v1/network/exchange/${listingId}/boost-surge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ boost_pct: boostPct }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Surge boost applied! New Supplier Payout: ₹${data.boosted_supplier_payable_inr}`);
        this.state.surgeModalListing = null;
        this.render();
      } else {
        alert(`Surge boost rejected: ${data.message || data.error || 'Margin floor breached'}`);
      }
    } catch (err) {
      console.warn("Surge boost error:", err);
      alert("Network error applying surge boost.");
    }
  }

  async handleInstantCashout(dutyId) {
    try {
      const res = await fetch("/api/v1/network/factoring/instant-cashout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duty_id: dutyId }),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Instant T+0 Cash-Out Complete!\nGross: ₹${data.gross_payable_inr}\nFactoring Fee (1.75%): ₹${data.platform_factoring_fee_inr}\nDisbursed to Wallet: ₹${data.instant_net_disbursement_inr}`);
        this.state.factoringDues = this.state.factoringDues.filter((f) => f.duty_id !== dutyId);
        this.render();
      } else {
        alert(`Cash-out failed: ${data.message || data.error || 'Server error'}`);
      }
    } catch (err) {
      console.warn("Cash-out error:", err);
      alert("Network error processing instant factoring.");
    }
  }
}
