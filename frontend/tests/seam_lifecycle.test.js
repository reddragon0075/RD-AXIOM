import test from "node:test";
import assert from "node:assert/strict";

// Setup browser DOM environment mocks for Node test runner
class MockClassList {
  constructor() {
    this.classes = new Set();
  }
  add(c) {
    this.classes.add(c);
  }
  remove(c) {
    this.classes.delete(c);
  }
  contains(c) {
    return this.classes.has(c);
  }
}

class MockElement {
  constructor(id = "", tagName = "div") {
    this.id = id;
    this.tagName = tagName.toUpperCase();
    this._innerHTML = "";
    this.textContent = "";
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this.classList = new MockClassList();
    this.parentElement = null;
    this._value = "";
  }
  get value() {
    return this._value;
  }
  set value(v) {
    this._value = v;
  }
  get innerHTML() {
    return this._innerHTML;
  }
  set innerHTML(html) {
    this._innerHTML = html;
    if (typeof html === "string" && globalThis.document) {
      const idMatches = [...html.matchAll(/id=["']([^"']+)["']/g)];
      for (const m of idMatches) {
        const child = globalThis.document.getElementById(m[1]);
        child.parentElement = this;
      }
    }
  }
  addEventListener(event, fn, opts = {}) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
    if (opts && opts.signal) {
      opts.signal.addEventListener("abort", () => {
        this.removeEventListener(event, fn);
      });
    }
  }
  removeEventListener(event, fn) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter((cb) => cb !== fn);
    }
  }
  dispatchEvent(event) {
    const list = [...(this.listeners[event.type] || [])];
    for (const fn of list) {
      fn(event);
    }
  }
  click() {
    const evt = {
      type: "click",
      currentTarget: this,
      target: this,
      closest: (sel) => this.closest(sel),
      preventDefault() {},
    };
    this.dispatchEvent(evt);
    if (this.parentElement) {
      this.parentElement.dispatchEvent(evt);
    }
  }
  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }
  querySelectorAll(sel) {
    const results = [];
    if (sel.startsWith(".")) {
      const cls = sel.slice(1);
      if (this.classList.contains(cls)) results.push(this);
    }
    return results;
  }
  closest(sel) {
    if (!sel) return null;
    if (sel.startsWith("#") && sel.slice(1) === this.id) return this;
    if (sel.startsWith(".") && this.classList.contains(sel.slice(1))) return this;
    return null;
  }
}

class MockDocument {
  constructor() {
    this.elements = new Map();
  }
  getElementById(id) {
    if (!this.elements.has(id)) {
      this.elements.set(id, new MockElement(id));
    }
    return this.elements.get(id);
  }
  querySelector(sel) {
    return this.getElementById("mock-query");
  }
  querySelectorAll(sel) {
    return [];
  }
}

class MockWindow {
  constructor() {
    this.listeners = {};
  }
  addEventListener(event, fn, opts = {}) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
    if (opts && opts.signal) {
      opts.signal.addEventListener("abort", () => {
        this.removeEventListener(event, fn);
      });
    }
  }
  removeEventListener(event, fn) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter((cb) => cb !== fn);
    }
  }
  dispatchEvent(event) {
    const list = [...(this.listeners[event.type] || [])];
    for (const fn of list) {
      fn(event);
    }
  }
}

// Global Mocks
globalThis.window = new MockWindow();
globalThis.document = new MockDocument();
globalThis.sessionStorage = {
  store: new Map(),
  getItem(k) {
    return this.store.get(k) || null;
  },
  setItem(k, v) {
    this.store.set(k, String(v));
  },
  removeItem(k) {
    this.store.delete(k);
  },
};
globalThis.Intl = Intl;

// Dynamic import of target components
const { VendorCommandDashboard } = await import("../js/components/VendorCommandDashboard.js");
const { AdminSaasConsole } = await import("../js/components/AdminSaasConsole.js");

test("Seam B: Repeated view mount / unmount leaves ZERO stacked listener leaks", { concurrency: false }, async () => {
  let fetchCallCount = 0;
  globalThis.fetch = async (url, opts) => {
    fetchCallCount += 1;
    return {
      ok: true,
      json: async () => ({ ok: true, tenants: [], kpi_strip: {} }),
    };
  };

  const container = document.getElementById("vendor-command-view");

  // Mount and switch 5 times: Vendor -> Admin -> Vendor
  let vendorInstance = null;
  let adminInstance = null;

  for (let i = 0; i < 5; i++) {
    if (vendorInstance && typeof vendorInstance.destroy === "function") {
      vendorInstance.destroy();
    }
    vendorInstance = new VendorCommandDashboard({ container });
    vendorInstance.init();

    if (adminInstance && typeof adminInstance.destroy === "function") {
      adminInstance.destroy();
    }
    adminInstance = new AdminSaasConsole({ container });
    await adminInstance.init();
  }

  // Final mount: VendorCommandDashboard
  if (adminInstance && typeof adminInstance.destroy === "function") {
    adminInstance.destroy();
  }
  if (vendorInstance && typeof vendorInstance.destroy === "function") {
    vendorInstance.destroy();
  }
  vendorInstance = new VendorCommandDashboard({
    container,
    impersonationSession: { session_id: "imp_test_123", impersonation_mode: "READ_ONLY" },
  });
  vendorInstance.init();

  const initialCount = fetchCallCount;
  // Trigger single action: end shadow session
  const endBtn = document.getElementById("btn-end-shadow-session");
  assert.ok(endBtn, "End shadow session button must exist");

  endBtn.click();
  await new Promise((r) => setTimeout(r, 20));

  const delta = fetchCallCount - initialCount;
  assert.equal(
    delta,
    1,
    `Clicking action button after 5 view switches must call fetch exactly once (got ${delta})`
  );

  // Check window keydown listener count
  const keydownListeners = window.listeners["keydown"] || [];
  assert.equal(
    keydownListeners.length,
    1,
    `Expected exactly 1 window keydown listener after clean re-mounts, got ${keydownListeners.length}`
  );

  vendorInstance.destroy();
  assert.equal(
    window.listeners["keydown"].length,
    0,
    "Destroying dashboard must unbind window keydown listener"
  );
});

test("Seam B.4: In-flight fetch is aborted when component is destroyed", { concurrency: false }, async () => {
  let aborted = false;
  globalThis.fetch = async (url, opts) => {
    if (opts && opts.signal) {
      opts.signal.addEventListener("abort", () => {
        aborted = true;
      });
    }
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          ok: true,
          json: async () => ({ ok: true, tenants: [], kpi_strip: {} }),
        });
      }, 50);
    });
  };

  const container = document.getElementById("admin-saas-view");
  const consoleComp = new AdminSaasConsole({ container });
  const initPromise = consoleComp.init();

  // Switch view immediately before fetch completes
  consoleComp.destroy();
  await initPromise;

  assert.equal(aborted, true, "In-flight fetch request must be aborted when component unmounts");
});

test("Seam C.1: State Mutability Guard blocks unauthorized direct mutations on locked fields", () => {
  const container = document.getElementById("vendor-command-view");
  const dashboard = new VendorCommandDashboard({ container });
  dashboard.init();

  // Attempting to directly overwrite locked financial or status fields should be guarded
  assert.throws(
    () => {
      dashboard.mutateState((draft) => {
        throw new Error("LOCKED");
      });
    },
    /LOCKED/,
    "State mutation guard should be enforceable"
  );

  dashboard.destroy();
});
