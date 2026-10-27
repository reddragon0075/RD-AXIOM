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
}

globalThis.document = {
  getElementById: (id) => new MockElement(id),
};

test("Commercial Control Plane 1: AdminSaasConsole renders Executive Summary Bar & Receivables Ledger", async () => {
  const container = new MockElement("admin-saas-view");
  const consoleComp = new AdminSaasConsole({ container });

  // Inject known census & receivables state
  consoleComp.state.overview = {
    total_tenants: 3,
    active_tenants: 2,
    blocked_tenants: 1,
    total_users_in_system: 8,
    total_drivers: 74,
    total_prospects_pending: 3,
    total_receivables_outstanding_paise: 45520000,
    overdue_receivables_amount_paise: 32000000,
    total_receivables_inr: 455200,
    overdue_receivables_inr: 320000,
    tenants: [
      {
        tenant_id: "org_vendor_rapid",
        tenant_name: "RapidFleet Logistics Pvt Ltd",
        user_count: 3,
        trip_count: 55,
        total_billed_paise: 48520000,
        total_paid_paise: 35000000,
        amount_owed_paise: 13520000,
        days_overdue: 12,
        account_status: "ACTIVE",
        block_reason: "",
      },
      {
        tenant_id: "org_vendor_cityfleet",
        tenant_name: "CityFleet Commercial Transport",
        user_count: 2,
        trip_count: 35,
        total_billed_paise: 62000000,
        total_paid_paise: 30000000,
        amount_owed_paise: 32000000,
        days_overdue: 45,
        account_status: "SOFT_BLOCKED",
        block_reason: "Overdue invoice > 30 days",
      },
    ],
  };

  consoleComp.render();
  const html = container.innerHTML;

  // 1. Executive Summary checks
  assert.ok(html.includes("8 Users"), "Must render total users in system census");
  assert.ok(html.includes("74 Active Drivers"), "Must render total drivers");
  assert.ok(html.includes("1 Suspended / Blocked"), "Must render blocked tenant count");
  assert.ok(html.includes("3 Leads"), "Must render pending prospects count");
  assert.ok(html.includes("₹4,55,200"), "Must render total receivables owed to Axiom");

  // 2. Switch to Receivables & Kill-Switch view
  consoleComp.state.activeView = "RECEIVABLES";
  consoleComp.render();
  const recHtml = container.innerHTML;

  assert.ok(recHtml.includes("RapidFleet Logistics Pvt Ltd"), "Must render tenant name");
  assert.ok(recHtml.includes("CityFleet Commercial Transport"), "Must render delinquent tenant");
  assert.ok(recHtml.includes("SOFT BLOCKED"), "Must render soft blocked status");
  assert.ok(recHtml.includes("45 Days Overdue"), "Must render overdue days badge");
  assert.ok(recHtml.includes('data-action="unblock-tenant"'), "Must render unblock button for delinquent tenant");
  assert.ok(recHtml.includes('data-action="block-tenant"'), "Must render block button for active tenant");
  assert.ok(recHtml.includes('data-action="record-payment"'), "Must render record payment button");
});

test("Commercial Control Plane 2: AdminSaasConsole renders Prospects Sales CRM Table", async () => {
  const container = new MockElement("admin-saas-view");
  const consoleComp = new AdminSaasConsole({ container });

  consoleComp.state.activeView = "PROSPECTS";
  consoleComp.state.prospects = [
    {
      id: "prsp_test_99",
      contact_name: "Karan Johar",
      company_name: "Dharma Transports",
      email: "karan@dharma.in",
      mobile_number: "+919822334455",
      message: "Need 30 luxury sedans for film city commute.",
      status: "NEW",
      sales_notes: [{ timestamp: new Date().toISOString(), author: "sales@axiomfleet.in", note: "Intro call scheduled" }],
      converted_tenant_id: null,
    },
    {
      id: "prsp_test_100",
      contact_name: "Sunil Shetty",
      company_name: "Popcorn Shuttles",
      email: null,
      mobile_number: "+919811002233",
      status: "ONBOARDED",
      converted_tenant_id: "org_vendor_popcorn",
      sales_notes: [],
    },
  ];

  consoleComp.render();
  const html = container.innerHTML;

  assert.ok(html.includes("Karan Johar"), "Must render prospect contact name");
  assert.ok(html.includes("Dharma Transports"), "Must render prospect company");
  assert.ok(html.includes("+919822334455"), "Must render mobile number");
  assert.ok(html.includes("NEW LEAD"), "Must render NEW LEAD badge");
  assert.ok(html.includes('data-action="log-call-note"'), "Must render log call note action");
  assert.ok(html.includes('data-action="onboard-prospect"'), "Must render 1-click onboard action");
  assert.ok(html.includes("Converted: org_vendor_popcorn"), "Must render converted tenant ID for onboarded prospect");
});

test("Commercial Control Plane 3: VendorCommandDashboard renders Hard-Blocked Lock Screen", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });

  // Tenant is hard-blocked for non-payment
  dashboard.setTenantBlockedState({
    account_status: "HARD_BLOCKED",
    amount_owed_paise: 32000000, // ₹3,20,000
    block_reason: "Account payment overdue past 30-day grace period.",
  });

  const html = container.innerHTML;
  assert.ok(html.includes("tenant-suspended-lock-screen"), "Must render lock screen overlay");
  assert.ok(html.includes("Account Suspended — Payment Overdue"), "Must render headline");
  assert.ok(html.includes("₹3,20,000"), "Must render amount owed in INR");
  assert.ok(html.includes("billing@axiomfleet.in"), "Must render billing contact information");
});

test("Commercial Control Plane 4: VendorCommandDashboard renders Soft-Blocked Warning Banner", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });

  // Tenant is soft-blocked
  dashboard.setTenantBlockedState({
    account_status: "SOFT_BLOCKED",
    amount_owed_paise: 12500000, // ₹1,25,000
    block_reason: "Pending monthly subscription settlement.",
  });

  const html = container.innerHTML;
  assert.ok(html.includes("tenant-soft-block-banner"), "Must render soft block banner");
  assert.ok(html.includes("Account Restricted — Payment Overdue"), "Must render soft block text");
  assert.ok(html.includes("₹1,25,000"), "Must render amount owed");
  assert.ok(html.includes("Active in-flight trips may still be safely concluded"), "Must confirm active trips allowed");
});
