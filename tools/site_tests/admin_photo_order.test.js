// Порядок снимков перетаскиванием (админка «Фото товаров», 02.10.2026).
// Запуск: node --test tools/site_tests/
//
// Правило вставки — единственное место, где легко ошибиться на полпикселя: снимок
// должен вставать ПРАВЕЕ соседа, если курсор в правой половине его плитки, и ЛЕВЕЕ,
// если в левой. Иначе перетаскивание «не доносит» снимок на одну позицию, и это
// замечают только руками. Поднимать браузер ради одного правила незачем — вырезаем
// функцию из исходника и проверяем в песочнице, как это уже сделано для сайта.
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "..", "backend", "django_api", "static", "admin", "mata.js"),
  "utf8",
);

function extract(name) {
  const start = SRC.indexOf("function " + name + "(");
  assert.ok(start >= 0, "в mata.js нет функции " + name);
  const open = SRC.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) return SRC.slice(start, i + 1);
  }
  throw new Error("не нашёл конец функции " + name);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(extract("dropAnchor") + "\nthis.dropAnchor = dropAnchor;", sandbox);

// Плитка шириной 100, левый край на 200: середина — 250.
function slot(next) {
  return {
    nextSibling: next,
    getBoundingClientRect: () => ({ left: 200, width: 100 }),
  };
}

test("курсор в правой половине — снимок встаёт ПРАВЕЕ соседа", () => {
  const next = { id: "следующий" };
  assert.strictEqual(sandbox.dropAnchor(slot(next), 280), next);
});

test("курсор в левой половине — снимок встаёт ЛЕВЕЕ соседа", () => {
  const over = slot({ id: "следующий" });
  assert.strictEqual(sandbox.dropAnchor(over, 220), over);
});

test("ровно середина считается левой половиной — порядок не прыгает", () => {
  const over = slot({ id: "следующий" });
  assert.strictEqual(sandbox.dropAnchor(over, 250), over);
});

test("последний снимок: правая половина даёт null — вставка в конец ряда", () => {
  assert.strictEqual(sandbox.dropAnchor(slot(null), 299), null);
});
