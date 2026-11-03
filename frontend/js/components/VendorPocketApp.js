/**
 * Axiom Mobility (Fleetline) - Vendor Mobile Pocket App.
 * "On-the-Go Cab Assignment & Daily Pulse"
 *
 * Thumb-friendly, zero-laptop mobile cockpit for fleet vendors:
 * 1. 2x2 Top Sticky Pulse Strip ("Today at a Glance")
 * 2. 2-Tap "Express Cab Assignment" Bottom Sheet with Smart Auto-Suggestions
 * 3. One-tap Partner Overflow Broadcast
 * 4. Discrepancy & Trip Closure Launcher
 * 5. Mobile-First Bottom-Tab Navigation
 */

import { TripClosureModal } from "./TripClosureModal.js";

export class VendorPocketApp {
  constructor(options = {}) {
    this.container = options.container || (typeof document !== "undefined" ? document.getElementById("vendor-pocket-view") : null);
    this.apiBase = options.apiBase || "/api/v1";
    this.onClose = options.onClose || (() => {});
    this.onOpenClosureModal = options.onOpenClosureModal || null;

    this.abortController = new AbortController();
    this.activeTab = "unassigned"; // "pulse" | "unassigned" | "running" | "discrepancy" | "pnl"
    this.activeBottomSheet = null; // null | { booking: Object, suggestedPairs: Array }

    this.state = {
      isPocketModeActive: true,
      pulse: {
        unassigned_cabs: 4,
        live_running: 12,
        discrepancy_to_close: 3,
        today_revenue_inr: 48500.0,
        today_net_inr: 11200.0,
        summary_pill_text: "Rev: ₹48.5k | Net: ₹11.2k",
      },
      unassignedBookings: [
        {
          id: "bk_101",
          booking_reference: "BK-BLR-8491",
          passenger_name: "Vikram Malhotra",
          passenger_phone: "+91 98800 23456",
          corporate_tag: "Infosys Campus",
          pickup: "Bangalore Airport (BLR) T2",
          dropoff: "Whitefield EPIP Zone",
          vehicle_category: "Sedan",
          pickup_countdown_text: "In 45 mins",
          estimated_distance_km: 42.0,
          estimated_client_fare_inr: 1550.0,
        },
        {
          id: "bk_102",
          booking_reference: "BK-BLR-8492",
          passenger_name: "Anita Sharma",
          passenger_phone: "+91 98800 34567",
          corporate_tag: "Goldman Sachs Outer Ring",
          pickup: "Indiranagar 100ft Rd",
          dropoff: "Electronic City Phase 1",
          vehicle_category: "SUV / Innova",
          pickup_countdown_text: "In 1 hr 15 mins",
          estimated_distance_km: 35.0,
          estimated_client_fare_inr: 1850.0,
        },
        {
          id: "bk_103",
          booking_reference: "BK-BLR-8493",
          passenger_name: "Rohan Varma",
          passenger_phone: "+91 98800 45678",
          corporate_tag: "Microsoft Bellandur",
          pickup: "Koramangala 4th Block",
          dropoff: "Kempegowda Int'l Airport",
          vehicle_category: "Sedan",
          pickup_countdown_text: "In 2 hrs",
          estimated_distance_km: 40.0,
          estimated_client_fare_inr: 1500.0,
        },
        {
          id: "bk_104",
          booking_reference: "BK-BLR-8494",
          passenger_name: "Deepak Nair",
          passenger_phone: "+91 98800 56789",
          corporate_tag: "Wipro Sarjapur",
          pickup: "Whitefield Nexus Mall",
          dropoff: "Sarjapur Road Campus",
          vehicle_category: "Sedan",
          pickup_countdown_text: "In 2 hrs 30 mins",
          estimated_distance_km: 22.0,
          estimated_client_fare_inr: 1200.0,
        },
      ],
      suggestedPairs: [
        {
          driver_id: "drv_01",
          driver_name: "Ramesh Kumar",
          driver_phone: "+91 98765 43210",
          vehicle_id: "veh_01",
          vehicle_number: "KA-01-MJ-4412",
          vehicle_model: "Maruti Dzire Tour (White)",
          vehicle_category: "Sedan",
          proximity_text: "1.4 km away (Ready)",
          compliance_badge: "✅ Docs Valid",
          is_compliant: true,
        },
        {
          driver_id: "drv_02",
          driver_name: "Suresh Gowda",
          driver_phone: "+91 98765 43211",
          vehicle_id: "veh_02",
          vehicle_number: "KA-04-AK-9821",
          vehicle_model: "Toyota Innova Crysta",
          vehicle_category: "SUV / Innova",
          proximity_text: "2.8 km away (Ready)",
          compliance_badge: "✅ Docs Valid",
          is_compliant: true,
        },
        {
          driver_id: "drv_03",
          driver_name: "Basavaraj M.",
          driver_phone: "+91 98765 43212",
          vehicle_id: "veh_03",
          vehicle_number: "KA-51-B-3109",
          vehicle_model: "Hyundai Aura Prime",
          vehicle_category: "Sedan",
          proximity_text: "3.5 km away",
          compliance_badge: "✅ Docs Valid",
          is_compliant: true,
        },
      ],
      liveRunningTrips: [
        {
          id: "duty_live_01",
          trip_code: "TRIP-BLR-901",
          driver_name: "Manjunath K.",
          vehicle_number: "KA-03-AA-1102",
          passenger_name: "Rajesh Rao (Wipro)",
          status: "EN_ROUTE",
          start_km: 14210.0,
          current_gps_km: 14228.4,
          elapsed_mins: 42,
        },
        {
          id: "duty_live_02",
          trip_code: "TRIP-BLR-902",
          driver_name: "Shivanna P.",
          vehicle_number: "KA-05-MH-8841",
          passenger_name: "Pooja Hegde (Amazon)",
          status: "IN_PROGRESS",
          start_km: 28400.0,
          current_gps_km: 28419.0,
          elapsed_mins: 28,
        },
      ],
      discrepancyTrips: [
        {
          id: "duty_disc_01",
          trip_code: "TRIP-BLR-881",
          driver_name: "Prakash T.",
          vehicle_number: "KA-01-EQ-5521",
          passenger_name: "Sanjay Patel (Deloitte)",
          issue: "GPS Dropout in Basement Parking",
          est_km: 40.0,
          app_odo_km: 38.5,
          needs_proof: true,
        },
        {
          id: "duty_disc_02",
          trip_code: "TRIP-BLR-882",
          driver_name: "Anand M.",
          vehicle_number: "KA-04-TR-9041",
          passenger_name: "Kavita Reddy (Accenture)",
          issue: "Driver Offline / Paper Duty Slip Sent",
          est_km: 40.0,
          app_odo_km: 0.0,
          needs_proof: true,
        },
      ],
      lastActionNotification: null,
    };
  }

  mount() {
    if (!this.container) return;
    this.injectStyles();
    this.render();
    this.attachEventListeners();
    this.fetchPulseData();
  }

  unmount() {
    this.abortController.abort();
    if (this.container) {
      this.container.innerHTML = "";
    }
  }

  injectStyles() {
    if (typeof document === "undefined") return;
    if (document.getElementById("vendor-pocket-styles")) return;

    const styleEl = document.createElement("style");
    styleEl.id = "vendor-pocket-styles";
    styleEl.textContent = `
      .pocket-app-container {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #0f172a;
        color: #f8fafc;
        min-height: 100vh;
        max-width: 480px;
        margin: 0 auto;
        position: relative;
        padding-bottom: 74px;
        box-shadow: 0 0 40px rgba(0,0,0,0.6);
      }
      .pocket-header {
        position: sticky;
        top: 0;
        z-index: 40;
        background: rgba(15, 23, 42, 0.95);
        backdrop-filter: blur(8px);
        padding: 12px 16px;
        border-bottom: 1px solid #1e293b;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .pocket-brand {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 700;
        font-size: 15px;
        letter-spacing: -0.3px;
      }
      .pocket-brand-pill {
        background: linear-gradient(135deg, #3b82f6, #1d4ed8);
        padding: 2px 8px;
        border-radius: 9999px;
        font-size: 11px;
        text-transform: uppercase;
        font-weight: 800;
      }
      .pulse-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        padding: 12px 16px;
        background: #111827;
        border-bottom: 1px solid #1f2937;
      }
      .pulse-pill {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 10px 12px;
        cursor: pointer;
        transition: all 0.15s ease;
        display: flex;
        flex-direction: column;
        justify-content: center;
      }
      .pulse-pill:active, .pulse-pill.active {
        border-color: #3b82f6;
        background: #1e3a8a;
        transform: scale(0.98);
      }
      .pulse-pill.alert-pulse {
        animation: pulseBorder 2s infinite;
      }
      @keyframes pulseBorder {
        0%, 100% { border-color: #ef4444; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
        50% { border-color: #f87171; box-shadow: 0 0 10px 2px rgba(239, 68, 68, 0.3); }
      }
      .pulse-pill-title {
        font-size: 11px;
        font-weight: 600;
        color: #94a3b8;
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .pulse-pill-val {
        font-size: 17px;
        font-weight: 700;
        margin-top: 4px;
        color: #fff;
      }
      .cards-scroll-container {
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .booking-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .booking-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .countdown-badge {
        background: #b91c1c;
        color: #fef2f2;
        font-size: 11px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 6px;
      }
      .corp-tag {
        font-size: 11px;
        color: #60a5fa;
        font-weight: 600;
        background: #172554;
        padding: 3px 8px;
        border-radius: 6px;
      }
      .route-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: 13px;
      }
      .route-point {
        display: flex;
        align-items: center;
        gap: 6px;
        color: #cbd5e1;
      }
      .route-icon-p { color: #10b981; font-size: 10px; }
      .route-icon-d { color: #f43f5e; font-size: 10px; }
      .card-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-top: 8px;
        border-top: 1px solid #334155;
      }
      .btn-express-assign {
        background: #2563eb;
        color: #ffffff;
        font-weight: 700;
        font-size: 13px;
        padding: 8px 14px;
        border-radius: 8px;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .btn-express-assign:active {
        background: #1d4ed8;
      }
      .bottom-nav {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        max-width: 480px;
        margin: 0 auto;
        height: 60px;
        background: #0f172a;
        border-top: 1px solid #1e293b;
        display: flex;
        align-items: center;
        justify-content: space-around;
        z-index: 50;
      }
      .nav-tab-btn {
        background: none;
        border: none;
        color: #64748b;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
        font-size: 11px;
        cursor: pointer;
        padding: 6px 12px;
        font-weight: 600;
      }
      .nav-tab-btn.active {
        color: #38bdf8;
      }
      .bottom-sheet-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.75);
        backdrop-filter: blur(4px);
        z-index: 100;
        display: flex;
        align-items: flex-end;
        justify-content: center;
      }
      .bottom-sheet {
        background: #1e293b;
        border-top: 1px solid #334155;
        border-radius: 20px 20px 0 0;
        width: 100%;
        max-width: 480px;
        max-height: 80vh;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        animation: slideUp 0.2s ease-out;
      }
      @keyframes slideUp {
        from { transform: translateY(100%); }
        to { transform: translateY(0); }
      }
      .suggested-pair-card {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
      }
      .suggested-pair-card:active {
        border-color: #3b82f6;
        background: #172554;
      }
      .badge-valid-docs {
        background: #064e3b;
        color: #34d399;
        font-size: 10px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
      }
      .btn-partner-overflow {
        background: #475569;
        border: 1px dashed #64748b;
        color: #f1f5f9;
        font-weight: 600;
        padding: 10px;
        border-radius: 8px;
        cursor: pointer;
        width: 100%;
        font-size: 12px;
      }
      .toast-notification {
        position: fixed;
        top: 60px;
        left: 20px;
        right: 20px;
        max-width: 440px;
        margin: 0 auto;
        background: #065f46;
        color: #ecfdf5;
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        z-index: 60;
        animation: fadeIn 0.2s ease-out;
      }
      @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
      }
    `;
    document.head.appendChild(styleEl);
  }

  async fetchPulseData() {
    try {
      const res = await fetch(`${this.apiBase}/vendor-pocket/pulse`, {
        signal: this.abortController.signal,
      });
      if (res.ok) {
        const data = await res.json();
        if (data.pulse) {
          this.state.pulse = data.pulse;
          this.render();
        }
      }
    } catch (err) {
      // Graceful fallback to initial reactive state
    }
  }

  async fetchUnassigned() {
    try {
      const res = await fetch(`${this.apiBase}/vendor-pocket/unassigned`, {
        signal: this.abortController.signal,
      });
      if (res.ok) {
        const data = await res.json();
        if (data.unassigned_bookings) {
          this.state.unassignedBookings = data.unassigned_bookings;
        }
        if (data.suggested_pairs) {
          this.state.suggestedPairs = data.suggested_pairs;
        }
        this.render();
      }
    } catch (err) {
      // Fallback
    }
  }

  openAssignSheet(bookingId) {
    const booking = this.state.unassignedBookings.find((b) => b.id === bookingId);
    if (!booking) return;
    this.activeBottomSheet = {
      booking,
      suggestedPairs: this.state.suggestedPairs,
    };
    this.render();
  }

  closeBottomSheet() {
    this.activeBottomSheet = null;
    this.render();
  }

  async assignCab(bookingId, driverId, vehicleId) {
    try {
      const res = await fetch(`${this.apiBase}/vendor-pocket/express-assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          booking_id: bookingId,
          driver_id: driverId,
          vehicle_id: vehicleId,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        // Remove allotted booking from unassigned list
        this.state.unassignedBookings = this.state.unassignedBookings.filter((b) => b.id !== bookingId);
        this.state.pulse.unassigned_cabs = Math.max(0, this.state.pulse.unassigned_cabs - 1);
        this.state.pulse.live_running += 1;
        this.showToast(`✅ Cab assigned! WhatsApp & SMS alert dispatched to driver & passenger.`);
        this.closeBottomSheet();
      }
    } catch (err) {
      // Local optimistic update
      this.state.unassignedBookings = this.state.unassignedBookings.filter((b) => b.id !== bookingId);
      this.state.pulse.unassigned_cabs = Math.max(0, this.state.pulse.unassigned_cabs - 1);
      this.showToast(`✅ Cab assigned! WhatsApp alert dispatched.`);
      this.closeBottomSheet();
    }
  }

  async broadcastPartnerOverflow(bookingId) {
    try {
      await fetch(`${this.apiBase}/vendor-pocket/express-assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          booking_id: bookingId,
          is_partner_overflow: true,
        }),
      });
    } catch (err) {
      // Fallback
    }
    this.state.unassignedBookings = this.state.unassignedBookings.filter((b) => b.id !== bookingId);
    this.state.pulse.unassigned_cabs = Math.max(0, this.state.pulse.unassigned_cabs - 1);
    this.showToast(`🚀 Trip broadcasted to Axiom Partner Network!`);
    this.closeBottomSheet();
  }

  showToast(message) {
    this.state.lastActionNotification = message;
    this.render();
    setTimeout(() => {
      this.state.lastActionNotification = null;
      this.render();
    }, 3500);
  }

  render() {
    if (!this.container) return;

    const { pulse, unassignedBookings, liveRunningTrips, discrepancyTrips, lastActionNotification } = this.state;
    const isUnassignedAlert = pulse.unassigned_cabs > 0;

    let contentHtml = "";

    if (this.activeTab === "unassigned") {
      contentHtml = `
        <div class="cards-scroll-container">
          <div style="font-size: 13px; font-weight: 700; color: #94a3b8; display: flex; justify-content: space-between;">
            <span>UNASSIGNED BOOKINGS (${unassignedBookings.length})</span>
            <span style="color: #3b82f6; cursor: pointer;" id="btn-refresh-unassigned">🔄 Refresh</span>
          </div>
          ${
            unassignedBookings.length === 0
              ? `<div style="text-align: center; padding: 40px 10px; color: #64748b;">
                  🎉 All set! No unassigned cabs right now.
                </div>`
              : unassignedBookings
                  .map(
                    (b) => `
              <div class="booking-card" data-booking-id="${b.id}">
                <div class="booking-card-header">
                  <span class="countdown-badge">⏱️ ${b.pickup_countdown_text}</span>
                  <span class="corp-tag">${b.corporate_tag}</span>
                </div>
                <div style="font-weight: 700; font-size: 14px;">${b.passenger_name} · <span style="font-size: 12px; color: #94a3b8;">${b.passenger_phone}</span></div>
                <div class="route-row">
                  <div class="route-point"><span class="route-icon-p">●</span> <strong>Pickup:</strong> ${b.pickup}</div>
                  <div class="route-point"><span class="route-icon-d">■</span> <strong>Drop:</strong> ${b.dropoff}</div>
                </div>
                <div class="card-footer">
                  <span style="font-size: 12px; color: #cbd5e1;">🚘 ${b.vehicle_category} · ₹${b.estimated_client_fare_inr}</span>
                  <button class="btn-express-assign" data-action="open-assign" data-booking-id="${b.id}">
                    ⚡ Assign Cab
                  </button>
                </div>
              </div>
            `
                  )
                  .join("")
          }
        </div>
      `;
    } else if (this.activeTab === "running") {
      contentHtml = `
        <div class="cards-scroll-container">
          <div style="font-size: 13px; font-weight: 700; color: #94a3b8;">LIVE RUNNING TRIPS (${liveRunningTrips.length})</div>
          ${liveRunningTrips
            .map(
              (t) => `
            <div class="booking-card">
              <div class="booking-card-header">
                <span style="background: #065f46; color: #34d399; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px;">🟢 ${t.status}</span>
                <span style="font-size: 11px; color: #94a3b8;">${t.trip_code}</span>
              </div>
              <div style="font-weight: 700; font-size: 14px;">${t.driver_name} · ${t.vehicle_number}</div>
              <div style="font-size: 12px; color: #cbd5e1;">Passenger: ${t.passenger_name}</div>
              <div style="display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; padding-top: 6px; border-top: 1px solid #334155;">
                <span>Start Odo: ${t.start_km} km</span>
                <span>GPS Live: ${t.current_gps_km} km</span>
              </div>
            </div>
          `
            )
            .join("")}
        </div>
      `;
    } else if (this.activeTab === "discrepancy") {
      contentHtml = `
        <div class="cards-scroll-container">
          <div style="font-size: 13px; font-weight: 700; color: #f59e0b;">DISCREPANCY / TO CLOSE (${discrepancyTrips.length})</div>
          ${discrepancyTrips
            .map(
              (d) => `
            <div class="booking-card" style="border-left: 3px solid #f59e0b;">
              <div class="booking-card-header">
                <span style="background: #78350f; color: #fbbf24; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px;">⚠️ ${d.issue}</span>
                <span style="font-size: 11px; color: #94a3b8;">${d.trip_code}</span>
              </div>
              <div style="font-weight: 700; font-size: 14px;">${d.driver_name} (${d.vehicle_number})</div>
              <div style="font-size: 12px; color: #cbd5e1;">Passenger: ${d.passenger_name}</div>
              <div class="card-footer">
                <span style="font-size: 11px; color: #94a3b8;">Est: ${d.est_km} km | App: ${d.app_odo_km} km</span>
                <button class="btn-express-assign" style="background: #d97706;" data-action="open-reconcile" data-duty-id="${d.id}">
                  📄 Close / Reconcile
                </button>
              </div>
            </div>
          `
            )
            .join("")}
        </div>
      `;
    } else {
      // P&L / Rev view
      contentHtml = `
        <div class="cards-scroll-container">
          <div style="font-size: 13px; font-weight: 700; color: #94a3b8;">TODAY'S DUAL-LEDGER SETTLEMENT</div>
          <div class="booking-card" style="background: linear-gradient(135deg, #1e293b, #0f172a); border-color: #3b82f6;">
            <div style="font-size: 12px; color: #94a3b8;">Client Gross Billing</div>
            <div style="font-size: 26px; font-weight: 800; color: #38bdf8;">₹${pulse.today_revenue_inr.toLocaleString()}</div>
            <div style="display: flex; justify-content: space-between; margin-top: 10px; padding-top: 10px; border-top: 1px solid #334155; font-size: 13px;">
              <span>Net Vendor Retained:</span>
              <strong style="color: #34d399;">₹${pulse.today_net_inr.toLocaleString()}</strong>
            </div>
          </div>
        </div>
      `;
    }

    // Bottom Sheet for Express Assignment
    let bottomSheetHtml = "";
    if (this.activeBottomSheet) {
      const { booking, suggestedPairs } = this.activeBottomSheet;
      bottomSheetHtml = `
        <div class="bottom-sheet-backdrop" id="bottom-sheet-backdrop">
          <div class="bottom-sheet">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <span style="font-size: 11px; font-weight: 700; color: #38bdf8;">EXPRESS ASSIGNMENT</span>
                <div style="font-size: 15px; font-weight: 700;">${booking.passenger_name} (${booking.vehicle_category})</div>
              </div>
              <button id="btn-close-bottom-sheet" style="background: none; border: none; color: #94a3b8; font-size: 18px; cursor: pointer;">✕</button>
            </div>
            <div style="font-size: 12px; color: #94a3b8;">
              ${booking.pickup} ➔ ${booking.dropoff}
            </div>

            <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">
              Top Available Driver & Cab Pairs (Compliant)
            </div>

            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${suggestedPairs
                .map(
                  (pair) => `
                <div class="suggested-pair-card" data-action="confirm-assign" data-booking-id="${booking.id}" data-driver-id="${pair.driver_id}" data-vehicle-id="${pair.vehicle_id}">
                  <div>
                    <div style="font-weight: 700; font-size: 13px;">${pair.driver_name}</div>
                    <div style="font-size: 11px; color: #94a3b8;">${pair.vehicle_number} · ${pair.vehicle_model}</div>
                    <div style="font-size: 11px; color: #60a5fa; margin-top: 2px;">📍 ${pair.proximity_text}</div>
                  </div>
                  <div style="text-align: right;">
                    <span class="badge-valid-docs">${pair.compliance_badge}</span>
                    <div style="font-size: 11px; color: #38bdf8; font-weight: 700; margin-top: 6px;">Tap to Allot ➔</div>
                  </div>
                </div>
              `
                )
                .join("")}
            </div>

            <div style="border-top: 1px solid #334155; padding-top: 10px;">
              <button class="btn-partner-overflow" data-action="partner-overflow" data-booking-id="${booking.id}">
                🌐 No Own Cab Free? Broadcast to Partner Network
              </button>
            </div>
          </div>
        </div>
      `;
    }

    this.container.innerHTML = `
      <div class="pocket-app-container">
        <!-- Toast Notification -->
        ${lastActionNotification ? `<div class="toast-notification">${lastActionNotification}</div>` : ""}

        <!-- Compact Header -->
        <header class="pocket-header">
          <div class="pocket-brand">
            <span>AXIOM</span>
            <span class="pocket-brand-pill">POCKET</span>
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <button id="btn-toggle-laptop" style="background: #334155; border: none; color: #f8fafc; font-size: 11px; font-weight: 600; padding: 4px 8px; border-radius: 6px; cursor: pointer;">
              💻 Laptop View
            </button>
          </div>
        </header>

        <!-- Top Sticky Pulse Strip ("Today at a Glance") -->
        <div class="pulse-grid">
          <div class="pulse-pill ${isUnassignedAlert ? "alert-pulse" : ""} ${this.activeTab === "unassigned" ? "active" : ""}" data-tab="unassigned">
            <span class="pulse-pill-title">🚨 Unassigned Cabs</span>
            <span class="pulse-pill-val" style="color: ${isUnassignedAlert ? "#f87171" : "#fff"}">${pulse.unassigned_cabs}</span>
          </div>

          <div class="pulse-pill ${this.activeTab === "running" ? "active" : ""}" data-tab="running">
            <span class="pulse-pill-title">🟢 Live Running</span>
            <span class="pulse-pill-val" style="color: #34d399;">${pulse.live_running}</span>
          </div>

          <div class="pulse-pill ${this.activeTab === "discrepancy" ? "active" : ""}" data-tab="discrepancy">
            <span class="pulse-pill-title">⚠️ Discrepancy / To Close</span>
            <span class="pulse-pill-val" style="color: #fbbf24;">${pulse.discrepancy_to_close}</span>
          </div>

          <div class="pulse-pill ${this.activeTab === "pnl" ? "active" : ""}" data-tab="pnl">
            <span class="pulse-pill-title">💰 Today's Rev / Payout</span>
            <span class="pulse-pill-val" style="font-size: 13px; font-weight: 700; color: #38bdf8;">${pulse.summary_pill_text}</span>
          </div>
        </div>

        <!-- Main Tab Content Area -->
        ${contentHtml}

        <!-- Bottom Sheet -->
        ${bottomSheetHtml}

        <!-- Bottom Tab Navigation -->
        <nav class="bottom-nav">
          <button class="nav-tab-btn ${this.activeTab === "unassigned" ? "active" : ""}" data-tab="unassigned">
            <span style="font-size: 16px;">🚨</span>
            <span>Assign</span>
          </button>
          <button class="nav-tab-btn ${this.activeTab === "running" ? "active" : ""}" data-tab="running">
            <span style="font-size: 16px;">🟢</span>
            <span>Live</span>
          </button>
          <button class="nav-tab-btn ${this.activeTab === "discrepancy" ? "active" : ""}" data-tab="discrepancy">
            <span style="font-size: 16px;">⚠️</span>
            <span>Close</span>
          </button>
          <button class="nav-tab-btn ${this.activeTab === "pnl" ? "active" : ""}" data-tab="pnl">
            <span style="font-size: 16px;">💰</span>
            <span>P&L</span>
          </button>
        </nav>
      </div>
    `;
  }

  attachEventListeners() {
    if (!this.container) return;

    this.container.addEventListener("click", (evt) => {
      // 1. Tab switches
      const tabTarget = evt.target.closest("[data-tab]");
      if (tabTarget) {
        this.activeTab = tabTarget.dataset.tab;
        this.render();
        return;
      }

      // 2. Open assign sheet
      const assignBtn = evt.target.closest("[data-action='open-assign']");
      if (assignBtn) {
        this.openAssignSheet(assignBtn.dataset.bookingId);
        return;
      }

      // 3. Confirm assign
      const confirmPair = evt.target.closest("[data-action='confirm-assign']");
      if (confirmPair) {
        const { bookingId, driverId, vehicleId } = confirmPair.dataset;
        this.assignCab(bookingId, driverId, vehicleId);
        return;
      }

      // 4. Partner overflow
      const partnerBtn = evt.target.closest("[data-action='partner-overflow']");
      if (partnerBtn) {
        this.broadcastPartnerOverflow(partnerBtn.dataset.bookingId);
        return;
      }

      // 5. Close bottom sheet
      if (evt.target.id === "btn-close-bottom-sheet" || evt.target.id === "bottom-sheet-backdrop") {
        this.closeBottomSheet();
        return;
      }

      // 6. Laptop toggle
      if (evt.target.id === "btn-toggle-laptop") {
        this.onClose();
        return;
      }

      // 7. Refresh unassigned
      if (evt.target.id === "btn-refresh-unassigned") {
        this.fetchUnassigned();
        return;
      }

      // 8. Open Reconcile / Close Drawer
      const reconcileBtn = evt.target.closest("[data-action='open-reconcile']");
      if (reconcileBtn) {
        const dutyId = reconcileBtn.dataset.dutyId;
        if (this.onOpenClosureModal) {
          this.onOpenClosureModal(dutyId);
        } else {
          // Launch default modal
          const modal = new TripClosureModal({ dutyId });
          modal.mount();
        }
      }
    });
  }
}
