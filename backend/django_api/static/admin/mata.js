/* Высота таблицы списка: полоса боковой прокрутки всегда над нижней панелью.
 *
 * В теме админки внизу экрана «прилипшая» панель — в ней «Сохранить» и
 * постраничная навигация. Таблица со своей прокруткой заканчивалась ПОД ней:
 * полосу видно, а нажать нельзя — клик уходит в панель (жалоба владельца
 * 18.09.2026: «ползунок есть, но не работает»).
 *
 * Одним CSS не обойтись: нужная высота зависит от того, сколько занято сверху —
 * поиск, фильтры, раскрытая панель «Столбцы», — а это меняется на ходу. В CSS
 * остаётся запасное правило на случай, если скрипт не выполнится.
 */
(function () {
  "use strict";

  var GAP = 10;      // зазор между полосой прокрутки и нижней панелью
  var MIN = 260;     // ниже этого таблица превращается в щёлочку
  var WIDE = 1024;   // на узких экранах высоту не ограничиваем

  /** Высота «прилипшей» панели внизу экрана (0, если её нет). */
  function bottomBarHeight() {
    var vh = window.innerHeight;
    var nodes = document.querySelectorAll('[class*="sticky"],[class*="fixed"],footer');
    var best = 0;
    for (var i = 0; i < nodes.length; i++) {
      var pos = getComputedStyle(nodes[i]).position;
      if (pos !== "sticky" && pos !== "fixed") continue;
      var r = nodes[i].getBoundingClientRect();
      // Именно нижняя панель: широкая, невысокая, прижата к низу экрана.
      if (r.height > 0 && r.height < 200 && r.width > window.innerWidth / 2
          && r.bottom >= vh - 2) {
        best = Math.max(best, r.height);
      }
    }
    return best;
  }

  /** Области прокрутки: таблица списка темы и наши таблицы на своих страницах. */
  function boxes() {
    var out = [];
    var table = document.getElementById("result_list");
    if (table && table.parentElement) out.push(table.parentElement);
    var ours = document.querySelectorAll(".m-wrap");
    for (var i = 0; i < ours.length; i++) out.push(ours[i]);
    return out;
  }

  function fit() {
    var list = boxes();
    if (!list.length) return;
    if (window.innerWidth < WIDE) {
      for (var i = 0; i < list.length; i++) list[i].style.maxHeight = "";
      return;
    }
    var limit = window.innerHeight - bottomBarHeight() - GAP;
    for (var j = 0; j < list.length; j++) {
      var box = list[j];
      box.style.maxHeight = "";                       // сначала измеряем честно
      var top = box.getBoundingClientRect().top;
      box.style.maxHeight = Math.max(MIN, Math.round(limit - top)) + "px";
    }
  }

  var timer = null;
  function later() {
    clearTimeout(timer);
    timer = setTimeout(fit, 60);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fit);
  } else {
    fit();
  }
  window.addEventListener("load", fit);
  window.addEventListener("resize", later);
  // Раскрыли/свернули панель «Столбцы» — таблица поехала вверх или вниз.
  document.addEventListener("toggle", later, true);
})();

/* Заливка фото товаров плиткой (D-91): перетащил картинку на карточку — она
 * ушла на сервер и встала на место. Без перезагрузки страницы: иначе на каждой
 * картинке пришлось бы ждать полной отрисовки списка. */
(function () {
  "use strict";

  // Тема подключает наши скрипты в <head> и БЕЗ defer: на момент выполнения
  // страницы ещё нет. Поэтому ждём разбор разметки, иначе плитка не найдётся
  // и перетаскивание молча не заработает (проверено в браузере 22.09.2026).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
  // ── «Фото товаров»: плитка = модель + цвет, внутри до шести снимков (D-99) ──
  var grid = document.getElementById("photo-grid");
  if (!grid) return;

  var token = document.querySelector("input[name=csrfmiddlewaretoken]");
  var left = document.querySelector(".m-tile b");
  var MAX = 6;

  function post(body) {
    if (token) body.append("csrfmiddlewaretoken", token.value);
    return fetch(window.location.pathname, {
      method: "POST", body: body, credentials: "same-origin",
      headers: token ? { "X-CSRFToken": token.value } : {}
    }).then(function (r) { return r.json(); });
  }

  function count(gal) {
    return gal.querySelectorAll(".m-slot.is-filled").length;
  }

  function refresh(gal, hadNone) {
    var n = count(gal);
    var label = gal.querySelector(".m-gal-count");
    if (label) label.textContent = n + " из " + MAX;
    // Пустых мест ровно столько, сколько осталось: лишние «+» врут о свободе.
    var free = gal.querySelectorAll(".m-slot:not(.is-filled)");
    var want = Math.max(0, MAX - n);
    for (var i = free.length - 1; i >= want; i--) free[i].remove();
    for (var j = free.length; j < want; j++) gal.querySelector(".m-gal-slots").appendChild(blank());
    if (hadNone && n > 0 && left) {          // счётчик «цветов без фото»
      var c = parseInt(left.textContent, 10);
      if (!isNaN(c) && c > 0) left.textContent = c - 1;
    }
  }

  function blank() {
    var label = document.createElement("label");
    label.className = "m-slot";
    label.innerHTML = '<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden><span>+</span>';
    return label;
  }

  function filled(data) {
    var box = document.createElement("div");
    box.className = "m-slot is-filled";
    box.dataset.id = data.id;
    var img = document.createElement("img");
    img.src = data.thumb || data.url;
    box.appendChild(img);
    box.insertAdjacentHTML("beforeend",
      '<button type="button" class="m-slot-main" title="Сделать обложкой">★</button>' +
      '<button type="button" class="m-slot-del" title="Удалить">×</button>');
    return box;
  }

  function fail(gal, text) {
    var note = gal.querySelector(".m-gal-error") || document.createElement("div");
    note.className = "m-gal-error";
    note.textContent = text;
    gal.appendChild(note);
  }

  // Файлы льём по одному: место в галерее занимает сервер, и параллельные
  // загрузки подрались бы за один и тот же номер.
  function upload(gal, files, i) {
    if (!files.length) return;
    i = i || 0;
    if (i >= files.length) { gal.classList.remove("is-busy"); return; }
    if (count(gal) >= MAX) {
      gal.classList.remove("is-busy");
      fail(gal, "мест больше нет — удалите лишнее");
      return;
    }
    gal.classList.add("is-busy");

    var body = new FormData();
    body.append("key", gal.dataset.key);
    body.append("color", gal.dataset.color || "");
    body.append("photo", files[i]);
    var hadNone = count(gal) === 0;

    post(body).then(function (data) {
      if (!data.ok) { fail(gal, data.error || "не вышло"); gal.classList.remove("is-busy"); return; }
      var slot = gal.querySelector(".m-slot:not(.is-filled)");
      var box = filled(data);
      if (slot) slot.replaceWith(box); else gal.querySelector(".m-gal-slots").appendChild(box);
      refresh(gal, hadNone);
      upload(gal, files, i + 1);
    }).catch(function () {
      gal.classList.remove("is-busy");
      fail(gal, "сеть не ответила");
    });
  }

  grid.addEventListener("click", function (e) {
    var gal = e.target.closest(".m-gal");
    var slot = e.target.closest(".m-slot");
    if (!gal || !slot) return;

    if (e.target.classList.contains("m-slot-del")) {
      var body = new FormData();
      body.append("action", "delete");
      body.append("id", slot.dataset.id);
      post(body).then(function (data) {
        if (!data.ok) { fail(gal, data.error || "не вышло"); return; }
        slot.remove();
        refresh(gal, false);
      });
    }
    if (e.target.classList.contains("m-slot-main")) {
      var main = new FormData();
      main.append("action", "main");
      main.append("id", slot.dataset.id);
      post(main).then(function (data) {
        if (!data.ok) { fail(gal, data.error || "не вышло"); return; }
        slot.parentNode.prepend(slot);       // обложка всегда первая
      });
    }
  });

  grid.addEventListener("dragover", function (e) {
    var gal = e.target.closest(".m-gal");
    if (!gal) return;
    e.preventDefault();
    gal.classList.add("is-over");
  });
  grid.addEventListener("dragleave", function (e) {
    var gal = e.target.closest(".m-gal");
    if (gal) gal.classList.remove("is-over");
  });
  grid.addEventListener("drop", function (e) {
    var gal = e.target.closest(".m-gal");
    if (!gal) return;
    e.preventDefault();
    gal.classList.remove("is-over");
    upload(gal, Array.prototype.slice.call(e.dataTransfer.files || []));
  });
  grid.addEventListener("change", function (e) {
    if (e.target.type !== "file") return;
    var gal = e.target.closest(".m-gal");
    upload(gal, Array.prototype.slice.call(e.target.files || []));
    e.target.value = "";
  });
  // Картинка, брошенная мимо плитки, иначе откроется во весь экран поверх админки.
  document.addEventListener("dragover", function (e) { e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    if (!e.target.closest(".m-gal")) e.preventDefault();
  });
  }
})();

