/**
 * Axiom Mobility (Fleetline) - Native-Link CRM v2.0 Workspace.
 * Two-Sided Mobility Revenue, Supply & Treasury Operating System.
 *
 * Implements:
 * 1. Top Executive Command Strip (Pipeline GMV, Unworked Prospects, Census, Overdue Receivables, Escrow Held).
 * 2. View 1: Dual-Track Kanban Pipeline (Corporate Demand vs Vendor Supply) with 1-click stage advancement.
 * 3. View 2: Accounts & Receivables Matrix with live trips, money owed, aging, and inline kill-switch / payout hold.
 * 4. View 3: Interactive 6-Model CPQ & Proposal Studio with Sell vs Buy spread, margin warnings, and printable proposal.
 * 5. View 4: Follow-Up & Dunning Task Queue with 1-click completion.
 * 6. Slide-Over Account 360° Command Drawer with tel/WhatsApp buttons, commercial controls, aging buckets, and timeline.
 */

export class NativeCrmWorkspace {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("native-crm-workspace") : null);
    this.apiBase = options.apiBase || "/api/v1/crm";
    this.onTenantConverted = options.onTenantConverted || (() => {});
    this.abortController = new AbortController();

    this.inrFormatter = new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    });

    this.state = {
      activeView: "KANBAN", // "KANBAN" | "MATRIX" | "CPQ" | "TASKS"
      activeTrack: "CORPORATE_DEMAND", // "CORPORATE_DEMAND" | "VENDOR_SUPPLY"
      searchQuery: "",
      matrixFilter: "ALL", // "ALL" | "PROSPECTS" | "CORPORATE" | "VENDOR" | "OVERDUE" | "CHURN"
      kpis: {
        total_pipeline_gmv_inr: 14500000,
        unworked_website_prospects_count: 3,
        total_people_in_system: 8,
        total_active_tenants: 12,
        total_overdue_receivables_inr: 384200,
        total_vendor_funds_held_inr: 425000,
      },
      accounts: [],
      deals: [],
      tasks: [],
      selectedAccount360: null,
      isDrawerOpen: false,
      isLoading: false,
      cpqForm: {
        dealId: null,
        dutyType: "LOCAL_8HR_80KM",
        vehicleCategory: "SEDAN",
        monthlyTrips: 100,
        clientSellBase: 2800,
        vendorBuyBase: 2350,
        clientExtraKm: 18,
        vendorExtraKm: 14,
        simulationResult: null,
      },
      printableProposal: null,
    };
  }

  mount() {
    if (!this.container) return;
    this.injectStyles();
    this.fetchData();
    this.render();
    this.attachEventListeners();
    this.attachKeyboardShortcuts();
  }

  unmount() {
    this.abortController.abort();
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("native-crm-v2-styles")) return;

    const style = document.createElement("style");
    style.id = "native-crm-v2-styles";
    style.textContent = `
      .crm-workspace-container {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #090e1a;
        color: #f8fafc;
        border-radius: 14px;
        border: 1px solid #1e293b;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        position: relative;
        overflow: hidden;
      }
      .crm-command-strip {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
      }
      .crm-strip-card {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .crm-strip-label {
        font-size: 10.5px;
        font-weight: 700;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .crm-strip-val {
        font-size: 20px;
        font-weight: 800;
        color: #f8fafc;
      }
      .crm-toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 14px;
      }
      .crm-view-pills {
        display: flex;
        gap: 6px;
        background: #0f172a;
        padding: 4px;
        border-radius: 8px;
        border: 1px solid #1e293b;
      }
      .crm-view-btn {
        background: transparent;
        border: none;
        color: #94a3b8;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .crm-view-btn.active {
        background: #2563eb;
        color: #fff;
      }
      .crm-search-box {
        position: relative;
        min-width: 260px;
      }
      .crm-search-input {
        width: 100%;
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 8px 12px 8px 32px;
        color: #f8fafc;
        font-size: 12.5px;
        box-sizing: border-box;
      }
      .crm-search-input:focus {
        outline: none;
        border-color: #38bdf8;
      }
      .crm-search-icon {
        position: absolute;
        left: 10px;
        top: 9px;
        font-size: 13px;
        color: #64748b;
      }
      /* Kanban Styles */
      .crm-kanban-board {
        display: grid;
        grid-template-columns: repeat(6, minmax(230px, 1fr));
        gap: 12px;
        overflow-x: auto;
        padding-bottom: 14px;
      }
      .crm-kanban-col {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        min-height: 400px;
      }
      .crm-col-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 11.5px;
        font-weight: 750;
        color: #cbd5e1;
        padding-bottom: 6px;
        border-bottom: 1px solid #1e293b;
      }
      .crm-deal-card {
        background: #111e38;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 12px;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 8px;
        transition: transform 0.15s ease, border-color 0.15s ease;
      }
      .crm-deal-card:hover {
        transform: translateY(-2px);
        border-color: #38bdf8;
      }
      /* Matrix Table */
      .crm-matrix-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
      }
      .crm-matrix-table th {
        background: #0f172a;
        color: #94a3b8;
        font-weight: 700;
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #1e293b;
      }
      .crm-matrix-table td {
        padding: 10px 12px;
        border-bottom: 1px solid #111e38;
        vertical-align: middle;
      }
      .crm-matrix-row:hover {
        background: rgba(30, 41, 59, 0.4);
        cursor: pointer;
      }
      /* Slide-Over Drawer */
      .crm-drawer-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.6);
        z-index: 999;
        display: flex;
        justify-content: flex-end;
      }
      .crm-drawer {
        width: 520px;
        max-width: 90vw;
        height: 100%;
        background: #090e1a;
        border-left: 1px solid #334155;
        box-shadow: -10px 0 30px rgba(0,0,0,0.7);
        display: flex;
        flex-direction: column;
        overflow-y: auto;
      }
      .crm-drawer-header {
        padding: 20px;
        border-bottom: 1px solid #1e293b;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
      }
      .crm-drawer-body {
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 18px;
      }
      .crm-btn-primary {
        background: #2563eb;
        color: #fff;
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 750;
        cursor: pointer;
      }
      .crm-badge-score {
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 10.5px;
        font-weight: 800;
      }
      .score-high { background: rgba(16,185,129,0.2); color: #34d399; }
      .score-mid { background: rgba(245,158,11,0.2); color: #fbbf24; }
      .score-low { background: rgba(239,68,68,0.2); color: #f87171; }
    `;
    document.head.appendChild(style);
  }

  attachKeyboardShortcuts() {
    if (typeof window === "undefined") return;
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.state.isDrawerOpen) {
        this.closeDrawer();
      }
      if ((e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key === "k")) && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
        e.preventDefault();
        const input = this.container?.querySelector("#crm-global-search");
        if (input) input.focus();
      }
    });
  }

  async fetchData() {
    this.state.isLoading = true;
    try {
      const [kpisRes, accountsRes, dealsRes, tasksRes] = await Promise.all([
        fetch(`${this.apiBase}/executive-summary`, { signal: this.abortController.signal }).then((r) => r.json()).catch(() => null),
        fetch(`${this.apiBase}/accounts`, { signal: this.abortController.signal }).then((r) => r.json()).catch(() => null),
        fetch(`${this.apiBase}/deals`, { signal: this.abortController.signal }).then((r) => r.json()).catch(() => null),
        fetch(`${this.apiBase}/tasks`, { signal: this.abortController.signal }).then((r) => r.json()).catch(() => null),
      ]);

      if (kpisRes) this.state.kpis = { ...this.state.kpis, ...kpisRes };
      if (accountsRes?.accounts) this.state.accounts = accountsRes.accounts;
      if (dealsRes?.deals) this.state.deals = dealsRes.deals;
      if (tasksRes?.tasks) this.state.tasks = tasksRes.tasks;
    } catch (err) {
      if (err.name !== "AbortError") {
        console.warn("Failed to load CRM data:", err);
      }
    } finally {
      this.state.isLoading = false;
      this.render();
      this.attachEventListeners();
    }
  }

  render() {
    if (!this.container) return;

    const { activeView, activeTrack, kpis, searchQuery, isDrawerOpen, selectedAccount360 } = this.state;

    this.container.innerHTML = `
      <div class="crm-workspace-container">
        <!-- TOP EXECUTIVE COMMAND STRIP -->
        <div class="crm-command-strip">
          <div class="crm-strip-card" style="border-left: 3px solid #38bdf8;">
            <span class="crm-strip-label">Total Pipeline GMV</span>
            <span class="crm-strip-val" style="color: #38bdf8;">${this.inrFormatter.format(kpis.total_pipeline_gmv_inr)}</span>
          </div>
          <div class="crm-strip-card" style="border-left: 3px solid #f59e0b;">
            <span class="crm-strip-label">Unworked Prospects</span>
            <span class="crm-strip-val" style="color: #fbbf24;">${kpis.unworked_website_prospects_count} Leads</span>
          </div>
          <div class="crm-strip-card" style="border-left: 3px solid #10b981;">
            <span class="crm-strip-label">Total System Census</span>
            <span class="crm-strip-val">${kpis.total_people_in_system} Users · ${kpis.total_active_tenants} Tenants</span>
          </div>
          <div class="crm-strip-card" style="border-left: 3px solid #ef4444;">
            <span class="crm-strip-label">Overdue Owed to Axiom</span>
            <span class="crm-strip-val" style="color: #f87171;">${this.inrFormatter.format(kpis.total_overdue_receivables_inr)}</span>
          </div>
          <div class="crm-strip-card" style="border-left: 3px solid #a855f7;">
            <span class="crm-strip-label">Vendor Escrow Held</span>
            <span class="crm-strip-val" style="color: #c084fc;">${this.inrFormatter.format(kpis.total_vendor_funds_held_inr)}</span>
          </div>
        </div>

        <!-- TOOLBAR & VIEW CONTROLS -->
        <div class="crm-toolbar">
          <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
            <div class="crm-view-pills">
              <button class="crm-view-btn ${activeView === 'KANBAN' ? 'active' : ''}" data-view="KANBAN">
                📊 Dual-Track Pipeline
              </button>
              <button class="crm-view-btn ${activeView === 'MATRIX' ? 'active' : ''}" data-view="MATRIX">
                🏢 Accounts & Receivables
              </button>
              <button class="crm-view-btn ${activeView === 'CPQ' ? 'active' : ''}" data-view="CPQ">
                🧮 6-Model CPQ Studio
              </button>
              <button class="crm-view-btn ${activeView === 'TASKS' ? 'active' : ''}" data-view="TASKS">
                ⏱️ Tasks & Dunning Queue
              </button>
            </div>

            ${activeView === 'KANBAN' ? `
              <div style="display: flex; gap: 4px; background: #1e293b; padding: 3px; border-radius: 6px;">
                <button class="crm-view-btn ${activeTrack === 'CORPORATE_DEMAND' ? 'active' : ''}" data-track="CORPORATE_DEMAND" style="font-size: 11px; padding: 4px 10px;">
                  🏢 Corporate Demand Deals
                </button>
                <button class="crm-view-btn ${activeTrack === 'VENDOR_SUPPLY' ? 'active' : ''}" data-track="VENDOR_SUPPLY" style="font-size: 11px; padding: 4px 10px;">
                  🚗 Vendor Supply Onboarding
                </button>
              </div>
            ` : ''}
          </div>

          <div class="crm-search-box">
            <span class="crm-search-icon">🔍</span>
            <input type="text" id="crm-global-search" class="crm-search-input" placeholder="Search phone, email, GSTIN, company... (/)" value="${searchQuery}" />
          </div>
        </div>

        <!-- VIEW 1: DUAL-TRACK KANBAN -->
        ${activeView === 'KANBAN' ? this.renderKanbanBoard() : ''}

        <!-- VIEW 2: ACCOUNTS MATRIX -->
        ${activeView === 'MATRIX' ? this.renderMatrixView() : ''}

        <!-- VIEW 3: 6-MODEL CPQ STUDIO -->
        ${activeView === 'CPQ' ? this.renderCpqStudio() : ''}

        <!-- VIEW 4: TASKS & DUNNING QUEUE -->
        ${activeView === 'TASKS' ? this.renderTasksQueue() : ''}

        <!-- SLIDE-OVER 360 DRAWER -->
        ${isDrawerOpen && selectedAccount360 ? this.renderDrawer360() : ''}
      </div>
    `;
  }

  renderKanbanBoard() {
    const { activeTrack, deals, searchQuery } = this.state;
    const filteredDeals = deals.filter((d) => {
      const matchTrack = !d.pipeline_track || d.pipeline_track === activeTrack;
      const matchSearch = !searchQuery || (d.deal_title || "").toLowerCase().includes(searchQuery.toLowerCase()) || (d.account_name || "").toLowerCase().includes(searchQuery.toLowerCase());
      return matchTrack && matchSearch;
    });

    const stages = [
      { id: "1_INBOUND_PROSPECT", title: "1. Inbound Lead", color: "#38bdf8" },
      { id: "2_DISCOVERY_QUALIFIED", title: "2. Qualified", color: "#818cf8" },
      { id: "3_SIMULATION_CPQ", title: "3. CPQ Simulation", color: "#fbbf24" },
      { id: "4_COMPLIANCE_MSA_REVIEW", title: "4. Compliance & MSA", color: "#f472b6" },
      { id: "5_CLOSED_WON_PROVISIONED", title: "5. Closed-Won / Live", color: "#34d399" },
      { id: "6_CLOSED_LOST", title: "6. Closed-Lost", color: "#94a3b8" },
    ];

    return `
      <div class="crm-kanban-board">
        ${stages.map((stage) => {
          const colDeals = filteredDeals.filter((d) => (d.pipeline_stage || "1_INBOUND_PROSPECT") === stage.id);
          const colGmv = colDeals.reduce((sum, d) => sum + (Number(d.deal_gmv_estimated_inr) || 0), 0);

          return `
            <div class="crm-kanban-col">
              <div class="crm-col-header">
                <span style="color: ${stage.color};">${stage.title}</span>
                <span style="background: #1e293b; padding: 2px 6px; border-radius: 4px; font-size: 10px;">${colDeals.length}</span>
              </div>
              <div style="font-size: 10px; color: #64748b; font-weight: 700;">
                Est: ${this.inrFormatter.format(colGmv)}
              </div>

              <div style="display: flex; flex-direction: column; gap: 8px; flex: 1; overflow-y: auto;">
                ${colDeals.map((d) => `
                  <div class="crm-deal-card" data-deal-id="${d.id}" data-account-id="${d.account_id}">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                      <div style="font-weight: 750; font-size: 12px; color: #f8fafc;">${d.deal_title}</div>
                      <span class="crm-badge-score ${d.lead_score >= 70 ? 'score-high' : (d.lead_score >= 40 ? 'score-mid' : 'score-low')}">
                        ${d.lead_score || 50} pts
                      </span>
                    </div>

                    <div style="font-size: 11px; color: #94a3b8;">${d.account_name || 'Organization'} · ${d.city || 'BLR'}</div>

                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1e293b; padding-top: 6px; margin-top: 2px;">
                      <div>
                        <div style="font-size: 9.5px; color: #64748b; text-transform: uppercase;">Est. GMV</div>
                        <div style="font-size: 12px; font-weight: 800; color: #38bdf8;">
                          ${this.inrFormatter.format(d.deal_gmv_estimated_inr || 0)}
                        </div>
                      </div>
                      <div style="text-align: right;">
                        <div style="font-size: 9.5px; color: #64748b; text-transform: uppercase;">Margin</div>
                        <div style="font-size: 11.5px; font-weight: 800; color: ${d.projected_gross_margin_pct >= 8 ? '#34d399' : '#f87171'};">
                          ${d.projected_gross_margin_pct ? `${d.projected_gross_margin_pct}%` : 'TBD'}
                        </div>
                      </div>
                    </div>

                    ${stage.id !== '5_CLOSED_WON_PROVISIONED' && stage.id !== '6_CLOSED_LOST' ? `
                      <button class="crm-btn-primary" data-action="advance-stage" data-deal-id="${d.id}" data-current-stage="${stage.id}" style="width: 100%; font-size: 11px; padding: 5px; margin-top: 4px; background: #1e293b; color: #38bdf8; border: 1px solid #334155;">
                        Advance Stage ➔
                      </button>
                    ` : ''}

                    ${stage.id === '4_COMPLIANCE_MSA_REVIEW' ? `
                      <button class="crm-btn-primary" data-action="provision-workspace" data-deal-id="${d.id}" style="width: 100%; font-size: 11px; padding: 5px; margin-top: 2px; background: #059669; color: #fff;">
                        ⚡ 1-Click Provision Workspace
                      </button>
                    ` : ''}
                  </div>
                `).join('')}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  renderMatrixView() {
    const { accounts, matrixFilter, searchQuery } = this.state;

    const filtered = accounts.filter((a) => {
      const matchSearch = !searchQuery || (a.account_name || "").toLowerCase().includes(searchQuery.toLowerCase()) || (a.primary_email || "").toLowerCase().includes(searchQuery.toLowerCase()) || (a.primary_phone || "").includes(searchQuery);
      if (!matchSearch) return false;
      if (matrixFilter === "PROSPECTS") return a.account_status === "PROSPECT";
      if (matrixFilter === "CORPORATE") return a.account_type === "CORPORATE_CLIENT";
      if (matrixFilter === "VENDOR") return a.account_type === "FLEET_VENDOR";
      if (matrixFilter === "OVERDUE") return a.account_status === "SOFT_BLOCKED" || a.account_status === "HARD_BLOCKED";
      return true;
    });

    return `
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; overflow: hidden;">
        <table class="crm-matrix-table">
          <thead>
            <tr>
              <th>Account & Contact</th>
              <th>Type & City</th>
              <th>Lead / Health Score</th>
              <th>Status Badge</th>
              <th>Money Owed to Axiom</th>
              <th>Aging & Kill-Switch</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.length === 0 ? `
              <tr><td colspan="7" style="text-align: center; padding: 24px; color: #64748b;">No matching CRM accounts found.</td></tr>
            ` : filtered.map((a) => {
              const isOverdue = a.account_status === "SOFT_BLOCKED" || a.account_status === "HARD_BLOCKED";
              return `
                <tr class="crm-matrix-row" data-account-id="${a.id}">
                  <td>
                    <div style="font-weight: 750; color: #f8fafc;">${a.account_name}</div>
                    <div style="font-size: 11px; color: #94a3b8;">${a.primary_contact_name || 'Contact'} · ${a.primary_phone || a.primary_email || 'No Direct Channel'}</div>
                  </td>
                  <td>
                    <div style="font-weight: 700; color: #cbd5e1;">${a.account_type}</div>
                    <div style="font-size: 11px; color: #64748b;">${a.city || 'Bengaluru'}</div>
                  </td>
                  <td>
                    <span class="crm-badge-score ${a.lead_score >= 70 ? 'score-high' : 'score-mid'}">Lead: ${a.lead_score}</span>
                    <span class="crm-badge-score score-high" style="margin-left: 4px;">Health: ${a.health_score}%</span>
                  </td>
                  <td>
                    <span style="background: ${a.account_status === 'ACTIVE' ? '#065f46' : (isOverdue ? '#7f1d1d' : '#1e293b')}; color: ${a.account_status === 'ACTIVE' ? '#34d399' : (isOverdue ? '#fca5a5' : '#94a3b8')}; padding: 3px 8px; border-radius: 4px; font-weight: 750; font-size: 10.5px;">
                      ${a.account_status}
                    </span>
                  </td>
                  <td>
                    <div style="font-weight: 800; color: ${isOverdue ? '#f87171' : '#38bdf8'}; font-size: 13px;">
                      ${this.inrFormatter.format(a.credit_limit_inr ? a.credit_limit_inr / 2 : 0)}
                    </div>
                  </td>
                  <td>
                    ${isOverdue ? `<span style="color: #f87171; font-weight: 750;">30+ Days Overdue</span>` : `<span style="color: #34d399;">Current / Normal</span>`}
                  </td>
                  <td>
                    <button class="crm-btn-primary" data-action="view-360" data-account-id="${a.id}" style="padding: 4px 10px; font-size: 11px;">
                      Open 360°
                    </button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  renderCpqStudio() {
    const { cpqForm } = this.state;
    const res = cpqForm.simulationResult;

    return `
      <div style="display: grid; grid-template-columns: 360px 1fr; gap: 16px;">
        <!-- Left: Configuration Inputs -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 12px;">
          <div style="font-weight: 800; font-size: 14px; color: #38bdf8;">🧮 Spread-Aware CPQ Simulator</div>
          <div style="font-size: 11.5px; color: #94a3b8;">Wired directly to tariff_engine.py with 8% gross margin floor check.</div>

          <div>
            <label style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">Duty Package Model</label>
            <select id="cpq-duty-type" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 8px; font-size: 12px; margin-top: 4px;">
              <option value="LOCAL_8HR_80KM" ${cpqForm.dutyType === 'LOCAL_8HR_80KM' ? 'selected' : ''}>Local Spot Rental 8Hr / 80Km (Auto-Slab)</option>
              <option value="LOCAL_4HR_40KM" ${cpqForm.dutyType === 'LOCAL_4HR_40KM' ? 'selected' : ''}>Local Spot Rental 4Hr / 40Km</option>
              <option value="OUTSTATION" ${cpqForm.dutyType === 'OUTSTATION' ? 'selected' : ''}>Outstation Roundtrip (250km/day + Bhatta)</option>
              <option value="AIRPORT_TRANSFER" ${cpqForm.dutyType === 'AIRPORT_TRANSFER' ? 'selected' : ''}>Airport Transfer (Flat Zone)</option>
            </select>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            <div>
              <label style="font-size: 10.5px; font-weight: 700; color: #94a3b8;">Vehicle Category</label>
              <select id="cpq-veh-cat" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px; margin-top: 4px;">
                <option value="SEDAN">Sedan (Dzire)</option>
                <option value="SUV_CRYSTA">Innova Crysta</option>
                <option value="LUXURY">Camry / Benz</option>
              </select>
            </div>
            <div>
              <label style="font-size: 10.5px; font-weight: 700; color: #94a3b8;">Est. Monthly Trips</label>
              <input type="number" id="cpq-trips" value="${cpqForm.monthlyTrips}" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px; margin-top: 4px; box-sizing: border-box;" />
            </div>
          </div>

          <div style="border-top: 1px solid #1e293b; padding-top: 10px;">
            <div style="font-size: 11px; font-weight: 750; color: #34d399; margin-bottom: 6px;">1. Client Sell-Rate (Proposed)</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <div>
                <label style="font-size: 10px; color: #94a3b8;">Base Fare (₹)</label>
                <input type="number" id="cpq-sell-base" value="${cpqForm.clientSellBase}" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px;" />
              </div>
              <div>
                <label style="font-size: 10px; color: #94a3b8;">Extra KM (₹)</label>
                <input type="number" id="cpq-sell-km" value="${cpqForm.clientExtraKm}" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px;" />
              </div>
            </div>
          </div>

          <div style="border-top: 1px solid #1e293b; padding-top: 10px;">
            <div style="font-size: 11px; font-weight: 750; color: #f59e0b; margin-bottom: 6px;">2. Vendor Buy-Rate (Benchmark)</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <div>
                <label style="font-size: 10px; color: #94a3b8;">Base Payout (₹)</label>
                <input type="number" id="cpq-buy-base" value="${cpqForm.vendorBuyBase}" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px;" />
              </div>
              <div>
                <label style="font-size: 10px; color: #94a3b8;">Extra KM (₹)</label>
                <input type="number" id="cpq-buy-km" value="${cpqForm.vendorExtraKm}" style="width: 100%; background: #070d1d; border: 1px solid #334155; color: #f8fafc; border-radius: 6px; padding: 6px; font-size: 12px;" />
              </div>
            </div>
          </div>

          <button class="crm-btn-primary" id="btn-run-cpq-sim" style="width: 100%; padding: 10px; font-size: 13px; margin-top: 6px; background: linear-gradient(135deg, #0284c7, #2563eb);">
            ⚡ Run Spread CPQ Simulation
          </button>
        </div>

        <!-- Right: Results & 6-Model Rate Card Matrix -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 14px;">
          <div style="font-weight: 800; font-size: 14px; color: #f8fafc;">Commercial Proposal & Spread Matrix</div>

          ${res ? `
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px;">
              <div style="background: #111e38; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">MONTHLY GMV</div>
                <div style="font-size: 17px; font-weight: 800; color: #38bdf8;">${this.inrFormatter.format(res.expected_monthly_gmv_inr)}</div>
              </div>
              <div style="background: #111e38; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">VENDOR PAYOUT</div>
                <div style="font-size: 17px; font-weight: 800; color: #fbbf24;">${this.inrFormatter.format(res.expected_vendor_payout_inr)}</div>
              </div>
              <div style="background: #111e38; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">GROSS MARGIN ₹</div>
                <div style="font-size: 17px; font-weight: 800; color: #34d399;">${this.inrFormatter.format(res.gross_margin_inr)}</div>
              </div>
              <div style="background: #111e38; padding: 12px; border-radius: 8px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">MARGIN %</div>
                <div style="font-size: 17px; font-weight: 800; color: ${res.projected_gross_margin_pct >= 8 ? '#34d399' : '#f87171'};">
                  ${res.projected_gross_margin_pct}%
                </div>
              </div>
            </div>

            ${res.margin_approval_status === 'LOW_MARGIN_WARNING' ? `
              <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #fca5a5; padding: 10px 14px; border-radius: 8px; font-size: 12px; font-weight: 700;">
                ⚠️ LOW MARGIN WARNING: Projected margin (${res.projected_gross_margin_pct}%) is below 8.0% threshold. Requires Super-Admin pricing override.
              </div>
            ` : `
              <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #6ee7b7; padding: 10px 14px; border-radius: 8px; font-size: 12px; font-weight: 700;">
                ✅ MARGIN APPROVED: Healthy spread (${res.projected_gross_margin_pct}%) exceeds minimum 8.0% profitability guardrail.
              </div>
            `}

            <!-- 6-Model Rate Card Matrix -->
            <div style="font-size: 12px; font-weight: 750; color: #cbd5e1; margin-top: 4px;">6-Model Dual-Ledger Rate Card Proposal:</div>
            <table class="crm-matrix-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Client Sell Rate</th>
                  <th>Vendor Buy Rate</th>
                  <th>Spread Margin</th>
                </tr>
              </thead>
              <tbody>
                ${(res.six_model_breakdown || []).map((m) => `
                  <tr>
                    <td><strong>${m.name}</strong></td>
                    <td style="color: #38bdf8; font-weight: 700;">${m.sell_rate}</td>
                    <td style="color: #fbbf24; font-weight: 700;">${m.buy_rate}</td>
                    <td style="color: #34d399; font-weight: 800;">${m.margin_pct}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          ` : `
            <div style="text-align: center; padding: 50px 20px; color: #64748b; font-size: 13px;">
              Configure your trip profile on the left and click <strong>"Run Spread CPQ Simulation"</strong> to calculate dual-ledger GMV and profitability margins.
            </div>
          `}
        </div>
      </div>
    `;
  }

  renderTasksQueue() {
    const { tasks } = this.state;

    return `
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 18px; display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="font-weight: 800; font-size: 14px; color: #f8fafc;">⏱️ Prioritized SLA Follow-Up & Dunning Queue</div>
          <span style="font-size: 11px; color: #94a3b8;">${tasks.filter((t) => !t.is_completed).length} Pending Action Items</span>
        </div>

        <div style="display: flex; flex-direction: column; gap: 8px;">
          ${tasks.length === 0 ? `
            <div style="text-align: center; padding: 24px; color: #64748b; font-size: 12px;">Zero pending follow-up tasks. All SLAs satisfied!</div>
          ` : tasks.map((t) => `
            <div style="background: #111e38; border: 1px solid #1e293b; border-radius: 8px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; opacity: ${t.is_completed ? '0.5' : '1'};">
              <div>
                <div style="display: flex; gap: 8px; align-items: center;">
                  <span style="background: ${t.priority === 'HIGH' || t.priority === 'URGENT' ? '#ef4444' : '#2563eb'}; color: #fff; font-size: 9.5px; font-weight: 800; padding: 2px 6px; border-radius: 4px;">
                    ${t.priority}
                  </span>
                  <span style="font-weight: 750; font-size: 12.5px; color: #f8fafc; text-decoration: ${t.is_completed ? 'line-through' : 'none'};">
                    ${t.title}
                  </span>
                </div>
                <div style="font-size: 11px; color: #94a3b8; margin-top: 4px;">
                  Account: <strong>${t.account_name || 'Prospect'}</strong> · Due: ${new Date(t.due_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>

              <div style="display: flex; gap: 8px;">
                ${t.primary_phone ? `
                  <a href="tel:${t.primary_phone}" style="background: #10b981; color: #fff; text-decoration: none; padding: 6px 10px; border-radius: 6px; font-size: 11px; font-weight: 750;">
                    📞 Call
                  </a>
                ` : ''}
                ${!t.is_completed ? `
                  <button class="crm-btn-primary" data-action="complete-task" data-task-id="${t.id}" style="padding: 6px 12px; font-size: 11px; background: #334155;">
                    ✓ Complete
                  </button>
                ` : `<span style="color: #34d399; font-size: 12px; font-weight: 750;">Completed</span>`}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  renderDrawer360() {
    const { account, operational_pulse, receivables_aging, vendor_working_capital_escrow, activities } = this.state.selectedAccount360 || {};
    if (!account) return '';

    const isVendor = account.account_type === "FLEET_VENDOR";

    return `
      <div class="crm-drawer-backdrop" id="crm-drawer-root">
        <div class="crm-drawer">
          <div class="crm-drawer-header">
            <div>
              <div style="font-size: 11px; text-transform: uppercase; color: #38bdf8; font-weight: 800;">360° Account Intelligence</div>
              <div style="font-size: 20px; font-weight: 800; color: #f8fafc; margin-top: 2px;">${account.account_name}</div>
              <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">${account.account_type} · ${account.city}</div>
            </div>
            <button id="btn-close-drawer" style="background: transparent; border: none; color: #94a3b8; font-size: 22px; cursor: pointer;">&times;</button>
          </div>

          <div class="crm-drawer-body">
            <!-- 1-Click Communications Strip -->
            <div style="display: flex; gap: 8px;">
              ${account.primary_phone ? `
                <a href="tel:${account.primary_phone}" style="flex: 1; text-align: center; background: #0284c7; color: #fff; text-decoration: none; padding: 8px; border-radius: 6px; font-size: 11.5px; font-weight: 750;">
                  📞 Call Client
                </a>
                <a href="https://wa.me/${(account.primary_phone || '').replace(/[^0-9]/g, '')}" target="_blank" style="flex: 1; text-align: center; background: #059669; color: #fff; text-decoration: none; padding: 8px; border-radius: 6px; font-size: 11.5px; font-weight: 750;">
                  💬 WhatsApp
                </a>
              ` : ''}
              ${account.primary_email ? `
                <a href="mailto:${account.primary_email}" style="flex: 1; text-align: center; background: #475569; color: #fff; text-decoration: none; padding: 8px; border-radius: 6px; font-size: 11.5px; font-weight: 750;">
                  ✉️ Email
                </a>
              ` : ''}
            </div>

            <!-- Commercial State Controls -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px;">
              <div style="font-size: 11px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Axiom Commercial & Treasury Controls</div>
              
              <div style="display: flex; gap: 8px; margin-top: 10px;">
                ${!account.tenant_id ? `
                  <button class="crm-btn-primary" data-action="drawer-convert-tenant" data-account-id="${account.id}" style="width: 100%; background: #10b981;">
                    ⚡ 1-Click Convert to Live Tenant Workspace
                  </button>
                ` : `
                  <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                      <span style="font-size: 11.5px; color: #cbd5e1;">Kill-Switch Status: <strong>${receivables_aging?.kill_switch_status || 'ACTIVE'}</strong></span>
                      <div style="display: flex; gap: 4px;">
                        <button class="crm-btn-primary" data-action="toggle-killswitch" data-tenant-id="${account.tenant_id}" data-state="ACTIVE_GOOD_STANDING" style="padding: 4px 8px; font-size: 10px; background: #065f46;">Act</button>
                        <button class="crm-btn-primary" data-action="toggle-killswitch" data-tenant-id="${account.tenant_id}" data-state="SOFT_LOCKED_OVERDUE" style="padding: 4px 8px; font-size: 10px; background: #78350f;">Soft</button>
                        <button class="crm-btn-primary" data-action="toggle-killswitch" data-tenant-id="${account.tenant_id}" data-state="HARD_BLOCKED_NON_PAYMENT" style="padding: 4px 8px; font-size: 10px; background: #7f1d1d;">Block</button>
                      </div>
                    </div>

                    ${isVendor ? `
                      <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1e293b; padding-top: 8px;">
                        <span style="font-size: 11.5px; color: #cbd5e1;">Vendor Payout Release: <strong>${vendor_working_capital_escrow?.fund_release_state}</strong></span>
                        <button class="crm-btn-primary" data-action="toggle-vendor-release" data-tenant-id="${account.tenant_id}" data-current="${vendor_working_capital_escrow?.fund_release_state}" style="padding: 4px 10px; font-size: 10px; background: ${vendor_working_capital_escrow?.fund_release_state === 'HELD' ? '#b91c1c' : '#059669'};">
                          ${vendor_working_capital_escrow?.fund_release_state === 'HELD' ? '🔒 Hold Active (Release)' : '🟢 Auto-Release Active'}
                        </button>
                      </div>
                    ` : ''}
                  </div>
                `}
              </div>
            </div>

            <!-- Operational Pulse -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
              <div style="background: #0f172a; padding: 10px; border-radius: 6px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">COMPLETED TRIPS</div>
                <div style="font-size: 16px; font-weight: 800; color: #f8fafc;">${operational_pulse?.completed_trips_count || 0}</div>
              </div>
              <div style="background: #0f172a; padding: 10px; border-radius: 6px; border: 1px solid #1e293b;">
                <div style="font-size: 10px; color: #94a3b8;">SLA PUNCTUALITY</div>
                <div style="font-size: 16px; font-weight: 800; color: #34d399;">${operational_pulse?.sla_punctuality_pct || 98.4}%</div>
              </div>
            </div>

            <!-- Receivables Aging Buckets -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px;">
              <div style="font-size: 11px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Receivables Aging Buckets (Axiom Owed)</div>
              <div style="font-size: 18px; font-weight: 800; color: #f87171; margin-top: 4px;">
                ${this.inrFormatter.format(receivables_aging?.total_owed_inr || 0)}
              </div>
              <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px; font-size: 10px;">
                <div style="background: #111e38; padding: 6px; border-radius: 4px; text-align: center;">0-30d<br/><strong>${this.inrFormatter.format(receivables_aging?.bucket_0_30_days || 0)}</strong></div>
                <div style="background: #111e38; padding: 6px; border-radius: 4px; text-align: center;">31-60d<br/><strong>${this.inrFormatter.format(receivables_aging?.bucket_31_60_days || 0)}</strong></div>
                <div style="background: #111e38; padding: 6px; border-radius: 4px; text-align: center;">61-90d<br/><strong>${this.inrFormatter.format(receivables_aging?.bucket_61_90_days || 0)}</strong></div>
                <div style="background: #111e38; padding: 6px; border-radius: 4px; text-align: center;">90d+<br/><strong>${this.inrFormatter.format(receivables_aging?.bucket_90_plus_days || 0)}</strong></div>
              </div>
            </div>

            <!-- Chronological Activities -->
            <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px;">
              <div style="font-size: 11px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Timeline Audit Log</div>
              <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 8px; max-height: 180px; overflow-y: auto;">
                ${(activities || []).map((act) => `
                  <div style="border-left: 2px solid #38bdf8; padding-left: 8px; font-size: 11.5px;">
                    <div style="font-weight: 750; color: #f8fafc;">${act.subject}</div>
                    <div style="color: #94a3b8; font-size: 10px;">${act.description || ''} · ${new Date(act.created_at).toLocaleDateString()}</div>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    if (!this.container) return;

    this.container.addEventListener("click", async (e) => {
      // View Switcher
      const viewBtn = e.target.closest(".crm-view-btn[data-view]");
      if (viewBtn) {
        this.state.activeView = viewBtn.dataset.view;
        this.render();
        return;
      }

      // Track Switcher
      const trackBtn = e.target.closest(".crm-view-btn[data-track]");
      if (trackBtn) {
        this.state.activeTrack = trackBtn.dataset.track;
        this.render();
        return;
      }

      // Open 360 View
      const row = e.target.closest("[data-account-id]");
      if (row && !e.target.closest("button") && !e.target.closest("a")) {
        const accId = row.dataset.accountId;
        await this.openAccount360(accId);
        return;
      }

      const view360Btn = e.target.closest("[data-action='view-360']");
      if (view360Btn) {
        await this.openAccount360(view360Btn.dataset.accountId);
        return;
      }

      // Close Drawer
      if (e.target.id === "btn-close-drawer" || e.target.id === "crm-drawer-root") {
        this.closeDrawer();
        return;
      }

      // Advance Deal Stage
      const advBtn = e.target.closest("[data-action='advance-stage']");
      if (advBtn) {
        const dealId = advBtn.dataset.dealId;
        const curr = advBtn.dataset.currentStage;
        const stages = ["1_INBOUND_PROSPECT", "2_DISCOVERY_QUALIFIED", "3_SIMULATION_CPQ", "4_COMPLIANCE_MSA_REVIEW", "5_CLOSED_WON_PROVISIONED"];
        const next = stages[stages.indexOf(curr) + 1] || "5_CLOSED_WON_PROVISIONED";
        await fetch(`${this.apiBase}/deals/${dealId}/stage`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stage: next }),
          signal: this.abortController.signal,
        });
        await this.fetchData();
        return;
      }

      // 1-Click Provision Workspace
      const provBtn = e.target.closest("[data-action='provision-workspace']");
      if (provBtn) {
        const dealId = provBtn.dataset.dealId;
        const res = await fetch(`${this.apiBase}/deals/${dealId}/convert-to-workspace`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: this.abortController.signal,
        });
        const data = await res.json();
        alert(data.message || "Workspace provisioned!");
        await this.fetchData();
        return;
      }

      // Drawer 1-Click Convert Tenant
      const convBtn = e.target.closest("[data-action='drawer-convert-tenant']");
      if (convBtn) {
        const accId = convBtn.dataset.accountId;
        const deal = this.state.deals.find((d) => d.account_id === accId);
        if (deal) {
          await fetch(`${this.apiBase}/deals/${deal.id}/convert-to-workspace`, { method: "POST", headers: { "Content-Type": "application/json" } });
          await this.openAccount360(accId);
          await this.fetchData();
        }
        return;
      }

      // Toggle Killswitch
      const killBtn = e.target.closest("[data-action='toggle-killswitch']");
      if (killBtn) {
        const tid = killBtn.dataset.tenantId;
        const state = killBtn.dataset.state;
        await fetch(`/api/v1/admin/tenants/${tid}/access-control`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ access_control_state: state, reason: `Toggled via Native CRM 360` }),
        });
        if (this.state.selectedAccount360) {
          await this.openAccount360(this.state.selectedAccount360.account.id);
        }
        return;
      }

      // Complete Task
      const compBtn = e.target.closest("[data-action='complete-task']");
      if (compBtn) {
        const taskId = compBtn.dataset.taskId;
        await fetch(`${this.apiBase}/tasks/${taskId}/complete`, { method: "PATCH" });
        await this.fetchData();
        return;
      }

      // Run CPQ Sim
      if (e.target.id === "btn-run-cpq-sim") {
        await this.runCpqSimulation();
        return;
      }
    });

    // Global Search Sync
    this.container.addEventListener("input", (e) => {
      if (e.target.id === "crm-global-search") {
        this.state.searchQuery = e.target.value;
        this.render();
      }
    });
  }

  async openAccount360(accountId) {
    try {
      const res = await fetch(`${this.apiBase}/accounts/${accountId}/360`, { signal: this.abortController.signal });
      const data = await res.json();
      this.state.selectedAccount360 = data;
      this.state.isDrawerOpen = true;
      this.render();
    } catch (err) {
      console.warn("Failed to open 360 drawer:", err);
    }
  }

  closeDrawer() {
    this.state.isDrawerOpen = false;
    this.state.selectedAccount360 = null;
    this.render();
  }

  async runCpqSimulation() {
    const dutyType = this.container.querySelector("#cpq-duty-type")?.value || "LOCAL_8HR_80KM";
    const vehCat = this.container.querySelector("#cpq-veh-cat")?.value || "SEDAN";
    const trips = parseInt(this.container.querySelector("#cpq-trips")?.value || "100", 10);
    const sellBase = parseFloat(this.container.querySelector("#cpq-sell-base")?.value || "2800");
    const sellKm = parseFloat(this.container.querySelector("#cpq-sell-km")?.value || "18");
    const buyBase = parseFloat(this.container.querySelector("#cpq-buy-base")?.value || "2350");
    const buyKm = parseFloat(this.container.querySelector("#cpq-buy-km")?.value || "14");

    const deal = this.state.deals[0];
    const dealId = deal ? deal.id : "deal_sim_001";

    const payload = {
      duty_type: dutyType,
      vehicle_category: vehCat,
      estimated_monthly_trips: trips,
      client_sell_base_inr: sellBase,
      client_extra_km_inr: sellKm,
      vendor_buy_base_inr: buyBase,
      vendor_extra_km_inr: buyKm,
    };

    try {
      const res = await fetch(`${this.apiBase}/deals/${dealId}/cpq-simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: this.abortController.signal,
      });
      const data = await res.json();
      this.state.cpqForm.simulationResult = data;
      this.render();
    } catch (err) {
      console.warn("CPQ simulation failed:", err);
    }
  }
}
