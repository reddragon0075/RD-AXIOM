import test from "node:test";
import assert from "node:assert/strict";
import { AdminSaasConsole } from "../js/components/AdminSaasConsole.js";
import { VendorCommandDashboard } from "../js/components/VendorCommandDashboard.js";

// Minimal DOM mock for Node.js test environment
class MockElement {
  constructor(id = "") {
    this.id = id;
    this._innerHTML = "";
    this.listeners = {};
    this.dataset = {};
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
}

globalThis.document = {
  getElementById: (id) => new MockElement(id),
  querySelector: (sel) => new MockElement(),
};

test("Autonomous Capability 1: AdminSaasConsole renders What-If Tariff Simulator", () => {
  const container = new MockElement("saas-console-view");
  const consoleComp = new AdminSaasConsole({ container });
  consoleComp.state.activeView = "SIMULATOR";
  consoleComp.state.tariffSimulation = {
    simulation_parameters: { monthly_trips: 120, avg_distance_km: 40, avg_duration_hours: 3.5, total_monthly_km: 4800 },
    optimal_recommendation: {
      optimal_model: "slab",
      optimal_title: "SLAB (HR/KM)",
      projected_monthly_spend_inr: 252000,
      effective_cost_per_km_inr: 52.5,
      projected_monthly_savings_inr: 45000,
      annual_projected_savings_inr: 540000,
      savings_percentage: 15.2,
      pitch_summary: "Saves ₹45,000/mo",
    },
    comparison_matrix: [
      {
        model: "slab",
        model_title: "HR/KM SLAB",
        monthly_client_spend_inr: 252000,
        monthly_vendor_cost_inr: 187200,
        gross_margin_inr: 64800,
        gross_margin_percentage: 25.7,
        effective_cost_per_km_inr: 52.5,
      },
    ],
  };

  consoleComp.render();
  const html = container.innerHTML;

  assert.match(html, /What-If/);
  assert.match(html, /data-action="run-tariff-sim"/);
  assert.match(html, /OPTIMAL RECOMMENDATION/);
  assert.match(html, /HR\/KM SLAB/);
});

test("Autonomous Capability 2: VendorCommandDashboard renders SLA Radar & Night Safety Strip", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });
  dashboard.render();

  const html = container.innerHTML;
  assert.match(html, /Autonomous SLA Breach Radar/);
  assert.match(html, /data-action="refresh-sla-radar"/);
  assert.match(html, /Night Safety Guardian Active/);
});

test("Autonomous Capability 3: VendorCommandDashboard renders 1-Click Discrepancy Resolver", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });

  const drawerElement = new MockElement("drawer-root");
  globalThis.document.getElementById = (id) => (id === "drawer-root" ? drawerElement : new MockElement(id));

  dashboard.openDrawerForType("distance_hold");
  const drawerHtml = drawerElement.innerHTML;

  assert.match(drawerHtml, /3-Way Distance Audit Discrepancies/);
  assert.match(drawerHtml, /data-action="resolve-audit"/);
  assert.match(drawerHtml, /data-resolution="snap_gps_distance"/);
  assert.match(drawerHtml, /data-resolution="approve_as_is"/);
});

test("Autonomous Capability 4: VendorCommandDashboard renders Self-Serve Settle button on soft and hard blocks", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });

  // Test Soft Block
  dashboard.setTenantBlockedState({
    account_status: "SOFT_BLOCKED",
    amount_owed_paise: 800000,
    block_reason: "Credit limit exceeded",
  });
  assert.match(container.innerHTML, /data-action="self-settle-dues"/);
  assert.match(container.innerHTML, /Account Restricted — Payment Overdue/);

  // Test Hard Block
  dashboard.setTenantBlockedState({
    account_status: "HARD_BLOCKED",
    amount_owed_paise: 800000,
    block_reason: "Overdue balance past 60 days",
  });
  assert.match(container.innerHTML, /data-action="self-settle-dues"/);
  assert.match(container.innerHTML, /Account Suspended — Payment Overdue/);
});
