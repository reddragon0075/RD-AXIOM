import test from "node:test";
import assert from "node:assert/strict";
import { AdminSaasConsole } from "../js/components/AdminSaasConsole.js";
import { VendorCommandDashboard } from "../js/components/VendorCommandDashboard.js";

// DOM mock with event bubbling & delegation support
class MockElement {
  constructor(id = "", tagName = "div") {
    this.id = id;
    this.tagName = tagName.toUpperCase();
    this._innerHTML = "";
    this.listeners = {};
    this.dataset = {};
    this.parentNode = null;
    this.classList = {
      _classes: new Set(),
      add: (c) => this.classList._classes.add(c),
      remove: (c) => this.classList._classes.delete(c),
      toggle: (c, force) => {
        if (force === undefined) {
          if (this.classList._classes.has(c)) this.classList._classes.delete(c);
          else this.classList._classes.add(c);
        } else if (force) this.classList._classes.add(c);
        else this.classList._classes.delete(c);
      },
      contains: (c) => this.classList._classes.has(c),
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

  closest(selector) {
    // Basic selector match
    if (selector.startsWith("#") && this.id === selector.slice(1)) return this;
    if (selector.startsWith(".") && this.classList.contains(selector.slice(1))) return this;
    if (selector.includes("[data-view]") && this.dataset.view) return this;
    if (selector.includes("[data-action]") && this.dataset.action) return this;
    return this.parentNode ? this.parentNode.closest(selector) : null;
  }

  querySelector(sel) {
    return new MockElement("mock-child");
  }
  querySelectorAll(sel) {
    return [];
  }
}

globalThis.document = {
  getElementById: (id) => new MockElement(id),
  querySelector: (sel) => new MockElement(),
};

test("DOM View Switch Integrity 1: AdminSaasConsole toggles views 10 times with zero leaks", () => {
  const container = new MockElement("saas-console-view");
  const consoleComp = new AdminSaasConsole({ container });

  const views = ["TENANTS", "RECEIVABLES", "PROSPECTS", "SIMULATOR"];
  for (let i = 0; i < 10; i++) {
    const view = views[i % views.length];
    consoleComp.state.activeView = view;
    consoleComp.render();
    assert.ok(container.innerHTML.length > 50, `View ${view} rendered meaningful content`);
  }

  // Verify AbortController clean teardown
  consoleComp.destroy();
  assert.ok(consoleComp.abortController.signal.aborted, "AbortController aborted on destroy");
});

test("DOM View Switch Integrity 2: VendorCommandDashboard toggles lenses & modes 10 times cleanly", () => {
  const container = new MockElement("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });

  for (let i = 0; i < 10; i++) {
    dashboard.state.dashboardLens = i % 2 === 0 ? "OPERATIONAL" : "REVENUE";
    dashboard.state.businessLine = i % 2 === 0 ? "RAC" : "ETS";
    dashboard.render();
    assert.ok(container.innerHTML.length > 50, `Cycle ${i} rendered view`);
  }

  dashboard.destroy();
  assert.ok(dashboard.abortController.signal.aborted, "AbortController aborted on destroy");
});
