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
    this.disabled = false;
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
  }
  addEventListener(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  }
  removeEventListener(event, fn) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter((f) => f !== fn);
  }
  click() {
    if (this.disabled) return;
    const evt = { target: this, preventDefault: () => {}, stopPropagation: () => {} };
    let curr = this;
    while (curr) {
      if (curr.listeners["click"]) {
        for (const fn of [...curr.listeners["click"]]) {
          fn(evt);
        }
      }
      curr = curr.parentElement;
    }
  }
  closest(selector) {
    if (selector.startsWith("#")) {
      const matchId = selector.slice(1);
      if (this.id === matchId) return this;
      return null;
    }
    if (selector.startsWith(".")) {
      const cls = selector.slice(1);
      if (this.classList.contains(cls)) return this;
      return null;
    }
    if (selector.includes("[data-action]")) {
      if (this.dataset?.action) return this;
      return null;
    }
    return null;
  }
}

const elementStore = new Map();
function getOrCreateElement(id, tagName = "div") {
  if (!elementStore.has(id)) {
    elementStore.set(id, new MockElement(id, tagName));
  }
  return elementStore.get(id);
}

globalThis.window = {
  listeners: {},
  addEventListener(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  },
  removeEventListener(event, fn) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter((f) => f !== fn);
  },
  confirm() {
    return true;
  },
  alert() {},
  location: { reload() {} },
};

globalThis.document = {
  getElementById(id) {
    return getOrCreateElement(id);
  },
  createElement(tag) {
    return new MockElement("", tag);
  },
  querySelector(sel) {
    if (sel.startsWith("#")) return this.getElementById(sel.slice(1));
    return new MockElement();
  },
  querySelectorAll() {
    return [];
  },
};

test("Resilience 1: Double-Click Rapid Tap Lock Prevents Duplicate API Requests", async () => {
  const { VendorCommandDashboard } = await import("../js/components/VendorCommandDashboard.js");
  const container = document.getElementById("resilience-vendor-view");

  const dashboard = new VendorCommandDashboard({
    container,
    impersonationSession: {
      session_id: "imp_res_1",
      target_tenant_id: "101",
      impersonation_mode: "READ_WRITE",
      scope_level: "FULL_OPERATIONAL",
    },
  });

  dashboard.init();

  let apiCallCount = 0;
  let resolveFirstCall;
  const inFlightPromise = new Promise((resolve) => {
    resolveFirstCall = resolve;
  });

  globalThis.fetch = async () => {
    apiCallCount++;
    await inFlightPromise;
    return {
      ok: true,
      json: async () => ({ ok: true }),
    };
  };

  const endBtn = document.getElementById("btn-end-shadow-session");
  endBtn.parentElement = container;

  // Simulate rapid double-click in same event loop tick
  endBtn.click();
  endBtn.click();
  endBtn.click();

  // Release in-flight fetch
  resolveFirstCall();
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(
    apiCallCount,
    1,
    `Double-clicking button while request is in-flight must issue EXACTLY 1 request, got ${apiCallCount}`
  );

  dashboard.destroy();
});

test("Resilience 2: Direct State Mutation on Locked Trip State Throws Guard Error", async () => {
  const { VendorCommandDashboard } = await import("../js/components/VendorCommandDashboard.js");
  const container = document.getElementById("resilience-vendor-view-2");

  const dashboard = new VendorCommandDashboard({
    container,
    impersonationSession: {
      session_id: "imp_res_2",
      target_tenant_id: "102",
      impersonation_mode: "READ_WRITE",
    },
  });

  dashboard.init();

  // Duty slip is marked finalized/invoiced
  dashboard.state.activeDuty = {
    id: "duty_finalized_1",
    status: "invoiced",
    total_fare_paise: 250000,
  };

  // Attempting to bypass lock by mutating locked fields via mutateState should throw Error
  assert.throws(
    () => {
      dashboard.mutateState((draft) => {
        draft.activeDuty.total_fare_paise = 100000;
      });
    },
    /locked|invoiced/i,
    "Mutating an invoiced duty must throw a mutability lock error"
  );

  dashboard.destroy();
});
