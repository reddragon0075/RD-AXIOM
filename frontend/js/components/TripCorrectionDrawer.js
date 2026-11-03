/**
 * Axiom Mobility (Fleetline) - Split-View Trip Correction Drawer & Image Inspector.
 *
 * Implements:
 * 1. Split-Pane Layout (720px expandable width):
 *    - Left Pane: Interactive Trip-Sheet / Odometer Photo Loupe (Zoom, Rotate 90°, High Contrast).
 *    - Right Pane: Comprehensive Odometer, Time, Toll, and Pricing Adjustment Workbench.
 * 2. Live Odometer Continuity Feedback (Continuous OK, Rollback Error, High Dead Mileage Gap).
 * 3. Dynamic Mode Switching:
 *    - Unbilled / Open Trips -> Standard Duty Details & Pricing Update (/api/v1/duties/{id}/trip-details)
 *    - Invoiced Trips (FINALIZED_IRN) -> Post-Invoice Credit/Debit Note Generator (/api/v1/duties/{id}/post-invoice-adjustment)
 */

export class TripCorrectionDrawer {
  constructor(options = {}) {
    this.duty = options.duty || {};
    this.apiBase = options.apiBase || "/api/v1";
    this.onSaved = options.onSaved || (() => {});
    this.onClose = options.onClose || (() => {});

    this.container = null;
    this.state = {
      zoomLevel: 1.0,
      rotationDeg: 0,
      highContrast: false,
      isSaving: false,
      errorMessage: null,
      successMessage: null,

      // Form state
      startKm: this.duty.practical_start_km ?? this.duty.start_odometer ?? 1000,
      endKm: this.duty.practical_end_km ?? this.duty.end_odometer ?? 1040,
      startTime: this.duty.practical_start_time || this.duty.started_at || "",
      endTime: this.duty.practical_end_time || this.duty.completed_at || "",
      tollParking: this.duty.toll_parking_inr || 0,
      clientFare: this.duty.final_client_fare_inr || 1500,
      supplierPayout: this.duty.final_supplier_payout_inr || 1200,
      overrideLock: Boolean(this.duty.override_tariff_lock),
      remarks: "",

      // Invoice status
      isInvoiced: Boolean(
        this.duty.invoice_status === "FINALIZED_IRN" ||
        this.duty.invoice_status === "invoiced" ||
        this.duty.invoice_status === "billed" ||
        this.duty.invoice_id
      ),
      originalInvoicedFare: this.duty.final_client_fare_inr || 1500,
    };
  }

  open(hostElement = null) {
    this.mount(hostElement);
  }

  close() {
    this.unmount();
    this.onClose();
  }

  mount(hostElement = null) {
    if (typeof document === "undefined") return;

    let host = hostElement || document.getElementById("trip-correction-drawer-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "trip-correction-drawer-host";
      document.body.appendChild(host);
    }
    this.container = host;
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
    if (document.getElementById("trip-correction-drawer-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "trip-correction-drawer-styles";
    styleEl.textContent = `
      .drawer-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.75);
        backdrop-filter: blur(4px);
        z-index: 9998;
        display: flex;
        justify-content: flex-end;
      }
      .drawer-pane {
        background: #0f172a;
        width: 100%;
        max-width: 780px;
        height: 100%;
        border-left: 1px solid #334155;
        box-shadow: -10px 0 30px rgba(0,0,0,0.6);
        display: flex;
        flex-direction: column;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }
      .drawer-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid #1e293b;
      }
      .drawer-body {
        flex: 1;
        display: grid;
        grid-template-columns: 1fr 1fr;
        overflow-y: auto;
      }
      .image-inspector-pane {
        background: #090d16;
        border-right: 1px solid #1e293b;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .inspector-toolbar {
        display: flex;
        gap: 6px;
        padding: 10px 14px;
        background: #1e293b;
        border-bottom: 1px solid #334155;
      }
      .inspector-btn {
        background: #334155;
        color: #f8fafc;
        border: 1px solid #475569;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .inspector-btn:hover {
        background: #475569;
      }
      .image-viewport {
        flex: 1;
        overflow: auto;
        display: grid;
        place-items: center;
        padding: 16px;
        background: #020617;
      }
      .inspected-image {
        max-width: 100%;
        transition: transform 0.2s ease, filter 0.2s ease;
        border-radius: 6px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
      }
      .correction-form-pane {
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        overflow-y: auto;
      }
      .continuity-badge {
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 700;
        display: inline-flex;
        align-items: center;
        gap: 5px;
      }
      .continuity-ok { background: #065f4633; border: 1px solid #10b981; color: #34d399; }
      .continuity-gap { background: #854d0e33; border: 1px solid #eab308; color: #fde047; }
      .continuity-rollback { background: #7f1d1d33; border: 1px solid #ef4444; color: #f87171; }
      .invoiced-alert {
        background: #1e1b4b;
        border: 1px solid #6366f1;
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 11.5px;
        color: #c7d2fe;
      }
    `;
    document.head.appendChild(styleEl);
  }

  calculateContinuityFeedback() {
    const { startKm } = this.state;
    const prevEnd = this.duty.prev_duty_end_km;
    if (prevEnd === undefined || prevEnd === null) {
      return { status: "FIRST", label: "🟢 First vehicle duty recorded", cls: "continuity-ok" };
    }
    const gap = roundNumber(startKm - prevEnd, 1);
    if (startKm < prevEnd) {
      return { status: "ROLLBACK", label: `🔴 Odometer Rollback (-${prevEnd - startKm} km vs Prev Trip)`, cls: "continuity-rollback" };
    }
    if (gap > 50) {
      return { status: "GAP", label: `🟠 +${gap} km Unaccounted Gap vs Prev Trip`, cls: "continuity-gap" };
    }
    return { status: "OK", label: `🟢 Continuous (+${gap} km from prev trip)`, cls: "continuity-ok" };
  }

  render() {
    if (!this.container) return;

    const { duty } = this;
    const {
      zoomLevel,
      rotationDeg,
      highContrast,
      startKm,
      endKm,
      tollParking,
      clientFare,
      overrideLock,
      isInvoiced,
      originalInvoicedFare,
      isSaving,
      errorMessage,
      successMessage,
    } = this.state;

    const billableKm = Math.max(0, endKm - startKm);
    const continuity = this.calculateContinuityFeedback();

    const photoUrl =
      duty.physical_tripsheet_file_url ||
      duty.odometer_photo_url ||
      "https://images.unsplash.com/photo-1580273916550-e323be2ae537?auto=format&fit=crop&w=800&q=80";

    const deltaFare = roundNumber(clientFare - originalInvoicedFare, 2);

    this.container.innerHTML = `
      <div class="drawer-backdrop" id="drawer-backdrop">
        <div class="drawer-pane">
          <!-- Header -->
          <div class="drawer-header">
            <div>
              <div style="font-size: 16px; font-weight: 800; color: #38bdf8;">
                🛠️ Split-View Trip & Pricing Correction Workbench
              </div>
              <div style="font-size: 11.5px; color: #94a3b8; margin-top: 2px;">
                Duty ${duty.id || "DT-001"} ${duty.external_tripsheet_no ? `(#${duty.external_tripsheet_no})` : ""} · Vehicle ${duty.vehicle_registration || duty.vehicle_plate || "KA-01-MJ-4412"} · Client ${duty.corporate_name || duty.customer_name || "Corporate Account"}
              </div>
            </div>
            <button id="btn-close-drawer" style="background:transparent;border:none;color:#94a3b8;font-size:20px;cursor:pointer;">✕</button>
          </div>

          ${errorMessage ? `<div style="background:#7f1d1d44;border-bottom:1px solid #ef4444;color:#fca5a5;padding:8px 16px;font-size:12px;">${errorMessage}</div>` : ""}
          ${successMessage ? `<div style="background:#065f4644;border-bottom:1px solid #10b981;color:#6ee7b7;padding:8px 16px;font-size:12px;">${successMessage}</div>` : ""}

          <!-- Body -->
          <div class="drawer-body">
            <!-- Left Pane: Image Loupe -->
            <div class="image-inspector-pane">
              <div class="inspector-toolbar">
                <button class="inspector-btn" id="btn-zoom-in">🔍 Zoom +</button>
                <button class="inspector-btn" id="btn-zoom-out">🔍 Zoom -</button>
                <button class="inspector-btn" id="btn-rotate">↻ Rotate 90°</button>
                <button class="inspector-btn" id="btn-contrast" style="${highContrast ? "background:#2563eb;color:#fff;" : ""}">
                  🔆 High Contrast
                </button>
                <div style="margin-left:auto;font-size:11px;color:#94a3b8;display:flex;align-items:center;">
                  ${Math.round(zoomLevel * 100)}% · ${rotationDeg}°
                </div>
              </div>
              <div class="image-viewport">
                <img
                  src="${photoUrl}"
                  alt="Physical Trip Sheet / Odometer Proof"
                  class="inspected-image"
                  style="transform: scale(${zoomLevel}) rotate(${rotationDeg}deg); filter: ${highContrast ? "contrast(180%) brightness(90%)" : "none"};"
                />
              </div>
            </div>

            <!-- Right Pane: Correction Form -->
            <div class="correction-form-pane">
              ${
                isInvoiced
                  ? `
                <div class="invoiced-alert">
                  <strong>🔒 Locked in Finalized GST Invoice (${duty.invoice_id || "INV-FINAL"})</strong>
                  <div style="margin-top: 3px;">
                    This trip is attached to invoice <strong>${duty.invoice_id || "INV-FINAL"}</strong>. Modifying pricing will automatically issue an official <strong>${deltaFare < 0 ? "Credit Note" : "Debit Note"}</strong> without altering the sealed invoice.
                  </div>
                </div>
              `
                  : ""
              }

              <!-- Odometer Section -->
              <div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                  <label style="font-weight:700;font-size:12px;color:#94a3b8;">Odometer Continuity Audit</label>
                  <span class="continuity-badge ${continuity.cls}">${continuity.label}</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                  <div>
                    <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">Start KM</label>
                    <input id="input-start-km" type="number" class="editable-cell" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px;color:#fff;font-weight:700;" value="${startKm}" />
                  </div>
                  <div>
                    <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">End KM</label>
                    <input id="input-end-km" type="number" class="editable-cell" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px;color:#fff;font-weight:700;" value="${endKm}" />
                  </div>
                </div>
                <div style="font-size:11px;color:#38bdf8;margin-top:4px;font-weight:700;">
                  Billable Distance: ${billableKm} km
                </div>
              </div>

              <!-- Toll & Parking -->
              <div>
                <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">Toll & Parking Charges (₹)</label>
                <input id="input-toll" type="number" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px;color:#fff;" value="${tollParking}" />
              </div>

              <!-- Rate Card / Price Mode -->
              <div style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;font-weight:700;color:#fde047;">
                  <input type="checkbox" id="check-override-lock" ${overrideLock ? "checked" : ""} />
                  🔒 Lock Manual Price Override
                </label>
                <div style="font-size:11px;color:#94a3b8;margin-top:4px;">
                  Uncheck to automatically re-evaluate tariff from distance and corporate rate cards.
                </div>
                <div style="margin-top:10px;">
                  <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">Final Client Price (₹)</label>
                  <input id="input-client-price" type="number" style="width:100%;background:#090d16;border:1px solid #334155;border-radius:6px;padding:6px;color:#38bdf8;font-size:14px;font-weight:800;" value="${clientFare}" />
                </div>
                ${
                  isInvoiced && deltaFare !== 0
                    ? `
                  <div style="margin-top:8px;font-size:11.5px;color:${deltaFare < 0 ? "#34d399" : "#fbbf24"};font-weight:700;">
                    ${deltaFare < 0 ? `🧾 Credit Note: ₹${Math.abs(deltaFare).toFixed(2)} refund to client` : `🧾 Debit Note: ₹${deltaFare.toFixed(2)} supplementary bill to client`}
                  </div>
                `
                    : ""
                }
              </div>

              <!-- Remarks -->
              <div>
                <label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px;">Adjustment Reason / Audit Notes</label>
                <textarea id="input-remarks" rows="2" style="width:100%;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px;color:#fff;font-size:11px;" placeholder="e.g. Corrected odometer based on legible handwritten slip"></textarea>
              </div>

              <!-- Action Bar -->
              <div style="margin-top:auto;display:flex;gap:8px;justify-content:flex-end;">
                <button id="btn-cancel-drawer" style="background:#334155;color:#fff;border:none;border-radius:6px;padding:8px 14px;font-size:12px;cursor:pointer;">Cancel</button>
                <button id="btn-save-drawer" style="background:#2563eb;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:12px;font-weight:700;cursor:pointer;" ${isSaving ? "disabled" : ""}>
                  ${isSaving ? "Processing..." : isInvoiced ? "🧾 Issue Credit/Debit Note Adjustment" : "💾 Save Trip Corrections"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    this.attachEventListeners();
  }

  attachEventListeners() {
    if (!this.container) return;

    // Close
    this.container.querySelector("#btn-close-drawer")?.addEventListener("click", () => this.onClose());
    this.container.querySelector("#btn-cancel-drawer")?.addEventListener("click", () => this.onClose());
    this.container.querySelector("#drawer-backdrop")?.addEventListener("click", (evt) => {
      if (evt.target.id === "drawer-backdrop") this.onClose();
    });

    // Inspector buttons
    this.container.querySelector("#btn-zoom-in")?.addEventListener("click", () => {
      this.state.zoomLevel = Math.min(3.0, roundNumber(this.state.zoomLevel + 0.25, 2));
      this.render();
    });
    this.container.querySelector("#btn-zoom-out")?.addEventListener("click", () => {
      this.state.zoomLevel = Math.max(0.5, roundNumber(this.state.zoomLevel - 0.25, 2));
      this.render();
    });
    this.container.querySelector("#btn-rotate")?.addEventListener("click", () => {
      this.state.rotationDeg = (this.state.rotationDeg + 90) % 360;
      this.render();
    });
    this.container.querySelector("#btn-contrast")?.addEventListener("click", () => {
      this.state.highContrast = !this.state.highContrast;
      this.render();
    });

    // Inputs
    const startInp = this.container.querySelector("#input-start-km");
    const endInp = this.container.querySelector("#input-end-km");
    const tollInp = this.container.querySelector("#input-toll");
    const clientPriceInp = this.container.querySelector("#input-client-price");
    const lockCheck = this.container.querySelector("#check-override-lock");

    startInp?.addEventListener("change", (e) => {
      this.state.startKm = parseFloat(e.target.value) || 0;
      this.render();
    });
    endInp?.addEventListener("change", (e) => {
      this.state.endKm = parseFloat(e.target.value) || 0;
      this.render();
    });
    tollInp?.addEventListener("change", (e) => {
      this.state.tollParking = parseFloat(e.target.value) || 0;
    });
    clientPriceInp?.addEventListener("change", (e) => {
      this.state.clientFare = parseFloat(e.target.value) || 0;
      this.render();
    });
    lockCheck?.addEventListener("change", (e) => {
      this.state.overrideLock = e.target.checked;
      this.render();
    });

    // Save Action
    this.container.querySelector("#btn-save-drawer")?.addEventListener("click", async () => {
      await this.saveAdjustments();
    });
  }

  async saveAdjustments() {
    this.state.isSaving = true;
    this.render();

    const { isInvoiced, startKm, endKm, tollParking, clientFare, overrideLock } = this.state;
    const dutyId = this.duty.id;
    const remarks = this.container.querySelector("#input-remarks")?.value || "Adjusted via Split-View Drawer";

    try {
      const endpoint = isInvoiced
        ? `${this.apiBase}/duties/${dutyId}/post-invoice-adjustment`
        : `${this.apiBase}/duties/${dutyId}/trip-details`;

      const payload = {
        practical_start_km: startKm,
        practical_end_km: endKm,
        toll_parking_inr: tollParking,
        final_client_fare_inr: clientFare,
        client_final_price_inr: clientFare,
        override_tariff_lock: overrideLock,
        remarks,
      };

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to save adjustments");

      this.state.isSaving = false;
      this.state.successMessage = isInvoiced
        ? `✅ Generated ${data.note_type} (${data.note_number}) for ₹${data.delta_amount_inr}!`
        : "✅ Successfully saved trip corrections!";
      this.render();
      this.onSaved(data);
    } catch (err) {
      this.state.isSaving = false;
      this.state.errorMessage = err.message;
      this.render();
    }
  }
}

function roundNumber(num, dec = 2) {
  return Math.round(num * Math.pow(10, dec)) / Math.pow(10, dec);
}
