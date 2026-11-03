import test from "node:test";
import assert from "node:assert/strict";
import { compressTripSheetImage } from "../js/utils/imageCompressor.js";
import { debounce, throttle } from "../js/utils/debounce.js";
import { TablePagination } from "../js/utils/tablePagination.js";
import { ModuleLoader, globalModuleLoader } from "../js/utils/moduleLoader.js";
import { ExecutiveWorkspaceShell } from "../js/components/ExecutiveWorkspaceShell.js";

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
    return new MockElement(sel);
  }
  querySelectorAll(sel) {
    return [new MockElement(sel)];
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
  querySelector: (sel) => new MockElement(sel),
  querySelectorAll: (sel) => [],
  createElement: (tag) => new MockElement(tag),
  head: { appendChild: () => {} },
  body: {
    appendChild: (el) => {
      elementsMap.set(el.id || "shell", el);
    },
  },
};
globalThis.window = {
  innerWidth: 1200,
  addEventListener: () => {},
};

test("imageCompressor - handles file compression fallback in test environment", async () => {
  const mockFile = {
    name: "tripsheet_camera_photo.jpg",
    size: 7 * 1024 * 1024, // 7MB
    type: "image/jpeg",
  };

  const result = await compressTripSheetImage(mockFile, {
    maxWidth: 1600,
    quality: 0.78,
  });

  assert.ok(result);
  assert.equal(result.originalSizeBytes, 7 * 1024 * 1024);
  assert.lessThanOrEqual ? assert.lessThanOrEqual(result.compressedSizeBytes, 200000) : assert.ok(result.compressedSizeBytes <= 200000);
  assert.ok(result.compressionRatio < 0.1);
  assert.equal(result.width, 1600);
});

test("debounce and throttle - control function invocation timing", async () => {
  let callCount = 0;
  let lastVal = null;
  const debouncedFn = debounce((val) => {
    callCount++;
    lastVal = val;
  }, 50);

  debouncedFn("a");
  debouncedFn("b");
  debouncedFn("c");

  assert.equal(callCount, 0); // Not called immediately
  await new Promise((r) => setTimeout(r, 80));
  assert.equal(callCount, 1);
  assert.equal(lastVal, "c");

  // Test cancellation
  debouncedFn("d");
  debouncedFn.cancel();
  await new Promise((r) => setTimeout(r, 80));
  assert.equal(callCount, 1); // Remains 1 because 'd' was cancelled
});

test("TablePagination - divides rows into 50-row pages with search filtering", () => {
  // Generate 125 test rows
  const mockRows = [];
  for (let i = 1; i <= 125; i++) {
    mockRows.push({
      id: `duty_${i}`,
      ref: `TS-2026-${i}`,
      client: i % 2 === 0 ? "Goldman Sachs" : "Infosys",
      fare: 1500 + i * 10,
    });
  }

  const pager = new TablePagination({ rows: mockRows, pageSize: 50 });
  assert.equal(pager.getTotalPages(), 3);

  // Page 1 should contain 50 rows
  const page1 = pager.getPageRows();
  assert.equal(page1.length, 50);
  assert.equal(page1[0].ref, "TS-2026-1");

  // Page 3 should contain 25 rows
  pager.setPage(3);
  const page3 = pager.getPageRows();
  assert.equal(page3.length, 25);
  assert.equal(page3[24].ref, "TS-2026-125");

  // Search filter
  pager.setSearch("Goldman");
  assert.equal(pager.filteredRows.length, 62);
  assert.equal(pager.currentPage, 1);

  // Pagination HTML controls
  const html = pager.renderPaginationControls();
  assert.match(html, /Showing/);
  assert.match(html, /62/);
  assert.match(html, /Page 1 of 2/);
});

test("ModuleLoader - manages dynamic module keys and abort signal", async () => {
  const loader = new ModuleLoader();
  assert.ok(loader.moduleRegistry.BULK_IMPORTER);
  assert.ok(loader.moduleRegistry.TIMESFM_FORECAST);

  const signal1 = loader.getAbortSignal();
  assert.equal(signal1.aborted, false);

  // Getting a new signal aborts the previous one
  const signal2 = loader.getAbortSignal();
  assert.equal(signal1.aborted, true);
  assert.equal(signal2.aborted, false);

  // Clean up
  loader.cleanupActiveView("BULK_IMPORTER");
  assert.equal(signal2.aborted, true);
});

test("ExecutiveWorkspaceShell - mounts 4-pillar navigation and toggles clean/audit mode", async () => {
  const host = new MockElement("shell-host");
  elementsMap.set("shell-host", host);

  // Mock global fetch for bootstrap
  globalThis.fetch = async (url) => {
    return {
      ok: true,
      json: async () => ({
        ok: true,
        status: "ok",
        tenant_access: { status: "ACTIVE_GOOD_STANDING", treasury_hold_active: false },
        duty_counts: { unassigned_count: 5, running_count: 12, discrepancy_to_close_count: 1, completed_today_count: 24 },
        dual_ledger_summary: { total_receivable_inr: 95000, total_payable_inr: 76000, net_margin_inr: 19000, margin_pct: 20.0, held_float_inr: 19000 },
      }),
    };
  };

  const shell = new ExecutiveWorkspaceShell({
    container: host,
    initialPillar: "OPERATIONS",
  });

  await shell.fetchBootstrapSummary();

  assert.equal(shell.state.isLoadingBootstrap, false);
  assert.match(host.innerHTML, /AXIOM/);
  assert.match(host.innerHTML, /12 Active · 5 Draft/);
  assert.match(host.innerHTML, /Live Operations & OSM Dispatch/);
  assert.match(host.innerHTML, /Trip Closure & Bulk Import/);
  assert.match(host.innerHTML, /Dual-Ledger Finance & AI Forecast/);
  assert.match(host.innerHTML, /Native CRM, Partner Network & Admin/);

  // Verify Clean Mode (8 core cols)
  assert.match(host.innerHTML, /Clean View: Showing 8 Critical Operational Columns/);
  assert.match(host.innerHTML, /8\. Client Fare/);

  // Toggle to Pro Audit Mode
  shell.toggleAuditMode();
  assert.equal(shell.state.auditMode, true);
  assert.match(host.innerHTML, /Pro Audit Mode \(Expanded\)/);
  assert.match(host.innerHTML, /Theoretical vs Practical/);
  assert.match(host.innerHTML, /Dead-Mileage Gap/);

  // Switch pillar
  shell.setPillar("CLOSURE");
  assert.equal(shell.state.activePillar, "CLOSURE");
  assert.match(host.innerHTML, /bulk-importer-mount-target/);
});
