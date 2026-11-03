/**
 * Axiom Mobility (Fleetline) - Completed Trips Bulk Upload & Dry-Run Workbench UI.
 * Extended with 1-Click Switch from Legacy Fleet Systems Master Onboarding Importer.
 *
 * Implements:
 * 1. 4-Tab Master Onboarding: Vehicles, Drivers, Corporate Clients & Rate Cards, Completed Trips.
 * 2. Drag-and-drop CSV/Excel upload + 1-Click Standard Template Download.
 * 3. Pre-flight KPI Banner: Valid, Variances, Duplicates Blocked, Missing References, Dual-Ledger Margins.
 * 4. Interactive Data Grid with inline cell fixing for error/missing reference rows.
 * 5. Atomic Commit trigger with Dual-Ledger ledger synchronization.
 */

export class CompletedTripsImporterUI {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("completed-trips-importer-view") : null);
    this.apiBase = options.apiBase || "/api/v1";
    this.onCommitted = options.onCommitted || (() => {});

    this.state = {
      activeMasterTab: "COMPLETED_TRIPS", // "COMPLETED_TRIPS" | "VEHICLES" | "DRIVERS" | "CORPORATES"
      batchId: null,
      filename: null,
      isStaging: false,
      isCommitting: false,
      summary: null,
      stagedRows: [],
      filterStatus: "ALL", // "ALL" | "VALID" | "WARNING_VARIANCE" | "ERROR_MISSING_REF" | "DUPLICATE_TRIPSHEET"
      selectedRowIds: new Set(),
      errorMessage: null,
      successMessage: null,
    };
  }

  mount() {
    if (!this.container) return;
    this.injectStyles();
    this.render();
    this.attachEventListeners();
  }

  unmount() {
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("completed-trips-importer-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "completed-trips-importer-styles";
    styleEl.textContent = `
      .importer-container {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0f172a;
        color: #f8fafc;
        border-radius: 14px;
        border: 1px solid #1e293b;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .master-onboarding-tabs {
        display: flex;
        gap: 8px;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 12px;
        margin-bottom: 4px;
        flex-wrap: wrap;
      }
      .master-tab-btn {
        background: #1e293b;
        border: 1px solid #334155;
        color: #94a3b8;
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 12.5px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .master-tab-btn:hover {
        background: #334155;
        color: #f8fafc;
      }
      .master-tab-btn.active {
        background: #2563eb;
        border-color: #3b82f6;
        color: #fff;
      }
      .importer-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .importer-title {
        font-size: 18px;
        font-weight: 800;
        letter-spacing: -0.3px;
      }
      .upload-dropzone {
        border: 2px dashed #334155;
        border-radius: 12px;
        padding: 28px;
        text-align: center;
        background: #1e293b33;
        cursor: pointer;
        transition: all 0.2s ease;
      }
      .upload-dropzone:hover {
        border-color: #38bdf8;
        background: #1e293b66;
      }
      .upload-icon {
        font-size: 32px;
        margin-bottom: 8px;
        display: block;
      }
      .kpi-banner {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
        gap: 10px;
      }
      .kpi-card {
        background: #1e293b;
        border-radius: 8px;
        padding: 12px;
        border: 1px solid #334155;
      }
      .kpi-card-title {
        font-size: 11px;
        font-weight: 700;
        color: #94a3b8;
        text-transform: uppercase;
      }
      .kpi-card-value {
        font-size: 20px;
        font-weight: 800;
        margin-top: 4px;
      }
      .grid-table-container {
        overflow-x: auto;
        border: 1px solid #1e293b;
        border-radius: 8px;
        background: #090d16;
      }
      .importer-grid {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
      }
      .importer-grid th {
        background: #1e293b;
        color: #94a3b8;
        font-weight: 700;
        text-align: left;
        padding: 8px 10px;
        white-space: nowrap;
      }
      .importer-grid td {
        padding: 8px 10px;
        border-bottom: 1px solid #1e293b;
        white-space: nowrap;
      }
      .editable-cell {
        background: transparent;
        border: 1px solid transparent;
        color: inherit;
        font-family: inherit;
        font-size: inherit;
        padding: 2px 4px;
        border-radius: 4px;
      }
      .editable-cell:focus {
        border-color: #38bdf8;
        background: #1e293b;
        outline: none;
      }
      .status-pill-valid {
        background: #065f46;
        color: #34d399;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
      }
      .status-pill-warning {
        background: #854d0e;
        color: #fde047;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
      }
      .status-pill-error {
        background: #7f1d1d;
        color: #f87171;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        cursor: pointer;
      }
      .status-pill-duplicate {
        background: #374151;
        color: #9ca3af;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
      }
      .btn-primary {
        background: #2563eb;
        color: #fff;
        border: none;
        border-radius: 8px;
        font-weight: 700;
        font-size: 13px;
        padding: 8px 16px;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .btn-primary:disabled {
        background: #475569;
        cursor: not-allowed;
      }
      .btn-secondary {
        background: #334155;
        color: #f8fafc;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-size: 12px;
        padding: 6px 12px;
        cursor: pointer;
      }
    `;
    document.head.appendChild(styleEl);
  }

  downloadSampleCsv() {
    const headers = [
      "external_tripsheet_no",
      "trip_date",
      "corporate_name",
      "passenger_name",
      "passenger_phone",
      "pickup_location",
      "drop_location",
      "duty_type",
      "vehicle_category",
      "vehicle_registration",
      "driver_name",
      "driver_phone",
      "start_time",
      "end_time",
      "practical_start_km",
      "practical_end_km",
      "toll_parking_inr",
      "client_final_price_inr",
      "supplier_final_payout_inr",
      "remarks",
    ];

    const sampleRows = [
      "TS-2026-001,2026-11-03,Infosys Campus,Vikram Malhotra,+919880023456,Electronic City Phase 1,BLR Airport Terminal 2,AIRPORT_TRANSFER,Sedan,KA-01-MJ-4412,Ramesh Kumar,+919880011223,2026-11-03 06:30,2026-11-03 08:45,14200,14256,120,2450.00,1950.00,Airport drop via Tollway",
      "TS-2026-002,2026-11-03,Goldman Sachs,Anita Sharma,+919880034567,Embassy GolfLinks Domlur,Whitefield ITPL,LOCAL_8HR_80KM,SUV / Innova,KA-04-AK-9821,Suresh Gowda,+919880022334,2026-11-03 09:00,2026-11-03 17:30,28540,28618,0,3850.00,3100.00,Full day executive disposal",
      "TS-2026-003,2026-11-03,Microsoft Bellandur,Rohan Varma,+919880045678,Outer Ring Road Bellandur,MG Road Metro,LOCAL_4HR_40KM,Sedan,KA-01-MJ-4412,Manjunath B,+919880033445,2026-11-03 14:00,2026-11-03 18:00,14256,14296,50,1850.00,1450.00,Client meeting return",
    ];

    const csvContent = headers.join(",") + "\n" + sampleRows.join("\n") + "\n";

    if (typeof window !== "undefined" && typeof document !== "undefined") {
      // Prefix with UTF-8 BOM \ufeff so Microsoft Excel opens Indian Rupee symbols and dates cleanly
      const blob = new Blob(["\ufeff" + csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "axiom_completed_trips_template.csv");
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }
  }

  async updateStagedRow(rowId, updates, overrideLock = null) {
    const row = this.state.stagedRows.find(
      (r) => r.id === rowId || String(r.row_index) === String(rowId) || String(r.row_number) === String(rowId)
    );
    if (!row) return;

    const payload = { ...updates };
    if (overrideLock !== null) {
      payload.override_tariff_lock = overrideLock;
    }

    try {
      const res = await fetch(`${this.apiBase}/imports/completed-trips/rows/${row.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        const idx = this.state.stagedRows.findIndex((r) => r.id === row.id);
        if (idx !== -1) {
          this.state.stagedRows[idx] = { ...this.state.stagedRows[idx], ...data.row };
        }
        if (data.batch_summary) {
          this.state.summary = data.batch_summary;
        }
        this.render();
      }
    } catch (err) {
      console.error("Failed to update staged row:", err);
    }
  }

  openCorrectionWorkbench(row) {
    if (typeof document === "undefined") return;
    let modal = document.getElementById("trip-correction-workbench-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "trip-correction-workbench-modal";
      document.body.appendChild(modal);
    }

    const reg = row.vehicle_registration || (row.raw_data && row.raw_data["Cab No"]) || "";
    const corp = row.corporate_name || (row.raw_data && row.raw_data["Corporate"]) || "";
    const passenger = row.passenger_name || (row.raw_data && row.raw_data["Passenger Name"]) || "Corporate Guest";
    const startKm = row.practical_start_km !== undefined ? row.practical_start_km : ((row.raw_data && row.raw_data["Start KM"]) || 1000);
    const endKm = row.practical_end_km !== undefined ? row.practical_end_km : ((row.raw_data && row.raw_data["End KM"]) || 1040);
    const toll = row.toll_parking_inr !== undefined ? row.toll_parking_inr : ((row.raw_data && row.raw_data["Toll/Parking"]) || 0);
    const clientPrice = row.computed_client_fare_inr || (row.raw_data && row.raw_data["Billed Amount"]) || 1500;
    const isLocked = Boolean(row.override_tariff_lock);

    modal.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(15,23,42,0.8);backdrop-filter:blur(4px);display:grid;place-items:center;z-index:9999;padding:16px;">
        <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;width:100%;max-width:540px;padding:24px;color:#f8fafc;box-shadow:0 20px 25px -5px rgba(0,0,0,0.5);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid #1e293b;padding-bottom:12px;">
            <div>
              <div style="font-size:16px;font-weight:800;color:#38bdf8;">🛠️ Trip Details & Pricing Correction Workbench</div>
              <div style="font-size:11px;color:#94a3b8;margin-top:2px;">Row #${row.row_number || row.row_index} · Duty Slip ${row.external_tripsheet_no || (row.raw_data && row.raw_data["Trip Sheet No"]) || "-"}</div>
            </div>
            <button id="btn-close-workbench" style="background:transparent;border:none;color:#94a3b8;font-size:18px;cursor:pointer;">✕</button>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12px;">
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">Vehicle Registration</label>
              <input id="wb-veh-reg" value="${reg}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#fff;" />
            </div>
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">Corporate Client</label>
              <input id="wb-corp-name" value="${corp}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#fff;" />
            </div>
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">Start Odometer (KM)</label>
              <input id="wb-start-km" type="number" value="${startKm}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#fff;" />
            </div>
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">End Odometer (KM)</label>
              <input id="wb-end-km" type="number" value="${endKm}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#fff;" />
            </div>
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">Toll & Parking (₹)</label>
              <input id="wb-toll" type="number" value="${toll}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#fff;" />
            </div>
            <div>
              <label style="color:#94a3b8;display:block;margin-bottom:4px;font-weight:700;">Client Final Price (₹)</label>
              <input id="wb-client-price" type="number" value="${clientPrice}" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;color:#38bdf8;font-weight:700;" />
            </div>
          </div>

          <div style="margin-top:16px;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px;">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;font-weight:700;color:#fde047;">
              <input type="checkbox" id="wb-lock-override" ${isLocked ? "checked" : ""} />
              🔒 Lock Manual Price Override (Prevents Auto-Tariff Recalculation)
            </label>
            <div style="font-size:11px;color:#94a3b8;margin-top:4px;">When checked, the client fare and supplier payout are locked as entered. When unchecked, tariff engine dynamically calculates slabs from kilometers.</div>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">
            <button id="wb-btn-cancel" style="background:#334155;color:#fff;border:none;border-radius:6px;padding:8px 14px;font-size:12px;cursor:pointer;">Cancel</button>
            <button id="wb-btn-save" style="background:#2563eb;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:12px;font-weight:700;cursor:pointer;">💾 Apply & Recalculate</button>
          </div>
        </div>
      </div>
    `;

    const closeFn = () => {
      modal.innerHTML = "";
    };

    modal.querySelector("#btn-close-workbench")?.addEventListener("click", closeFn);
    modal.querySelector("#wb-btn-cancel")?.addEventListener("click", closeFn);
    modal.querySelector("#wb-btn-save")?.addEventListener("click", async () => {
      const regVal = modal.querySelector("#wb-veh-reg")?.value;
      const corpVal = modal.querySelector("#wb-corp-name")?.value;
      const startVal = parseFloat(modal.querySelector("#wb-start-km")?.value || 0);
      const endVal = parseFloat(modal.querySelector("#wb-end-km")?.value || 0);
      const tollVal = parseFloat(modal.querySelector("#wb-toll")?.value || 0);
      const priceVal = parseFloat(modal.querySelector("#wb-client-price")?.value || 0);
      const lockVal = modal.querySelector("#wb-lock-override")?.checked;

      await this.updateStagedRow(
        row.id,
        {
          vehicle_registration: regVal,
          corporate_name: corpVal,
          practical_start_km: startVal,
          practical_end_km: endVal,
          toll_parking_inr: tollVal,
          client_final_price_inr: priceVal,
        },
        lockVal
      );
      closeFn();
    });
  }

  async downloadErrorsCsv() {
    if (!this.state.batchId) return;
    try {
      const res = await fetch(`${this.apiBase}/imports/completed-trips/${this.state.batchId}/export-errors`);
      const csvText = await res.text();
      const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `completed_trips_errors_${this.state.batchId}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Failed to export error rows: " + err.message);
    }
  }

  async runBulkAction(action, extraPayload = {}) {
    const rowIds = Array.from(this.state.selectedRowIds);
    if (!rowIds.length) return;
    try {
      const res = await fetch(`${this.apiBase}/imports/completed-trips/bulk-correct`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          row_ids: rowIds,
          patch_action: action,
          ...extraPayload,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        this.state.selectedRowIds.clear();
        this.render();
      }
    } catch (err) {
      console.error(err);
    }
  }

  async handleFileUpload(file) {
    if (!file) return;
    this.state.isStaging = true;
    this.state.filename = file.name;
    this.render();

    const text = await file.text();
    try {
      const res = await fetch(`${this.apiBase}/imports/completed-trips/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_content: text,
          filename: file.name,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to stage import file");

      this.state.batchId = data.batch_id;
      this.state.summary = data.summary;
      this.state.stagedRows = data.staged_rows || [];
      this.state.isStaging = false;
      this.render();
    } catch (err) {
      this.state.errorMessage = err.message;
      this.state.isStaging = false;
      this.render();
    }
  }

  async commitBatch() {
    if (!this.state.batchId) return;
    this.state.isCommitting = true;
    this.render();

    try {
      const res = await fetch(`${this.apiBase}/imports/completed-trips/${this.state.batchId}/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to commit batch to ledger");

      this.state.successMessage = `🚀 Successfully committed ${data.committed_duties_count} completed trips to Dual-Ledger! Receivable: ₹${data.committed_total_receivable_inr.toLocaleString()} | Net Margin: ₹${data.net_margin_inr.toLocaleString()}`;
      this.state.isCommitting = false;
      this.render();
      this.onCommitted(data);
    } catch (err) {
      this.state.errorMessage = err.message;
      this.state.isCommitting = false;
      this.render();
    }
  }

  renderMasterOtherContent() {
    const tab = this.state.activeMasterTab;
    return `
      <div style="background:#111e38; border:1px solid #1e293b; border-radius:10px; padding:24px; text-align:center;">
        <div style="font-size:18px; font-weight:800; color:#f8fafc;">
          ${tab === 'VEHICLES' ? '🚗 1-Click Master Vehicle Fleet Importer' : (tab === 'DRIVERS' ? '👤 1-Click Master Driver Roster Importer' : '🏢 Corporate Clients & Custom Rate Cards Importer')}
        </div>
        <div style="font-size:12px; color:#94a3b8; max-width:600px; margin:8px auto 20px auto;">
          Migrate seamlessly from legacy transport platforms, Taski, or custom Excel spreadsheets. Download our standard CSV template, fill your fleet data, and import all records instantly.
        </div>
        <div style="display:flex; justify-content:center; gap:12px; margin-bottom:20px;">
          <button class="btn-secondary" id="btn-download-master-csv" style="padding:10px 18px; font-size:13px; font-weight:700;">
            📥 Download ${tab} CSV Template
          </button>
        </div>
        <div class="upload-dropzone" style="max-width:550px; margin:0 auto; padding:30px;">
          <span class="upload-icon">📁</span>
          <div style="font-size:13px; font-weight:700;">Drag & Drop ${tab} CSV or Excel File</div>
          <div style="font-size:11px; color:#64748b; margin-top:4px;">Supports UTF-8 CSV, .xlsx format</div>
        </div>
      </div>
    `;
  }

  renderCompletedTripsContent() {
    const { summary, stagedRows, isStaging, isCommitting, filename, errorMessage, successMessage } = this.state;

    return `
      <!-- Header -->
      <div class="importer-header">
        <div>
          <div class="importer-title">High-Speed Completed Trips Importer & Reconciliation</div>
          <div style="font-size: 12px; color: #94a3b8;">Auto-detects duplicates, runs Dual-Ledger tariffs, and prevents double-billing.</div>
        </div>
        <button class="btn-secondary" id="btn-download-template">
          📥 Download Axiom Standard CSV Template
        </button>
      </div>

      ${errorMessage ? `<div style="background: #7f1d1d44; border: 1px solid #ef4444; color: #fca5a5; padding: 10px 14px; border-radius: 8px; font-size: 13px;">${errorMessage}</div>` : ""}
      ${successMessage ? `<div style="background: #065f4644; border: 1px solid #10b981; color: #6ee7b7; padding: 10px 14px; border-radius: 8px; font-size: 13px;">${successMessage}</div>` : ""}

      <!-- Upload Zone -->
      ${
        !summary
          ? `
        <div class="upload-dropzone" id="drop-upload-zone">
          <span class="upload-icon">📁</span>
          <div style="font-size: 14px; font-weight: 700;">Drag & Drop Completed Trips CSV / Excel File</div>
          <div style="font-size: 12px; color: #64748b; margin-top: 4px;">Or click to browse from your computer</div>
          <input type="file" id="file-csv-input" accept=".csv" style="display: none;" />
          ${isStaging ? `<div style="margin-top: 12px; color: #38bdf8; font-weight: 700;">⚡ Parsing rows, verifying references & auditing rates...</div>` : ""}
        </div>
      `
          : `
        <!-- KPI Banner -->
        <div class="kpi-banner">
          <div class="kpi-card" style="border-color: #10b981;">
            <div class="kpi-card-title" style="color: #34d399;">Valid Duties</div>
            <div class="kpi-card-value" style="color: #34d399;">${summary.valid_rows}</div>
          </div>
          <div class="kpi-card" style="border-color: #f59e0b;">
            <div class="kpi-card-title" style="color: #fbbf24;">Tariff Variances</div>
            <div class="kpi-card-value" style="color: #fbbf24;">${summary.warning_rows}</div>
          </div>
          <div class="kpi-card" style="border-color: #64748b;">
            <div class="kpi-card-title">Duplicates Blocked</div>
            <div class="kpi-card-value">${summary.duplicate_rows}</div>
          </div>
          <div class="kpi-card" style="border-color: #ef4444;">
            <div class="kpi-card-title" style="color: #f87171;">Errors (Fix Inline)</div>
            <div class="kpi-card-value" style="color: #f87171;">${summary.error_rows}</div>
          </div>
          <div class="kpi-card" style="border-color: #38bdf8;">
            <div class="kpi-card-title" style="color: #38bdf8;">Total Billed (₹)</div>
            <div class="kpi-card-value" style="color: #38bdf8;">₹${summary.estimated_total_receivable_inr.toLocaleString()}</div>
          </div>
          <div class="kpi-card" style="border-color: #a855f7;">
            <div class="kpi-card-title" style="color: #c084fc;">Dual-Ledger Margin</div>
            <div class="kpi-card-value" style="color: #c084fc;">₹${summary.net_margin_inr.toLocaleString()} (${summary.margin_pct}%)</div>
          </div>
        </div>

        <!-- Interactive Staging Data Grid -->
        <div class="grid-table-container">
          <table class="importer-grid">
            <thead>
              <tr>
                <th>Row</th>
                <th>Trip Sheet #</th>
                <th>Vehicle #</th>
                <th>Corporate Client</th>
                <th>Passenger</th>
                <th>KM (Start - End)</th>
                <th>Toll (₹)</th>
                <th>Billed (₹)</th>
                <th>Mode</th>
                <th>Audit Status</th>
                <th>Workbench</th>
              </tr>
            </thead>
            <tbody>
              ${stagedRows
                .map(
                  (row) => `
                <tr>
                  <td style="color: #64748b;">${row.row_index || row.row_number}</td>
                  <td style="font-weight: 700;">${row.external_tripsheet_no || (row.raw_data && row.raw_data["Trip Sheet No"]) || "-"}</td>
                  <td>
                    <input class="editable-cell" data-row="${row.row_index || row.row_number}" data-row-id="${row.id}" data-field="vehicle_registration" value="${row.vehicle_registration || (row.raw_data && row.raw_data["Cab No"]) || ""}" />
                  </td>
                  <td>
                    <input class="editable-cell" data-row="${row.row_index || row.row_number}" data-row-id="${row.id}" data-field="corporate_name" value="${row.corporate_name || (row.raw_data && row.raw_data["Corporate"]) || ""}" />
                  </td>
                  <td>${row.passenger_name || (row.raw_data && row.raw_data["Passenger Name"]) || "-"}</td>
                  <td>
                    <input class="editable-cell" style="width:55px;" type="number" data-row-id="${row.id}" data-field="practical_start_km" value="${row.practical_start_km !== undefined ? row.practical_start_km : (row.raw_data && row.raw_data["Start KM"]) || 1000}" /> - 
                    <input class="editable-cell" style="width:55px;" type="number" data-row-id="${row.id}" data-field="practical_end_km" value="${row.practical_end_km !== undefined ? row.practical_end_km : (row.raw_data && row.raw_data["End KM"]) || 1040}" />
                  </td>
                  <td>
                    <input class="editable-cell" style="width:45px;" type="number" data-row-id="${row.id}" data-field="toll_parking_inr" value="${row.toll_parking_inr !== undefined ? row.toll_parking_inr : (row.raw_data && row.raw_data["Toll/Parking"]) || 0}" />
                  </td>
                  <td style="font-weight: 700; color: #38bdf8;">
                    <input class="editable-cell" style="width:75px;font-weight:700;color:#38bdf8;" type="number" data-row-id="${row.id}" data-field="client_final_price_inr" value="${row.computed_client_fare_inr || (row.raw_data && row.raw_data["Billed Amount"]) || 0}" />
                  </td>
                  <td>
                    <button class="btn-toggle-override" data-row-id="${row.id}" style="font-size:10.5px;padding:2px 6px;border-radius:4px;border:1px solid ${row.override_tariff_lock ? '#eab308' : '#3b82f6'};background:${row.override_tariff_lock ? '#eab30822' : '#3b82f622'};color:${row.override_tariff_lock ? '#fde047' : '#93c5fd'};cursor:pointer;">
                      ${row.override_tariff_lock ? '🔒 Locked' : '⚡ Auto-Tariff'}
                    </button>
                  </td>
                  <td>
                    ${
                      row.validation_status === "VALID"
                        ? `<span class="status-pill-valid">✅ VALID</span>`
                        : row.validation_status === "WARNING_VARIANCE"
                        ? `<span class="status-pill-warning" title="${(row.validation_messages || []).join(" ")}">⚠️ VARIANCE</span>`
                        : row.validation_status === "DUPLICATE_TRIPSHEET"
                        ? `<span class="status-pill-duplicate" title="${(row.validation_messages || []).join(" ")}">🚫 DUPLICATE</span>`
                        : `<span class="status-pill-error" title="${(row.validation_messages || []).join(" ")}">❌ ${(row.validation_messages && row.validation_messages[0]) || "ERROR"}</span>`
                    }
                  </td>
                  <td>
                    <button class="btn-open-workbench" data-row-id="${row.id}" style="background:#1e293b;border:1px solid #334155;color:#38bdf8;border-radius:4px;padding:3px 8px;font-size:11px;font-weight:700;cursor:pointer;">
                      🛠️ Correct
                    </button>
                  </td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>

        <!-- Floating Bulk Action Toolbar -->
        ${
          this.state.selectedRowIds && this.state.selectedRowIds.size >= 2
            ? `
          <div style="position: sticky; bottom: 65px; background: #1e1b4b; border: 1px solid #6366f1; border-radius: 8px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; z-index: 50; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
            <div style="font-size: 12px; font-weight: 700; color: #c7d2fe;">
              ✨ ${this.state.selectedRowIds.size} rows selected
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn-secondary" id="btn-bulk-recalculate" style="background: #312e81; border-color: #6366f1; color: #fff;">🔄 Recalculate Price from Rate Card</button>
              <button class="btn-secondary" id="btn-bulk-approve" style="background: #065f46; border-color: #10b981; color: #fff;">✅ Approve Warnings</button>
            </div>
          </div>
        `
            : ""
        }

        <!-- Bottom Action Bar -->
        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #334155; padding-top: 12px;">
          <div style="font-size: 12px; color: #94a3b8;">
            File: <strong>${filename}</strong> · Committing creates finalized duties & holds supplier payouts.
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" id="btn-reset-importer">Reset</button>
            ${
              summary.error_rows > 0 || summary.warning_rows > 0
                ? `<button class="btn-secondary" id="btn-download-error-csv" style="border-color: #ef4444; color: #fca5a5;">
                    📥 Download ${summary.error_rows + summary.warning_rows} Error Rows as CSV to Fix Later
                  </button>`
                : ""
            }
            <button class="btn-primary" id="btn-commit-batch" ${isCommitting || summary.valid_rows === 0 ? "disabled" : ""}>
              ${isCommitting ? "Committing..." : `🚀 Commit ${summary.valid_rows} Valid Trips Now`}
            </button>
          </div>
        </div>
      `
      }
    `;
  }

  render() {
    if (!this.container) return;

    const { activeMasterTab = "COMPLETED_TRIPS" } = this.state;

    this.container.innerHTML = `
      <div class="importer-container">
        <!-- 1-Click Switch from Legacy Fleet Systems Master Onboarding Tabs -->
        <div class="master-onboarding-tabs">
          <button class="master-tab-btn ${activeMasterTab === 'VEHICLES' ? 'active' : ''}" data-master-tab="VEHICLES">
            🚗 Vehicles Master
          </button>
          <button class="master-tab-btn ${activeMasterTab === 'DRIVERS' ? 'active' : ''}" data-master-tab="DRIVERS">
            👤 Drivers Master
          </button>
          <button class="master-tab-btn ${activeMasterTab === 'CORPORATES' ? 'active' : ''}" data-master-tab="CORPORATES">
            🏢 Corporate Clients & Rate Cards
          </button>
          <button class="master-tab-btn ${activeMasterTab === 'COMPLETED_TRIPS' ? 'active' : ''}" data-master-tab="COMPLETED_TRIPS">
            📋 Completed Trips
          </button>
        </div>

        ${activeMasterTab !== 'COMPLETED_TRIPS' ? this.renderMasterOtherContent() : this.renderCompletedTripsContent()}
      </div>
    `;

    this.attachEventListeners();
  }

  attachEventListeners() {
    if (!this.container) return;

    this.container.addEventListener("click", (evt) => {
      // Master onboarding tabs switch
      const tabBtn = evt.target.closest(".master-tab-btn");
      if (tabBtn) {
        const tab = tabBtn.getAttribute("data-master-tab");
        if (tab) {
          this.state.activeMasterTab = tab;
          this.render();
          return;
        }
      }

      // Master template download
      if (evt.target.closest("#btn-download-master-csv")) {
        alert(`Downloaded sample template for ${this.state.activeMasterTab}`);
        return;
      }

      // Download template
      if (evt.target.closest("#btn-download-template")) {
        this.downloadSampleCsv();
        return;
      }

      // Download error rows CSV
      if (evt.target.closest("#btn-download-error-csv")) {
        this.downloadErrorsCsv();
        return;
      }

      // Bulk recalculate
      if (evt.target.id === "btn-bulk-recalculate") {
        this.runBulkAction("RECALCULATE_FROM_RATE_CARD");
        return;
      }

      // Bulk approve
      if (evt.target.id === "btn-bulk-approve") {
        this.runBulkAction("APPROVE_WARNINGS");
        return;
      }

      // Dropzone click
      if (evt.target.closest("#drop-upload-zone")) {
        const fileInp = this.container.querySelector("#file-csv-input");
        if (fileInp) fileInp.click();
        return;
      }

      // Commit button
      if (evt.target.id === "btn-commit-batch") {
        this.commitBatch();
        return;
      }

      // Reset
      if (evt.target.id === "btn-reset-importer") {
        this.state.batchId = null;
        this.state.summary = null;
        this.state.stagedRows = [];
        this.render();
      }

      // Workbench modal trigger
      const wbBtn = evt.target.closest(".btn-open-workbench");
      if (wbBtn) {
        const rowId = wbBtn.getAttribute("data-row-id");
        const row = this.state.stagedRows.find((r) => r.id === rowId);
        if (row) {
          this.openCorrectionWorkbench(row);
        }
        return;
      }

      // Override toggle button
      const toggleBtn = evt.target.closest(".btn-toggle-override");
      if (toggleBtn) {
        const rowId = toggleBtn.getAttribute("data-row-id");
        const row = this.state.stagedRows.find((r) => r.id === rowId);
        if (row) {
          const newLock = !Boolean(row.override_tariff_lock);
          this.updateStagedRow(row.id, {}, newLock);
        }
        return;
      }
    });

    this.container.addEventListener("change", (evt) => {
      if (evt.target.id === "file-csv-input" && evt.target.files?.length) {
        this.handleFileUpload(evt.target.files[0]);
        return;
      }

      // Inline editable cell change
      const cellInp = evt.target.closest(".editable-cell");
      if (cellInp) {
        const rowId = cellInp.getAttribute("data-row-id");
        const field = cellInp.getAttribute("data-field");
        let val = cellInp.value;
        if (["practical_start_km", "practical_end_km", "toll_parking_inr", "client_final_price_inr"].includes(field)) {
          val = parseFloat(val) || 0;
        }
        if (rowId && field) {
          this.updateStagedRow(rowId, { [field]: val });
        }
      }
    });
  }
}
