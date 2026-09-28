// Поведенческие тесты профиля сайта (аудит D02). Запуск: node --test tools/site_tests/
//
// script.js/ecosystem.js — обычные браузерные скрипты с DOM на верхнем уровне, целиком
// их в node не поднять. Поэтому тест вырезает из исходника нужные функции по имени
// и исполняет их в песочнице с минимальными заглушками DOM и localStorage.
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SITE = path.join(__dirname, "..", "..", "САЙТ МАТА");
const SCRIPT = fs.readFileSync(path.join(SITE, "script.js"), "utf8");
const ECO = fs.readFileSync(path.join(SITE, "ecosystem.js"), "utf8");

// Текст объявления `function name(...) {...}` или `const NAME = ...;` из исходника.
function extract(src, name) {
  let start = src.indexOf("function " + name + "(");
  if (start < 0) start = src.indexOf("const " + name + " =");
  if (start < 0) return "";
  const open = src.indexOf(src.startsWith("const", start) ? "[" : "{", start);
  const pair = src[open] === "[" ? ["[", "]"] : ["{", "}"];
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === pair[0]) depth++;
    else if (src[i] === pair[1] && --depth === 0) {
      let end = i + 1;
      if (src[end] === ";") end++;
      return src.slice(start, end);
    }
  }
  throw new Error("не нашёл конец " + name);
}

function fakeStorage(init) {
  const m = new Map(Object.entries(init || {}));
  return {
    get length() { return m.size; },
    key: (i) => Array.from(m.keys())[i] ?? null,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    dump: () => Object.fromEntries(m),
  };
}

// Элемент-заглушка: помнит innerHTML и вешаемые обработчики кнопки повтора.
function fakeList() {
  const btn = { handlers: [], addEventListener(ev, fn) { this.handlers.push(fn); } };
  return {
    innerHTML: "",
    btn,
    querySelector(sel) {
      return sel === "[data-pr-orders-retry]" && this.innerHTML.includes("data-pr-orders-retry") ? btn : null;
    },
  };
}

function profileSandbox({ api, demo }) {
  const list = fakeList();
  const calls = { logout: 0, openLogin: 0 };
  const ctx = {
    window: {
      STAW: {
        api,
        logout: () => calls.logout++,
        openLogin: () => calls.openLogin++,
      },
    },
    prModal: { querySelector: (sel) => (sel === "[data-pr-orders-list]" ? list : null) },
    prSetView: () => {},
    closeProfile: () => {},
    formatPrice: (n) => n + " ₽",
    escapeHtml: (s) => String(s),
  };
  if (demo) ctx.window.STAW_DEMO = true;
  vm.createContext(ctx);
  const names = [
    "PR_ORDERS_DEMO", "prStatusMap", "prOrderSource", "prOrderItems", "prOrderDate",
    "prRenderOrders", "prDemoMode", "prRenderOrdersError", "prShowOrders",
  ];
  vm.runInContext(names.map((n) => extract(SCRIPT, n)).join("\n") + "\nthis.prShowOrders = prShowOrders;", ctx);
  return { ctx, list, calls };
}

const tick = () => new Promise((r) => setImmediate(r));
const DEMO_IDS = ["МАТА-205990", "МАТА-198003", "SS-191244"];
const hasDemo = (html) => DEMO_IDS.some((id) => html.includes(id));

test("сетевой отказ: демо-заказов нет, есть ошибка и кнопка «Повторить»", async () => {
  let n = 0;
  const { ctx, list } = profileSandbox({
    api: () => (n++ === 0 ? Promise.reject(new TypeError("Failed to fetch")) : Promise.resolve([])),
  });
  ctx.prShowOrders();
  await tick();
  assert.ok(!hasDemo(list.innerHTML), "при сетевой ошибке показаны демо-заказы");
  assert.match(list.innerHTML, /data-pr-orders-error/);
  assert.match(list.innerHTML, /Повторить/);
  // Повтор действительно перезапрашивает заказы.
  assert.strictEqual(list.btn.handlers.length, 1);
  list.btn.handlers[0]();
  await tick();
  assert.strictEqual(n, 2);
  assert.match(list.innerHTML, /Заказов пока нет/);
});

test("401: демо-заказов нет, сессия сбрасывается, предлагается вход", async () => {
  const err = Object.assign(new Error("Not authenticated"), { status: 401 });
  const { ctx, list, calls } = profileSandbox({ api: () => Promise.reject(err) });
  ctx.prShowOrders();
  await tick();
  assert.ok(!hasDemo(list.innerHTML), "при 401 показаны демо-заказы");
  assert.match(list.innerHTML, /Войти/);
  assert.strictEqual(calls.logout, 1);
  list.btn.handlers[0]();
  assert.strictEqual(calls.openLogin, 1);
});

test("без модуля экосистемы — тоже ошибка, а не демо", async () => {
  const { ctx, list } = profileSandbox({ api: undefined });
  ctx.prShowOrders();
  await tick();
  assert.ok(!hasDemo(list.innerHTML));
  assert.match(list.innerHTML, /data-pr-orders-error/);
});

test("явный демо-режим (window.STAW_DEMO) по-прежнему показывает демо-заказы", async () => {
  const { ctx, list } = profileSandbox({ api: () => Promise.reject(new Error("x")), demo: true });
  ctx.prShowOrders();
  await tick();
  assert.ok(hasDemo(list.innerHTML));
});

test("успешный ответ рисует настоящие заказы", async () => {
  const { ctx, list } = profileSandbox({
    api: () => Promise.resolve([{ id: "SS-1", status: "delivered", total: 100, items: "Носки" }]),
  });
  ctx.prShowOrders();
  await tick();
  assert.match(list.innerHTML, /SS-1/);
  assert.ok(!hasDemo(list.innerHTML));
});

// ── Адреса: локальная копия по аккаунту ────────────────────────────────────────
function addressSandbox(storage, user) {
  const ctx = { localStorage: storage, prGetUser: () => user || {} };
  vm.createContext(ctx);
  const names = ["prGetAddresses", "prAddressesKey", "prSaveAddresses"];
  vm.runInContext(names.map((n) => extract(SCRIPT, n)).join("\n") +
    "\nthis.get = prGetAddresses; this.save = prSaveAddresses;", ctx);
  return ctx;
}

test("адреса одного аккаунта не видны другому в том же браузере", () => {
  const storage = fakeStorage({ staw_addresses: JSON.stringify([{ city: "Чужой" }]) });
  const a = addressSandbox(storage, { id: "u_A" });
  a.save([{ city: "Якутск", street: "Ленина", house: "1" }]);
  const b = addressSandbox(storage, { id: "u_B" });
  assert.deepStrictEqual(Array.from(b.get()), [], "аккаунт B видит адреса A или общий ключ");
  assert.strictEqual(addressSandbox(storage, { id: "u_A" }).get()[0].city, "Якутск");
  // Без входа локальных адресов нет вовсе.
  assert.deepStrictEqual(Array.from(addressSandbox(storage, null).get()), []);
});

test("смена сессии чистит чужие копии адресов и старый общий ключ", () => {
  const storage = fakeStorage({
    staw_addresses: "[1]",
    "staw_addresses:u_A": "[2]",
    "staw_addresses:u_B": "[3]",
    staw_cart: "[]",
  });
  const ctx = { localStorage: storage, LS_TOKEN: "staw_jwt", LS_USER: "staw_user" };
  vm.createContext(ctx);
  const names = ["addressCacheKey", "purgeAddressCache", "setSession", "clearSession"];
  vm.runInContext(names.map((n) => extract(ECO, n)).join("\n") +
    "\nthis.setSession = setSession; this.clearSession = clearSession;", ctx);

  ctx.setSession("jwt", { id: "u_B" });
  let keys = Object.keys(storage.dump()).sort();
  assert.deepStrictEqual(keys, ["staw_addresses:u_B", "staw_cart", "staw_jwt", "staw_user"]);

  ctx.clearSession();
  keys = Object.keys(storage.dump()).sort();
  assert.deepStrictEqual(keys, ["staw_cart"]);
});
