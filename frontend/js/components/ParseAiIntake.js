/**
 * Axiom Mobility (Fleetline) - "Parse AI" Unstructured Booking Intake Drawer.
 * Zero-Build Vanilla ES6+ Component.
 *
 * Implements:
 * 1. Split-pane layout: Raw WhatsApp/email message intake on the left;
 *    Extracted structured booking preview with confidence metrics on the right.
 * 2. Instant sample templates for 1-click test drive (Airport Transfer, 8hr Package, Outstation).
 * 3. Integrated OpenStreetMap route preview & Theoretical Fare calculation.
 * 4. 1-Click "Confirm & Create Booking" with theoretical baselines locked.
 */

export class ParseAiIntake {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("parse-ai-intake-view") : null);
    this.apiBase = options.apiBase || "/api/v1";
    this.onBookingCreated = options.onBookingCreated || (() => {});

    this.state = {
      rawText: "",
      isParsing: false,
      isCreating: false,
      parsedData: null,
      errorMessage: null,
      createdBooking: null,
    };

    this.sampleTemplates = [
      {
        label: "✈️ Airport Drop (Rohan)",
        text: "Please book a sedan for Rohan Deshmukh (9845012345, rohan.d@infosys.com) tomorrow 6:30 AM from Koramangala 4th Block to BLR Kempegowda Airport for flight 6E-204. Need clean cab.",
      },
      {
        label: "⏱️ 8hr/80km Package (Priya)",
        text: "Duty for Priya Sharma (+91 9988776655) on 04 Nov 9:00 AM. 8hr 80km corporate local duty from Whitefield Tech Park to Electronic City Phase 1. Vehicle: Innova Crysta. Billing to Wipro.",
      },
      {
        label: "🛣️ Outstation Mysore (Vikram)",
        text: "Outstation round trip to Mysore for Vikram Malhotra 9822334455 tonight 10 PM. Pickup from 100ft Road Indiranagar to Royal Orchid Mysore. Sedan required.",
      },
    ];
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
    if (document.getElementById("parse-ai-intake-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "parse-ai-intake-styles";
    styleEl.textContent = `
      .parse-ai-container {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0b132b;
        color: #f8fafc;
        border-radius: 14px;
        border: 1px solid #1e293b;
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 20px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.4);
      }
      .parse-ai-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #1e293b;
        padding-bottom: 16px;
      }
      .parse-ai-title {
        font-size: 20px;
        font-weight: 800;
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .parse-ai-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
      }
      @media (max-width: 900px) {
        .parse-ai-grid {
          grid-template-columns: 1fr;
        }
      }
      .parse-ai-pane {
        background: #111e38;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 18px;
        display: flex;
        flex-direction: column;
        gap: 14px;
      }
      .parse-ai-textarea {
        width: 100%;
        min-height: 160px;
        background: #070d1d;
        border: 1px solid #334155;
        border-radius: 8px;
        color: #f1f5f9;
        padding: 12px;
        font-size: 13.5px;
        font-family: inherit;
        resize: vertical;
        box-sizing: border-box;
      }
      .parse-ai-textarea:focus {
        outline: none;
        border-color: #38bdf8;
      }
      .template-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .template-pill {
        background: #1e293b;
        border: 1px solid #334155;
        color: #94a3b8;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 11.5px;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .template-pill:hover {
        background: #334155;
        color: #f8fafc;
      }
      .parse-btn-primary {
        background: linear-gradient(135deg, #0284c7, #2563eb);
        color: white;
        border: none;
        padding: 10px 18px;
        border-radius: 8px;
        font-size: 13.5px;
        font-weight: 700;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
      }
      .parse-btn-confirm {
        background: linear-gradient(135deg, #10b981, #059669);
        color: white;
        border: none;
        padding: 12px 20px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 800;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
      }
      .parse-ai-field {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .parse-ai-label {
        font-size: 11px;
        text-transform: uppercase;
        color: #94a3b8;
        font-weight: 700;
      }
      .parse-ai-input {
        background: #070d1d;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 8px 10px;
        color: #f8fafc;
        font-size: 12.5px;
        width: 100%;
        box-sizing: border-box;
      }
      .confidence-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 750;
      }
      .confidence-high { background: rgba(16, 185, 129, 0.2); color: #34d399; }
      .confidence-mid { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
      .confidence-low { background: rgba(239, 68, 68, 0.2); color: #f87171; }
      .theo-metric-box {
        background: #070d1d;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
    `;
    document.head.appendChild(styleEl);
  }

  render() {
    if (!this.container) return;

    const { rawText, isParsing, isCreating, parsedData, errorMessage, createdBooking } = this.state;

    this.container.innerHTML = `
      <div class="parse-ai-container">
        <div class="parse-ai-header">
          <div>
            <div class="parse-ai-title">
              <span>⚡</span> Parse AI — WhatsApp & Email Intake Engine
            </div>
            <div style="font-size:12px; color:#94a3b8; margin-top:4px;">
              Zero-effort dispatch: Paste unstructured client booking messages and get geocoded, priced duties in seconds.
            </div>
          </div>
          <div style="font-size:11px; color:#38bdf8; background:rgba(56,189,248,0.1); padding:6px 12px; border-radius:6px; border:1px solid rgba(56,189,248,0.2);">
            OpenStreetMap & OSRM Powered
          </div>
        </div>

        ${errorMessage ? `<div style="background:rgba(239,68,68,0.15); border:1px solid #ef4444; color:#fca5a5; padding:10px 14px; border-radius:6px; font-size:12.5px;">${errorMessage}</div>` : ""}

        ${createdBooking ? `
          <div style="background:rgba(16,185,129,0.15); border:1px solid #10b981; color:#6ee7b7; padding:14px; border-radius:8px; font-size:13px; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <strong>✅ Booking Created Successfully:</strong> #${createdBooking.id || createdBooking.booking_id}
              <div style="font-size:11.5px; color:#a7f3d0; margin-top:4px;">
                Passenger: ${createdBooking.passenger_name} | Est: ${createdBooking.estimated_distance_km} km | ₹${createdBooking.estimated_client_fare_inr}
              </div>
            </div>
            <button id="btn-parse-another" style="background:#10b981; color:#0f172a; border:none; padding:8px 14px; border-radius:6px; font-weight:700; cursor:pointer;">
              + Parse Another Booking
            </button>
          </div>
        ` : ""}

        <div class="parse-ai-grid">
          <!-- LEFT PANE: RAW INTAKE -->
          <div class="parse-ai-pane">
            <div style="font-size:13px; font-weight:750; color:#cbd5e1; display:flex; justify-content:space-between;">
              <span>1. Paste Unstructured Message</span>
              <span style="font-size:11px; color:#64748b;">WhatsApp, Email or SMS</span>
            </div>

            <textarea id="parse-ai-raw-input" class="parse-ai-textarea" placeholder="Paste WhatsApp booking text, email thread, or client flight instructions here...">${rawText}</textarea>

            <div>
              <div style="font-size:11px; color:#94a3b8; font-weight:700; margin-bottom:6px;">QUICK TEST TEMPLATES:</div>
              <div class="template-pills">
                ${this.sampleTemplates.map((t, idx) => `
                  <button class="template-pill" data-template-idx="${idx}">${t.label}</button>
                `).join("")}
              </div>
            </div>

            <button id="btn-run-parse" class="parse-btn-primary" ${isParsing ? "disabled" : ""}>
              ${isParsing ? "⏳ Extracting & Geocoding..." : "✨ Parse Booking Details"}
            </button>
          </div>

          <!-- RIGHT PANE: EXTRACTED STRUCTURED PREVIEW -->
          <div class="parse-ai-pane">
            <div style="font-size:13px; font-weight:750; color:#cbd5e1; display:flex; justify-content:space-between; align-items:center;">
              <span>2. Extracted Booking & Theoretical Estimate</span>
              ${parsedData ? `
                <span class="confidence-badge ${parsedData.confidence >= 0.8 ? "confidence-high" : (parsedData.confidence >= 0.5 ? "confidence-mid" : "confidence-low")}">
                  🟢 ${(parsedData.confidence * 100).toFixed(0)}% Confidence
                </span>
              ` : `<span style="font-size:11px; color:#64748b;">Awaiting extraction</span>`}
            </div>

            ${!parsedData ? `
              <div style="text-align:center; padding:40px 20px; color:#64748b; font-size:13px;">
                Paste a booking on the left and click <strong>"Parse Booking Details"</strong> to preview geocoded addresses, road distance, and theoretical tariffs.
              </div>
            ` : `
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div class="parse-ai-field">
                  <span class="parse-ai-label">Passenger Name</span>
                  <input id="field-passenger-name" class="parse-ai-input" value="${parsedData.passenger_name || ""}" />
                </div>
                <div class="parse-ai-field">
                  <span class="parse-ai-label">Phone Number</span>
                  <input id="field-passenger-phone" class="parse-ai-input" value="${parsedData.passenger_phone || ""}" />
                </div>
              </div>

              <div class="parse-ai-field">
                <span class="parse-ai-label">Pickup Date & Time</span>
                <input id="field-pickup-datetime" class="parse-ai-input" value="${parsedData.pickup_datetime || ""}" />
              </div>

              <div class="parse-ai-field">
                <span class="parse-ai-label">Pickup Location (Geocoded)</span>
                <input id="field-pickup-address" class="parse-ai-input" value="${parsedData.pickup_address_raw || ""}" />
              </div>

              <div class="parse-ai-field">
                <span class="parse-ai-label">Drop Location (Geocoded)</span>
                <input id="field-drop-address" class="parse-ai-input" value="${parsedData.drop_address_raw || ""}" />
              </div>

              <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div class="parse-ai-field">
                  <span class="parse-ai-label">Vehicle Category</span>
                  <select id="field-vehicle-cat" class="parse-ai-input">
                    <option value="SEDAN" ${parsedData.vehicle_category_hint === "SEDAN" ? "selected" : ""}>Sedan (Dzire/Etios)</option>
                    <option value="SUV_CRYSTA" ${parsedData.vehicle_category_hint === "SUV_CRYSTA" ? "selected" : ""}>Innova Crysta</option>
                    <option value="LUXURY" ${parsedData.vehicle_category_hint === "LUXURY" ? "selected" : ""}>Luxury (Camry/Mercedes)</option>
                    <option value="TEMPO_TRAVELLER" ${parsedData.vehicle_category_hint === "TEMPO_TRAVELLER" ? "selected" : ""}>Tempo Traveller</option>
                  </select>
                </div>
                <div class="parse-ai-field">
                  <span class="parse-ai-label">Duty Type</span>
                  <select id="field-duty-type" class="parse-ai-input">
                    <option value="AIRPORT_TRANSFER" ${parsedData.duty_type === "AIRPORT_TRANSFER" ? "selected" : ""}>Airport Transfer</option>
                    <option value="LOCAL_4HR_40KM" ${parsedData.duty_type === "LOCAL_4HR_40KM" ? "selected" : ""}>Local 4hr / 40km</option>
                    <option value="LOCAL_8HR_80KM" ${parsedData.duty_type === "LOCAL_8HR_80KM" ? "selected" : ""}>Local 8hr / 80km</option>
                    <option value="OUTSTATION" ${parsedData.duty_type === "OUTSTATION" ? "selected" : ""}>Outstation</option>
                  </select>
                </div>
              </div>

              <div class="theo-metric-box">
                <div>
                  <div style="font-size:10px; color:#38bdf8; font-weight:700;">THEORETICAL DISTANCE & TIME</div>
                  <div style="font-size:15px; font-weight:800; color:#f8fafc; margin-top:2px;">
                    ${parsedData.estimated_distance_km} km | ${parsedData.estimated_duration_mins} mins
                  </div>
                </div>
                <div style="text-align:right;">
                  <div style="font-size:10px; color:#34d399; font-weight:700;">THEORETICAL ESTIMATE</div>
                  <div style="font-size:16px; font-weight:800; color:#34d399; margin-top:2px;">
                    ₹${parsedData.estimated_client_fare_inr.toLocaleString()}
                  </div>
                </div>
              </div>

              <button id="btn-confirm-create" class="parse-btn-confirm" ${isCreating ? "disabled" : ""}>
                ${isCreating ? "⏳ Creating Booking..." : "⚡ Confirm & Create Booking"}
              </button>
            `}
          </div>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    if (!this.container) return;

    // Template clicks
    this.container.querySelectorAll(".template-pill").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const idx = parseInt(e.target.getAttribute("data-template-idx"), 10);
        const template = this.sampleTemplates[idx];
        if (template) {
          this.state.rawText = template.text;
          const textarea = this.container.querySelector("#parse-ai-raw-input");
          if (textarea) textarea.value = template.text;
        }
      });
    });

    // Parse button click
    const runBtn = this.container.querySelector("#btn-run-parse");
    if (runBtn) {
      runBtn.addEventListener("click", () => this.handleParse());
    }

    // Textarea input sync
    const textarea = this.container.querySelector("#parse-ai-raw-input");
    if (textarea) {
      textarea.addEventListener("input", (e) => {
        this.state.rawText = e.target.value;
      });
    }

    // Confirm button click
    const confirmBtn = this.container.querySelector("#btn-confirm-create");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", () => this.handleConfirmCreate());
    }

    // Parse another click
    const parseAnotherBtn = this.container.querySelector("#btn-parse-another");
    if (parseAnotherBtn) {
      parseAnotherBtn.addEventListener("click", () => {
        this.state.createdBooking = null;
        this.state.parsedData = null;
        this.state.rawText = "";
        this.render();
        this.attachEventListeners();
      });
    }
  }

  async handleParse() {
    const raw = (this.state.rawText || "").trim();
    if (!raw) {
      this.state.errorMessage = "Please enter or paste a message to parse.";
      this.render();
      this.attachEventListeners();
      return;
    }

    this.state.isParsing = true;
    this.state.errorMessage = null;
    this.render();
    this.attachEventListeners();

    try {
      const res = await fetch(`${this.apiBase}/bookings/parse-unstructured`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: raw }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || "Failed to parse booking message");
      }

      const data = await res.json();
      this.state.parsedData = data;
    } catch (err) {
      this.state.errorMessage = err.message || "Failed to connect to parser service";
    } finally {
      this.state.isParsing = false;
      this.render();
      this.attachEventListeners();
    }
  }

  async handleConfirmCreate() {
    if (!this.state.parsedData) return;

    this.state.isCreating = true;
    this.state.errorMessage = null;
    this.render();
    this.attachEventListeners();

    // Read current form values
    const p = this.state.parsedData;
    const nameInput = this.container.querySelector("#field-passenger-name");
    const phoneInput = this.container.querySelector("#field-passenger-phone");
    const dtInput = this.container.querySelector("#field-pickup-datetime");
    const pickupInput = this.container.querySelector("#field-pickup-address");
    const dropInput = this.container.querySelector("#field-drop-address");
    const vehCatInput = this.container.querySelector("#field-vehicle-cat");
    const dutyTypeInput = this.container.querySelector("#field-duty-type");

    const bookingPayload = {
      passenger_name: nameInput ? nameInput.value : p.passenger_name,
      passenger_phone: phoneInput ? phoneInput.value : p.passenger_phone,
      passenger_email: p.passenger_email,
      pickup_time: dtInput ? dtInput.value : p.pickup_datetime,
      pickup_address: pickupInput ? pickupInput.value : p.pickup_address_raw,
      drop_address: dropInput ? dropInput.value : p.drop_address_raw,
      vehicle_category: vehCatInput ? vehCatInput.value : p.vehicle_category_hint,
      duty_type: dutyTypeInput ? dutyTypeInput.value : p.duty_type,
      estimated_distance_km: p.estimated_distance_km,
      estimated_duration_mins: p.estimated_duration_mins,
      estimated_client_fare_inr: p.estimated_client_fare_inr,
      estimated_supplier_payout_inr: p.estimated_supplier_payout_inr,
      flight_number: p.flight_number,
      special_instructions: p.special_instructions,
      source: "PARSE_AI",
    };

    try {
      const res = await fetch("/api/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bookingPayload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || "Failed to create booking in database");
      }

      const created = await res.json();
      this.state.createdBooking = { ...bookingPayload, ...created };
      this.onBookingCreated(this.state.createdBooking);
    } catch (err) {
      this.state.errorMessage = err.message || "Failed to save booking";
    } finally {
      this.state.isCreating = false;
      this.render();
      this.attachEventListeners();
    }
  }
}
