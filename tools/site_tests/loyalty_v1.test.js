// Программа лояльности v1 на сайте (ТЗ 30.09.2026, этап 3): профиль и касса.
// Запуск: node --test tools/site_tests/
//
// Как в profile.test.js: функции вырезаются из script.js по имени и гоняются в
// песочнице — данные в формате ответа сервера (/v1/loyalty/account → v1,
// POST /v1/loyalty/redeem-preview).
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SITE = path.join(__dirname, "..", "..", "САЙТ МАТА");
const SCRIPT = fs.readFileSync(path.join(SITE, "script.js"), "utf8");
const ECO = fs.readFileSync(path.join(SITE, "ecosystem.js"), "utf8");
const HTML = fs.readFileSync(path.join(SITE, "index.html"), "utf8");

function extract(src, name) {
  const start = src.indexOf("function " + name + "(");
  if (start < 0) throw new Error("нет функции " + name);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error("не нашёл конец " + name);
}

function sandbox(win) {
  const ctx = { window: win || {} };
  vm.createContext(ctx);
  const names = [
    "loyV1", "loyGroup", "loyBonusWord", "loyPct", "loyDate",
    "loyV1View", "loyLevelTexts", "loyCheckoutPlan",
  ];
  vm.runInContext(names.map((n) => extract(SCRIPT, n)).join("\n"), ctx);
  return ctx;
}

const NB = " ";
const V1 = {
  available: 250, redeemable: 250, held: 375, statusPoints: 320, purchases365: 7500,
  level: "basic", levelIndex: 0, levelUntil: null, nextLevelThreshold: 500,
  platinumMinSpend: 60000, redeemMin: 300, redeemCeiling: 0.15,
  levels: [
    { key: "basic", title: "Базовый", threshold: 0, minSpend: 0, purchaseRate: 0.05, redeemCeiling: 0.15 },
    { key: "platinum", title: "Платина", threshold: 5000, minSpend: 60000, purchaseRate: 0.09, redeemCeiling: 0.3 },
  ],
  lots: [],
};

test("профиль v1: доступно, шкала до минимума списания, уровень", () => {
  const c = sandbox();
  const w = c.loyV1View(V1);
  assert.strictEqual(w.availableText, "Доступно 250 бонусов");
  assert.strictEqual(w.toMin, true);
  assert.strictEqual(w.minText, "Списание от 300: накоплено 250 из 300");
  assert.ok(Math.abs(w.minProgress - 250 / 3) < 1e-9);
  assert.strictEqual(w.name, "Базовый");
  assert.strictEqual(w.levelText, "до Серебра: 320 из 500 статусных");
  assert.strictEqual(w.levelProgress, 64);
  assert.strictEqual(w.spendShow, false);
  assert.strictEqual(w.perk, "5% бонусами с покупок · оплата бонусами до 15% заказа");
});

test("профиль v1: Золото — две шкалы к Платине, пороги с сервера", () => {
  const c = sandbox();
  const w = c.loyV1View(Object.assign({}, V1, {
    level: "gold", redeemable: 900, statusPoints: 3200, nextLevelThreshold: 5000, purchases365: 12300,
  }));
  assert.strictEqual(w.toMin, false);
  assert.strictEqual(w.levelText, "до Платины: 3" + NB + "200 из 5" + NB + "000 статусных");
  assert.strictEqual(w.spendShow, true);
  assert.strictEqual(w.spendText, "покупки за год: 12" + NB + "300 из 60" + NB + "000 ₽");
  assert.strictEqual(w.spendProgress, 20.5);
});

test("профиль v1: Платина — максимальный уровень, долг не уводит в минус", () => {
  const c = sandbox();
  const w = c.loyV1View(Object.assign({}, V1, {
    level: "platinum", redeemable: -40, nextLevelThreshold: null, levelUntil: "2027-10-01T12:00:00+09:00",
  }));
  assert.strictEqual(w.spendable, 0);
  assert.ok(w.levelText.startsWith("Максимальный уровень · до "));
  assert.strictEqual(w.spendShow, false);
});

test("уровни: условие и привилегии из таблицы сервера", () => {
  const c = sandbox();
  const t = c.loyLevelTexts(V1.levels[1]);
  assert.strictEqual(t.range, "от 5" + NB + "000 статусных и 60" + NB + "000 ₽ покупок за год");
  assert.strictEqual(t.perk, "9% бонусами с покупок · оплата бонусами до 30% заказа");
  assert.strictEqual(c.loyLevelTexts(V1.levels[0]).range, "с первого бонуса");
});

test("касса v1: максимум из превью; ниже минимума — неактивно с причиной", () => {
  const c = sandbox();
  const ok = { programV1: true, available: 5000, redeemMax: 2100, redeemMin: 300, canRedeem: true, reason: "" };
  assert.strictEqual(c.loyCheckoutPlan(ok, true).applied, 2100);
  assert.strictEqual(c.loyCheckoutPlan(ok, false).applied, 0);
  assert.strictEqual(c.loyCheckoutPlan(ok, true).note, "Можно списать до 2100 бонусов — от 300");
  const low = {
    programV1: true, available: 250, redeemMax: 250, redeemMin: 300, canRedeem: false,
    reason: "Списать бонусы можно от 300: сейчас доступно 250",
  };
  const p = c.loyCheckoutPlan(low, true);
  assert.strictEqual(p.applied, 0);
  assert.strictEqual(p.can, false);
  assert.strictEqual(p.note, low.reason);
});

test("прежняя программа: превью нет или programV1 false — старые правила", () => {
  const c = sandbox();
  assert.strictEqual(c.loyCheckoutPlan(null, true), null);
  assert.strictEqual(c.loyCheckoutPlan({ programV1: false, available: 400 }, true), null);
  assert.strictEqual(sandbox({ STAW: { ecoPoints: 400 } }).loyV1(), null);
});

test("ecosystem.js кладёт блок v1 только при programV1 = true", () => {
  assert.ok(ECO.includes("acc.programV1 === true && acc.v1"));
});

test("сайт не обещает кэшбэк, бесплатную доставку и VIP", () => {
  for (const src of [SCRIPT, HTML]) {
    assert.ok(!/кэшбэк/i.test(src), "кэшбэк");
    assert.ok(!/VIP/.test(src), "VIP");
    assert.ok(!/бесплатная доставка/i.test(src), "бесплатная доставка");
  }
});
