const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class FakeClassList {
  constructor(...names) {
    this.names = new Set(names);
  }

  add(name) {
    this.names.add(name);
  }

  remove(name) {
    this.names.delete(name);
  }

  contains(name) {
    return this.names.has(name);
  }

  toggle(name, force) {
    if (force) this.add(name);
    else this.remove(name);
  }
}

class FakeButton {
  constructor(level, { selected = false } = {}) {
    this.dataset = { caseRequest: level };
    this.attributes = new Map();
    this.classList = new FakeClassList(...(selected ? ["is-selected"] : []));
    this.parentElement = null;
  }

  closest(selector) {
    return selector === ".choice-list button" ? this : null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }
}

const listeners = new Map();
const elements = new Map();

global.document = {
  body: { classList: new FakeClassList() },
  hidden: false,
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: (id) => elements.get(id) ?? null,
  addEventListener: (name, handler) => listeners.set(name, handler),
};

const script = readFileSync(
  resolve(__dirname, "../../tf2price/painel/static/briefcase.js"),
  "utf8",
);
vm.runInThisContext(script, { filename: "briefcase.js" });

function navigationContext({ hidden = false } = {}) {
  const handlers = new Map();
  const toggleHandlers = new Map();
  const navHandlers = new Map();
  const toggle = new FakeButton();
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener = (name, handler) => toggleHandlers.set(name, handler);
  toggle.focus = () => { document.activeElement = toggle; };
  const nav = {
    addEventListener: (name, handler) => navHandlers.set(name, handler),
  };
  const media = { matches: true };
  const document = {
    body: { classList: new FakeClassList() }, hidden, activeElement: null,
    querySelector: (selector) => selector === "[data-nav-toggle]" ? toggle : nav,
    querySelectorAll: () => [],
    addEventListener: (name, handler) => handlers.set(name, handler),
  };
  vm.runInNewContext(script, { document, window: { matchMedia: () => media } });
  return { document, toggle, handlers, toggleHandlers, navHandlers, media };
}

test("mobile menu Escape closes it and restores focus", () => {
  const context = navigationContext();
  context.toggleHandlers.get("click")();
  assert.equal(context.toggle.getAttribute("aria-expanded"), "true");
  context.handlers.get("keydown")({ key: "Escape" });
  assert.equal(context.toggle.getAttribute("aria-expanded"), "false");
  assert.equal(context.document.activeElement, context.toggle);
});

test("mobile navigation closes after following a link without stealing focus", () => {
  const context = navigationContext();
  context.toggleHandlers.get("click")();
  context.navHandlers.get("click")?.({ target: { closest: () => ({ href: "/cases" }) } });
  assert.equal(context.toggle.getAttribute("aria-expanded"), "false");
  assert.equal(context.document.activeElement, null);
  context.media.matches = false;
  context.toggleHandlers.get("click")();
  context.navHandlers.get("click")?.({ target: { closest: () => ({ href: "/cases" }) } });
  assert.equal(context.toggle.getAttribute("aria-expanded"), "true");
});

test("visibility state pauses existing and subsequently inserted animations", () => {
  const context = navigationContext({ hidden: true });
  assert.equal(context.document.body.classList.contains("page-hidden"), true);
  context.document.hidden = false;
  context.handlers.get("visibilitychange")();
  assert.equal(context.document.body.classList.contains("page-hidden"), false);
  context.document.hidden = true;
  context.handlers.get("visibilitychange")();
  assert.equal(context.document.body.classList.contains("page-hidden"), true);
});

test("effect request clears the previous analysis immediately", () => {
  const analysis = { innerHTML: "<p>R$ 180,44</p>" };
  elements.set("analysis", analysis);

  listeners.get("htmx:beforeRequest")({
    detail: { elt: new FakeButton("effect") },
  });

  assert.equal(
    analysis.innerHTML,
    '<p class="empty-state">Loading evidence</p>',
  );
  assert.doesNotMatch(analysis.innerHTML, /180,44/);
});

test("item request removes old effect controls before they can replace the pending item request", () => {
  const oldEffect = new FakeButton("effect");
  oldEffect.setAttribute("hx-sync", "#case-workflow:replace");
  oldEffect.setAttribute("hx-get", "/analise");
  // Model the DOM consequence of assigning innerHTML: existing controls detach.
  const effects = {
    children: [oldEffect],
    html: "<button>Item A effect</button>",
    get innerHTML() { return this.html; },
    set innerHTML(html) {
      this.children.forEach((child) => { child.parentElement = null; });
      this.children = [];
      this.html = html;
    },
  };
  oldEffect.parentElement = effects;
  const analysis = { innerHTML: "<p>Item A: R$ 180,44</p>" };
  const itemA = new FakeButton("item", { selected: true });
  const itemB = new FakeButton("item");
  itemB.setAttribute("hx-sync", "#case-workflow:replace");
  const group = { querySelectorAll: () => [itemA, itemB] };
  itemA.parentElement = itemB.parentElement = group;
  elements.set("effects", effects);
  elements.set("analysis", analysis);

  assert.equal(oldEffect.getAttribute("hx-sync"), itemB.getAttribute("hx-sync"));
  assert.equal(effects.children.length, 1);
  listeners.get("click")({ target: itemB });
  listeners.get("htmx:beforeRequest")({ detail: { elt: itemB } });

  // Before any response arrives, no old effect remains available to click and
  // cancel B through the shared HTMX replace group.
  assert.equal(effects.children.length, 0);
  assert.equal(oldEffect.parentElement, null);
  assert.equal(effects.innerHTML, '<p class="empty-state">Loading effects</p>');
  assert.equal(analysis.innerHTML, '<p class="empty-state">Waiting for an effect</p>');
  assert.equal(itemB.hasAttribute("data-selected"), true);
  assert.equal(itemA.classList.contains("is-selected"), false);
});

test("search request clears both downstream regions immediately", () => {
  const effects = { innerHTML: "<button>Old effect</button>" };
  const analysis = { innerHTML: "<p>Old evidence</p>" };
  elements.set("effects", effects);
  elements.set("analysis", analysis);

  listeners.get("htmx:beforeRequest")({ detail: { elt: new FakeButton("search") } });

  assert.equal(effects.innerHTML, '<p class="empty-state">Waiting for an item</p>');
  assert.equal(analysis.innerHTML, '<p class="empty-state">Waiting for an effect</p>');
});

test("effect activation leaves one authoritative pressed choice", () => {
  const first = new FakeButton("effect", { selected: true });
  const second = new FakeButton("effect");
  first.setAttribute("aria-pressed", "true");
  second.setAttribute("aria-pressed", "false");
  const buttons = [first, second];
  const group = { querySelectorAll: () => buttons };
  buttons.forEach((button) => { button.parentElement = group; });

  listeners.get("click")({ target: second });

  assert.equal(first.classList.contains("is-selected"), false);
  assert.equal(first.hasAttribute("data-selected"), false);
  assert.equal(first.getAttribute("aria-pressed"), "false");
  assert.equal(second.classList.contains("is-selected"), false);
  assert.equal(second.hasAttribute("data-selected"), true);
  assert.equal(second.getAttribute("aria-pressed"), "true");
  assert.equal(
    buttons.filter((button) => button.getAttribute("aria-pressed") === "true").length,
    1,
  );
});
