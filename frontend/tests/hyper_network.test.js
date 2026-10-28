import test from "node:test";
import assert from "node:assert/strict";
import { PartnerExchangeView } from "../js/components/PartnerExchangeView.js";
import { VendorCommandDashboard } from "../js/components/VendorCommandDashboard.js";

// Minimal DOM mock for Node.js test environment
class MockElement {
  constructor(id = "") {
    this.id = id;
    this._innerHTML = "";
    this.listeners = {};
    this.dataset = {};
    this.children = [];
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

const elementsById = {};
globalThis.document = {
  getElementById: (id) => {
    if (!elementsById[id]) elementsById[id] = new MockElement(id);
    return elementsById[id];
  },
  querySelector: (sel) => new MockElement(),
};

test("Hyper-Network Module 1: PartnerExchangeView renders Live Duty Board with Waterfall & EV badges", () => {
  const container = new MockElement("network-view");
  const view = new PartnerExchangeView({
    container,
    user: { tenant_id: "vendor_1", role: "TENANT_DISPATCHER", company_name: "Apex Fleet" }
  });

  view.state.activeTab = "EXCHANGE_FEED";
  view.state.listings = [
    {
      id: "net_duty_101",
      duty_id: "DT-9104",
      origin_vendor_name: "BlueLine Mobility",
      client_display_name: "Originating Partner: BlueLine Mobility",
      trip_class: "Executive Airport Chauffeur",
      pickup_address: "Terminal 3, DEL",
      dropoff_address: "Cyber City, GGN",
      reporting_time: "18:30 IST",
      estimated_distance_km: 65,
      supplier_payout_inr: 2850.0,
      current_wave: 1,
      eligible_tier: "TIER_1_PLATINUM",
      wave_seconds_remaining: 184,
      prefer_ev_green_corridor: true,
      status: "BROADCASTING",
      compliance_status: "PASSED_VERIFIED"
    }
  ];

  view.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Axiom Hyper-Network Exchange"), "Title must render");
  assert.ok(html.includes("DT-9104"), "Duty code must render");
  assert.ok(html.includes("EV GREEN PRIORITY"), "EV badge must render");
  assert.ok(html.includes("TIER_1_PLATINUM"), "Waterfall tier must render");
  assert.ok(html.includes("Originating Partner: BlueLine Mobility"), "Double-blind origin partner must render");
  assert.ok(!html.includes("client_receivable_paise"), "Corporate client rate must NOT be leaked");
});

test("Hyper-Network Module 2: Smart Surge Slider renders Margin Floor Guardrail", () => {
  const container = new MockElement("network-view");
  const view = new PartnerExchangeView({
    container,
    user: { tenant_id: "vendor_1", role: "TENANT_DISPATCHER", company_name: "Apex Fleet" }
  });

  view.openSurgeModal({
    id: "net_duty_102",
    supplier_payout_inr: 2000.0,
    client_receivable_inr: 3000.0,
    base_payout_inr: 2000.0,
    margin_floor_pct: 12.0
  });

  const modalHtml = container.innerHTML;
  assert.ok(modalHtml.includes("surge-modal-backdrop"), "Surge modal container must render");
  assert.ok(modalHtml.includes("Smart Clearing Surge Slider"), "Surge modal header must render");
  assert.ok(modalHtml.includes("surge-slider-input"), "Surge slider must render");
  assert.ok(modalHtml.includes("Margin Safe") || modalHtml.includes("Margin Floor Breached"), "Margin guardrail must be active");
});

test("Hyper-Network Module 4: Empty-Leg Return Deadhead Matchmaker renders Corridor Radar", () => {
  const container = new MockElement("network-view");
  const view = new PartnerExchangeView({
    container,
    user: { tenant_id: "vendor_1", role: "TENANT_DISPATCHER", company_name: "Apex Fleet" }
  });

  view.state.activeTab = "EMPTY_LEGS";
  view.state.emptyLegs = [
    {
      id: "el_corridor_99",
      vendor_name: "MetroFleet Cabs",
      origin_city: "Mysuru",
      destination_city: "Bengaluru",
      corridor_name: "Mysuru -> Bengaluru Expressway Deadhead",
      vehicle_category: "Innova Crysta",
      discounted_partner_rate_per_km: 12.6,
      standard_rate_per_km: 18.0,
      discount_pct: 30.0,
      status: "AVAILABLE"
    }
  ];

  view.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Empty-Leg Deadhead Return Matchmaker"), "Empty-Leg header must render");
  assert.ok(html.includes("Mysuru -> Bengaluru"), "Route must render");
  assert.ok(html.includes("-30% below standard tariff"), "Discount badge must render");
  assert.ok(html.includes("Innova Crysta"), "Vehicle category must render");
});

test("Hyper-Network Module 5: Demand Swarm Radar renders Heatmap Cells", () => {
  const container = new MockElement("network-view");
  const view = new PartnerExchangeView({
    container,
    user: { tenant_id: "vendor_1", role: "TENANT_DISPATCHER", company_name: "Apex Fleet" }
  });

  view.state.activeTab = "DEMAND_SWARM";
  view.state.demandSwarm = [
    { zone: "Aerocity / IGI Airport", predicted_duties: 48, active_partner_idle_vehicles: 12, deficit: 36, surge_eligible: true, surge_boost_pct: 15.0 },
    { zone: "Cyber Hub / DLF Ph 2", predicted_duties: 35, active_partner_idle_vehicles: 32, deficit: 3, surge_eligible: false, surge_boost_pct: 0 }
  ];

  view.render();
  const html = container.innerHTML;

  assert.ok(html.includes("City Demand Swarm Heatmap"), "Swarm title must render");
  assert.ok(html.includes("Aerocity / IGI Airport"), "Zone must render");
  assert.ok(html.includes("SURGE ELIGIBLE"), "High demand zone must trigger surge badge");
  assert.ok(html.includes("BALANCED"), "Balanced zone must show balanced badge");
});

test("Hyper-Network Module 3: VendorCommandDashboard renders Instant T+0 Factoring Drawer", () => {
  const container = new MockElement("dashboard-view");
  const dash = new VendorCommandDashboard({
    container,
    user: { tenant_id: "vendor_test", role: "TENANT_DISPATCHER" }
  });

  dash.openDrawerForType("factoring_cashout");
  const html = elementsById["drawer-root"] ? elementsById["drawer-root"].innerHTML : "";

  assert.ok(html.includes("T+0 Instant Factoring Clearinghouse"), "T+0 Clearinghouse header must render");
  assert.ok(html.includes("1.75%"), "Platform factoring fee rate must render");
  assert.ok(html.includes("Instant Cash-Out to Wallet"), "Action button must render");
});
