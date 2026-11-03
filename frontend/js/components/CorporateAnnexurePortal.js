/**
 * Axiom Mobility (Fleetline) - Zero-Login Corporate Proforma Annexure & Trip-Sheet Verification Portal.
 * Zero-Build Vanilla ES6+ Component.
 *
 * Implements:
 * 1. Zero-login secure review link token resolver.
 * 2. Visual trip-sheet verification with side-by-side paper duty slip photos and Practical KM.
 * 3. Line-item 1-click approvals and itemized discrepancy flagging.
 * 4. Automatic dispute routing to Billing Maker-Checker reconciliation queue.
 */

export class CorporateAnnexurePortal {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("corporate-annexure-view") : null);
    this.token = options.token || this.extractTokenFromUrl() || "demo-token";
    this.apiBase = options.apiBase || "/api/v1";
    this.onDecided = options.onDecided || (() => {});

    this.state = {
      isLoading: true,
      isSubmitting: false,
      proformaData: null,
      errorMessage: null,
      successMessage: null,
      decisions: {}, // duty_id -> { status: "APPROVED" | "FLAGGED", reason?: string, proposed_km?: number }
    };
  }

  extractTokenFromUrl() {
    if (typeof window === "undefined") return null;
    const match = window.location.pathname.match(/\/corporate-review\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  }

  mount() {
    if (!this.container) return;
    this.injectStyles();
    this.fetchReviewData();
  }

  unmount() {
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("corporate-annexure-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "corporate-annexure-styles";
    styleEl.textContent = `
      .annexure-container {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0f172a;
        color: #f8fafc;
        border-radius: 12px;
        border: 1px solid #1e293b;
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 20px;
        max-width: 1200px;
        margin: 0 auto;
      }
      .annexure-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 18px;
      }
      .annexure-kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
      }
      .annexure-kpi-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px 16px;
      }
      .annexure-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12.5px;
      }
      .annexure-table th {
        background: #1e293b;
        color: #94a3b8;
        font-weight: 700;
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #334155;
      }
      .annexure-table td {
        padding: 12px;
        border-bottom: 1px solid #1e293b;
        vertical-align: middle;
      }
      .annexure-row:hover {
        background: rgba(30, 41, 59, 0.5);
      }
      .btn-pill-action {
        border: none;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 11.5px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .btn-approve {
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
      }
      .btn-approve.active {
        background: #10b981;
        color: #0f172a;
      }
      .btn-flag {
        background: rgba(239, 68, 68, 0.15);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
      }
      .btn-flag.active {
        background: #ef4444;
        color: white;
      }
      .status-badge-locked {
        background: rgba(59, 130, 246, 0.2);
        color: #60a5fa;
        border: 1px solid #3b82f6;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 750;
      }
      .sticky-submit-bar {
        position: sticky;
        bottom: 16px;
        background: #1e293b;
        border: 1px solid #475569;
        border-radius: 10px;
        padding: 14px 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      }
    `;
    document.head.appendChild(styleEl);
  }

  async fetchReviewData() {
    this.state.isLoading = true;
    this.state.errorMessage = null;
    this.render();

    try {
      const res = await fetch(`${this.apiBase}/billing/corporate-review/${this.token}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || `Failed to load review data (HTTP ${res.status})`);
      }

      const data = await res.json();
      this.state.proformaData = data;

      // Seed initial decisions from existing data
      const initialDecisions = {};
      if (Array.isArray(data.duties)) {
        data.duties.forEach((d) => {
          if (d.review_status === "APPROVED") {
            initialDecisions[d.id] = { status: "APPROVED" };
          } else if (d.review_status === "FLAGGED") {
            initialDecisions[d.id] = { status: "FLAGGED", reason: d.discrepancy_reason || "Mismatched duty details" };
          }
        });
      }
      this.state.decisions = initialDecisions;
    } catch (err) {
      this.state.errorMessage = err.message || "Failed to load proforma review portal";
    } finally {
      this.state.isLoading = false;
      this.render();
      this.attachEventListeners();
    }
  }

  render() {
    if (!this.container) return;

    const { isLoading, isSubmitting, proformaData, errorMessage, successMessage, decisions } = this.state;

    if (isLoading) {
      this.container.innerHTML = `
        <div class="annexure-container" style="text-align:center; padding:50px;">
          <div style="font-size:18px; font-weight:700;">⏳ Verifying Secure Annexure Token...</div>
          <div style="font-size:12px; color:#94a3b8; margin-top:8px;">Decrypting proforma and trip-sheet records</div>
        </div>
      `;
      return;
    }

    if (errorMessage && !proformaData) {
      this.container.innerHTML = `
        <div class="annexure-container" style="text-align:center; padding:50px; border-color:#ef4444;">
          <div style="font-size:20px; font-weight:800; color:#ef4444;">⚠️ Access Error</div>
          <div style="font-size:13px; color:#fca5a5; margin-top:10px;">${errorMessage}</div>
        </div>
      `;
      return;
    }

    const { corporate_name, proforma_id, summary, duties = [], status } = proformaData || {};

    const approvedCount = Object.values(decisions).filter((d) => d.status === "APPROVED").length;
    const flaggedCount = Object.values(decisions).filter((d) => d.status === "FLAGGED").length;

    this.container.innerHTML = `
      <div class="annexure-container">
        <!-- HEADER -->
        <div class="annexure-header">
          <div>
            <div style="font-size:11px; text-transform:uppercase; color:#38bdf8; font-weight:750;">
              CORPORATE TRIP SHEET VERIFICATION PORTAL
            </div>
            <div style="font-size:22px; font-weight:800; color:#f8fafc; margin-top:2px;">
              ${corporate_name || "Corporate Client"}
            </div>
            <div style="font-size:12px; color:#94a3b8; margin-top:4px;">
              Proforma Annexure: <strong>${proforma_id}</strong> | Zero-Login Verification Link
            </div>
          </div>
          <div>
            <span class="status-badge-locked">
              ${status === "APPROVED_LOCKED" ? "🔒 LOCKED & APPROVED" : (status === "PARTIALLY_APPROVED" ? "⚠️ PARTIALLY APPROVED" : "⏳ PENDING CORPORATE REVIEW")}
            </span>
          </div>
        </div>

        ${successMessage ? `<div style="background:rgba(16,185,129,0.15); border:1px solid #10b981; color:#6ee7b7; padding:12px; border-radius:8px; font-size:13px;">${successMessage}</div>` : ""}

        <!-- SUMMARY CARDS -->
        <div class="annexure-kpi-grid">
          <div class="annexure-kpi-card">
            <div style="font-size:10px; color:#94a3b8; font-weight:700;">TOTAL DUTY ITEMS</div>
            <div style="font-size:20px; font-weight:800; color:#f8fafc; margin-top:4px;">${summary?.total_duties || duties.length}</div>
          </div>
          <div class="annexure-kpi-card">
            <div style="font-size:10px; color:#34d399; font-weight:700;">APPROVED</div>
            <div style="font-size:20px; font-weight:800; color:#34d399; margin-top:4px;">${approvedCount}</div>
          </div>
          <div class="annexure-kpi-card">
            <div style="font-size:10px; color:#f87171; font-weight:700;">FLAGGED / DISPUTED</div>
            <div style="font-size:20px; font-weight:800; color:#f87171; margin-top:4px;">${flaggedCount}</div>
          </div>
          <div class="annexure-kpi-card">
            <div style="font-size:10px; color:#38bdf8; font-weight:700;">TOTAL BILLABLE AMOUNT</div>
            <div style="font-size:20px; font-weight:800; color:#38bdf8; margin-top:4px;">₹${(summary?.total_amount_inr || 0).toLocaleString()}</div>
          </div>
        </div>

        <!-- DUTIES TABLE -->
        <div style="overflow-x:auto;">
          <table class="annexure-table">
            <thead>
              <tr>
                <th>Duty ID & Date</th>
                <th>Passenger & Route</th>
                <th>Vehicle</th>
                <th>Kilometers & Hours</th>
                <th>Amount (₹)</th>
                <th>Trip Sheet Proof</th>
                <th style="text-align:right;">Verification Decision</th>
              </tr>
            </thead>
            <tbody>
              ${duties.map((d) => {
                const dec = decisions[d.id] || {};
                const isApproved = dec.status === "APPROVED";
                const isFlagged = dec.status === "FLAGGED";
                return `
                  <tr class="annexure-row" data-duty-id="${d.id}">
                    <td>
                      <div style="font-weight:750; color:#f8fafc;">${d.id}</div>
                      <div style="font-size:11px; color:#94a3b8;">${d.duty_date || "2026-11-01"}</div>
                    </td>
                    <td>
                      <div style="font-weight:700; color:#cbd5e1;">${d.passenger_name || "Corporate Guest"}</div>
                      <div style="font-size:11px; color:#94a3b8; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        ${d.route_name || "Pickup to Destination"}
                      </div>
                    </td>
                    <td>
                      <span style="background:#1e293b; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600;">
                        ${d.vehicle_category || "SEDAN"}
                      </span>
                    </td>
                    <td>
                      <div style="font-weight:750; color:#f8fafc;">${d.practical_billable_km || d.estimated_distance_km || 0} km</div>
                      <div style="font-size:10.5px; color:#64748b;">
                        Est: ${d.estimated_distance_km || 0} km | ${d.practical_duration_mins || 60}m
                      </div>
                    </td>
                    <td>
                      <div style="font-weight:800; color:#34d399; font-size:13.5px;">
                        ₹${(d.final_client_fare_inr || d.estimated_client_fare_inr || 0).toLocaleString()}
                      </div>
                    </td>
                    <td>
                      ${d.physical_tripsheet_file_url ? `
                        <a href="${d.physical_tripsheet_file_url}" target="_blank" style="color:#38bdf8; text-decoration:none; font-size:11px; font-weight:700; display:inline-flex; align-items:center; gap:4px;">
                          <span>📄</span> View Slip
                        </a>
                      ` : `<span style="font-size:11px; color:#64748b;">App Telemetry</span>`}
                    </td>
                    <td style="text-align:right;">
                      <div style="display:inline-flex; gap:6px;">
                        <button class="btn-pill-action btn-approve ${isApproved ? "active" : ""}" data-action="approve" data-id="${d.id}">
                          ✅ Approve
                        </button>
                        <button class="btn-pill-action btn-flag ${isFlagged ? "active" : ""}" data-action="flag" data-id="${d.id}">
                          ⚠️ Flag
                        </button>
                      </div>
                      ${isFlagged ? `
                        <div style="margin-top:6px; text-align:right;">
                          <input type="text" class="flag-reason-input" data-id="${d.id}" placeholder="Specify dispute reason..." value="${dec.reason || ""}" style="background:#070d1d; border:1px solid #ef4444; border-radius:4px; color:#f8fafc; font-size:11px; padding:4px 8px; width:180px;" />
                        </div>
                      ` : ""}
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>

        <!-- STICKY ACTION FOOTER -->
        <div class="sticky-submit-bar">
          <div>
            <div style="font-size:13px; font-weight:750; color:#f8fafc;">
              Ready to submit verification?
            </div>
            <div style="font-size:11.5px; color:#94a3b8; margin-top:2px;">
              ${approvedCount} approved | ${flaggedCount} routed to Maker-Checker dispute
            </div>
          </div>
          <div style="display:flex; gap:10px;">
            <button id="btn-approve-all" style="background:#334155; color:#cbd5e1; border:none; padding:10px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">
              Approve All (${duties.length})
            </button>
            <button id="btn-submit-review" style="background:#10b981; color:#0f172a; border:none; padding:10px 20px; border-radius:6px; font-size:13px; font-weight:800; cursor:pointer;" ${isSubmitting ? "disabled" : ""}>
              ${isSubmitting ? "⏳ Submitting..." : "🚀 Submit Review Decisions"}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    if (!this.container) return;

    // Approve / Flag click
    this.container.querySelectorAll(".btn-pill-action").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const action = e.currentTarget.getAttribute("data-action");
        const dutyId = e.currentTarget.getAttribute("data-id");
        if (action === "approve") {
          this.state.decisions[dutyId] = { status: "APPROVED" };
        } else if (action === "flag") {
          const current = this.state.decisions[dutyId];
          const reason = current?.reason || "Disputed meter reading or route detour";
          this.state.decisions[dutyId] = { status: "FLAGGED", reason };
        }
        this.render();
        this.attachEventListeners();
      });
    });

    // Reason input change
    this.container.querySelectorAll(".flag-reason-input").forEach((input) => {
      input.addEventListener("input", (e) => {
        const dutyId = e.target.getAttribute("data-id");
        if (this.state.decisions[dutyId]) {
          this.state.decisions[dutyId].reason = e.target.value;
        }
      });
    });

    // Approve all
    const approveAllBtn = this.container.querySelector("#btn-approve-all");
    if (approveAllBtn) {
      approveAllBtn.addEventListener("click", () => {
        const duties = this.state.proformaData?.duties || [];
        duties.forEach((d) => {
          this.state.decisions[d.id] = { status: "APPROVED" };
        });
        this.render();
        this.attachEventListeners();
      });
    }

    // Submit batch decisions
    const submitBtn = this.container.querySelector("#btn-submit-review");
    if (submitBtn) {
      submitBtn.addEventListener("click", () => this.handleSubmitDecisions());
    }
  }

  async handleSubmitDecisions() {
    this.state.isSubmitting = true;
    this.render();
    this.attachEventListeners();

    const approvedDutyIds = [];
    const flaggedDuties = [];

    Object.entries(this.state.decisions).forEach(([dutyId, dec]) => {
      if (dec.status === "APPROVED") {
        approvedDutyIds.push(dutyId);
      } else if (dec.status === "FLAGGED") {
        flaggedDuties.push({
          duty_id: dutyId,
          dispute_reason: dec.reason || "Disputed by corporate reviewer",
        });
      }
    });

    try {
      const res = await fetch(`${this.apiBase}/billing/corporate-review/${this.token}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved_duty_ids: approvedDutyIds,
          flagged_duties: flaggedDuties,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || "Failed to submit verification decisions");
      }

      const result = await res.json();
      this.state.successMessage = `Verification submitted! ${result.approved_count} duties confirmed; ${result.flagged_count} sent to dispute resolution.`;
      if (this.state.proformaData) {
        this.state.proformaData.status = result.status;
      }
      this.onDecided(result);
    } catch (err) {
      this.state.errorMessage = err.message || "Failed to submit decisions";
    } finally {
      this.state.isSubmitting = false;
      this.render();
      this.attachEventListeners();
    }
  }
}
