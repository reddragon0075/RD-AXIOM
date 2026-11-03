import test from "node:test";
import assert from "node:assert/strict";
import { NativeCrmWorkspace } from "../js/components/NativeCrmWorkspace.js";
import { AdminSaasConsole } from "../js/components/AdminSaasConsole.js";

// Minimal DOM Mock
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

globalThis.document = {
  getElementById: (id) => new MockElement(id),
  querySelector: (sel) => new MockElement(),
  querySelectorAll: (sel) => [],
  createElement: (tag) => new MockElement(tag),
  head: { appendChild: () => {} },
  body: { appendChild: () => {}, removeChild: () => {} },
};

test("Native CRM 1: NativeCrmWorkspace renders Top Command Strip and Global Search", () => {
  const container = new MockElement("crm-view");
  const crm = new NativeCrmWorkspace({ container });
  crm.render();

  assert.match(crm.container.innerHTML, /Total Pipeline GMV/);
  assert.match(crm.container.innerHTML, /Unworked Prospects/);
  assert.match(crm.container.innerHTML, /Total System Census/);
  assert.match(crm.container.innerHTML, /Overdue Owed to Axiom/);
  assert.match(crm.container.innerHTML, /Vendor Escrow Held/);
  assert.match(crm.container.innerHTML, /Search phone, email, GSTIN, company/);
});

test("Native CRM 2: NativeCrmWorkspace renders Dual-Track Kanban Pipeline", () => {
  const container = new MockElement("crm-view");
  const crm = new NativeCrmWorkspace({ container });
  crm.state.activeView = "KANBAN";
  crm.state.deals = [
    {
      id: "deal_001",
      account_id: "acc_001",
      deal_title: "Corporate Mobility - Wipro Technologies",
      pipeline_track: "CORPORATE_DEMAND",
      pipeline_stage: "1_INBOUND_PROSPECT",
      lead_score: 85,
      deal_gmv_estimated_inr: 560000,
      projected_gross_margin_pct: 16.5,
      city: "Bengaluru",
    },
    {
      id: "deal_002",
      account_id: "acc_002",
      deal_title: "Fleet Supply - Sharma Cabs",
      pipeline_track: "CORPORATE_DEMAND",
      pipeline_stage: "4_COMPLIANCE_MSA_REVIEW",
      lead_score: 50,
      deal_gmv_estimated_inr: 280000,
      projected_gross_margin_pct: 14.0,
      city: "Bengaluru",
    },
  ];
  crm.render();

  assert.match(crm.container.innerHTML, /Corporate Mobility - Wipro Technologies/);
  assert.match(crm.container.innerHTML, /85 pts/);
  assert.match(crm.container.innerHTML, /16\.5%/);
  assert.match(crm.container.innerHTML, /Advance Stage ➔/);
  assert.match(crm.container.innerHTML, /1-Click Provision Workspace/);
});

test("Native CRM 3: NativeCrmWorkspace renders 6-Model CPQ Studio & Simulation Spread", () => {
  const container = new MockElement("crm-view");
  const crm = new NativeCrmWorkspace({ container });
  crm.state.activeView = "CPQ";
  crm.state.cpqForm.simulationResult = {
    expected_monthly_gmv_inr: 280000,
    expected_vendor_payout_inr: 235000,
    gross_margin_inr: 45000,
    projected_gross_margin_pct: 16.1,
    margin_approval_status: "APPROVED",
    six_model_breakdown: [
      { name: "Spot Rental Auto-Slab (4H/40K, 8H/80K)", sell_rate: "₹2,800", buy_rate: "₹2,350", margin_pct: "16.1%" },
      { name: "Outstation Roundtrip (Min 250km/day)", sell_rate: "₹16.50/km", buy_rate: "₹13.50/km", margin_pct: "18.2%" },
    ],
  };
  crm.render();

  assert.match(crm.container.innerHTML, /Spread-Aware CPQ Simulator/);
  assert.match(crm.container.innerHTML, /2,?80,?000/);
  assert.match(crm.container.innerHTML, /16\.1%/);
  assert.match(crm.container.innerHTML, /MARGIN APPROVED/);
  assert.match(crm.container.innerHTML, /Spot Rental Auto-Slab/);
});

test("Native CRM 4: NativeCrmWorkspace renders Slide-Over 360° Drawer with Channels & Controls", () => {
  const container = new MockElement("crm-view");
  const crm = new NativeCrmWorkspace({ container });
  crm.state.isDrawerOpen = true;
  crm.state.selectedAccount360 = {
    account: {
      id: "acc_demo",
      account_name: "Infosys Technologies Ltd",
      account_type: "CORPORATE_CLIENT",
      city: "Bengaluru",
      primary_phone: "+919845012345",
      primary_email: "transport@infosys.com",
      tenant_id: "org_infosys_demo",
    },
    operational_pulse: {
      completed_trips_count: 142,
      sla_punctuality_pct: 98.6,
    },
    receivables_aging: {
      total_owed_inr: 135000,
      kill_switch_status: "ACTIVE",
      bucket_0_30_days: 85000,
      bucket_31_60_days: 50000,
      bucket_61_90_days: 0,
      bucket_90_plus_days: 0,
    },
    activities: [
      { subject: "Discovery Call Completed", description: "Agreed on 50 cab ETS", created_at: "2026-11-01" },
    ],
  };
  crm.render();

  assert.match(crm.container.innerHTML, /360° Account Intelligence/);
  assert.match(crm.container.innerHTML, /Infosys Technologies Ltd/);
  assert.match(crm.container.innerHTML, /Call Client/);
  assert.match(crm.container.innerHTML, /WhatsApp/);
  assert.match(crm.container.innerHTML, /Kill-Switch Status/);
  assert.match(crm.container.innerHTML, /142/);
  assert.match(crm.container.innerHTML, /1,?35,?000/);
});

test("Native CRM 5: AdminSaasConsole provides Native-Link CRM v2.0 Tab", () => {
  const container = new MockElement("admin-saas-view");
  const consoleComp = new AdminSaasConsole({ container });
  consoleComp.render();

  assert.match(consoleComp.container.innerHTML, /Native-Link CRM v2\.0/);

  // Switch to NATIVE_CRM view
  consoleComp.state.activeView = "NATIVE_CRM";
  consoleComp.render();

  assert.match(consoleComp.container.innerHTML, /native-crm-mount-point/);
});
