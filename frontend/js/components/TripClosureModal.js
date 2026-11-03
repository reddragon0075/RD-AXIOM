/**
 * Axiom Mobility (Fleetline) - Trip Closure & Discrepancy Resolution Modal.
 *
 * Implements:
 * 1. Path A: Standard Driver App Auto-Close (DRIVER_APP_AUTO).
 * 2. Path B: Physical Trip-Sheet Upload & Discrepancy Override (PHYSICAL_TRIPSHEET_OVERRIDE).
 * 3. 3-Column Comparison Table:
 *    - Column 1: Theoretical (Estimated Baseline)
 *    - Column 2: Driver App Telemetry Captured
 *    - Column 3: Practical Operator Entry (Editable Inputs)
 * 4. Paper Duty Slip Upload Zone + Mock/Simulation OCR Auto-Extract Button.
 * 5. Live Pricing Preview Strip with Auto-Slab Recalculation & Margin Guardrail.
 * 6. Submit Gate: Blocks closing if discrepancy flagged without trip-sheet proof.
 */

export class TripClosureModal {
  constructor(options = {}) {
    this.dutyId = options.dutyId || "duty_demo_01";
    this.container = options.container || null;
    this.apiBase = options.apiBase || "/api/v1";
    this.onClosed = options.onClosed || (() => {});
    this.onDismiss = options.onDismiss || (() => {});

    this.isOpen = false;
    this.isSubmitting = false;

    // Internal State
    this.state = {
      duty: {
        id: this.dutyId,
        booking_reference: "BK-BLR-8491",
        customer_name: "Infosys Limited",
        passenger_name: "Vikram Malhotra",
        driver_name: "Ramesh Kumar (+91 98765 43210)",
        vehicle_plate: "KA-01-MJ-4412 (Maruti Dzire)",

        // Column 1: Theoretical
        estimated_distance_km: 40.0,
        estimated_duration_mins: 240, // 4 hours
        estimated_client_fare_inr: 1500.0,
        estimated_supplier_payout_inr: 1200.0,

        // Column 2: App Captured
        app_captured_start_km: 1000.0,
        app_captured_end_km: 1038.5,
        app_gps_distance_km: 37.2,
        app_status: "⚠️ GPS Dropout / Mismatch",
      },

      // Column 3: Practical Editable Inputs
      practical: {
        start_km: 1000.0,
        end_km: 1074.0,
        start_time: "2026-11-03T09:00",
        end_time: "2026-11-03T13:00",
        toll_parking_inr: 0.0,
      },

      // Discrepancy & Proof State
      hasDiscrepancyToggle: false,
      closingSource: "DRIVER_APP_AUTO", // "DRIVER_APP_AUTO" | "PHYSICAL_TRIPSHEET_OVERRIDE"
      discrepancyReason: "GPS Signal Lost",
      physicalTripsheetUrl: null,
      isOcrExtracting: false,
      ocrConfidence: null,

      // Live Recalculated Pricing Preview
      recalculated: {
        billable_km: 74.0,
        duration_mins: 270,
        final_client_fare: 2350.0,
        final_supplier_payout: 1880.0,
        variance_delta: 850.0,
        slab_label: "4Hr/40Km Standard + Extra Km",
      },

      errorMessage: null,
      successMessage: null,
    };
  }

  mount() {
    this.isOpen = true;
    if (!this.container) {
      let modalHost = document.getElementById("trip-closure-modal-host");
      if (!modalHost) {
        modalHost = document.createElement("div");
        modalHost.id = "trip-closure-modal-host";
        document.body.appendChild(modalHost);
      }
      this.container = modalHost;
    }
    this.injectStyles();
    this.recalculateLivePricing();
    this.render();
    this.attachEventListeners();
  }

  unmount() {
    this.isOpen = false;
    if (this.container) {
      this.container.innerHTML = "";
    }
    this.onDismiss();
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("trip-closure-modal-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "trip-closure-modal-styles";
    styleEl.textContent = `
      .closure-modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.85);
        backdrop-filter: blur(6px);
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 16px;
      }
      .closure-modal-window {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 16px;
        width: 100%;
        max-width: 820px;
        max-height: 90vh;
        overflow-y: auto;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
        color: #f8fafc;
        display: flex;
        flex-direction: column;
      }
      .closure-modal-header {
        padding: 16px 20px;
        border-bottom: 1px solid #334155;
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #0f172a;
      }
      .closure-title {
        font-size: 16px;
        font-weight: 700;
        color: #f8fafc;
      }
      .closure-subtitle {
        font-size: 12px;
        color: #94a3b8;
      }
      .comparison-table-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1.3fr;
        gap: 12px;
        padding: 16px 20px;
        background: #111827;
        border-bottom: 1px solid #1e293b;
      }
      .comp-col {
        background: #1e293b;
        border-radius: 10px;
        padding: 12px;
        border: 1px solid #334155;
      }
      .comp-col-header {
        font-size: 11px;
        font-weight: 800;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .comp-row {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        padding: 4px 0;
        color: #cbd5e1;
      }
      .comp-row strong {
        color: #fff;
      }
      .comp-input {
        background: #0f172a;
        border: 1px solid #475569;
        border-radius: 6px;
        color: #f8fafc;
        padding: 6px 8px;
        font-size: 12px;
        width: 100%;
        margin-top: 2px;
      }
      .comp-input:focus {
        outline: none;
        border-color: #38bdf8;
      }
      .discrepancy-section {
        padding: 16px 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .toggle-bar {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 10px 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
      }
      .upload-zone {
        border: 2px dashed #475569;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        background: #0f172a;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
      }
      .upload-zone:hover {
        border-color: #38bdf8;
      }
      .live-preview-strip {
        background: linear-gradient(135deg, #1e3a8a, #0f172a);
        border: 1px solid #3b82f6;
        border-radius: 10px;
        padding: 12px 16px;
        margin: 0 20px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .preview-val-box {
        display: flex;
        flex-direction: column;
      }
      .preview-label {
        font-size: 11px;
        font-weight: 700;
        color: #93c5fd;
      }
      .preview-val {
        font-size: 18px;
        font-weight: 800;
        color: #fff;
      }
      .variance-pill {
        background: #065f46;
        color: #6ee7b7;
        font-size: 11px;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 9999px;
      }
      .closure-modal-footer {
        padding: 14px 20px;
        border-top: 1px solid #334155;
        background: #0f172a;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 12px;
      }
      .btn-cancel {
        background: #334155;
        border: none;
        color: #f8fafc;
        font-weight: 600;
        font-size: 13px;
        padding: 8px 16px;
        border-radius: 8px;
        cursor: pointer;
      }
      .btn-confirm-close {
        background: #2563eb;
        border: none;
        color: #ffffff;
        font-weight: 700;
        font-size: 13px;
        padding: 8px 18px;
        border-radius: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .btn-confirm-close:disabled {
        background: #475569;
        color: #94a3b8;
        cursor: not-allowed;
      }
    `;
    document.head.appendChild(styleEl);
  }

  recalculateLivePricing() {
    const startKm = parseFloat(this.state.practical.start_km) || 0.0;
    const endKm = parseFloat(this.state.practical.end_km) || 0.0;
    const billableKm = Math.max(0.0, Math.round((endKm - startKm) * 10) / 10);

    // Duration calculation
    let durMins = 240;
    try {
      const d1 = new Date(this.state.practical.start_time);
      const d2 = new Date(this.state.practical.end_time);
      if (!isNaN(d1) && !isNaN(d2) && d2 >= d1) {
        durMins = Math.max(15, Math.round((d2 - d1) / 60000));
      }
    } catch (e) {
      durMins = 240;
    }

    const toll = parseFloat(this.state.practical.toll_parking_inr) || 0.0;

    // Standard slab 4H/40K (₹1,500 base, ₹25/extra km)
    const extraKm4 = Math.max(0.0, billableKm - 40.0);
    const extraHrs4 = Math.max(0.0, (durMins / 60.0) - 4.0);
    const cost4 = 1500.0 + Math.ceil(extraKm4) * 25.0 + Math.ceil(extraHrs4) * 150.0;

    // Higher slab 8H/80K (₹2,500 base)
    const cost8 = 2500.0 + Math.ceil(Math.max(0.0, billableKm - 80.0)) * 25.0 + Math.ceil(Math.max(0.0, (durMins / 60.0) - 8.0)) * 150.0;

    let chosenFare = cost4;
    let slabLabel = "4Hr/40Km Standard Slab";

    if (cost8 < cost4 && billableKm >= 65) {
      chosenFare = cost8;
      slabLabel = "8Hr/80Km Slab (Auto-Upgraded)";
    }

    const finalClient = chosenFare + toll;
    const finalSupplier = (chosenFare * 0.80) + toll;
    const variance = finalClient - this.state.duty.estimated_client_fare_inr;

    this.state.recalculated = {
      billable_km: billableKm,
      duration_mins: durMins,
      final_client_fare: Math.round(finalClient * 100) / 100,
      final_supplier_payout: Math.round(finalSupplier * 100) / 100,
      variance_delta: Math.round(variance * 100) / 100,
      slab_label: slabLabel,
    };
  }

  triggerOcrExtraction() {
    this.state.isOcrExtracting = true;
    this.render();

    setTimeout(() => {
      // Simulate OCR auto-extraction from scanned duty slip
      this.state.practical.start_km = 1000.0;
      this.state.practical.end_km = 1074.0;
      this.state.practical.toll_parking_inr = 150.0;
      this.state.physicalTripsheetUrl = "https://supabase.axiomfleet.in/storage/v1/object/public/trip-sheets/duty_blr_signed_slip.jpg";
      this.state.isOcrExtracting = false;
      this.state.ocrConfidence = "98.5% OCR Match";
      this.recalculateLivePricing();
      this.render();
    }, 800);
  }

  handleFileUpload(file) {
    if (!file) return;
    // Mock Supabase storage upload
    this.state.physicalTripsheetUrl = `https://supabase.axiomfleet.in/storage/v1/object/public/trip-sheets/${Date.now()}_${file.name}`;
    this.state.errorMessage = null;
    this.render();
  }

  async submitClosure() {
    const { hasDiscrepancyToggle, closingSource, discrepancyReason, physicalTripsheetUrl, practical } = this.state;

    // Check submit gate
    if ((hasDiscrepancyToggle || closingSource === "PHYSICAL_TRIPSHEET_OVERRIDE") && !physicalTripsheetUrl) {
      this.state.errorMessage = "422 PHYSICAL_TRIPSHEET_PROOF_REQUIRED: Please upload the signed physical paper slip.";
      this.render();
      return;
    }

    this.isSubmitting = true;
    this.render();

    try {
      const payload = {
        practical_start_km: parseFloat(practical.start_km),
        practical_end_km: parseFloat(practical.end_km),
        practical_start_time: practical.start_time,
        practical_end_time: practical.end_time,
        toll_parking_inr: parseFloat(practical.toll_parking_inr) || 0.0,
        closing_source: hasDiscrepancyToggle ? "PHYSICAL_TRIPSHEET_OVERRIDE" : "DRIVER_APP_AUTO",
        has_discrepancy: hasDiscrepancyToggle,
        discrepancy_reason: hasDiscrepancyToggle ? discrepancyReason : null,
        physical_tripsheet_file_url: physicalTripsheetUrl,
      };

      const res = await fetch(`${this.apiBase}/duties/${this.dutyId}/close-practical`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Failed to close trip");
      }

      this.state.successMessage = "Trip successfully reconciled and closed! Final invoice annexure attached.";
      this.render();

      setTimeout(() => {
        this.onClosed(data);
        this.unmount();
      }, 1200);
    } catch (err) {
      this.state.errorMessage = err.message || "Error submitting trip closure.";
      this.isSubmitting = false;
      this.render();
    }
  }

  render() {
    if (!this.container || !this.isOpen) return;

    const { duty, practical, hasDiscrepancyToggle, discrepancyReason, physicalTripsheetUrl, recalculated, isOcrExtracting, ocrConfidence, errorMessage, successMessage } = this.state;

    const isGateLocked = (hasDiscrepancyToggle || this.state.closingSource === "PHYSICAL_TRIPSHEET_OVERRIDE") && !physicalTripsheetUrl;

    this.container.innerHTML = `
      <div class="closure-modal-backdrop" id="modal-backdrop">
        <div class="closure-modal-window">
          <!-- Header -->
          <div class="closure-modal-header">
            <div>
              <div class="closure-title">Reconcile & Close Duty: ${duty.id}</div>
              <div class="closure-subtitle">${duty.customer_name} · ${duty.passenger_name} · ${duty.vehicle_plate}</div>
            </div>
            <button id="btn-close-modal" style="background: none; border: none; color: #94a3b8; font-size: 20px; cursor: pointer;">✕</button>
          </div>

          <!-- Error / Success Alert -->
          ${errorMessage ? `<div style="background: #7f1d1d; color: #fecaca; padding: 10px 20px; font-size: 12px; font-weight: 600;">⚠️ ${errorMessage}</div>` : ""}
          ${successMessage ? `<div style="background: #065f46; color: #a7f3d0; padding: 10px 20px; font-size: 12px; font-weight: 600;">✅ ${successMessage}</div>` : ""}

          <!-- 3-Column Comparison Table -->
          <div class="comparison-table-grid">
            <!-- Col 1: Theoretical -->
            <div class="comp-col">
              <div class="comp-col-header">
                <span>📘 Theoretical (Estimated)</span>
              </div>
              <div class="comp-row"><span>Distance:</span> <strong>${duty.estimated_distance_km} km</strong></div>
              <div class="comp-row"><span>Duration:</span> <strong>${duty.estimated_duration_mins} mins</strong></div>
              <div class="comp-row"><span>Client Fare:</span> <strong>₹${duty.estimated_client_fare_inr.toLocaleString()}</strong></div>
              <div class="comp-row"><span>Driver Payout:</span> <strong>₹${duty.estimated_supplier_payout_inr.toLocaleString()}</strong></div>
              <div style="font-size: 10px; color: #94a3b8; margin-top: 8px;">Locked baseline created at booking dispatch.</div>
            </div>

            <!-- Col 2: App Captured -->
            <div class="comp-col" style="border-color: #f59e0b;">
              <div class="comp-col-header" style="color: #fbbf24;">
                <span>📱 Driver App Captured</span>
              </div>
              <div class="comp-row"><span>Start Odo:</span> <strong>${duty.app_captured_start_km} km</strong></div>
              <div class="comp-row"><span>End Odo:</span> <strong>${duty.app_captured_end_km} km</strong></div>
              <div class="comp-row"><span>App Delta:</span> <strong>${Math.round((duty.app_captured_end_km - duty.app_captured_start_km) * 10) / 10} km</strong></div>
              <div class="comp-row"><span>GPS Road:</span> <strong>${duty.app_gps_distance_km} km</strong></div>
              <div style="font-size: 11px; color: #f59e0b; font-weight: 700; margin-top: 8px;">${duty.app_status}</div>
            </div>

            <!-- Col 3: Practical Operator Entry -->
            <div class="comp-col" style="border-color: #38bdf8;">
              <div class="comp-col-header" style="color: #38bdf8;">
                <span>✍️ Practical Operator Entry</span>
              </div>
              <div>
                <label style="font-size: 10px; color: #94a3b8;">Start Km</label>
                <input type="number" step="0.1" class="comp-input" id="inp-practical-start-km" value="${practical.start_km}" />
              </div>
              <div style="margin-top: 4px;">
                <label style="font-size: 10px; color: #94a3b8;">End Km</label>
                <input type="number" step="0.1" class="comp-input" id="inp-practical-end-km" value="${practical.end_km}" />
              </div>
              <div style="margin-top: 4px;">
                <label style="font-size: 10px; color: #94a3b8;">Tolls / Parking (₹)</label>
                <input type="number" class="comp-input" id="inp-practical-toll" value="${practical.toll_parking_inr}" />
              </div>
              <div style="display: flex; gap: 4px; margin-top: 4px;">
                <div style="flex: 1;">
                  <label style="font-size: 10px; color: #94a3b8;">Start Time</label>
                  <input type="datetime-local" class="comp-input" id="inp-practical-start-time" value="${practical.start_time}" />
                </div>
                <div style="flex: 1;">
                  <label style="font-size: 10px; color: #94a3b8;">End Time</label>
                  <input type="datetime-local" class="comp-input" id="inp-practical-end-time" value="${practical.end_time}" />
                </div>
              </div>
            </div>
          </div>

          <!-- Discrepancy & Separate Trip-Sheet Toggle -->
          <div class="discrepancy-section">
            <div class="toggle-bar" id="btn-toggle-discrepancy">
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="checkbox" id="chk-discrepancy" ${hasDiscrepancyToggle ? "checked" : ""} style="cursor: pointer;" />
                <span style="font-size: 13px; font-weight: 700;">📄 Driver Sent Separate Physical Trip Sheet / Discrepancy</span>
              </div>
              <span style="font-size: 11px; color: #94a3b8;">${hasDiscrepancyToggle ? "Override Mode Active" : "Click to Enable Override"}</span>
            </div>

            <!-- Revealed Discrepancy & Proof Upload Zone -->
            ${
              hasDiscrepancyToggle
                ? `
              <div style="background: #111827; border: 1px solid #f59e0b; border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <label style="font-size: 12px; font-weight: 700; color: #fbbf24;">Discrepancy Reason (Mandatory):</label>
                  <select id="select-discrepancy-reason" class="comp-input" style="width: auto;">
                    <option value="GPS Signal Lost" ${discrepancyReason === "GPS Signal Lost" ? "selected" : ""}>GPS Signal Lost / Basement Parking</option>
                    <option value="App Not Used by Sub-Vendor Driver" ${discrepancyReason === "App Not Used by Sub-Vendor Driver" ? "selected" : ""}>App Not Used by Sub-Vendor Driver</option>
                    <option value="Client Extended Route" ${discrepancyReason === "Client Extended Route" ? "selected" : ""}>Client Extended Route / Detour</option>
                    <option value="Odometer Photo Blur" ${discrepancyReason === "Odometer Photo Blur" ? "selected" : ""}>Odometer Photo Blur / Phone Died</option>
                  </select>
                </div>

                <!-- Upload Zone -->
                <div class="upload-zone" id="upload-dropzone">
                  <span style="font-size: 24px;">📸</span>
                  <div style="font-size: 12px; font-weight: 600;">
                    ${physicalTripsheetUrl ? `✅ Paper Slip Attached: ${physicalTripsheetUrl.split("/").pop()}` : "Tap or Drag & Drop Signed Physical Paper Slip (JPG/PNG/PDF)"}
                  </div>
                  <input type="file" id="file-tripsheet" accept="image/*,application/pdf" style="display: none;" />
                </div>

                <!-- OCR Auto-Extract Button -->
                <div style="display: flex; align-items: center; justify-content: space-between;">
                  <button id="btn-ocr-extract" style="background: #0284c7; border: none; color: #fff; font-size: 11px; font-weight: 700; padding: 6px 12px; border-radius: 6px; cursor: pointer;" ${isOcrExtracting ? "disabled" : ""}>
                    ${isOcrExtracting ? "⏳ Extracting Odometer & Tolls..." : "✨ Auto-Extract from Photo (OCR)"}
                  </button>
                  ${ocrConfidence ? `<span style="font-size: 11px; color: #34d399; font-weight: 700;">${ocrConfidence}</span>` : ""}
                </div>
              </div>
            `
                : ""
            }
          </div>

          <!-- Live Pricing Preview Strip -->
          <div class="live-preview-strip">
            <div class="preview-val-box">
              <span class="preview-label">PRACTICAL BILLABLE</span>
              <span class="preview-val">${recalculated.billable_km} km</span>
              <span style="font-size: 11px; color: #cbd5e1;">${recalculated.slab_label}</span>
            </div>

            <div class="preview-val-box">
              <span class="preview-label">FINAL CLIENT BILL</span>
              <span class="preview-val" style="color: #38bdf8;">₹${recalculated.final_client_fare.toLocaleString()}</span>
              <span style="font-size: 11px; color: #94a3b8;">Est: ₹${duty.estimated_client_fare_inr.toLocaleString()}</span>
            </div>

            <div class="preview-val-box">
              <span class="preview-label">SUPPLIER PAYOUT</span>
              <span class="preview-val" style="color: #34d399;">₹${recalculated.final_supplier_payout.toLocaleString()}</span>
              <span style="font-size: 11px; color: #94a3b8;">Net Margin: ₹${Math.round((recalculated.final_client_fare - recalculated.final_supplier_payout) * 100) / 100}</span>
            </div>

            <div>
              <span class="variance-pill">
                ${recalculated.variance_delta >= 0 ? "+" : ""}₹${recalculated.variance_delta.toLocaleString()} vs Est
              </span>
            </div>
          </div>

          <!-- Footer Actions & Submit Gate -->
          <div class="closure-modal-footer">
            <button class="btn-cancel" id="btn-cancel-modal">Cancel</button>
            <button class="btn-confirm-close" id="btn-confirm-close" ${isGateLocked || this.isSubmitting ? "disabled" : ""}>
              ${this.isSubmitting ? "Processing..." : "Confirm & Close Trip"}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    if (!this.container) return;

    // 1. Input field listeners for live price recalculation
    const handleInputChange = () => {
      const startInp = this.container.querySelector("#inp-practical-start-km");
      const endInp = this.container.querySelector("#inp-practical-end-km");
      const tollInp = this.container.querySelector("#inp-practical-toll");
      const startTimeInp = this.container.querySelector("#inp-practical-start-time");
      const endTimeInp = this.container.querySelector("#inp-practical-end-time");

      if (startInp) this.state.practical.start_km = parseFloat(startInp.value) || 0;
      if (endInp) this.state.practical.end_km = parseFloat(endInp.value) || 0;
      if (tollInp) this.state.practical.toll_parking_inr = parseFloat(tollInp.value) || 0;
      if (startTimeInp) this.state.practical.start_time = startTimeInp.value;
      if (endTimeInp) this.state.practical.end_time = endTimeInp.value;

      this.recalculateLivePricing();
      this.render();
    };

    this.container.addEventListener("input", (evt) => {
      if (evt.target.classList.contains("comp-input")) {
        handleInputChange();
      }
    });

    this.container.addEventListener("click", (evt) => {
      // Close / cancel
      if (evt.target.id === "btn-close-modal" || evt.target.id === "btn-cancel-modal" || evt.target.id === "modal-backdrop") {
        this.unmount();
        return;
      }

      // Discrepancy toggle
      if (evt.target.closest("#btn-toggle-discrepancy") || evt.target.id === "chk-discrepancy") {
        this.state.hasDiscrepancyToggle = !this.state.hasDiscrepancyToggle;
        this.state.closingSource = this.state.hasDiscrepancyToggle ? "PHYSICAL_TRIPSHEET_OVERRIDE" : "DRIVER_APP_AUTO";
        this.render();
        return;
      }

      // Upload dropzone click
      if (evt.target.closest("#upload-dropzone")) {
        const fileInp = this.container.querySelector("#file-tripsheet");
        if (fileInp) fileInp.click();
        return;
      }

      // OCR extract button
      if (evt.target.id === "btn-ocr-extract") {
        this.triggerOcrExtraction();
        return;
      }

      // Confirm and close button
      if (evt.target.id === "btn-confirm-close") {
        this.submitClosure();
        return;
      }
    });

    this.container.addEventListener("change", (evt) => {
      if (evt.target.id === "select-discrepancy-reason") {
        this.state.discrepancyReason = evt.target.value;
      }
      if (evt.target.id === "file-tripsheet" && evt.target.files?.length) {
        this.handleFileUpload(evt.target.files[0]);
      }
    });
  }
}
