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
