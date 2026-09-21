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
  var grid = document.getElementById("photo-grid");
  if (!grid) return;

  var token = document.querySelector("input[name=csrfmiddlewaretoken]");
  var left = document.querySelector(".m-tile b");

  function send(card, file) {
    if (!file || card.classList.contains("is-busy")) return;
    var box = card.querySelector(".m-photo-box");
    var had = !!box.querySelector("img");
    card.classList.remove("is-bad", "is-done");
    card.classList.add("is-busy");

    var body = new FormData();
    body.append("id", card.dataset.id);
    body.append("photo", file);
    if (token) body.append("csrfmiddlewaretoken", token.value);

    fetch(window.location.pathname, {
      method: "POST", body: body, credentials: "same-origin",
      headers: token ? { "X-CSRFToken": token.value } : {}
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        card.classList.remove("is-busy");
        if (!data.ok) {
          card.classList.add("is-bad");
          box.innerHTML = '<span class="m-photo-empty">' + (data.error || "не вышло") + "</span>";
          return;
        }
        card.classList.add("is-done");
        box.innerHTML = "";
        var img = document.createElement("img");
        img.src = data.url + "?t=" + Date.now();   // чтобы браузер не показал прежнюю
        box.appendChild(img);
        if (!had && left) {                        // счётчик «осталось без фото»
          var n = parseInt(left.textContent, 10);
          if (!isNaN(n) && n > 0) left.textContent = n - 1;
        }
      })
      .catch(function () {
        card.classList.remove("is-busy");
        card.classList.add("is-bad");
      });
  }

  grid.addEventListener("dragover", function (e) {
    var card = e.target.closest(".m-photo");
    if (!card) return;
    e.preventDefault();
    card.classList.add("is-over");
  });
  grid.addEventListener("dragleave", function (e) {
    var card = e.target.closest(".m-photo");
    if (card) card.classList.remove("is-over");
  });
  grid.addEventListener("drop", function (e) {
    var card = e.target.closest(".m-photo");
    if (!card) return;
    e.preventDefault();
    card.classList.remove("is-over");
    send(card, e.dataTransfer.files && e.dataTransfer.files[0]);
  });
  grid.addEventListener("change", function (e) {
    if (e.target.type !== "file") return;
    var card = e.target.closest(".m-photo");
    send(card, e.target.files && e.target.files[0]);
    e.target.value = "";
  });
  // Картинка, брошенная мимо плитки, иначе откроется во весь экран поверх админки.
  document.addEventListener("dragover", function (e) { e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    if (!e.target.closest(".m-photo")) e.preventDefault();
  });
  }
})();

