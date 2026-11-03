import test from "node:test";
import assert from "node:assert/strict";
import { TimesFmForecastWidget } from "../js/components/TimesFmForecastWidget.js";

// Minimal DOM mock with attribute and event listener support
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
      elementsMap.set(el.id || "widget", el);
    },
  },
};
globalThis.window = {
  addEventListener: () => {},
};

test("TimesFmForecastWidget - initial state and currency formatters", () => {
  const widget = new TimesFmForecastWidget({
    vendorId: "vendor-123",
    corporateId: "corp-456",
    initialMode: "VENDOR_EARNINGS",
    initialHorizon: 30,
  });

  assert.equal(widget.state.mode, "VENDOR_EARNINGS");
  assert.equal(widget.state.horizonDays, 30);
  assert.equal(widget.vendorId, "vendor-123");
  assert.equal(widget.corporateId, "corp-456");

  // Currency formatting tests
  assert.equal(widget.formatInr(0), "₹0");
  assert.equal(widget.formatInr(54321), "₹54,321");
  assert.equal(widget.formatShortInr(850), "₹850");
  assert.equal(widget.formatShortInr(12500), "₹12.5 k");
  assert.equal(widget.formatShortInr(450000), "₹4.50 L");
  assert.equal(widget.formatShortInr(25000000), "₹2.50 Cr");
});

test("TimesFmForecastWidget - renderFanChartSvg outputs SVG elements and confidence cone", () => {
  const widget = new TimesFmForecastWidget();
  const mockData = {
    model_backend_used: "google/timesfm-2.0-500m-pytorch",
    historical_series: [
      { date: "2026-10-01", actual_amount_inr: 8000, trip_count: 5 },
      { date: "2026-10-02", actual_amount_inr: 12000, trip_count: 8 },
      { date: "2026-10-03", actual_amount_inr: 15000, trip_count: 10 },
    ],
    forecast_series: [
      { date: "2026-10-04", p10_inr: 9000, p50_expected_inr: 13000, p90_inr: 17000, predicted_trips: 9 },
      { date: "2026-10-05", p10_inr: 9500, p50_expected_inr: 13500, p90_inr: 18000, predicted_trips: 9 },
    ],
    summary_metrics: {
      total_p50_inr: 26500,
      total_p10_inr: 18500,
      total_p90_inr: 35000,
      growth_trend_pct: 8.5,
      confidence_score: 0.92,
    },
  };

  const svgHtml = widget.renderFanChartSvg(mockData);
  assert.match(svgHtml, /<svg viewBox="0 0 800 260"/);
  // Fan chart confidence cone
  assert.match(svgHtml, /fill="url\(#fanFill\)"/);
  // Split line for 'Today'
  assert.match(svgHtml, /TODAY/);
  // Historical solid line
  assert.match(svgHtml, /stroke="#38bdf8"/);
  // Forecast p50 expected line
  assert.match(svgHtml, /stroke="#818cf8"/);
});

test("TimesFmForecastWidget - render outputs vendor earnings cards and liquidity projection", () => {
  const host = new MockElement("vendor-widget");
  const widget = new TimesFmForecastWidget({
    container: host,
    initialMode: "VENDOR_EARNINGS",
    initialHorizon: 30,
  });

  widget.state.data = {
    model_backend_used: "google/timesfm-2.0-500m-pytorch",
    historical_series: [{ date: "2026-10-01", actual_amount_inr: 8000 }],
    forecast_series: [{ date: "2026-10-02", p10_inr: 7000, p50_expected_inr: 10000, p90_inr: 14000 }],
    summary_metrics: {
      total_p50_inr: 450000,
      total_p10_inr: 390000,
      total_p90_inr: 520000,
      projected_week1_unlock_inr: 105000,
      projected_week2_unlock_inr: 110000,
      default_fund_hold_hours: 48,
      capacity_recommendation: "Strong airport rush projected. Adding 1 vehicle could increase earnings.",
    },
  };

  widget.render();

  assert.match(host.innerHTML, /Expected 30-Day Earnings \(p50\)/);
  assert.match(host.innerHTML, /₹4,50,000/);
  assert.match(host.innerHTML, /Projected Withdrawable Cash Flow/);
  assert.match(host.innerHTML, /₹1,05,000/);
  assert.match(host.innerHTML, /48h hold/);
  assert.match(host.innerHTML, /AI Capacity & Fleet Advice/);
  assert.match(host.innerHTML, /Google TimesFM 500M/);
});

test("TimesFmForecastWidget - render outputs corporate budget breach alert and cost saving advice", () => {
  const host = new MockElement("corp-widget");
  const widget = new TimesFmForecastWidget({
    container: host,
    initialMode: "CORPORATE_EXPENDITURE",
    initialHorizon: 30,
  });

  widget.state.data = {
    model_backend_used: "axiom_seasonal_quantile_v1",
    historical_series: [{ date: "2026-10-01", actual_amount_inr: 25000 }],
    forecast_series: [{ date: "2026-10-02", p10_inr: 20000, p50_expected_inr: 28000, p90_inr: 35000 }],
    summary_metrics: {
      budget_cap_inr: 500000,
      projected_month_end_spend_inr: 610000,
      budget_exhaustion_pct: 122,
      alert_status: "BREACH_PREDICTED",
      budget_breach_date: "2026-10-24",
      days_until_breach: 12,
      breach_variance_inr: 110000,
      cost_saving_optimization: "Converting 8 ad-hoc airport spot rentals into monthly scheduled ETS passes saves ₹35,000.",
    },
  };

  widget.render();

  assert.match(host.innerHTML, /Projected Month-End Spend/);
  assert.match(host.innerHTML, /₹6,10,000/);
  assert.match(host.innerHTML, /Budget Breach Alert/);
  assert.match(host.innerHTML, /Breach in 12 days \(2026-10-24\)/);
  assert.match(host.innerHTML, /Cost-Saving Optimization/);
  assert.match(host.innerHTML, /Converting 8 ad-hoc airport spot rentals/);
  assert.match(host.innerHTML, /Axiom Harmonic Quantile v1/);
});

test("TimesFmForecastWidget - mount, fetchForecast and mode toggling", async () => {
  const host = new MockElement("test-container");
  elementsMap.set("test-container", host);

  // Mock global fetch
  globalThis.fetch = async (url) => {
    return {
      ok: true,
      json: async () => ({
        tenant_id: "00000000-0000-0000-0000-000000000001",
        model_backend_used: "axiom_seasonal_quantile_v1",
        historical_series: [{ date: "2026-10-01", actual_amount_inr: 5000 }],
        forecast_series: [{ date: "2026-10-02", p10_inr: 4000, p50_expected_inr: 5200, p90_inr: 6500 }],
        summary_metrics: {
          total_p50_inr: 5200,
          total_p10_inr: 4000,
          total_p90_inr: 6500,
          growth_trend_pct: 4.0,
          projected_week1_unlock_inr: 5200,
          projected_week2_unlock_inr: 5200,
        },
      }),
    };
  };

  const widget = new TimesFmForecastWidget({
    container: host,
    initialMode: "VENDOR_EARNINGS",
    initialHorizon: 7,
  });

  await widget.fetchForecast();
  assert.equal(widget.state.isLoading, false);
  assert.ok(widget.state.data);
  assert.match(host.innerHTML, /Vendor Future Earnings & Cash-Flow Forecaster/);
  assert.match(host.innerHTML, /Axiom Harmonic Quantile v1/);

  // Switch horizon and mode
  widget.setHorizon(90);
  assert.equal(widget.state.horizonDays, 90);

  widget.setMode("CORPORATE_EXPENDITURE");
  assert.equal(widget.state.mode, "CORPORATE_EXPENDITURE");
});
