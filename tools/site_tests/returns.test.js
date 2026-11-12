// Отмена и возврат заказа на сайте (returns.js, D-123).
// Запуск: node --test tools/site_tests/
//
// Решает сервер, но форма не должна сама подводить покупателя: предлагать после
// 7 дней «не подошёл размер» (сервер откажет), пропускать брак без фото или
// терять ключ photos (тогда сервер не потребует снимок). Функции вырезаем из
// исходника и гоняем в песочнице — как в profile.test.js.
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "..", "САЙТ МАТА", "returns.js"),
  "utf8",
);

function extract(name) {
  const start = SRC.indexOf("function " + name + "(");
  assert.ok(start >= 0, "в returns.js нет функции " + name);
  const open = SRC.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) return SRC.slice(start, i + 1);
  }
  throw new Error("не нашёл конец функции " + name);
}

const NAMES = [
  "rtAllowedReasons", "rtNeedsComment", "rtValidate", "rtPayload",
  "rtOrderEligible", "rtRequestHtml", "rtStatusCls", "rtEsc", "rtDate",
];
const sandbox = {
  escapeHtml: (s) => String(s).replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";"),
  formatPrice: (v) => v + " ₽",
};
vm.createContext(sandbox);
vm.runInContext(
  "var RT_QUALITY = { defect: 1, wrong_item: 1, not_as_described: 1 };\nvar rt = { trackFor: null };\n" +
    NAMES.map(extract).join("\n") + "\n" +
    NAMES.map((n) => "this." + n + " = " + n + ";").join("\n") +
    "\nthis.setRt = function (v) { rt = v; };",
  sandbox,
);

const REASONS = {
  size: "Не подошёл размер",
  style: "Не подошёл цвет или фасон",
  defect: "Брак или дефект",
  wrong_item: "Пришёл не тот товар",
  other: "Другое",
};

test("в срок — все причины; после 7 дней — только качество", () => {
  assert.strictEqual(sandbox.rtAllowedReasons(REASONS, true).length, 5);
  const late = sandbox.rtAllowedReasons(REASONS, false).map((r) => r[0]);
  assert.strictEqual(JSON.stringify(late), JSON.stringify(["defect", "wrong_item"]));
});

test("брак без фото и без описания не отправляем", () => {
  assert.match(sandbox.rtValidate({}, []), /Отметьте/);
  assert.match(sandbox.rtValidate({ 0: { reason: "defect", comment: "шов" } }, []), /Опишите/);
  assert.match(
    sandbox.rtValidate({ 0: { reason: "defect", comment: "Разошёлся шов" } }, []),
    /фото брака/,
  );
  assert.match(
    sandbox.rtValidate({ 0: { reason: "size", comment: "" } }, [{ id: null, status: "loading" }]),
    /Дождитесь/,
  );
  assert.strictEqual(
    sandbox.rtValidate({ 0: { reason: "defect", comment: "Разошёлся шов" } }, [{ id: 5, status: "ok" }]),
    "",
  );
  assert.strictEqual(sandbox.rtValidate({ 1: { reason: "size", comment: "" } }, []), "");
});

test("тело заявки: ключ photos всегда, только загруженные id", () => {
  const body = sandbox.rtPayload("parcel", { 2: { reason: "size", comment: "  мал  " } }, [
    { id: 7, status: "ok" },
    { id: null, status: "failed" },
  ]);
  assert.strictEqual(JSON.stringify(body), JSON.stringify({
    method: "parcel",
    photos: [7],
    lines: [{ index: 2, reason: "size", comment: "мал" }],
  }));
  assert.deepStrictEqual(Array.from(sandbox.rtPayload("x", { 0: { reason: "size" } }, []).photos), []);
  assert.strictEqual(sandbox.rtPayload("x", {}, []).method, "store");
});

test("кнопка «Отменить или вернуть» — только у оплаченных заказов", () => {
  assert.ok(sandbox.rtOrderEligible({ paymentStatus: "paid" }));
  assert.ok(sandbox.rtOrderEligible({ paymentStatus: "partially_refunded" }));
  assert.ok(!sandbox.rtOrderEligible({ paymentStatus: "pending" }));
  assert.ok(!sandbox.rtOrderEligible(null));
});

test("заявка: отказ по вещи виден, выбор «как забрать», текст экранирован", () => {
  sandbox.setRt({ trackFor: null });
  const html = sandbox.rtRequestHtml({
    id: 7,
    number: "МАТА-1-В1",
    status: "partial",
    statusLabel: "Принята частично",
    method: "parcel",
    lines: [{ name: "<b>Майка</b>", reasonLabel: "Не подошёл размер",
              rejectReasonLabels: ["Есть следы носки"] }],
    needsGoodsBack: true,
    refundRub: 1500,
  });
  assert.match(html, /Заявка МАТА-1-В1/);
  assert.match(html, /Отказ: Есть следы носки/);
  assert.match(html, /data-rt-way="pickup"/);
  assert.match(html, /data-rt-way="ship"/);
  assert.match(html, /Возвращено: 1500 ₽/);
  assert.ok(!html.includes("<b>Майка</b>"), "имя вещи должно быть экранировано");
});
