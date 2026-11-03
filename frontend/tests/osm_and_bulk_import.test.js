import test from "node:test";
import assert from "node:assert/strict";
import { AxiomOsmMap } from "../js/components/AxiomOsmMap.js";
import { CompletedTripsImporterUI } from "../js/components/CompletedTripsImporterUI.js";

// Minimal DOM mock with event listener support
class MockElement {
  constructor(id = "") {
    this.id = id;
    this._innerHTML = "";
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
}

const elementsMap = new Map();
globalThis.document = {
  getElementById: (id) => {
    if (!elementsMap.has(id)) elementsMap.set(id, new MockElement(id));
    return elementsMap.get(id);
  },
  querySelector: (sel) => new MockElement(),
  createElement: (tag) => new MockElement(tag),
  head: { appendChild: () => {} },
  body: {
    appendChild: (el) => {
      if (el && el.id) elementsMap.set(el.id, el);
    },
    removeChild: () => {},
  },
};

test("OSM Map: Renders interactive map canvas, toolbar, search input and status legend", () => {
  const container = new MockElement("osm-map-view");
  const mapComp = new AxiomOsmMap({ container });
  mapComp.render();

  assert.match(mapComp.container.innerHTML, /Search Bangalore landmark/);
  assert.match(mapComp.container.innerHTML, /Voyager/);
  assert.match(mapComp.container.innerHTML, /Positron/);
  assert.match(mapComp.container.innerHTML, /Running/);
  assert.match(mapComp.container.innerHTML, /POSH Night Escort/);
});

test("Bulk Importer UI: Renders template download button, upload dropzone, and pre-flight KPI banner", () => {
  const container = new MockElement("importer-view");
  const importer = new CompletedTripsImporterUI({ container });
  importer.render();

  assert.match(importer.container.innerHTML, /High-Speed Completed Trips Importer/);
  assert.match(importer.container.innerHTML, /Download Axiom Standard CSV Template/);
  assert.match(importer.container.innerHTML, /Drag & Drop Completed Trips CSV/);

  // Set dry-run staged summary
  importer.state.summary = {
    valid_rows: 142,
    warning_rows: 6,
    duplicate_rows: 2,
    error_rows: 1,
    estimated_total_receivable_inr: 384200.0,
    estimated_total_payable_inr: 291500.0,
    net_margin_inr: 92700.0,
    margin_pct: 24.1,
  };
  importer.render();

  assert.match(importer.container.innerHTML, /142/);
  assert.match(importer.container.innerHTML, /Tariff Variances/);
  assert.match(importer.container.innerHTML, /Duplicates Blocked/);
  assert.match(importer.container.innerHTML, /3,?84,?200/);
  assert.match(importer.container.innerHTML, /Commit (142 Valid Trips Now|148 Completed Trips to Ledger)/);
});

test("Bulk Importer UI: Standard template download, inline staging cell editing, and correction workbench modal", () => {
  const container = new MockElement("importer-view");
  const importer = new CompletedTripsImporterUI({ container });
  importer.state.summary = {
    valid_rows: 1,
    warning_rows: 0,
    duplicate_rows: 0,
    error_rows: 1,
    estimated_total_receivable_inr: 2500.0,
    estimated_total_payable_inr: 2000.0,
    net_margin_inr: 500.0,
    margin_pct: 20.0,
  };
  importer.state.stagedRows = [
    {
      id: "imp_row_test_1",
      row_index: 1,
      row_number: 1,
      external_tripsheet_no: "TS-2026-001",
      vehicle_registration: "KA-01-MJ-4412",
      corporate_name: "Infosys Campus",
      passenger_name: "Vikram Malhotra",
      practical_start_km: 1000,
      practical_end_km: 1040,
      practical_billable_km: 40,
      toll_parking_inr: 50,
      computed_client_fare_inr: 1550,
      computed_supplier_payout_inr: 1240,
      validation_status: "VALID",
      validation_messages: [],
      override_tariff_lock: false,
      raw_data: {
        "Trip Sheet No": "TS-2026-001",
        "Cab No": "KA-01-MJ-4412",
        "Corporate": "Infosys Campus",
        "Passenger Name": "Vikram Malhotra",
        "Start KM": 1000,
        "End KM": 1040,
        "Toll/Parking": 50,
        "Billed Amount": 1550,
      },
    },
  ];

  importer.render();

  // Verify headers and buttons
  assert.match(importer.container.innerHTML, /Workbench/);
  assert.match(importer.container.innerHTML, /Auto-Tariff/);
  assert.match(importer.container.innerHTML, /Correct/);

  // Trigger workbench modal opening
  importer.openCorrectionWorkbench(importer.state.stagedRows[0]);
  const modal = globalThis.document.getElementById("trip-correction-workbench-modal");
  assert.ok(modal);
  assert.match(modal.innerHTML, /Trip Details & Pricing Correction Workbench/);
  assert.match(modal.innerHTML, /Lock Manual Price Override/);
  assert.match(modal.innerHTML, /Apply & Recalculate/);
});
