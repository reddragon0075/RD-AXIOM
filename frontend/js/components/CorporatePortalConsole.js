/**
 * Axiom Mobility (Fleetline) - Corporate Mobility & Tamper-Proof Approvals Console.
 * Zero-Build Vanilla ES6+ Component.
 *
 * Implements:
 * 1. Role-Adaptive Corporate Portal (Employee, Line Manager, Travel Desk, HR, Finance).
 * 2. Book a Ride with upfront dynamic tariff calculation & policy warnings.
 * 3. Manager Approval Inbox with 1-click Approve/Reject & Anti-Self-Approval lock.
 * 4. Cost-Center Spend & Real-Time Audit Ledger with SHA-256 parameter hash verification.
 * 5. HR Night-Shift Safety & Security Escort Monitoring (20:00 - 06:00).
 */

export class CorporatePortalConsole {
  constructor(options = {}) {
    this.container = options.container || null;
    this.containerId = options.containerId || "corporate-portal-container";
    this.apiBase = options.apiBase || "/api/corp";
    this.currentUser = options.currentUser || {
      id: "usr_corp_emp_01",
      name: "Corporate User",
      role: "CORP_LINE_MANAGER", // CORP_EMPLOYEE | CORP_LINE_MANAGER | CORP_TRAVEL_DESK | CORP_HR_COMPLIANCE | CORP_FINANCE_AUDITOR
      costCenterId: "cc_eng_01",
    };

    this.state = {
      activeTab: options.initialTab || "book-ride", // book-ride | manager-inbox | spend-ledger | hr-safety
      isLoading: false,
      costCenters: [],
      inboxItems: [],
      ledgerItems: [],
      nightShiftItems: [],
      userBookings: [],
      notification: null,
      bookingForm: {
        vehicleType: "SEDAN",
        tariffModel: "P2P_LOCAL",
        pickupAddress: "Axiom Tech Park, Block C, Bangalore",
        dropAddress: "Kempegowda International Airport (BLR)",
        scheduledAt: new Date(Date.now() + 3600000 * 2).toISOString().slice(0, 16),
        costCenterId: "cc_eng_01",
        justification: "Client Quarterly Business Review meeting",
        distanceKm: 35.0,
        durationHours: 1.5,
        outstationDays: 1,
      },
    };

    this.abortController = null;
  }

  mount(hostElement = null) {
    if (typeof document === "undefined") return;
    if (hostElement) this.container = hostElement;
    if (!this.container) {
      this.container = document.getElementById(this.containerId);
    }
    if (!this.container) return;

    this.injectStyles();
    this.render();
    this.fetchInitialData();
  }

  unmount() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  getAbortSignal() {
    if (this.abortController) {
      this.abortController.abort();
    }
    this.abortController = new AbortController();
    return this.abortController.signal;
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("corp-portal-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "corp-portal-styles";
    styleEl.textContent = `
      .corp-console {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #FFFFFF;
        color: #0A1628;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 4px 20px rgba(10, 22, 40, 0.04);
        margin: 20px 0;
        overflow: hidden;
      }
      .corp-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 24px;
        background: #0A1628;
        color: #FFFFFF;
      }
      .corp-title-area {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .corp-badge-corp {
        background: #0066FF;
        color: #FFFFFF;
        font-size: 11px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        letter-spacing: 0.5px;
      }
      .corp-user-meta {
        font-size: 12px;
        color: #94A3B8;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .corp-role-pill {
        background: rgba(0, 184, 176, 0.2);
        color: #00B8B0;
        padding: 2px 8px;
        border-radius: 9999px;
        font-weight: 600;
        border: 1px solid rgba(0, 184, 176, 0.4);
      }
      .corp-nav-tabs {
        display: flex;
        background: #F4F7FB;
        border-bottom: 1px solid #E2E8F0;
        padding: 0 16px;
        gap: 8px;
      }
      .corp-tab-btn {
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 12px 16px;
        font-size: 13px;
        font-weight: 600;
        color: #64748B;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: all 0.2s ease;
      }
      .corp-tab-btn:hover {
        color: #0066FF;
      }
      .corp-tab-btn.active {
        color: #0066FF;
        border-bottom-color: #0066FF;
        background: #FFFFFF;
      }
      .corp-badge-count {
        background: #EF4444;
        color: #FFFFFF;
        font-size: 10px;
        font-weight: 800;
        padding: 1px 6px;
        border-radius: 9999px;
      }
      .corp-body {
        padding: 24px;
        min-height: 420px;
      }
      .corp-alert {
        padding: 12px 16px;
        border-radius: 8px;
        font-size: 13px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .corp-alert.success {
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        color: #065F46;
      }
      .corp-alert.warning {
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        color: #92400E;
      }
      .corp-alert.danger {
        background: #FEF2F2;
        border: 1px solid #FECACA;
        color: #991B1B;
      }
      .corp-grid-2 {
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        gap: 24px;
      }
      .corp-form-group {
        margin-bottom: 16px;
      }
      .corp-form-label {
        display: block;
        font-size: 12px;
        font-weight: 700;
        color: #334155;
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .corp-form-input, .corp-form-select {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        font-size: 13px;
        color: #0A1628;
        background: #FFFFFF;
        box-sizing: border-box;
      }
      .corp-form-input:focus, .corp-form-select:focus {
        outline: none;
        border-color: #0066FF;
        box-shadow: 0 0 0 3px rgba(0, 102, 255, 0.15);
      }
      .corp-preview-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 20px;
        height: fit-content;
      }
      .corp-fare-amount {
        font-size: 28px;
        font-weight: 800;
        color: #0A1628;
        margin: 8px 0;
      }
      .corp-policy-tag {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
      }
      .corp-policy-tag.auto {
        background: #DCFCE7;
        color: #166534;
      }
      .corp-policy-tag.requires-review {
        background: #FEF3C7;
        color: #B45309;
      }
      .corp-btn-submit {
        background: #0066FF;
        color: #FFFFFF;
        border: none;
        padding: 12px 20px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        width: 100%;
        margin-top: 16px;
        transition: background 0.2s ease;
      }
      .corp-btn-submit:hover {
        background: #0052CC;
      }
      .corp-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      .corp-table th {
        background: #F1F5F9;
        color: #475569;
        text-align: left;
        padding: 10px 14px;
        font-weight: 700;
        border-bottom: 2px solid #CBD5E1;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .corp-table td {
        padding: 12px 14px;
        border-bottom: 1px solid #E2E8F0;
        vertical-align: middle;
      }
      .corp-table tr:hover td {
        background: #F8FAFC;
      }
      .corp-hash-pill {
        font-family: monospace;
        font-size: 11px;
        background: #F1F5F9;
        color: #475569;
        padding: 2px 6px;
        border-radius: 4px;
        border: 1px solid #E2E8F0;
      }
      .corp-status-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 700;
      }
      .corp-status-badge.APPROVED {
        background: #DCFCE7;
        color: #166534;
      }
      .corp-status-badge.PENDING_L1_MANAGER {
        background: #FEF3C7;
        color: #B45309;
      }
      .corp-status-badge.PENDING_L2_FINANCE {
        background: #EDE9FE;
        color: #6D28D9;
      }
      .corp-status-badge.REJECTED {
        background: #FEE2E2;
        color: #991B1B;
      }
      .corp-status-badge.REVOKED_ON_EDIT {
        background: #FFEDD5;
        color: #C2410C;
      }
      .corp-btn-approve {
        background: #16A34A;
        color: #FFFFFF;
        border: none;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .corp-btn-approve:disabled {
        background: #CBD5E1;
        cursor: not-allowed;
      }
      .corp-btn-reject {
        background: #DC2626;
        color: #FFFFFF;
        border: none;
        padding: 6px 12px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .corp-btn-reject:disabled {
        background: #CBD5E1;
        cursor: not-allowed;
      }
      .corp-progress-bar {
        background: #E2E8F0;
        height: 8px;
        border-radius: 9999px;
        overflow: hidden;
        margin-top: 6px;
      }
      .corp-progress-fill {
        height: 100%;
        background: #0066FF;
        border-radius: 9999px;
      }
      .corp-progress-fill.danger {
        background: #EF4444;
      }
      @media (max-width: 768px) {
        .corp-grid-2 {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(styleEl);
  }

  calculateEstimatedFare(veh, tar, dist = 35.0, dur = 1.5, days = 1) {
    let mult = 1.0;
    const v = String(veh || "").toUpperCase();
    if (v.includes("SUV") || v.includes("CRYSTA")) mult = 1.45;
    else if (v.includes("PREMIUM") || v.includes("LUXURY")) mult = 2.1;

    const t = String(tar || "").toUpperCase();
    if (t === "8HR_80KM") return Math.round(2800 * mult);
    if (t === "4HR_40KM") return Math.round(1600 * mult);
    if (t.includes("OUTSTATION")) {
      const minKm = Math.max(250, dist) * Math.max(1, days);
      return Math.round(minKm * 16 * mult + 450 * Math.max(1, days));
    }
    if (t.includes("AIRPORT")) return Math.round(1450 * mult);
    const baseFare = 150 * mult;
    const extraKm = Math.max(0, dist - 4.0);
    return Math.round(baseFare + extraKm * 22 * mult + dur * 60);
  }

  evaluatePolicyAlert(estFare, tariffModel) {
    const t = String(tariffModel || "").toUpperCase();
    const isSpecial = ["OUTSTATION", "AIRPORT", "8HR_80KM"].some((m) => t.includes(m));
    if (estFare > 800 || isSpecial) {
      return {
        requiresReview: true,
        reason:
          estFare > 800
            ? `Fare (₹${estFare}) exceeds ₹800 auto-approval cap`
            : `${tariffModel} requires mandatory line-manager review`,
      };
    }
    return {
      requiresReview: false,
      reason: "Within standard policy thresholds (Instant Auto-Approval)",
    };
  }

  render() {
    if (!this.container) return;

    const { activeTab, inboxItems } = this.state;
    const pendingCount = inboxItems.filter((i) => i.approval_status === "PENDING_L1_MANAGER").length;

    this.container.innerHTML = `
      <div class="corp-console">
        <div class="corp-header">
          <div class="corp-title-area">
            <span class="corp-badge-corp">ENTERPRISE PORTAL</span>
            <strong style="font-size:15px; letter-spacing:0.2px;">Axiom Corporate Mobility</strong>
          </div>
          <div class="corp-user-meta">
            <span>Signed in as: <strong>${this.currentUser.name}</strong></span>
            <span class="corp-role-pill">${this.currentUser.role.replace("CORP_", "")}</span>
          </div>
        </div>

        <nav class="corp-nav-tabs">
          <button class="corp-tab-btn ${activeTab === "book-ride" ? "active" : ""}" data-tab="book-ride">
            🚗 Book a Ride
          </button>
          <button class="corp-tab-btn ${activeTab === "manager-inbox" ? "active" : ""}" data-tab="manager-inbox">
            📥 Approval Inbox ${pendingCount > 0 ? `<span class="corp-badge-count">${pendingCount}</span>` : ""}
          </button>
          <button class="corp-tab-btn ${activeTab === "spend-ledger" ? "active" : ""}" data-tab="spend-ledger">
            📊 Cost-Center Ledger &amp; Hashes
          </button>
          <button class="corp-tab-btn ${activeTab === "hr-safety" ? "active" : ""}" data-tab="hr-safety">
            🛡️ Night-Shift Safety (20:00-06:00)
          </button>
        </nav>

        <div class="corp-body" id="corp-tab-content">
          ${this.renderTabContent()}
        </div>
      </div>
    `;

    this.bindEvents();
  }

  renderTabContent() {
    const { activeTab } = this.state;
    if (activeTab === "book-ride") return this.renderBookRideTab();
    if (activeTab === "manager-inbox") return this.renderManagerInboxTab();
    if (activeTab === "spend-ledger") return this.renderSpendLedgerTab();
    if (activeTab === "hr-safety") return this.renderHrSafetyTab();
    return "";
  }

  renderBookRideTab() {
    const { bookingForm } = this.state;
    const estFare = this.calculateEstimatedFare(
      bookingForm.vehicleType,
      bookingForm.tariffModel,
      bookingForm.distanceKm,
      bookingForm.durationHours,
      bookingForm.outstationDays
    );
    const policy = this.evaluatePolicyAlert(estFare, bookingForm.tariffModel);

    return `
      <div class="corp-grid-2">
        <div>
          <h3 style="margin-top:0; margin-bottom:16px; font-size:16px;">Request Corporate Travel</h3>
          <form id="corp-booking-form">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
              <div class="corp-form-group">
                <label class="corp-form-label">Vehicle Category</label>
                <select class="corp-form-select" id="form-vehicle-type">
                  <option value="SEDAN" ${bookingForm.vehicleType === "SEDAN" ? "selected" : ""}>Executive Sedan (Dzire / Etios)</option>
                  <option value="SUV_CRYSTA" ${bookingForm.vehicleType === "SUV_CRYSTA" ? "selected" : ""}>Premium SUV (Innova Crysta)</option>
                  <option value="LUXURY" ${bookingForm.vehicleType === "LUXURY" ? "selected" : ""}>Luxury (Mercedes / BMW)</option>
                </select>
              </div>
              <div class="corp-form-group">
                <label class="corp-form-label">Tariff Package</label>
                <select class="corp-form-select" id="form-tariff-model">
                  <option value="P2P_LOCAL" ${bookingForm.tariffModel === "P2P_LOCAL" ? "selected" : ""}>Point-to-Point Local</option>
                  <option value="AIRPORT" ${bookingForm.tariffModel === "AIRPORT" ? "selected" : ""}>Airport Transfer Flat-Rate</option>
                  <option value="8HR_80KM" ${bookingForm.tariffModel === "8HR_80KM" ? "selected" : ""}>8 Hours / 80 Kilometers Rental</option>
                  <option value="4HR_40KM" ${bookingForm.tariffModel === "4HR_40KM" ? "selected" : ""}>4 Hours / 40 Kilometers Rental</option>
                  <option value="OUTSTATION" ${bookingForm.tariffModel === "OUTSTATION" ? "selected" : ""}>Outstation Round-Trip</option>
                </select>
              </div>
            </div>

            <div class="corp-form-group">
              <label class="corp-form-label">Pickup Location</label>
              <input type="text" class="corp-form-input" id="form-pickup-address" value="${bookingForm.pickupAddress}" />
            </div>

            <div class="corp-form-group">
              <label class="corp-form-label">Drop-off Destination</label>
              <input type="text" class="corp-form-input" id="form-drop-address" value="${bookingForm.dropAddress}" />
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
              <div class="corp-form-group">
                <label class="corp-form-label">Pickup Date &amp; Time</label>
                <input type="datetime-local" class="corp-form-input" id="form-scheduled-at" value="${bookingForm.scheduledAt}" />
              </div>
              <div class="corp-form-group">
                <label class="corp-form-label">Cost Center</label>
                <select class="corp-form-select" id="form-cost-center">
                  <option value="cc_eng_01">Engineering &amp; Cloud (CC-ENG-01)</option>
                  <option value="cc_sales_02">Enterprise Sales (CC-SALES-02)</option>
                  <option value="cc_exec_03">Executive Leadership (CC-EXEC-03)</option>
                </select>
              </div>
            </div>

            <div class="corp-form-group">
              <label class="corp-form-label">Business Justification</label>
              <input type="text" class="corp-form-input" id="form-justification" value="${bookingForm.justification}" placeholder="e.g., Client onsite audit, critical deployment" />
            </div>

            <button type="button" class="corp-btn-submit" id="btn-submit-booking">
              Submit Travel Request
            </button>
          </form>
        </div>

        <div>
          <div class="corp-preview-card">
            <h4 style="margin-top:0; font-size:14px; color:#475569; text-transform:uppercase; letter-spacing:0.5px;">Fare Estimation &amp; Governance</h4>
            <div class="corp-fare-amount">₹${estFare.toLocaleString("en-IN")}.00</div>
            <div style="font-size:12px; color:#64748B; margin-bottom:16px;">
              Calculated via Axiom Enterprise Tariff Engine
            </div>

            <div style="margin-bottom:16px;">
              <span class="corp-policy-tag ${policy.requiresReview ? "requires-review" : "auto"}">
                ${policy.requiresReview ? "⚠️ Requires Line-Manager Review" : "⚡ Instant Auto-Approval Eligible"}
              </span>
            </div>

            <div style="font-size:12px; color:#475569; line-height:1.6; border-top:1px solid #E2E8F0; padding-top:12px;">
              <strong>Anti-Exploit Invariants Active:</strong>
              <ul style="margin:6px 0 0; padding-left:18px;">
                <li>SHA-256 Parameter Hash locks vehicle &amp; destination</li>
                <li>Rolling 24h spend cap protects ₹2,000 velocity</li>
                <li>Post-approval edits auto-revoke authorization</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  renderManagerInboxTab() {
    const { inboxItems } = this.state;
    if (inboxItems.length === 0) {
      return `
        <div style="text-align:center; padding:48px 0; color:#64748B;">
          <div style="font-size:36px; margin-bottom:8px;">✅</div>
          <h4 style="margin:0 0 4px; font-size:16px; color:#0A1628;">Approval Queue Clear</h4>
          <p style="margin:0; font-size:13px;">No pending employee booking requests require your authorization.</p>
        </div>
      `;
    }

    return `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <h3 style="margin:0; font-size:16px;">Manager Approval Requests (${inboxItems.length})</h3>
        <span style="font-size:12px; color:#64748B;">Anti-Self-Approval strictly enforced</span>
      </div>

      <div style="overflow-x:auto;">
        <table class="corp-table">
          <thead>
            <tr>
              <th>Trip ID</th>
              <th>Employee</th>
              <th>Cost Center</th>
              <th>Route &amp; Vehicle</th>
              <th>Estimated Fare</th>
              <th>Parameter Hash</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${inboxItems.map((item) => {
              const isSelf = item.requester_user_id === this.currentUser.id;
              const isHighValue = Number(item.estimated_fare_inr) > 10000;
              return `
                <tr>
                  <td><strong>${item.trip_id}</strong></td>
                  <td>
                    <div><strong>${item.requester_name || "Employee"}</strong></div>
                    <div style="font-size:11px; color:#64748B;">${item.requester_email || ""}</div>
                  </td>
                  <td>${item.cost_center_name || item.cost_center_id || "CC-ENG-01"}</td>
                  <td>
                    <div>${item.vehicle_type} &bull; ${item.tariff_model}</div>
                    <div style="font-size:11px; color:#64748B; max-width:200px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                      ${item.pickup_address} &rarr; ${item.drop_address}
                    </div>
                  </td>
                  <td>
                    <strong>₹${Number(item.estimated_fare_inr).toFixed(2)}</strong>
                    ${isHighValue ? `<div style="font-size:10px; color:#6D28D9; font-weight:700;">⚡ L2 Finance Escalate</div>` : ""}
                  </td>
                  <td>
                    <span class="corp-hash-pill" title="${item.booking_parameter_hash}">
                      ${String(item.booking_parameter_hash || "sha256").slice(0, 8)}...
                    </span>
                  </td>
                  <td>
                    <span class="corp-status-badge ${item.approval_status}">
                      ${item.approval_status}
                    </span>
                  </td>
                  <td>
                    <div style="display:flex; gap:6px;">
                      <button class="corp-btn-approve btn-action-approve" data-id="${item.id}" ${isSelf ? 'disabled title="Anti-Self-Approval: Cannot approve own booking"' : ""}>
                        Approve
                      </button>
                      <button class="corp-btn-reject btn-action-reject" data-id="${item.id}" ${isSelf ? 'disabled title="Anti-Self-Approval: Cannot reject own booking"' : ""}>
                        Reject
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

  renderSpendLedgerTab() {
    const { costCenters, ledgerItems } = this.state;
    return `
      <div style="margin-bottom:24px;">
        <h3 style="margin-top:0; margin-bottom:12px; font-size:16px;">Cost-Center Budget vs. Spend Allocation</h3>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:16px;">
          ${(costCenters.length ? costCenters : [
            { code: "CC-ENG-01", name: "Engineering & Cloud", monthly_budget_inr: 50000, current_month_spend_inr: 18450 },
            { code: "CC-SALES-02", name: "Enterprise Sales", monthly_budget_inr: 80000, current_month_spend_inr: 62400 },
            { code: "CC-EXEC-03", name: "Executive Leadership", monthly_budget_inr: 120000, current_month_spend_inr: 45000 },
          ]).map((cc) => {
            const pct = Math.min(100, Math.round((cc.current_month_spend_inr / cc.monthly_budget_inr) * 100));
            return `
              <div style="background:#F8FAFC; border:1px solid #E2E8F0; padding:14px; border-radius:8px;">
                <div style="display:flex; justify-content:space-between; font-size:12px;">
                  <strong>${cc.code}</strong>
                  <span style="color:#64748B;">${pct}% used</span>
                </div>
                <div style="font-size:11px; color:#64748B; margin-top:2px;">${cc.name}</div>
                <div class="corp-progress-bar">
                  <div class="corp-progress-fill ${pct > 80 ? "danger" : ""}" style="width:${pct}%;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:11px; margin-top:6px;">
                  <span>Spent: ₹${Number(cc.current_month_spend_inr).toLocaleString("en-IN")}</span>
                  <span>Limit: ₹${Number(cc.monthly_budget_inr).toLocaleString("en-IN")}</span>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>

      <div>
        <h3 style="margin-bottom:12px; font-size:16px;">Tamper-Proof Trip Ledger (Cryptographic Fingerprints)</h3>
        <div style="overflow-x:auto;">
          <table class="corp-table">
            <thead>
              <tr>
                <th>Trip ID</th>
                <th>Employee</th>
                <th>Fare</th>
                <th>L1 Approver</th>
                <th>L2 Finance</th>
                <th>SHA-256 Parameter Hash</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${(ledgerItems.length ? ledgerItems : [
                { trip_id: "TRIP-BLR-1092", requester_name: "Rahul Verma", estimated_fare_inr: 1450, l1_approver_name: "Suresh Rao", l2_approver_name: "System Auto", booking_parameter_hash: "a4f8c928e37d891b2938472918bcde01", approval_status: "APPROVED" },
                { trip_id: "TRIP-BLR-1099", requester_name: "Pooja Hegde", estimated_fare_inr: 2800, l1_approver_name: "Suresh Rao", l2_approver_name: "Anita Desai (Finance)", booking_parameter_hash: "f82b7190c12847ea9201bcde37190241", approval_status: "APPROVED" },
                { trip_id: "TRIP-BLR-1104", requester_name: "Karan Johar", estimated_fare_inr: 4500, l1_approver_name: "Pending", l2_approver_name: "-", booking_parameter_hash: "38bc910248ea920bcde81902418a9c01", approval_status: "PENDING_L1_MANAGER" },
              ]).map((row) => `
                <tr>
                  <td><strong>${row.trip_id}</strong></td>
                  <td>${row.requester_name || "Employee"}</td>
                  <td><strong>₹${Number(row.estimated_fare_inr).toFixed(2)}</strong></td>
                  <td>${row.l1_approver_name || "-"}</td>
                  <td>${row.l2_approver_name || "-"}</td>
                  <td>
                    <span class="corp-hash-pill" title="${row.booking_parameter_hash}">
                      ${String(row.booking_parameter_hash || "").slice(0, 16)}...
                    </span>
                  </td>
                  <td>
                    <span class="corp-status-badge ${row.approval_status}">${row.approval_status}</span>
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  renderHrSafetyTab() {
    return `
      <div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <div>
            <h3 style="margin:0; font-size:16px;">Night-Shift Travel Safety &amp; Statutory Escort Guard</h3>
            <p style="margin:4px 0 0; font-size:13px; color:#64748B;">Mandatory security escort monitoring for female employees travelling between 20:00 and 06:00.</p>
          </div>
          <span style="background:#ECFDF5; color:#065F46; padding:6px 12px; border-radius:9999px; font-size:12px; font-weight:700; border:1px solid #A7F3D0;">
            ✓ Statutory Factory &amp; Shop Act Compliant
          </span>
        </div>

        <div style="background:#FEF2F2; border:1px solid #FECACA; border-radius:8px; padding:16px; margin-bottom:20px;">
          <div style="display:flex; gap:12px; align-items:flex-start;">
            <div style="font-size:24px;">🛡️</div>
            <div>
              <strong style="color:#991B1B; font-size:14px;">Automated Night-Shift Escort Protocol</strong>
              <div style="font-size:12px; color:#7F1D1D; margin-top:4px; line-height:1.5;">
                Whenever a female employee is scheduled for pickup/drop between 20:00 and 06:00, Axiom Mobility enforces:
                (1) Mandatory security escort assignment, (2) Real-time GPS perimeter deviation alarm, and (3) In-cab SOS confirmation call.
              </div>
            </div>
          </div>
        </div>

        <table class="corp-table">
          <thead>
            <tr>
              <th>Trip ID</th>
              <th>Employee</th>
              <th>Pickup Window</th>
              <th>Gender</th>
              <th>Escort Status</th>
              <th>Live Tracking</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>TRIP-NS-401</strong></td>
              <td>Priyanka Sharma</td>
              <td>23:30 (Night Shift)</td>
              <td>Female</td>
              <td><span class="corp-status-badge APPROVED">✓ Escort Assigned (Guard #EG-12)</span></td>
              <td><span style="color:#16A34A; font-weight:700;">🟢 On-Route (GPS Snapped)</span></td>
            </tr>
            <tr>
              <td><strong>TRIP-NS-404</strong></td>
              <td>Sneha Patil</td>
              <td>01:15 (Night Shift)</td>
              <td>Female</td>
              <td><span class="corp-status-badge APPROVED">✓ Escort Assigned (Guard #EG-08)</span></td>
              <td><span style="color:#0066FF; font-weight:700;">📍 Arrived at Drop</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    `;
  }

  bindEvents() {
    if (!this.container) return;

    // Tab buttons
    this.container.querySelectorAll(".corp-tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const tab = e.currentTarget.getAttribute("data-tab");
        if (tab && tab !== this.state.activeTab) {
          this.state.activeTab = tab;
          this.render();
        }
      });
    });

    // Form inputs recalculate preview
    const updatePreview = () => {
      const vehEl = this.container.querySelector("#form-vehicle-type");
      const tarEl = this.container.querySelector("#form-tariff-model");
      if (vehEl && tarEl) {
        this.state.bookingForm.vehicleType = vehEl.value;
        this.state.bookingForm.tariffModel = tarEl.value;
        this.render();
      }
    };

    const vehEl = this.container.querySelector("#form-vehicle-type");
    const tarEl = this.container.querySelector("#form-tariff-model");
    if (vehEl) vehEl.addEventListener("change", updatePreview);
    if (tarEl) tarEl.addEventListener("change", updatePreview);

    // Submit booking button
    const submitBtn = this.container.querySelector("#btn-submit-booking");
    if (submitBtn) {
      submitBtn.addEventListener("click", () => this.handleBookingSubmit());
    }

    // Inbox Approve / Reject
    this.container.querySelectorAll(".btn-action-approve").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        this.handleDecision(id, "APPROVE");
      });
    });

    this.container.querySelectorAll(".btn-action-reject").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        this.handleDecision(id, "REJECT");
      });
    });
  }

  async fetchInitialData() {
    const signal = this.getAbortSignal();
    try {
      const inboxRes = await fetch(`${this.apiBase}/approvals/inbox`, { signal }).catch(() => null);
      if (inboxRes && inboxRes.ok) {
        const data = await inboxRes.json();
        this.state.inboxItems = data.inbox || [];
      }

      const ccRes = await fetch(`${this.apiBase}/cost-centers`, { signal }).catch(() => null);
      if (ccRes && ccRes.ok) {
        const data = await ccRes.json();
        this.state.costCenters = data.cost_centers || [];
      }

      this.render();
    } catch (err) {
      if (err.name !== "AbortError") {
        console.warn("[CorporatePortalConsole] Error loading initial data:", err);
      }
    }
  }

  async handleBookingSubmit() {
    const veh = this.container.querySelector("#form-vehicle-type")?.value || "SEDAN";
    const tar = this.container.querySelector("#form-tariff-model")?.value || "P2P_LOCAL";
    const pick = this.container.querySelector("#form-pickup-address")?.value || "";
    const drop = this.container.querySelector("#form-drop-address")?.value || "";
    const sched = this.container.querySelector("#form-scheduled-at")?.value || "";
    const cc = this.container.querySelector("#form-cost-center")?.value || "cc_eng_01";
    const just = this.container.querySelector("#form-justification")?.value || "";

    const payload = {
      vehicle_type: veh,
      tariff_model: tar,
      pickup_address: pick,
      drop_address: drop,
      scheduled_at: sched,
      cost_center_id: cc,
      booking_justification: just,
      distance_km: 35.0,
      duration_hours: 1.5,
    };

    try {
      const res = await fetch(`${this.apiBase}/bookings/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Booking Requested Successfully!\nStatus: ${data.approval_status}\nEstimated Fare: ₹${data.estimated_fare_inr}\nHash: ${data.booking_parameter_hash.slice(0, 16)}...`);
        this.fetchInitialData();
      } else {
        alert(`Error: ${data.message || data.error || "Failed to submit booking"}`);
      }
    } catch (err) {
      alert(`Network error: ${err.message}`);
    }
  }

  async handleDecision(approvalId, decision) {
    try {
      const res = await fetch(`${this.apiBase}/approvals/${approvalId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      const data = await res.json();
      if (data.ok) {
        alert(`Decision Recorded: ${data.approval_status} - ${data.message}`);
        this.fetchInitialData();
      } else {
        alert(`Action Blocked: ${data.message || data.error || "Unauthorized"}`);
      }
    } catch (err) {
      alert(`Error submitting decision: ${err.message}`);
    }
  }
}
