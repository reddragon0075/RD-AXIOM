import test from "node:test";
import assert from "node:assert/strict";
import { VendorPocketApp } from "../js/components/VendorPocketApp.js";
import { TripClosureModal } from "../js/components/TripClosureModal.js";

// Minimal DOM mock for Node.js test environment
class MockElement {
  constructor(id = "") {
    this.id = id;
    this._innerHTML = "";
    this.listeners = {};
    this.dataset = {};
    this.classList = {
      contains: (c) => false,
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

globalThis.document = {
  getElementById: (id) => new MockElement(id),
  querySelector: (sel) => new MockElement(),
  createElement: (tag) => new MockElement(tag),
  head: {
    appendChild: () => {},
  },
  body: {
    appendChild: () => {},
  },
};

test("Vendor Pocket App: Renders 2x2 pulse strip with unassigned cabs, live running, and P&L pill", () => {
  const container = new MockElement("vendor-pocket-view");
  const app = new VendorPocketApp({ container });
  app.render();

  assert.match(app.container.innerHTML, /Unassigned Cabs/);
  assert.match(app.container.innerHTML, /Live Running/);
  assert.match(app.container.innerHTML, /Discrepancy \/ To Close/);
  assert.match(app.container.innerHTML, /Rev: ₹48.5k \| Net: ₹11.2k/);
  assert.match(app.container.innerHTML, /⏱️ In 45 mins/);
  assert.match(app.container.innerHTML, /⚡ Assign Cab/);
});

test("Vendor Pocket App: Express cab assignment bottom sheet renders compliant driver-cab pairs", () => {
  const container = new MockElement("vendor-pocket-view");
  const app = new VendorPocketApp({ container });
  app.openAssignSheet("bk_101");

  assert.match(app.container.innerHTML, /EXPRESS ASSIGNMENT/);
  assert.match(app.container.innerHTML, /✅ Docs Valid/);
  assert.match(app.container.innerHTML, /Ramesh Kumar/);
  assert.match(app.container.innerHTML, /Broadcast to Partner Network/);
});

test("Trip Closure Modal: 3-Column comparison table & live practical tariff recalculation", () => {
  const container = new MockElement("trip-closure-modal-host");
  const modal = new TripClosureModal({ dutyId: "duty_test_01", container });
  modal.isOpen = true;
  modal.state.practical.start_km = 1000.0;
  modal.state.practical.end_km = 1074.0;
  modal.recalculateLivePricing();
  modal.render();

  // 1074 - 1000 = 74 km billable
  assert.equal(modal.state.recalculated.billable_km, 74.0);
  // Base 1500 + 34 km * 25 = 2350
  assert.equal(modal.state.recalculated.final_client_fare, 2350.0);
  assert.equal(modal.state.recalculated.variance_delta, 850.0);

  assert.match(modal.container.innerHTML, /Theoretical \(Estimated\)/);
  assert.match(modal.container.innerHTML, /Driver App Captured/);
  assert.match(modal.container.innerHTML, /Practical Operator Entry/);
  assert.match(modal.container.innerHTML, /₹2,350/);
});

test("Trip Closure Modal: Submit gate blocks confirmation if discrepancy lacks paper slip proof", () => {
  const container = new MockElement("trip-closure-modal-host");
  const modal = new TripClosureModal({ dutyId: "duty_test_01", container });
  modal.isOpen = true;
  modal.state.hasDiscrepancyToggle = true;
  modal.state.physicalTripsheetUrl = null; // No file uploaded
  modal.render();

  assert.match(modal.container.innerHTML, /disabled/);

  // When proof is attached, submit gate unlocks
  modal.state.physicalTripsheetUrl = "https://supabase.axiomfleet.in/storage/v1/object/public/trip-sheets/slip.jpg";
  modal.render();
  assert.doesNotMatch(modal.container.innerHTML, /disabled>/);
});
