/**
 * Axiom Mobility (Fleetline) - Google TimesFM Financial & Demand Forecasting Widget.
 *
 * Interactive Dual-Ledger Forecasting Fan-Chart & Insights:
 * 1. Two-Tier TimesFM Point & Quantile Prediction Visualization (p10 / p50 / p90).
 * 2. Vendor Future Earnings & Liquidity Release Forecaster.
 * 3. Corporate Transport Expenditure & Budget Cap Breach Forecaster.
 * 4. SVG Fan-Chart with Shaded Confidence Cone, Historical Continuity, and Budget Reference Lines.
 */

export class TimesFmForecastWidget {
  constructor(options = {}) {
    this.container = options.container || null;
    this.containerId = options.containerId || "timesfm-forecast-container";
    this.apiBase = options.apiBase || "/api/v1";
    this.vendorId = options.vendorId || null;
    this.corporateId = options.corporateId || null;

    this.state = {
      mode: options.initialMode || "VENDOR_EARNINGS", // "VENDOR_EARNINGS" | "CORPORATE_EXPENDITURE"
      horizonDays: options.initialHorizon || 30, // 7 | 30 | 90
      isLoading: false,
      data: null,
      errorMessage: null,
      hoverPoint: null,
    };

    if (!this.container && typeof document !== "undefined") {
      this.container = document.getElementById(this.containerId);
    }
  }

  mount(hostElement = null) {
    if (typeof document === "undefined") return;
    if (hostElement) this.container = hostElement;
    if (!this.container) {
      this.container = document.getElementById(this.containerId);
    }
    if (!this.container) return;

    this.injectStyles();
    this.fetchForecast();
  }

  unmount() {
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("timesfm-widget-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "timesfm-widget-styles";
    styleEl.textContent = `
      .timesfm-wrapper {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 20px;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
      }
      .timesfm-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
      }
      .timesfm-mode-toggle {
        display: flex;
        background: #1e293b;
        border-radius: 8px;
        padding: 3px;
        border: 1px solid #334155;
      }
      .timesfm-toggle-btn {
        padding: 6px 14px;
        font-size: 12.5px;
        font-weight: 700;
        border: none;
        background: transparent;
        color: #94a3b8;
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .timesfm-toggle-btn.active {
        background: #38bdf8;
        color: #0f172a;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
      }
      .timesfm-horizon-pills {
        display: flex;
        gap: 6px;
      }
      .horizon-pill {
        padding: 5px 12px;
        font-size: 11.5px;
        font-weight: 600;
        background: #1e293b;
        border: 1px solid #334155;
        color: #94a3b8;
        border-radius: 20px;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .horizon-pill.active {
        border-color: #38bdf8;
        color: #38bdf8;
        background: rgba(56, 189, 248, 0.1);
      }
      .timesfm-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #1e1b4b;
        border: 1px solid #6366f1;
        color: #c7d2fe;
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 700;
      }
      .timesfm-chart-container {
        position: relative;
        width: 100%;
        background: #090d16;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 20px;
        overflow: hidden;
      }
      .timesfm-cards-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 14px;
      }
      .timesfm-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }
      .timesfm-card.alert-breach {
        border-color: #ef4444;
        background: rgba(239, 68, 68, 0.08);
      }
      .timesfm-card.alert-warning {
        border-color: #f59e0b;
        background: rgba(245, 158, 11, 0.08);
      }
      .timesfm-card.alert-ok {
        border-color: #10b981;
        background: rgba(16, 185, 129, 0.08);
      }
      .timesfm-card-title {
        font-size: 11.5px;
        font-weight: 700;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .timesfm-card-value {
        font-size: 22px;
        font-weight: 800;
        margin: 6px 0;
      }
      .timesfm-card-subtext {
        font-size: 12px;
        color: #94a3b8;
        line-height: 1.4;
      }
      .btn-refresh-timesfm {
        background: #1e293b;
        border: 1px solid #334155;
        color: #e2e8f0;
        font-size: 12px;
        padding: 5px 10px;
        border-radius: 6px;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
      .btn-refresh-timesfm:hover {
        background: #334155;
      }
    `;
    document.head.appendChild(styleEl);
  }

  async fetchForecast(forceRefresh = false) {
    this.state.isLoading = true;
    this.state.errorMessage = null;
    this.render();

    const { mode, horizonDays } = this.state;
    const endpoint =
      mode === "VENDOR_EARNINGS"
        ? `${this.apiBase}/forecasts/vendor-earnings`
        : `${this.apiBase}/forecasts/corporate-expenditure`;

    const params = new URLSearchParams({
      horizon_days: String(horizonDays),
      force_refresh: String(forceRefresh),
    });
    if (mode === "VENDOR_EARNINGS" && this.vendorId) params.append("vendor_id", this.vendorId);
    if (mode === "CORPORATE_EXPENDITURE" && this.corporateId) params.append("corporate_id", this.corporateId);

    try {
      const res = await fetch(`${endpoint}?${params.toString()}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      this.state.data = data;
    } catch (err) {
      this.state.errorMessage = `Forecasting model failed: ${err.message}`;
    } finally {
      this.state.isLoading = false;
      this.render();
    }
  }

  setMode(newMode) {
    if (this.state.mode === newMode) return;
    this.state.mode = newMode;
    this.fetchForecast();
  }

  setHorizon(newHorizon) {
    if (this.state.horizonDays === newHorizon) return;
    this.state.horizonDays = newHorizon;
    this.fetchForecast();
  }

  formatInr(val) {
    if (val === undefined || val === null) return "₹0";
    return "₹" + Math.round(val).toLocaleString("en-IN");
  }

  formatShortInr(val) {
    if (val === undefined || val === null) return "₹0";
    if (val >= 10000000) return "₹" + (val / 10000000).toFixed(2) + " Cr";
    if (val >= 100000) return "₹" + (val / 100000).toFixed(2) + " L";
    if (val >= 1000) return "₹" + (val / 1000).toFixed(1) + " k";
    return "₹" + Math.round(val);
  }

  renderFanChartSvg(data) {
    const historical = (data && data.historical_series) || [];
    const forecast = (data && data.forecast_series) || [];
    const summary = (data && data.summary_metrics) || {};
    const { mode } = this.state;

    // Use recent 21 days for clean historical visualization
    const histSlice = historical.slice(-21);
    const totalPoints = histSlice.length + forecast.length;
    if (totalPoints === 0) {
      return `<div style="padding: 40px; text-align: center; color: #64748b;">No time-series data available to plot</div>`;
    }

    const width = 800;
    const height = 260;
    const padding = { top: 30, right: 30, bottom: 40, left: 65 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;

    // Determine Y-scale max
    const allValues = [
      ...histSlice.map((d) => d.actual_amount_inr || 0),
      ...forecast.map((d) => d.p90_inr || 0),
    ];
    if (mode === "CORPORATE_EXPENDITURE" && summary.budget_cap_inr) {
      // Show daily budget reference if applicable
      allValues.push(summary.budget_cap_inr / 30);
    }
    const maxY = Math.max(1000, ...allValues) * 1.15;

    const getX = (idx) => padding.left + (idx / Math.max(1, totalPoints - 1)) * chartW;
    const getY = (val) => padding.top + chartH - (Math.max(0, val) / maxY) * chartH;

    // Split point: boundary between history and forecast
    const splitIdx = Math.max(0, histSlice.length - 1);
    const splitX = getX(splitIdx);

    // 1. Build Historical Path
    let histPathD = "";
    histSlice.forEach((pt, i) => {
      const x = getX(i);
      const y = getY(pt.actual_amount_inr);
      histPathD += (i === 0 ? "M " : " L ") + `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    // 2. Build Forecast Quantile Fan (p10 to p90 polygon)
    let fanUpperD = "";
    let fanLowerD = "";
    let p50PathD = "";

    forecast.forEach((pt, j) => {
      const i = histSlice.length + j;
      const x = getX(i);
      const yP10 = getY(pt.p10_inr);
      const yP50 = getY(pt.p50_expected_inr);
      const yP90 = getY(pt.p90_inr);

      if (j === 0) {
        // Connect to the last historical point
        const lastHistX = getX(splitIdx);
        const lastHistY = getY(histSlice[splitIdx]?.actual_amount_inr || pt.p50_expected_inr);
        fanUpperD = `M ${lastHistX.toFixed(1)},${lastHistY.toFixed(1)} L ${x.toFixed(1)},${yP90.toFixed(1)}`;
        p50PathD = `M ${lastHistX.toFixed(1)},${lastHistY.toFixed(1)} L ${x.toFixed(1)},${yP50.toFixed(1)}`;
      } else {
        fanUpperD += ` L ${x.toFixed(1)},${yP90.toFixed(1)}`;
        p50PathD += ` L ${x.toFixed(1)},${yP50.toFixed(1)}`;
      }

      fanLowerD = ` L ${x.toFixed(1)},${yP10.toFixed(1)}` + fanLowerD;
    });

    const fanPolygonD = fanUpperD + fanLowerD + " Z";

    // 3. Grid Lines & Axis Labels
    const yGridSteps = 4;
    let gridLinesSvg = "";
    for (let s = 0; s <= yGridSteps; s++) {
      const v = (maxY / yGridSteps) * s;
      const y = getY(v);
      gridLinesSvg += `
        <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#1e293b" stroke-width="1" stroke-dasharray="3,3" />
        <text x="${padding.left - 8}" y="${y + 4}" fill="#64748b" font-size="10" text-anchor="end">${this.formatShortInr(v)}</text>
      `;
    }

    const todayStr = new Date().toISOString().split("T")[0];

    return `
      <svg viewBox="0 0 ${width} ${height}" style="width: 100%; height: auto; display: block;" id="timesfm-fan-chart-svg">
        <defs>
          <linearGradient id="histFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
          </linearGradient>
          <linearGradient id="fanFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#818cf8" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#6366f1" stop-opacity="0.08"/>
          </linearGradient>
        </defs>

        <!-- Grid Lines -->
        ${gridLinesSvg}

        <!-- Vertical "Today" Separator -->
        <line x1="${splitX}" y1="${padding.top - 10}" x2="${splitX}" y2="${height - padding.bottom}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4,4" />
        <rect x="${splitX - 35}" y="${padding.top - 20}" width="70" height="18" rx="4" fill="#1e293b" stroke="#475569" stroke-width="1" />
        <text x="${splitX}" y="${padding.top - 8}" fill="#38bdf8" font-size="10" font-weight="700" text-anchor="middle">TODAY</text>

        <!-- Historical Series (Solid Line) -->
        <path d="${histPathD}" fill="none" stroke="#38bdf8" stroke-width="2.5" />

        <!-- TimesFM Shaded Confidence Cone (p10 to p90) -->
        ${forecast.length ? `<path d="${fanPolygonD}" fill="url(#fanFill)" stroke="none" />` : ""}

        <!-- TimesFM p50 Expected Centerline (Dashed Line) -->
        ${forecast.length ? `<path d="${p50PathD}" fill="none" stroke="#818cf8" stroke-width="2.2" stroke-dasharray="5,4" />` : ""}

        <!-- Section Headers -->
        <text x="${(padding.left + splitX) / 2}" y="${height - 12}" fill="#64748b" font-size="11" font-weight="600" text-anchor="middle">
          ◀ Historical Actuals
        </text>
        <text x="${(splitX + width - padding.right) / 2}" y="${height - 12}" fill="#818cf8" font-size="11" font-weight="700" text-anchor="middle">
          TimesFM Forecast (+${this.state.horizonDays}d Cone) ▶
        </text>
      </svg>
    `;
  }

  render() {
    if (!this.container) return;

    const { mode, horizonDays, isLoading, data, errorMessage } = this.state;
    const summary = (data && data.summary_metrics) || {};
    const backendUsed = (data && data.model_backend_used) || "axiom_seasonal_quantile_v1";
    const isGoogleTimesFM = backendUsed.includes("timesfm");

    this.container.innerHTML = `
      <div class="timesfm-wrapper">
        <!-- Top Toolbar -->
        <div class="timesfm-header">
          <div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
              <span style="font-size: 16px; font-weight: 800;">
                ${mode === "VENDOR_EARNINGS" ? "📈 Vendor Future Earnings & Cash-Flow Forecaster" : "🏢 Corporate Transport Expenditure & Budget Cap Forecaster"}
              </span>
              <span class="timesfm-badge">
                ${isGoogleTimesFM ? "⚡ Google TimesFM 500M" : "⏱️ Axiom Harmonic Quantile v1"}
              </span>
            </div>
            <div style="font-size: 12px; color: #94a3b8;">
              ${
                mode === "VENDOR_EARNINGS"
                  ? "Zero-shot predictive earnings model with p10 floor, p50 expected, and p90 peak revenue cones."
                  : "Predicts monthly RAC vs ETS corporate transport run-rate with automatic travel budget exhaustion alerts."
              }
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <!-- Mode Switch -->
            <div class="timesfm-mode-toggle">
              <button class="timesfm-toggle-btn ${mode === "VENDOR_EARNINGS" ? "active" : ""}" id="btn-toggle-vendor">
                Vendor Earnings
              </button>
              <button class="timesfm-toggle-btn ${mode === "CORPORATE_EXPENDITURE" ? "active" : ""}" id="btn-toggle-corp">
                Corporate Spend
              </button>
            </div>

            <!-- Horizon Pills -->
            <div class="timesfm-horizon-pills">
              <button class="horizon-pill ${horizonDays === 7 ? "active" : ""}" data-horizon="7">7 Days</button>
              <button class="horizon-pill ${horizonDays === 30 ? "active" : ""}" data-horizon="30">30 Days</button>
              <button class="horizon-pill ${horizonDays === 90 ? "active" : ""}" data-horizon="90">90 Days</button>
            </div>

            <!-- Refresh Model Button -->
            <button class="btn-refresh-timesfm" id="btn-re-run-model">
              🔄 ${isLoading ? "Running..." : "Re-Run Model"}
            </button>
          </div>
        </div>

        ${errorMessage ? `<div style="background:#7f1d1d44;border:1px solid #ef4444;color:#fca5a5;padding:10px 14px;border-radius:8px;font-size:12px;margin-bottom:14px;">${errorMessage}</div>` : ""}

        <!-- Fan Chart Canvas / SVG Container -->
        <div class="timesfm-chart-container">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <div style="font-size:12px;font-weight:700;color:#94a3b8;display:flex;gap:16px;">
              <span><span style="color:#38bdf8;">━</span> Actuals</span>
              <span><span style="color:#818cf8;">╍╍</span> p50 Expected</span>
              <span><span style="color:#6366f1;">░</span> p10–p90 Range</span>
            </div>
            <div style="font-size:11px;color:#64748b;">
              Confidence Score: <strong>${Math.round((summary.confidence_score || 0.85) * 100)}%</strong>
            </div>
          </div>
          ${isLoading ? `<div style="padding: 60px 0; text-align: center; color: #38bdf8; font-weight: 700;">⚡ Running TimesFM inference and residual decomposition...</div>` : this.renderFanChartSvg(data)}
        </div>

        <!-- Financial Intelligence Cards -->
        <div class="timesfm-cards-grid">
          ${
            mode === "VENDOR_EARNINGS"
              ? `
            <!-- Card 1: Expected Earnings -->
            <div class="timesfm-card">
              <div class="timesfm-card-title">Expected ${horizonDays}-Day Earnings (p50)</div>
              <div class="timesfm-card-value" style="color: #38bdf8;">
                ${this.formatInr(summary.total_p50_inr)}
              </div>
              <div class="timesfm-card-subtext">
                Conservative Floor: <strong>${this.formatShortInr(summary.total_p10_inr)}</strong> · Peak Upside: <strong>${this.formatShortInr(summary.total_p90_inr)}</strong>
              </div>
            </div>

            <!-- Card 2: Projected Liquidity Schedule -->
            <div class="timesfm-card">
              <div class="timesfm-card-title">Projected Withdrawable Cash Flow</div>
              <div class="timesfm-card-value" style="color: #34d399;">
                ${this.formatInr(summary.projected_week1_unlock_inr)}
              </div>
              <div class="timesfm-card-subtext">
                Unlocks in Next 7 Days (after ${summary.default_fund_hold_hours || 48}h hold). Week 2 projection: <strong>${this.formatShortInr(summary.projected_week2_unlock_inr)}</strong>.
              </div>
            </div>

            <!-- Card 3: AI Capacity Recommendation -->
            <div class="timesfm-card" style="border-color: #6366f1; background: rgba(99, 102, 241, 0.08);">
              <div class="timesfm-card-title" style="color: #a5b4fc;">AI Capacity & Fleet Advice</div>
              <div style="font-size: 13px; font-weight: 700; color: #e0e7ff; margin: 8px 0;">
                💡 Demand Spike Detected
              </div>
              <div class="timesfm-card-subtext" style="color: #c7d2fe;">
                ${summary.capacity_recommendation || "High Friday airport rush projected next month. Adding 1 vehicle could increase monthly earnings."}
              </div>
            </div>
          `
              : `
            <!-- Card 1: Corporate Month-End Spend -->
            <div class="timesfm-card ${summary.alert_status === "BREACH_PREDICTED" ? "alert-breach" : summary.alert_status === "WARNING_APPROACHING_CAP" ? "alert-warning" : "alert-ok"}">
              <div class="timesfm-card-title">Projected Month-End Spend</div>
              <div class="timesfm-card-value" style="color: ${summary.alert_status === "BREACH_PREDICTED" ? "#f87171" : "#38bdf8"};">
                ${this.formatInr(summary.projected_month_end_spend_inr)}
              </div>
              <div class="timesfm-card-subtext">
                Monthly Cap: <strong>${this.formatInr(summary.budget_cap_inr)}</strong> (${summary.budget_exhaustion_pct || 0}% of cap utilized)
              </div>
            </div>

            <!-- Card 2: Budget Breach Warning -->
            <div class="timesfm-card ${summary.budget_breach_date ? "alert-breach" : "alert-ok"}">
              <div class="timesfm-card-title">${summary.budget_breach_date ? "⚠️ Budget Breach Alert" : "✅ Budget Health Status"}</div>
              <div class="timesfm-card-value" style="font-size: 17px; color: ${summary.budget_breach_date ? "#f87171" : "#34d399"};">
                ${
                  summary.budget_breach_date
                    ? `Breach in ${summary.days_until_breach} days (${summary.budget_breach_date})`
                    : "Within Monthly Spend Budget"
                }
              </div>
              <div class="timesfm-card-subtext">
                ${
                  summary.budget_breach_date
                    ? `Projected budget overrun of <strong>${this.formatInr(summary.breach_variance_inr)}</strong> before month-end.`
                    : "Corporate travel spend trajectory is well within approved limits."
                }
              </div>
            </div>

            <!-- Card 3: Cost-Saving Optimization Lever -->
            <div class="timesfm-card" style="border-color: #38bdf8; background: rgba(56, 189, 248, 0.08);">
              <div class="timesfm-card-title" style="color: #38bdf8;">Cost-Saving Optimization</div>
              <div style="font-size: 13px; font-weight: 700; color: #bae6fd; margin: 8px 0;">
                📊 Spot vs ETS Rationalization
              </div>
              <div class="timesfm-card-subtext" style="color: #e0f2fe;">
                ${summary.cost_saving_optimization || "Switching projected spot rentals to pooled ETS cabs can save significant expenditure."}
              </div>
            </div>
          `
          }
        </div>
      </div>
    `;

    this.attachEventListeners();
  }

  attachEventListeners() {
    if (!this.container) return;

    // Mode toggles
    const btnVendor = this.container.querySelector("#btn-toggle-vendor");
    if (btnVendor) {
      btnVendor.addEventListener("click", () => this.setMode("VENDOR_EARNINGS"));
    }

    const btnCorp = this.container.querySelector("#btn-toggle-corp");
    if (btnCorp) {
      btnCorp.addEventListener("click", () => this.setMode("CORPORATE_EXPENDITURE"));
    }

    // Horizon pills
    const horizonPills = this.container.querySelectorAll(".horizon-pill");
    horizonPills.forEach((pill) => {
      pill.addEventListener("click", (e) => {
        const h = parseInt(e.target.dataset.horizon, 10);
        if (h) this.setHorizon(h);
      });
    });

    // Re-run model button
    const btnRerun = this.container.querySelector("#btn-re-run-model");
    if (btnRerun) {
      btnRerun.addEventListener("click", () => this.fetchForecast(true));
    }
  }
}
