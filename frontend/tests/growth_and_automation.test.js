import test from "node:test";
import assert from "node:assert/strict";
import { ParseAiIntake } from "../js/components/ParseAiIntake.js";
import { CorporateAnnexurePortal } from "../js/components/CorporateAnnexurePortal.js";
import { AdminSaasConsole } from "../js/components/AdminSaasConsole.js";
import { CompletedTripsImporterUI } from "../js/components/CompletedTripsImporterUI.js";

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
  getAttribute(attr) {
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

test("Growth & Automation 1: ParseAiIntake renders split-pane layout, test templates, and theoretical estimates", () => {
  const container = new MockElement("parse-ai-view");
  const intake = new ParseAiIntake({ container });
  intake.render();

  assert.match(intake.container.innerHTML, /Parse AI — WhatsApp & Email Intake Engine/);
  assert.match(intake.container.innerHTML, /Airport Drop \(Rohan\)/);
  assert.match(intake.container.innerHTML, /8hr\/80km Package \(Priya\)/);
  assert.match(intake.container.innerHTML, /Outstation Mysore \(Vikram\)/);
  assert.match(intake.container.innerHTML, /Parse Booking Details/);

  // Set parsed state
  intake.state.parsedData = {
    passenger_name: "Rohan Deshmukh",
    passenger_phone: "9845012345",
    pickup_datetime: "2026-11-04 06:30:00",
    pickup_address_raw: "Koramangala 4th Block",
    drop_address_raw: "BLR Kempegowda Airport",
    vehicle_category_hint: "SEDAN",
    duty_type: "AIRPORT_TRANSFER",
    confidence: 0.95,
    estimated_distance_km: 38.4,
    estimated_duration_mins: 72,
    estimated_client_fare_inr: 1650.0,
    estimated_supplier_payout_inr: 1320.0,
  };
  intake.render();

  assert.match(intake.container.innerHTML, /95% Confidence/);
  assert.match(intake.container.innerHTML, /Rohan Deshmukh/);
  assert.match(intake.container.innerHTML, /38\.4 km/);
  assert.match(intake.container.innerHTML, /1,?650/);
  assert.match(intake.container.innerHTML, /Confirm & Create Booking/);
});

test("Growth & Automation 2: CorporateAnnexurePortal renders zero-login proforma review, proof links & decisions", () => {
  const container = new MockElement("annexure-view");
  const portal = new CorporateAnnexurePortal({ container, token: "test-token-xyz" });
  portal.state.isLoading = false;
  portal.state.proformaData = {
    corporate_name: "Infosys Technologies Ltd",
    proforma_id: "PROF-2026-881",
    status: "PENDING_REVIEW",
    summary: {
      total_duties: 2,
      approved_count: 1,
      flagged_count: 0,
      total_amount_inr: 3250.0,
      total_km: 74.5,
    },
    duties: [
      {
        id: "DUTY-101",
        duty_date: "2026-11-01",
        passenger_name: "Anita Sharma",
        route_name: "Electronic City to BLR Airport",
        vehicle_category: "SEDAN",
        practical_billable_km: 52.0,
        estimated_distance_km: 49.0,
        final_client_fare_inr: 1950.0,
        physical_tripsheet_file_url: "https://storage.axiommobility.in/slip_101.png",
      },
      {
        id: "DUTY-102",
        duty_date: "2026-11-02",
        passenger_name: "Karan Johar",
        route_name: "Whitefield to Koramangala",
        vehicle_category: "SUV_CRYSTA",
        practical_billable_km: 22.5,
        estimated_distance_km: 20.0,
        final_client_fare_inr: 1300.0,
      },
    ],
  };
  portal.state.decisions = {
    "DUTY-101": { status: "APPROVED" },
    "DUTY-102": { status: "FLAGGED", reason: "Excess KM claimed" },
  };
  portal.render();

  assert.match(portal.container.innerHTML, /Infosys Technologies Ltd/);
  assert.match(portal.container.innerHTML, /PROF-2026-881/);
  assert.match(portal.container.innerHTML, /Anita Sharma/);
  assert.match(portal.container.innerHTML, /View Slip/);
  assert.match(portal.container.innerHTML, /Submit Review Decisions/);
  assert.match(portal.container.innerHTML, /Specify dispute reason/);
});

test("Growth & Automation 3: AdminSaasConsole renders SaaS Dues KPI Radar and 3-State Access Control Pills", () => {
  const container = new MockElement("admin-saas-view");
  const consoleComp = new AdminSaasConsole({ container });
  consoleComp.state.activeView = "RECEIVABLES";
  consoleComp.state.overview = {
    total_tenants: 2,
    total_receivables_outstanding_paise: 38420000,
    tenants: [
      {
        tenant_id: "org_rapid",
        tenant_name: "RapidFleet Logistics",
        user_count: 2,
        trip_count: 40,
        total_billed_paise: 40000000,
        total_paid_paise: 25000000,
        amount_owed_paise: 15000000,
        days_overdue: 14,
        account_status: "ACTIVE",
        access_control_state: "ACTIVE_GOOD_STANDING",
      },
      {
        tenant_id: "org_city",
        tenant_name: "CityFleet Cabs",
        user_count: 1,
        trip_count: 20,
        total_billed_paise: 30000000,
        total_paid_paise: 10000000,
        amount_owed_paise: 20000000,
        days_overdue: 35,
        account_status: "SOFT_BLOCKED",
        access_control_state: "SOFT_LOCKED_OVERDUE",
      },
    ],
  };
  consoleComp.render();

  assert.match(consoleComp.container.innerHTML, /SaaS Subscription Receivables & Dunning Radar/);
  assert.match(consoleComp.container.innerHTML, /3,?84,?200/);
  assert.match(consoleComp.container.innerHTML, /data-action="toggle-3state-access"/);
  assert.match(consoleComp.container.innerHTML, /data-state="ACTIVE_GOOD_STANDING"/);
  assert.match(consoleComp.container.innerHTML, /data-state="SOFT_LOCKED_OVERDUE"/);
  assert.match(consoleComp.container.innerHTML, /data-state="HARD_BLOCKED_NON_PAYMENT"/);
});

test("Growth & Automation 4: CompletedTripsImporterUI provides 4-Tab Master Onboarding Switching", () => {
  const container = new MockElement("importer-view");
  const importer = new CompletedTripsImporterUI({ container });
  importer.render();

  assert.match(importer.container.innerHTML, /Vehicles Master/);
  assert.match(importer.container.innerHTML, /Drivers Master/);
  assert.match(importer.container.innerHTML, /Corporate Clients & Rate Cards/);
  assert.match(importer.container.innerHTML, /Completed Trips/);

  // Switch to Vehicles Master tab
  importer.state.activeMasterTab = "VEHICLES";
  importer.render();

  assert.match(importer.container.innerHTML, /1-Click Master Vehicle Fleet Importer/);
  assert.match(importer.container.innerHTML, /Download VEHICLES CSV Template/);
});
