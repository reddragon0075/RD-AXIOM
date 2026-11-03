import test from "node:test";
import assert from "node:assert/strict";
import { TripCorrectionDrawer } from "../js/components/TripCorrectionDrawer.js";
import { CompletedTripsImporterUI } from "../js/components/CompletedTripsImporterUI.js";

// Minimal DOM mock with event listener support
class MockElement {
  constructor(id = "") {
    this.id = id;
    this._innerHTML = "";
    this.value = "";
    this.checked = false;
    this.style = {};
    this.listeners = {};
    this.dataset = {};
    this.classList = {
      contains: () => false,
      add: () => {},
      remove: () => {},
    };
  }
  get innerHTML() {
    return this._innerHTML;
  }
  set innerHTML(val) {
    this._innerHTML = val;
  }
  addEventListener(evt, fn) {
    if (!this.listeners[evt]) this.listeners[evt] = [];
    this.listeners[evt].push(fn);
  }
  querySelector(sel) {
    return new MockElement();
  }
  querySelectorAll(sel) {
    return [];
  }
  closest(sel) {
    return null;
  }
  remove() {}
}

const elementsMap = new Map();
globalThis.document = {
  getElementById: (id) => {
    if (!elementsMap.has(id)) elementsMap.set(id, new MockElement(id));
    return elementsMap.get(id);
  },
  querySelector: (sel) => new MockElement(),
  querySelectorAll: (sel) => [],
  createElement: (tag) => new MockElement(tag),
  head: { appendChild: () => {} },
  body: {
    appendChild: (el) => {
      elementsMap.set(el.id || "drawer", el);
    },
  },
};
globalThis.window = {
  addEventListener: () => {},
  removeEventListener: () => {},
};

test("TripCorrectionDrawer: Renders 720px split-view with Loupe controls & Live Continuity Badges", () => {
  const host = new MockElement("host_1");
  const duty = {
    id: "duty_101",
    external_tripsheet_no: "TS-7788",
    vehicle_registration: "KA-01-AB-1234",
    practical_start_km: 10508,
    practical_end_km: 10558,
    prev_duty_end_km: 10500,
    practical_start_time: "2026-11-04T10:00:00Z",
    practical_end_time: "2026-11-04T12:00:00Z",
    toll_parking_inr: 100,
    final_client_fare_inr: 2200,
    final_supplier_payout_inr: 1750,
    physical_tripsheet_file_url: "https://example.com/slips/slip_101.jpg",
    odometer_continuity_status: "CONTINUOUS_OK",
    continuity_message: "+8 km continuous from Duty #99",
    invoice_status: "UNBILLED",
  };

  const drawer = new TripCorrectionDrawer({ duty });
  drawer.open(host);

  assert.ok(drawer.container, "Drawer container mounted");
  assert.match(drawer.container.innerHTML, /TS-7788/, "Tripsheet number rendered");
  assert.match(drawer.container.innerHTML, /Physical Trip Sheet/, "Split-view image loupe rendered");
  assert.match(drawer.container.innerHTML, /Zoom \+/, "Zoom in button present");
  assert.match(drawer.container.innerHTML, /Rotate 90°/, "Rotate button present");
  assert.match(drawer.container.innerHTML, /High Contrast/, "High contrast toggle present");
  assert.match(drawer.container.innerHTML, /Continuous \(\+8 km from prev trip\)/, "Live continuity badge rendered");
  assert.match(drawer.container.innerHTML, /Save Trip Corrections/, "Save button rendered for unbilled trip");
});

test("TripCorrectionDrawer: Switches to Credit/Debit Note Mode for FINALIZED_IRN Duty", () => {
  const host = new MockElement("host_2");
  const invoicedDuty = {
    id: "duty_invoiced_88",
    external_tripsheet_no: "TS-INV-88",
    vehicle_registration: "KA-04-MJ-9999",
    practical_start_km: 4000,
    practical_end_km: 4060,
    prev_duty_end_km: 3880,
    final_client_fare_inr: 2500,
    final_supplier_payout_inr: 2000,
    invoice_status: "FINALIZED_IRN",
    invoice_id: "INV-2026-0042",
    odometer_continuity_status: "HIGH_DEAD_MILEAGE_GAP",
    continuity_message: "120 km unaccounted gap",
  };

  const drawer = new TripCorrectionDrawer({ duty: invoicedDuty });
  drawer.open(host);

  assert.match(drawer.container.innerHTML, /Locked in Finalized GST Invoice/, "GST invoice lock banner displayed");
  assert.match(drawer.container.innerHTML, /Issue Credit\/Debit Note Adjustment/, "Switches action to Issue Credit/Debit Note");
  assert.match(drawer.container.innerHTML, /Unaccounted Gap/, "Continuity warning rendered");
});

test("CompletedTripsImporterUI: Partial Batch Commit & Error CSV Download Bars", () => {
  const container = new MockElement("importer-container");
  const importer = new CompletedTripsImporterUI({ container });
  importer.state.batchId = "batch_mixed_99";
  importer.state.filename = "mixed_100_trips.csv";
  importer.state.summary = {
    total_rows: 100,
    valid_rows: 94,
    warning_rows: 2,
    error_rows: 6,
    duplicate_rows: 0,
    estimated_total_receivable_inr: 150000,
    estimated_total_payable_inr: 120000,
    net_margin_inr: 30000,
    margin_pct: 20.0,
  };
  importer.state.stagedRows = [];

  importer.render();
  assert.match(importer.container.innerHTML, /Commit 94 Valid Trips Now/, "Partial commit button rendered with count");
  assert.match(importer.container.innerHTML, /Download 8 Error Rows as CSV to Fix Later/, "Error CSV download button rendered with count");
});
