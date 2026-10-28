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

test("Treasury Feature 1: AdminSaasConsole renders Global Treasury Control Bar", () => {
  const container = new MockElement("saas-console-view");
  const consoleComp = new AdminSaasConsole({ container });

  consoleComp.state.treasury = {
    global_payout_release_enabled: false,
    default_fund_hold_hours: 72,
    t0_instant_cashout_enabled: true,
    total_funds_held_paise: 148250000,
    total_funds_held_inr: 1482500.0,
    total_mature_ready_paise: 61000000,
    total_mature_ready_inr: 610000.0,
    held_duties_count: 48,
    mature_duties_count: 18,
  };

  consoleComp.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Total Funds Held in Float"), "Float title must render");
  assert.ok(html.includes("14,82,500"), "Held float amount ₹14,82,500 must render");
  assert.ok(html.includes("Mature &amp; Ready to Release"), "Mature title must render");
  assert.ok(html.includes("6,10,000"), "Mature ready amount ₹6,10,000 must render");
  assert.ok(html.includes("HOLD ALL RELEASES"), "Master hold switch must show HOLD ALL RELEASES when locked");
  assert.ok(html.includes("treasury-hold-duration-select"), "Hold duration dropdown must render");
  assert.ok(html.includes("Release Mature Funds"), "Primary release action button must render");
});

test("Treasury Feature 2: AdminSaasConsole renders Per-Vendor Hold/Release Toggle in Tenants Table", () => {
  const container = new MockElement("saas-console-view");
  const consoleComp = new AdminSaasConsole({ container });

  consoleComp.state.tenants = [
    {
      tenant_id: 101,
      tenant_name: "Apex Fleet Solutions",
      phone: "+91 98450 11223",
      email: "ops@apexfleet.in",
      plan_tier: "GROWTH",
      subscription_status: "ACTIVE",
      mrr_paise: 4500000,
      corporate_quota: { used: 3, total: 5 },
      trip_quota: { used: 120, total: 500 },
      wallet_balance_paise: 2500000,
      held_float_paise: 4200000,
      withdrawable_paise: 500000,
      payout_hold_override: "FORCE_HOLD",
      features: { network: true, market: true, whatsapp_bot: false },
    },
  ];

  consoleComp.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Wallet & Payouts") || html.includes("Wallet &amp; Payouts"), "Table column must render Wallet & Payouts");
  assert.ok(html.includes("Held Float: ₹42,000"), "Held float must render ₹42,000");
  assert.ok(html.includes("Withdrawable: ₹5,000"), "Withdrawable must render ₹5,000");
  assert.ok(html.includes("Hold Funds: ON"), "Vendor toggle must render Hold Funds: ON when FORCE_HOLD");
});

test("Treasury Feature 3: VendorCommandDashboard renders Dual-Ledger P&L & Payouts Transparency Card", () => {
  const container = new MockElement("dashboard-view");
  const dash = new VendorCommandDashboard({
    container,
    user: { tenant_id: "vendor_apex", role: "TENANT_DISPATCHER" },
  });

  dash.state.dashboardLens = "REVENUE";
  dash.state.payoutBalance = {
    total_earned_paise: 36290000,
    in_clearing_held_paise: 11290000,
    released_withdrawable_paise: 25000000,
    payout_hold_override: "INHERIT_GLOBAL",
    payout_hold_reason: "",
  };

  dash.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Dual-Ledger P&amp;L &amp; Payouts"), "P&L & Payouts header must render");
  assert.ok(html.includes("Total Earned (Payable):"), "Total earned label must render");
  assert.ok(html.includes("3,62,900"), "Total earned amount ₹3,62,900 must render");
  assert.ok(html.includes("In Clearing / Held by Axiom:"), "In Clearing label must render");
  assert.ok(html.includes("1,12,900"), "Held by Axiom amount ₹1,12,900 must render");
  assert.ok(html.includes("Funds are held during the standard verification"), "Tooltip must explain clearing period");
  assert.ok(html.includes("Released &amp; Withdrawable:"), "Released label must render");
  assert.ok(html.includes("2,50,000"), "Withdrawable amount ₹2,50,000 must render");
  assert.ok(html.includes("Withdraw to Bank"), "Withdraw to bank button must render");
});
