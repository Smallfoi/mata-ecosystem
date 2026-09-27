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


/* Фотопайплайн: загрузка партии. Папка = артикул, первый по имени файл — обложка.
 * Браузер заранее уменьшает снимки до 2560 px: так быстро и не упирается в лимит
 * размера запроса на сервере. Файлы уходят по одному, потом партия запускается в фон. */
(function () {
  "use strict";

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    var box = document.getElementById("pipeline-upload");
    if (!box) return;

    var token = document.querySelector("input[name=csrfmiddlewaretoken]");
    var pick = box.querySelector("[data-role=pick]");
    var drop = box.querySelector("[data-role=drop]");
    var plan = box.querySelector("[data-role=plan]");
    var rows = box.querySelector("[data-role=rows]");
    var go = box.querySelector("[data-role=go]");
    var status = box.querySelector("[data-role=status]");
    var track = box.querySelector("select[name=track]");
    var IMG = /\.(jpe?g|png|webp)$/i;
    // Крупный план принта: в имени файла detail / деталь / принт / print / macro / close / крупн.
    var DETAIL = /(detail|детал|принт|print|macro|close|крупн)/i;
    var MAXPX = 2560;
    var groups = {};    // артикул → { shots: [File], details: [File] }
    var matched = {};   // артикул → true, если нашёлся товар

    function post(body) {
      if (token) body.append("csrfmiddlewaretoken", token.value);
      return fetch(window.location.pathname, {
        method: "POST", body: body, credentials: "same-origin",
        headers: token ? { "X-CSRFToken": token.value } : {}
      }).then(function (r) { return r.json(); });
    }

    // Артикул — имя папки, в которой лежит файл (подходит и «ART/1.jpg», и «Партия/ART/1.jpg»).
    function folderOf(path) {
      var parts = (path || "").split("/");
      return parts.length > 1 ? parts[parts.length - 2].trim() : "";
    }

    function byName(x, y) {
      return x.name.localeCompare(y.name, undefined, { numeric: true });
    }

    function collect(list) {
      groups = {};
      list.forEach(function (it) {
        if (!IMG.test(it.file.name)) return;
        var a = folderOf(it.path);
        if (!a) return;
        var g = groups[a] = groups[a] || { shots: [], details: [] };
        var bare = it.file.name.replace(/\.[^.]+$/, "");
        (DETAIL.test(bare) ? g.details : g.shots).push(it.file);
      });
      Object.keys(groups).forEach(function (a) {
        groups[a].shots.sort(byName);
        groups[a].details.sort(byName);
      });
      check();
    }

    function addRow(cells, off) {
      var tr = document.createElement("tr");
      if (off) tr.className = "m-off";
      cells.forEach(function (v, i) {
        var td = document.createElement("td");
        td.textContent = v;
        if (i >= 3) td.className = "n";
        tr.appendChild(td);
      });
      rows.appendChild(tr);
    }

    function check() {
      rows.innerHTML = "";
      plan.hidden = false;
      var names = Object.keys(groups);
      if (!names.length) {
        status.textContent = "Папок со снимками JPEG/PNG/WEBP не нашлось";
        go.disabled = true;
        return;
      }
      var body = new FormData();
      body.append("action", "match");
      body.append("folders", JSON.stringify(names));
      status.textContent = "Ищу товары по артикулам…";
      post(body).then(function (data) {
        if (!data.ok) { status.textContent = data.error || "не вышло"; return; }
        matched = {};
        data.matched.forEach(function (m) {
          var g = groups[m.folder];
          matched[m.folder] = true;
          addRow([m.folder, m.name, m.color || "—", g.shots.length, g.details.length,
                  m.used + " из " + m.max], g.shots.length === 0);
        });
        data.unmatched.forEach(function (u) {
          var g = groups[u.folder] || { shots: [], details: [] };
          addRow([u.folder, "товар не найден — пропустим", "",
                  g.shots.length, g.details.length, ""], true);
        });
        var n = 0, d = 0;
        Object.keys(matched).forEach(function (a) {
          if (!groups[a].shots.length) return;       // одни крупные планы — нечего снимать
          n += groups[a].shots.length;
          d += groups[a].details.length;
        });
        status.textContent = "К загрузке: " + n + " снимков" +
          (d ? " и " + d + " крупных планов" : "") + " из " +
          Object.keys(matched).length + " папок";
        go.disabled = n === 0;
      }).catch(function () { status.textContent = "сеть не ответила"; });
    }

    // Уменьшить до 2560 px по длинной стороне. Не декодируется (например, HEIC) — как есть.
    function shrink(file) {
      if (!window.createImageBitmap) return Promise.resolve(file);
      return createImageBitmap(file).then(function (bmp) {
        var k = Math.min(1, MAXPX / Math.max(bmp.width, bmp.height));
        var c = document.createElement("canvas");
        c.width = Math.round(bmp.width * k);
        c.height = Math.round(bmp.height * k);
        c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
        return new Promise(function (res) {
          c.toBlob(function (b) { res(b || file); }, "image/jpeg", 0.9);
        });
      }).catch(function () { return file; });
    }

    function finish(batch, done, bad) {
      var body = new FormData();
      body.append("action", "start");
      body.append("batch", batch);
      return post(body).then(function (data) {
        status.textContent = "Загружено " + done + (bad ? ", не загрузилось " + bad : "") +
          ". Обработка идёт в фоне, около 15 секунд на снимок. ";
        var a = document.createElement("a");
        a.href = (data && data.review) || "review/";
        a.textContent = "Открыть проверку";
        status.appendChild(a);
      });
    }

    go.addEventListener("click", function () {
      var queue = [];
      Object.keys(matched).forEach(function (a) {
        var g = groups[a];
        if (!g.shots.length) return;
        // Сначала крупные планы: к запуску генерации они уже должны лежать на сервере.
        g.details.forEach(function (f) { queue.push({ a: a, f: f, role: "detail" }); });
        g.shots.forEach(function (f, i) {
          queue.push({ a: a, f: f, role: i === 0 ? "main" : "gallery" });
        });
      });
      if (!queue.length) return;
      go.disabled = true;

      var body = new FormData();
      body.append("action", "create");
      body.append("track", track ? track.value : "catalog");
      post(body).then(function (data) {
        if (!data.ok) throw new Error(data.error || "не вышло");
        var batch = data.batch, done = 0, bad = 0;

        function next(i) {
          if (i >= queue.length) return finish(batch, done, bad);
          status.textContent = "Загружаю " + (i + 1) + " из " + queue.length + "…";
          var q = queue[i];
          return shrink(q.f).then(function (blob) {
            var fd = new FormData();
            fd.append("action", "upload");
            fd.append("batch", batch);
            fd.append("article", q.a);
            fd.append("attach_as", q.role);
            var name = blob === q.f ? q.f.name : q.f.name.replace(/\.[^.]+$/, "") + ".jpg";
            fd.append("photo", blob, name);
            return post(fd);
          }).then(function (r) {
            if (r && r.ok) { done++; } else { bad++; }
          }, function () { bad++; }).then(function () { return next(i + 1); });
        }
        return next(0);
      }).catch(function (e) {
        status.textContent = "Не вышло: " + (e && e.message ? e.message : "сеть");
        go.disabled = false;
      });
    });

    pick.addEventListener("change", function () {
      collect(Array.prototype.map.call(pick.files || [], function (f) {
        return { file: f, path: f.webkitRelativePath || f.name };
      }));
      pick.value = "";
    });

    // Перетаскивание папок: обходим дерево через webkitGetAsEntry.
    function walk(entry, path, out) {
      return new Promise(function (resolve) {
        if (entry.isFile) {
          entry.file(function (f) { out.push({ file: f, path: path + f.name }); resolve(); },
                     function () { resolve(); });
        } else if (entry.isDirectory) {
          var reader = entry.createReader(), all = [];
          (function more() {
            reader.readEntries(function (ents) {
              if (!ents.length) {
                Promise.all(all.map(function (e) {
                  return walk(e, path + entry.name + "/", out);
                })).then(resolve);
              } else {
                all = all.concat(Array.prototype.slice.call(ents));
                more();
              }
            }, function () { resolve(); });
          })();
        } else {
          resolve();
        }
      });
    }

    drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("is-over"); });
    drop.addEventListener("dragleave", function () { drop.classList.remove("is-over"); });
    drop.addEventListener("drop", function (e) {
      e.preventDefault();
      drop.classList.remove("is-over");
      var items = e.dataTransfer.items || [], out = [], jobs = [];
      for (var i = 0; i < items.length; i++) {
        var en = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
        if (en) jobs.push(walk(en, "", out));
      }
      Promise.all(jobs).then(function () { collect(out); });
    });
  }
})();

/* Фотопайплайн: проверка. «Принять» → витрина; «Переделать» с замечанием → новая
 * генерация в фоне; «Отклонить» → брак. Решение уходит без перезагрузки страницы. */
(function () {
  "use strict";

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    var grid = document.getElementById("photo-review");
    if (!grid) return;

    var token = document.querySelector("input[name=csrfmiddlewaretoken]");
    var AFTER = {
      approve: "Принято — снимок на витрине",
      redo: "Переделывается в фоне — обновите страницу через минуту",
      retry: "Генерируется заново — обновите страницу через минуту",
      reject: "Отклонено"
    };

    function post(body) {
      if (token) body.append("csrfmiddlewaretoken", token.value);
      return fetch(window.location.pathname, {
        method: "POST", body: body, credentials: "same-origin",
        headers: token ? { "X-CSRFToken": token.value } : {}
      }).then(function (r) { return r.json(); });
    }

    function fail(card, text) {
      var note = card.querySelector(".m-gal-error") || document.createElement("div");
      note.className = "m-gal-error";
      note.textContent = text;
      card.appendChild(note);
    }

    grid.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-act]");
      if (!btn) return;
      var card = btn.closest(".m-gal");
      var act = btn.dataset.act;
      var field = card.querySelector("[data-role=note]");
      var note = field ? field.value.trim() : "";
      if (act === "redo" && !note) { fail(card, "Напишите, что исправить"); return; }

      var body = new FormData();
      body.append("action", act);
      body.append("job", card.dataset.job);
      body.append("note", note);
      card.classList.add("is-busy");
      post(body).then(function (data) {
        card.classList.remove("is-busy");
        if (!data.ok) { fail(card, data.error || "не вышло"); return; }
        var state = card.querySelector("[data-role=state]");
        if (state) state.textContent = data.label;
        var acts = card.querySelector(".m-acts");
        if (acts) acts.textContent = AFTER[act] || data.label;
        if (field) field.remove();
        var err = card.querySelector(".m-gal-error");
        if (err) err.remove();
      }).catch(function () {
        card.classList.remove("is-busy");
        fail(card, "сеть не ответила");
      });
    });
  }
})();

/* Фотопайплайн: промты. «Сохранить новую версию», «Вернуть» из истории, «Вернуть
 * встроенный». Каждое действие создаёт новую версию — старые остаются в истории. */
(function () {
  "use strict";

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    var root = document.getElementById("photo-prompts");
    if (!root) return;
    var token = document.querySelector("input[name=csrfmiddlewaretoken]");

    function post(body) {
      if (token) body.append("csrfmiddlewaretoken", token.value);
      return fetch(window.location.pathname, {
        method: "POST", body: body, credentials: "same-origin",
        headers: token ? { "X-CSRFToken": token.value } : {}
      }).then(function (r) { return r.json(); });
    }

    root.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-prompt-act]");
      if (!btn) return;
      var card = btn.closest("[data-track]");
      var act = btn.dataset.promptAct;
      var err = card.querySelector("[data-role=error]");
      if (act === "reset" && !window.confirm("Вернуть встроенный промт? Текущая версия останется в истории.")) return;

      var body = new FormData();
      body.append("action", act);
      body.append("track", card.dataset.track);
      if (act === "save") {
        body.append("text", card.querySelector("[data-role=text]").value);
        body.append("comment", (card.querySelector("[data-role=comment]") || {}).value || "");
      }
      if (act === "restore") body.append("id", btn.dataset.id);

      btn.disabled = true;
      post(body).then(function (data) {
        if (!data.ok) {
          btn.disabled = false;
          if (err) { err.hidden = false; err.textContent = data.error || "не вышло"; }
          return;
        }
        window.location.reload();
      }).catch(function () {
        btn.disabled = false;
        if (err) { err.hidden = false; err.textContent = "сеть не ответила"; }
      });
    });
  }
})();
