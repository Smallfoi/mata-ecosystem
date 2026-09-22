/**
 * Режим редактирования сайта для «Конструктора» (мини-CMS, headless-подход).
 * Активируется ТОЛЬКО при ?edit=1 — на живом сайте не работает и не мешает.
 *
 * Правки копятся в ЧЕРНОВИК у родителя-конструктора (публикуются по кнопке):
 *  - клик по [data-edit]/[data-edit-img] → правка текста/фото;
 *  - клик по товару (.product-card) → правка товара;
 *  - клик по баннеру (.promo-card) → правка баннера; drag баннеров → порядок;
 *  - перетаскивание в группе [data-sortable] → порядок (order.<group>);
 *  - «➕ Добавить блок» (плитка в сетке) → новый блок (extra.<group>);
 *  - у блока по наведению — панель: «Скрыть/Вернуть» (или «Удалить» для добавленного) и «✨» (анимация).
 * Добавленные блоки помечены зелёной обводкой. Кнопки показываются ПО НАВЕДЕНИЮ — не перекрывают текст.
 */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  // Прод-защита: режим правки активен ТОЛЬКО внутри iframe «Конструктора» (window.parent !== window).
  // На живом сайте (даже с ?edit=1 напрямую) редактор не включается — UI правки не виден посетителям.
  if (params.get("edit") !== "1" || window.parent === window) return;
  var PLATFORM = params.get("platform") === "app" ? "app" : "site";
  // Origin «Конструктора» он передаёт сам в адресе фрейма. Разговариваем только с ним:
  // поле source внутри сообщения подделывается тривиально, e.origin — нет.
  var CONSOLE_ORIGIN = params.get("console") || location.origin;

  // Сайт стал многостраничным: переходы внутри него (например, на «Философию»)
  // не должны терять режим правки — иначе в Конструкторе вторая страница
  // открывается обычной, и редактировать её нечем. Дописываем текущие параметры
  // ко всем внутренним ссылкам, кроме якорей.
  (function keepEditParams() {
    function patch() {
      var q = location.search;
      [].forEach.call(document.querySelectorAll("a[href]"), function (a) {
        var href = a.getAttribute("href") || "";
        if (!href || href.charAt(0) === "#" || /^(https?:|mailto:|tel:)/i.test(href)) return;
        if (href.indexOf("edit=1") !== -1) return;
        a.setAttribute("href", href + (href.indexOf("?") === -1 ? q : q.replace("?", "&")));
      });
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", patch);
    } else {
      patch();
    }
  })();

  var css = document.createElement("style");
  css.textContent =
    "html.staw-edit [data-sid],html.staw-edit .product-card{cursor:grab;outline:2px dashed transparent;outline-offset:3px;transition:outline-color .12s}" +
    "html.staw-edit [data-sid]:hover,html.staw-edit .product-card:hover{outline-color:#0a84ff}" +
    "html.staw-edit .staw-dragging{opacity:.4}" +
    "html.staw-edit [data-edit],html.staw-edit [data-edit-img],html.staw-edit [data-edit-ph]{outline:2px dashed transparent;outline-offset:3px;cursor:pointer;transition:outline-color .12s}" +
    "html.staw-edit [data-edit]:hover,html.staw-edit [data-edit-img]:hover,html.staw-edit [data-edit-ph]:hover{outline-color:#0a84ff}" +
    "html.staw-edit [data-hideable]{position:relative}" +
    // Уголок растягивания текста: виден по наведению на сам текст.
    ".staw-size{position:fixed;z-index:2147483001;display:none;width:15px;height:15px;" +
    "border:2px solid #0a84ff;border-radius:3px;background:#fff;cursor:nwse-resize;padding:0;" +
    "box-shadow:0 2px 8px rgba(0,0,0,.28)}" +
    "html.staw-edit .staw-sizing{outline-color:#0a84ff!important;user-select:none}" +
    "html.staw-edit [data-extra]{outline:2px solid #22c55e !important;outline-offset:2px}" +
    "html.staw-edit .staw-cms-hidden{opacity:.32;filter:grayscale(1)}" +
    // В режиме правки ГЛУШИМ анимации появления: их transform создаёт новый stacking-контекст,
    // и служебные контролы (кнопка «Фон», панель блока) проваливаются под соседние слои —
    // становятся некликабельными (баг на экране входа и не только). Анимация всё равно
    // играет на живом/опубликованном сайте; в конструкторе контент и так статичен.
    "html.staw-edit [class*='staw-anim-']{animation:none!important}" +
    // Панель управления блоком — ПО НАВЕДЕНИЮ (не перекрывает контент постоянно).
    // ВАЖНО: жёстко фиксируем позицию/размер через !important. Панель — это <div>, и правила
    // сайта вида «.cinema-card div{position:absolute;inset;z-index:1}» иначе ловят наш служебный
    // div и растягивают его на всю карточку → он (даже прозрачный) перехватывает клик по фото.
    "html.staw-edit .staw-tools{position:absolute!important;top:6px!important;right:6px!important;left:auto!important;bottom:auto!important;" +
      "width:auto!important;height:auto!important;max-width:none!important;margin:0!important;padding:0!important;transform:none!important;" +
      "z-index:50!important;display:flex!important;flex-direction:row!important;align-items:flex-start!important;gap:4px;opacity:0;pointer-events:none;transition:opacity .12s}" +
    "html.staw-edit [data-hideable]:hover>.staw-tools,html.staw-edit .staw-tools:hover{opacity:1;pointer-events:auto}" +
    "html.staw-edit .staw-tools button{position:static!important;width:auto!important;height:auto!important;min-height:0!important;flex:0 0 auto!important;" +
      "border:0;border-radius:6px;padding:4px 8px;color:#fff;font:600 11px/1 system-ui,-apple-system,sans-serif;cursor:pointer;box-shadow:0 1px 5px rgba(0,0,0,.4)}" +
    "html.staw-edit .staw-del{background:rgba(17,24,39,.92)}" +
    "html.staw-edit .staw-anim-btn{background:rgba(124,58,237,.95)}" +
    "html.staw-edit .staw-bg-btn{position:absolute!important;top:6px!important;left:6px!important;right:auto!important;bottom:auto!important;" +
      "width:auto!important;height:auto!important;margin:0!important;transform:none!important;z-index:50!important;border:0;border-radius:6px;padding:4px 9px;" +
      "color:#fff;font:600 11px/1 system-ui,-apple-system,sans-serif;cursor:pointer;background:rgba(16,122,87,.95);" +
      "box-shadow:0 1px 5px rgba(0,0,0,.4);opacity:.55;transition:opacity .12s}" +
    // Кнопка видна всегда (приглушённой): пока она всплывала только по наведению,
    // на блоках, накрытых содержимым, до неё было не добраться вовсе.
    "html.staw-edit [data-edit-bg]:hover>.staw-bg-btn,html.staw-edit .staw-bg-btn:hover{opacity:1}" +
    // Полноэкранные блоки: верх уходит под фиксированную шапку — опускаем кнопку.
    "html.staw-edit [data-bg-btn='low']>.staw-bg-btn{opacity:1;top:78px!important;left:14px!important}" +
    // Экран входа/регистрации: кнопка «Фон» панели видна СРАЗУ (не только по наведению) —
    // панель перекрыта текстом-оверлеем, навести на неё сложно. Виден только активный слой.
    "html.staw-edit .eco-photo>.staw-bg-btn{opacity:1}" +
    // Герой (главный экран): фон-медиа накрыт контентом (hover не доходит) + верх под
    // фикс-навбаром. Кнопку «Фон» показываем ВСЕГДА и опускаем НИЖЕ навбара (слева-вверху —
    // стандартное место кнопки «Фон»).
    // Любой полноэкранный герой (главная, «Философия», будущие страницы): кнопка
    // видна сразу и опущена ниже фикс-шапки, иначе она под ней и до неё не добраться.
    "html.staw-edit [data-edit-bg='hero']>.staw-bg-btn,html.staw-edit .hero-media[data-edit-bg]>.staw-bg-btn{opacity:1;top:78px!important;left:14px!important;right:auto!important}" +
    "html.staw-edit .staw-size-btn{background:rgba(37,99,235,.95)}" +
    // «Добавить блок» — плитка ВНУТРИ сетки (не ломает раскладку секции).
    "html.staw-edit .staw-add{display:flex;align-items:center;justify-content:center;gap:6px;min-height:64px;padding:14px;" +
      "border:2px dashed #0a84ff;border-radius:12px;background:rgba(239,246,255,.9);color:#0a58ca;cursor:pointer;" +
      "font:600 13px/1.2 system-ui,-apple-system,sans-serif;width:100%;box-sizing:border-box}" +
    "html.staw-edit .promo-add-banner{display:flex;align-items:center;justify-content:center;min-width:180px;min-height:90px;" +
      "margin-left:10px;border:2px dashed #0a84ff;border-radius:14px;background:rgba(239,246,255,.9);color:#0a58ca;cursor:pointer;" +
      "font:600 13px/1.2 system-ui,-apple-system,sans-serif}" +
    "html.staw-edit .promo-card{cursor:pointer;outline:2px dashed transparent;outline-offset:3px;transition:outline-color .12s}" +
    "html.staw-edit .promo-card:hover{outline-color:#0a84ff}" +
    "html.staw-edit .staw-align-bar{display:flex;gap:4px;justify-content:center;margin:0 0 8px}" +
    "html.staw-edit .staw-align-btn{border:1px solid #d1d5db;border-radius:6px;padding:3px 10px;background:#fff;color:#374151;cursor:pointer}" +
    "html.staw-edit .product-add,html.staw-edit [data-quick-view]{pointer-events:none}";
  document.documentElement.appendChild(css);
  document.documentElement.classList.add("staw-edit");

  function send(msg) { msg.source = "staw-editor"; if (window.parent !== window) window.parent.postMessage(msg, CONSOLE_ORIGIN); }
  function draft(key, value) { send({ type: "draftContent", key: key, value: value }); }
  function safeId(s) { return typeof s === "string" && /^[\w.-]+$/.test(s); }
  // rgb(a)(...) → #rrggbb (для стартового значения пикера цвета в конструкторе)
  function rgbToHex(c) {
    var m = /rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(c || "");
    if (!m) return "";
    function h(n) { n = (+n).toString(16); return n.length < 2 ? "0" + n : n; }
    return "#" + h(m[1]) + h(m[2]) + h(m[3]);
  }
  var COLOR_OK = /^#[0-9a-fA-F]{3,8}$|^rgba?\([\d.,\s%]+\)$/;
  // Цвет текста: value = "#rrggbb"/"rgb(...)" или "" (сброс к цвету темы).
  function applyColorLocal(key, val) {
    var ok = COLOR_OK.test(val || "");
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.color = ok ? val : "";
      el.style.webkitTextFillColor = ok ? val : ""; // перебить брендовый gradient-text, если он есть
    });
  }
  // Шрифт/размер/тень текста (правка в конструкторе) — зеркалит content.js.
  function stawFontFamily(t) {
    if (t === "unbounded") return "'Unbounded','Manrope','Inter',sans-serif";
    if (t === "manrope") return "'Manrope','Inter',sans-serif";
    if (t === "inter") return "'Inter','Segoe UI',Arial,sans-serif";
    return "";
  }
  function stawShadowCss(v) {
    var n = parseInt(v, 10) || 0;
    if (n <= 0) return "";
    var k = n / 100;
    return "0 " + (1 + 3 * k).toFixed(1) + "px " + (2 + 10 * k).toFixed(1) +
      "px rgba(0,0,0," + (0.25 + 0.5 * k).toFixed(2) + ")";
  }
  // ВНИМАНИЕ: имя не должно совпадать с applyAlignLocal ниже (выравнивание блоков) —
  // в JavaScript побеждает последнее объявление, и правка молча перестаёт работать.
  function applyTextAlignLocal(key, val) {
    // Ширину, заданную владельцем (уголком), выравнивание переопределять не должно:
    // иначе оно растягивает родителя, и проценты начинают считаться от него —
    // в редакторе текст в две строки, а на сайте в три.
    if (window.__stawAlign) {
      var probe = document.querySelector('[data-edit="' + key + '"]');
      var own = !!(probe && probe.style.width && !probe.dataset.stawAlignWidth);
      window.__stawAlign(key, val, own);
      return;
    }
    return applyTextAlignFallback(key, val);
  }

  function applyTextAlignFallback(key, val) {
    var v = (val || "").trim();
    if (v && ["left", "center", "right", "justify"].indexOf(v) === -1) return;
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.textAlign = v;
      // Рамка заголовка обтягивает текст — центрировать внутри неё нечего.
      // Раздвигаем на всю ширину родителя, если владелец не задал свою.
      if (!v) {
        if (el.dataset.stawAlignWidth) { el.style.width = ""; delete el.dataset.stawAlignWidth; }
        var box0 = el.parentElement;
        if (box0 && box0.dataset.stawAlignFlex) { box0.style.flex = ""; delete box0.dataset.stawAlignFlex; }
        return;
      }
      if (!el.style.width) {
        el.style.width = "100%";
        el.dataset.stawAlignWidth = "1";
      }
      if (getComputedStyle(el).display === "inline") el.style.display = "block";
      // Рамка может обтягивать текст не только сама: её родитель бывает сжатым
      // элементом гибкой раскладки (заголовок рядом с подписью). Тогда ширина
      // «100%» ничего не даёт — растягиваем и родителя, но не трогаем соседей.
      var box = el.parentElement;
      var row = box && box.parentElement;
      if (box && row && getComputedStyle(row).display.indexOf("flex") === 0) {
        box.style.flex = "1 1 auto";
        box.dataset.stawAlignFlex = "1";
      }
    });
  }
  function applyFontLocal(key, val) {
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.fontFamily = stawFontFamily(val);
      if (val) { el.dataset.stawFont = val; } else { delete el.dataset.stawFont; }
    });
  }
  function applyFontSizeLocal(key, val) {
    var n = parseInt(val, 10);
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.fontSize = (n && n > 0) ? n + "px" : "";
    });
  }
  function applyShadowLocal(key, val) {
    var css = stawShadowCss(val);
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.textShadow = css;
      if (parseInt(val, 10) > 0) { el.dataset.stawShadow = val; } else { delete el.dataset.stawShadow; }
    });
  }
  var VOID_TAGS = { IMG: 1, INPUT: 1, BR: 1, HR: 1, AREA: 1, EMBED: 1 };

  function isItem(ch) { return ch.hasAttribute("data-sid") || (ch.classList && ch.classList.contains("product-card")); }
  function sidsOf(c) { return [].filter.call(c.children, isItem).map(function (x) { return x.getAttribute("data-sid"); }); }
  function extrasOf(c) {
    return [].filter.call(c.children, function (x) { return x.hasAttribute("data-sid") && x.hasAttribute("data-extra"); })
      .map(function (x) { return x.getAttribute("data-sid"); });
  }
  function addTileOf(c) { for (var i = 0; i < c.children.length; i++) if (c.children[i].classList && c.children[i].classList.contains("staw-add")) return c.children[i]; return null; }

  // ── Перетаскивание (товары + баннеры + любые [data-sortable]) ──
  var dragged = null, dragContainer = null;
  function sortItem(node) { return node && node.closest ? node.closest("[data-sid], .product-card") : null; }
  function containerOf(item) {
    if (!item) return null;
    if (item.classList.contains("product-card")) return item.closest("[data-product-grid]");
    return item.closest("[data-sortable]");
  }
  function markDraggable() {
    [].forEach.call(document.querySelectorAll("[data-sortable] > [data-sid]"), function (el) { el.setAttribute("draggable", "true"); });
    [].forEach.call(document.querySelectorAll("[data-product-grid] > .product-card"), function (el) { el.setAttribute("draggable", "true"); });
    // <img> браузер делает «перетаскиваемым» по умолчанию: клик по фото с малейшим сдвигом
    // мыши превращается в нативный drag картинки, и правка (editImage) не открывается —
    // именно поэтому фото Бег/Тренировка/Город «не менялись», хотя кнопки/драг карточки работали.
    // Гасим нативный drag на редактируемых фото, которые НЕ являются сами сорт-элементом
    // (референс-картинка = сам <img data-sid> — её оставляем перетаскиваемой для реордера).
    // Перетащить карточку за фото по-прежнему можно: тянется родитель article[data-sid].
    [].forEach.call(document.querySelectorAll("[data-edit-img]"), function (el) {
      if (el.tagName === "IMG" && !el.hasAttribute("data-sid")) el.setAttribute("draggable", "false");
    });
  }
  document.addEventListener("dragstart", function (e) {
    if (e.target.closest && e.target.closest(".staw-ui, .staw-tools")) return;
    var item = sortItem(e.target); if (!item) return;
    var c = containerOf(item); if (!c) return;
    dragged = item; dragContainer = c; item.classList.add("staw-dragging");
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  });
  document.addEventListener("dragend", function () {
    if (!dragged) return;
    dragged.classList.remove("staw-dragging");
    saveOrder(dragContainer); dragged = null; dragContainer = null;
  });
  document.addEventListener("dragover", function (e) {
    if (!dragged || !dragContainer) return;
    e.preventDefault();
    var after = afterEl(dragContainer, e.clientX, e.clientY);
    if (after == null) {
      var tile = addTileOf(dragContainer);          // держим «Добавить блок» последним
      if (tile) dragContainer.insertBefore(dragged, tile); else dragContainer.appendChild(dragged);
    } else if (after !== dragged) dragContainer.insertBefore(dragged, after);
  });
  function afterEl(c, x, y) {
    var els = [].filter.call(c.children, function (ch) { return isItem(ch) && !ch.classList.contains("staw-dragging"); });
    for (var i = 0; i < els.length; i++) {
      var b = els[i].getBoundingClientRect(), cx = b.left + b.width / 2;
      if (y < b.top || (y <= b.bottom && x < cx)) return els[i];
    }
    return null;
  }
  function saveOrder(c) {
    if (!c) return;
    if (c.hasAttribute("data-product-grid")) {
      send({ type: "reorder", platform: PLATFORM, order: [].filter.call(c.children, isItem).map(function (x) { return x.getAttribute("data-id"); }) });
      return;
    }
    var g = c.getAttribute("data-sortable");
    if (g === "banners") { send({ type: "bannerReorder", platform: PLATFORM, order: sidsOf(c) }); return; }
    if (g) draft("order." + g, JSON.stringify(sidsOf(c)));
  }

  // ── Клик: баннер/товар/фото/текст ──
  function sendEditImage(img) {
    var isImg = img.tagName === "IMG";
    // ВАЖНО: img.src (абсолютный URL), а НЕ getAttribute("src") (относительный "media/…").
    // Конструктор на :8000, картинки сайта на :5577 — относительный путь превью не загрузит.
    var url = isImg ? img.src : (img.style.backgroundImage || "").replace(/^url\(["']?/, "").replace(/["']?\)$/, "");
    send({
      type: "editImage", key: img.getAttribute("data-edit-img"), url: url || "",
      focal: (isImg ? img.style.objectPosition : img.style.backgroundPosition) || "",
      fit: ((isImg ? img.style.objectFit : img.style.backgroundSize) === "contain") ? "contain" : "cover",
      aspect: (img.clientWidth && img.clientHeight) ? (img.clientWidth / img.clientHeight) : 0,
      anim: currentAnim(img),   // текущая анимация фото (для пикера «✨ Анимация» в модалке)
    });
  }
  // Текст элемента БЕЗ служебных вставок (.staw-ui: панель инструментов, крестик и т.п.).
  function cleanText(el) {
    var t = "";
    [].forEach.call(el.childNodes, function (n) {
      if (n.nodeType === 3) t += n.nodeValue;
      else if (n.nodeType === 1 && !(n.classList && n.classList.contains("staw-ui"))) t += cleanText(n);
    });
    return t;
  }
  document.addEventListener("click", function (e) {
    // После перетаскивания надписи «съедаем» следующий click, чтобы не открылась правка.
    if (justDragged) { justDragged = false; e.preventDefault(); e.stopPropagation(); return; }
    if (e.target.closest && e.target.closest(".staw-ui, .staw-tools")) return;
    var addb = e.target.closest && e.target.closest(".promo-add-banner");
    if (addb) { e.preventDefault(); e.stopPropagation(); send({ type: "addBanner" }); return; }
    var bnr = e.target.closest(".promo-card");
    if (bnr && bnr.getAttribute("data-banner-id")) { e.preventDefault(); e.stopPropagation(); send({ type: "editBanner", id: bnr.getAttribute("data-banner-id") }); return; }
    var card = e.target.closest(".product-card");
    if (card) { e.preventDefault(); e.stopPropagation(); send({ type: "editProduct", id: card.getAttribute("data-id") }); return; }
    var img = e.target.closest("[data-edit-img]");
    if (img) { e.preventDefault(); e.stopPropagation(); sendEditImage(img); return; }
    var ph = e.target.closest("[data-edit-ph]");
    if (ph) {
      // Поле ввода: правим его подсказку (placeholder), а не содержимое.
      e.preventDefault(); e.stopPropagation();
      send({ type: "editContent", key: ph.getAttribute("data-edit-ph"),
        value: (ph.getAttribute("placeholder") || "").trim() });
      return;
    }
    var ed = e.target.closest("[data-edit]");
    if (ed) {
      e.preventDefault(); e.stopPropagation();
      send({ type: "editContent", key: ed.getAttribute("data-edit"), value: cleanText(ed).trim(),
        color: rgbToHex(getComputedStyle(ed).color), hasColor: !!ed.style.color,
        // текущие шрифт/размер/тень — чтобы окно правки показало их (fallback к опубликованному)
        font: ed.dataset.stawFont || "", fontsize: (parseInt(ed.style.fontSize, 10) || ""),
        shadow: ed.dataset.stawShadow || "",
        // выравнивание — из своего стиля: вёрстку сайта сюда не тянем
        talign: ed.style.textAlign || "" });
      return;
    }
    // Fallback: у многих карточек поверх фото лежит декоративный оверлей/scrim
    // (напр. .cinema-card::after{inset:0}) — тогда цель клика = карточка, а не <img>,
    // и прямой поиск [data-edit-img] выше не срабатывает. Если клик попал в карточку/блок
    // с фото и НЕ по тексту/ссылке/кнопке — правим фото этой карточки.
    var host = e.target.closest("[data-sid], [data-hideable], .cinema-card");
    if (host && !e.target.closest("a, button, input, textarea, select")) {
      var hostImg = host.querySelector("[data-edit-img]");
      if (hostImg) { e.preventDefault(); e.stopPropagation(); sendEditImage(hostImg); }
    }
  }, true);

  // ── Репитеры ──
  function replaceTokens(node, sid) {
    var all = [node].concat([].slice.call(node.querySelectorAll ? node.querySelectorAll("*") : []));
    all.forEach(function (el) {
      ["data-sid", "data-hideable", "data-edit", "data-edit-img", "data-edit-bg"].forEach(function (a) {
        var v = el.getAttribute && el.getAttribute(a);
        if (v && v.indexOf("{sid}") >= 0) el.setAttribute(a, v.replace(/\{sid\}/g, sid));
      });
    });
  }
  function makeSid() { return "n" + Date.now().toString(36) + Math.floor(Math.random() * 1e4).toString(36); }
  function templateFor(group) { return document.querySelector('template[data-block-template="' + group + '"]'); }
  function addBlock(group, container) {
    var tpl = templateFor(group);
    if (!tpl || !tpl.content || !tpl.content.firstElementChild) return;
    var sid = makeSid();
    var node = tpl.content.firstElementChild.cloneNode(true);
    replaceTokens(node, sid); node.setAttribute("data-extra", "1");
    var tile = addTileOf(container);
    if (tile) container.insertBefore(node, tile); else container.appendChild(node);
    markDraggable(); initHideOn(node);
    draft("extra." + group, JSON.stringify(extrasOf(container)));
    draft("order." + group, JSON.stringify(sidsOf(container)));
  }
  function removeExtra(el) {
    // Добавленная надпись — просто убрать и пересобрать список xlabels.
    if (el.classList.contains("staw-newlabel")) { el.remove(); draft("xlabels", JSON.stringify(allLabels())); return; }
    var container = el.closest("[data-sortable]");
    var group = container && container.getAttribute("data-sortable");
    el.remove();
    if (group && container) {
      draft("extra." + group, JSON.stringify(extrasOf(container)));
      draft("order." + group, JSON.stringify(sidsOf(container)));
    }
  }
  function initAdders() {
    [].forEach.call(document.querySelectorAll("[data-sortable]"), function (container) {
      var group = container.getAttribute("data-sortable");
      if (!templateFor(group) || addTileOf(container)) return;
      var btn = document.createElement("button");
      btn.type = "button"; btn.className = "staw-ui staw-add"; btn.setAttribute("data-add", group);
      btn.textContent = "➕ Добавить блок";
      container.appendChild(btn);                 // плитка последней в сетке
      btn.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); addBlock(group, container); });
    });
  }

  // ── Выравнивание ──
  var ALIGN = { left: "flex-start", center: "center", right: "flex-end" };
  function applyAlignLocal(el, val) {
    if (!el) return;
    el.style.justifyContent = ALIGN[val] || "";
    el.style.textAlign = val === "right" ? "right" : val === "center" ? "center" : val === "left" ? "left" : "";
  }
  function initAlign() {
    [].forEach.call(document.querySelectorAll("[data-align]"), function (container) {
      var key = container.getAttribute("data-align");
      if (!key || container.parentNode.querySelector('.staw-align-bar[data-align-for="' + key + '"]')) return;
      var bar = document.createElement("div"); bar.className = "staw-ui staw-align-bar"; bar.setAttribute("data-align-for", key);
      [["left", "⇤"], ["center", "⇔"], ["right", "⇥"]].forEach(function (pair) {
        var b = document.createElement("button"); b.type = "button"; b.className = "staw-ui staw-align-btn"; b.textContent = pair[1];
        b.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); applyAlignLocal(container, pair[0]); draft("align." + key, pair[0]); });
        bar.appendChild(b);
      });
      container.parentNode.insertBefore(bar, container);
    });
  }

  // ── Анимация ──
  function currentAnim(el) { var m = /\bstaw-anim-([\w-]+)/.exec(el.className); return m ? m[1] : ""; }
  function applyAnimLocal(key, val) {
    // Анимация применяется к блокам (data-hideable), к фото (data-edit-img) И к фону (data-edit-bg).
    document.querySelectorAll('[data-hideable="' + key + '"], [data-edit-img="' + key + '"], [data-edit-bg="' + key + '"]').forEach(function (el) {
      el.className = el.className.replace(/\s*\bstaw-anim-[\w-]+/g, "").trim();
      if (val && /^[\w-]+$/.test(val) && val !== "none") el.classList.add("staw-anim-" + val);
    });
  }
  // Фокус-область (object-position) / подгон (object-fit) фото — применить к превью.
  function applyImgStyle(key, type, value) {
    document.querySelectorAll('[data-edit-img="' + key + '"]').forEach(function (el) {
      var isImg = el.tagName === "IMG";
      if (type === "focal") {
        var ok = /^\d{1,3}% \d{1,3}%$/.test(value || "");
        if (isImg) el.style.objectPosition = ok ? value : ""; else el.style.backgroundPosition = ok ? value : "";
      } else {
        var contain = value === "contain";
        if (isImg) el.style.objectFit = contain ? "contain" : ""; else el.style.backgroundSize = contain ? "contain" : "";
      }
    });
  }

  // ── Фон блока (фото/видео/градиент) — применение черновика в превью + кнопка «Фон» ──
  // Фоновое видео. Флаги (тумблеры «Конструктора», по умолчанию ВКЛ):
  //  fade — плавное появление (opacity 0→1); seamless — бесшовная петля (кроссфейд 2 видео).
  function setupBgVideo(layer, src, fit, focal, fade, seamless) {
    var need = seamless ? 2 : 1;
    var vs = layer.querySelectorAll("video");
    var fresh = vs.length !== need;
    if (fresh) {
      layer.textContent = "";
      for (var i = 0; i < need; i++) {
        var v = document.createElement("video");
        v.muted = true; v.defaultMuted = true;
        v.setAttribute("muted", ""); v.setAttribute("playsinline", ""); v.setAttribute("preload", "auto");
        // Нативный loop ВСЕГДА — страховка от «зависло на последнем кадре» (см. content.js).
        v.loop = true; v.setAttribute("loop", "");
        layer.appendChild(v);
      }
      vs = layer.querySelectorAll("video");
    }
    var a = vs[0], b = vs[1] || null;
    var newSrc = a.getAttribute("src") !== src;
    if (newSrc) { a.setAttribute("src", src); if (b) b.setAttribute("src", src); }
    [a, b].forEach(function (v) { if (v) { v.style.objectFit = fit; v.style.objectPosition = focal; } });
    if (fresh || newSrc) {
      layer._active = a;
      a.style.transition = fade ? "opacity .6s ease" : "none";
      a.style.opacity = fade ? "0" : "1";
      if (b) { b.style.transition = fade ? "opacity .6s ease" : "none"; b.style.opacity = "0"; try { b.pause(); } catch (e) {} }
      if (fade && !a._faded) {
        a._faded = 1;
        var showA = function () { a.style.opacity = "1"; };
        // Показываем по ПЕРВОМУ КАДРУ (loadeddata) — раньше всего и не зависит от autoplay.
        if (a.readyState >= 2) showA();
        else { a.addEventListener("loadeddata", showA, { once: true }); a.addEventListener("canplay", showA, { once: true }); }
      }
      if (seamless && b) {
        var XF = 0.55;
        [a, b].forEach(function (vv) {
          if (vv._wrap) return; vv._wrap = 1;
          vv.addEventListener("timeupdate", function () {
            if (vv !== layer._active || !vv.duration || vv.duration === Infinity) return;
            if (vv.currentTime >= vv.duration - XF && !vv._switching) {
              vv._switching = 1;
              var other = (vv === a) ? b : a;
              try { other.currentTime = 0; } catch (e) {}
              // Свап только после реального play() второго видео (см. content.js) — иначе
              // не гасим текущее: оно зациклится нативным loop, «застыть» не сможет.
              var swap = function () {
                layer._active = other;
                other.style.opacity = "1"; vv.style.opacity = "0";
                setTimeout(function () { try { vv.pause(); } catch (e) {} vv._switching = 0; }, (XF + 0.12) * 1000);
              };
              var p = other.play();
              if (p && p.then) p.then(swap).catch(function () { vv._switching = 0; });
              else swap();
            }
          });
        });
      }
    }
    var pp = (layer._active || a).play(); if (pp && pp.catch) pp.catch(function () {});
  }
  function bgEl(key) { return safeId(key) ? document.querySelector('[data-edit-bg="' + key + '"]') : null; }
  // Масштаб фото-фона (зеркалит content.js): cover×Z раскладываем на ведущую сторону.
  function parseZoom(v) { var z = parseFloat(v); return (z && z > 1 && z <= 6) ? z : 1; }
  function bgImgSize(el, fit, zoom) {
    if (fit === "contain") return "contain";
    if (zoom <= 1) return "cover";
    var a = el._bgNatAspect, ew = el.clientWidth, eh = el.clientHeight;
    if (!a || !ew || !eh) return "cover";
    return (ew / eh >= a) ? (100 * zoom) + "% auto" : "auto " + (100 * zoom) + "%";
  }
  function refreshBg(el) {
    if (!el) return;
    var off = el._bgOff === "1", vid = el._bgVid || "", img = el._bgImg || "";
    var focal = /^\d{1,3}% \d{1,3}%$/.test(el._bgFocal || "") ? el._bgFocal : "50% 50%";
    var fit = el._bgFit === "contain" ? "contain" : "cover";
    var zoom = parseZoom(el._bgZoom);
    var layer = el.querySelector(":scope > .staw-bg-layer");
    if (!off && vid) {
      el.style.backgroundImage = ""; el.style.backgroundSize = ""; el.style.backgroundPosition = "";
      if (!layer) { layer = document.createElement("div"); layer.className = "staw-bg-layer"; el.insertBefore(layer, el.firstChild); }
      setupBgVideo(layer, vid, fit, focal, el._bgFade !== "0", el._bgLoop !== "0");
      el.classList.add("staw-bg-on");
    } else if (!off && img) {
      if (layer) layer.remove(); el.classList.remove("staw-bg-on");
      if (zoom > 1 && fit !== "contain" && !el._bgNatAspect) {
        var probe = new Image();
        probe.onload = function () { if (probe.naturalWidth && probe.naturalHeight) { el._bgNatAspect = probe.naturalWidth / probe.naturalHeight; refreshBg(el); } };
        probe.src = img;
      }
      el.style.backgroundImage = "linear-gradient(rgba(0,0,0,.15),rgba(0,0,0,.5)), url('" + img + "')";
      el.style.backgroundSize = "cover, " + bgImgSize(el, fit, zoom);
      el.style.backgroundPosition = "center, " + focal; el.style.backgroundRepeat = "no-repeat";
    } else {
      if (layer) layer.remove(); el.classList.remove("staw-bg-on");
      el.style.backgroundImage = ""; el.style.backgroundSize = ""; el.style.backgroundPosition = "";
    }
  }
  function setBgField(key, field, val) { var el = bgEl(key); if (!el) return; el[field] = val; refreshBg(el); }
  function setBgImg(key, url) { var el = bgEl(key); if (!el) return; el._bgImg = url || ""; refreshBg(el); }
  function initBg() {
    [].forEach.call(document.querySelectorAll("[data-edit-bg]"), function (el) {
      var key = el.getAttribute("data-edit-bg");
      if (!key || el.querySelector(":scope > .staw-bg-btn")) return;
      var b = document.createElement("button");
      b.type = "button"; b.className = "staw-ui staw-bg-btn"; b.textContent = "🖼 Фон"; b.draggable = false;
      b.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        send({
          type: "editBg", key: key,
          img: el._bgImg || "", vid: el._bgVid || "", off: el._bgOff || "",
          focal: el._bgFocal || "", fit: el._bgFit || "cover",
          zoom: el._bgZoom || "", fade: el._bgFade || "", loop: el._bgLoop || "",
          // Реальные пропорции блока — чтобы рамка кадра в окне «Фон» повторяла форму
          // именно этого блока (герой — вытянутый, карточка — горизонтальная и т.п.).
          aspect: (el.offsetHeight ? (el.offsetWidth / el.offsetHeight) : 0),
          anim: currentAnim(el),   // текущая анимация фона — для пикера «✨» в окне «Фон»
        });
      });
      el.insertBefore(b, el.firstChild);
    });
  }

  // ── Размер текстовой рамки: тянем уголок, как в графическом редакторе ──
  // Уголок ОДИН на страницу и стоит поверх всего (position: fixed): вложенный
  // внутрь текста, он пропадал при правке (она заменяет содержимое целиком) и
  // срезался обрезкой у заголовков. Поэтому работает на любом тексте.
  var _size = null, _sizeTarget = null, _sizeTimer = null, _sizeDrag = null;

  function hideSize() {
    if (_sizeDrag) return;                       // во время перетаскивания не прячем
    if (_size) _size.style.display = "none";
    _sizeTarget = null;
  }

  function placeSize(el) {
    var r = el.getBoundingClientRect();
    var b = sizeGrip();
    b.style.display = "block";
    b.style.left = Math.round(r.right - 7) + "px";
    b.style.top = Math.round(r.bottom - 7) + "px";
    _sizeTarget = el;
  }

  function sizeGrip() {
    if (_size) return _size;
    _size = document.createElement("button");
    _size.type = "button";
    _size.className = "staw-ui staw-size";
    _size.title = "Тянуть — ширина и высота. Двойной клик — вернуть как было";
    _size.addEventListener("mouseenter", function () { if (_sizeTimer) clearTimeout(_sizeTimer); });
    _size.addEventListener("mouseleave", function () { _sizeTimer = setTimeout(hideSize, 220); });

    _size.addEventListener("pointerdown", function (e) {
      var el = _sizeTarget;
      if (!el) return;
      e.preventDefault(); e.stopPropagation();
      _size.setPointerCapture(e.pointerId);
      var parent = el.parentElement || document.body;
      var r = el.getBoundingClientRect();
      _sizeDrag = {
        el: el, x: e.clientX, y: e.clientY, w: r.width, h: r.height,
        pw: parent.getBoundingClientRect().width || 1,
      };
      el.classList.add("staw-sizing");
    });

    _size.addEventListener("pointermove", function (e) {
      if (!_sizeDrag) return;
      e.preventDefault();
      var el = _sizeDrag.el;
      var w = Math.max(60, _sizeDrag.w + (e.clientX - _sizeDrag.x));
      var h = Math.max(20, _sizeDrag.h + (e.clientY - _sizeDrag.y));
      el.style.width = Math.min(100, Math.round((w / _sizeDrag.pw) * 1000) / 10) + "%";
      el.style.minHeight = Math.round(h) + "px";
      // Строчным элементам ширина не применяется — иначе тянешь, а ничего не двигается.
      if (getComputedStyle(el).display === "inline") el.style.display = "inline-block";
      placeSize(el);                              // уголок едет вместе с углом рамки
    });

    function finish(e) {
      if (!_sizeDrag) return;
      var el = _sizeDrag.el;
      _sizeDrag = null;
      el.classList.remove("staw-sizing");
      try { _size.releasePointerCapture(e.pointerId); } catch (err) {}
      var key = el.getAttribute("data-edit");
      if (!safeId(key)) return;
      // В черновик: на живой сайт уйдёт по «Опубликовать», как и всё остальное.
      draft("width." + key, el.style.width || "");
      draft("minh." + key, el.style.minHeight || "");
      justDragged = true;                         // не открывать правку текста от этого клика
    }
    _size.addEventListener("pointerup", finish);
    _size.addEventListener("pointercancel", finish);

    _size.addEventListener("dblclick", function (e) {
      e.preventDefault(); e.stopPropagation();
      var el = _sizeTarget;
      if (!el) return;
      el.style.width = ""; el.style.minHeight = "";
      if (el.style.display === "inline-block") el.style.display = "";
      var key = el.getAttribute("data-edit");
      if (safeId(key)) { draft("width." + key, ""); draft("minh." + key, ""); }
      placeSize(el);
    });

    if (document.body) document.body.appendChild(_size);
    return _size;
  }

  document.addEventListener("mouseover", function (e) {
    if (!document.documentElement.classList.contains("staw-edit")) return;
    if (_sizeDrag) return;
    if (e.target.closest(".staw-ui, .staw-tools, input, textarea, select")) return;
    var el = e.target.closest("[data-edit]:not([data-edit-ph])");
    if (el) { if (_sizeTimer) clearTimeout(_sizeTimer); placeSize(el); }
  }, true);

  document.addEventListener("mouseout", function (e) {
    if (!_sizeTarget || _sizeDrag) return;
    var to = e.relatedTarget;
    if (to && to.closest && (to === _size || to.closest(".staw-size") || to.closest("[data-edit]") === _sizeTarget)) return;
    if (_sizeTimer) clearTimeout(_sizeTimer);
    _sizeTimer = setTimeout(hideSize, 220);
  }, true);

  // Страница едет — уголок должен ехать с ней, иначе повиснет в пустоте.
  window.addEventListener("scroll", function () { if (_sizeTarget && !_sizeDrag) placeSize(_sizeTarget); }, true);
  window.addEventListener("resize", function () { if (_sizeTarget && !_sizeDrag) placeSize(_sizeTarget); });

  // ── Панель блока (по наведению): Скрыть/Вернуть/Удалить + Анимация ──
  var hideBtns = {};
  function updateHideBtn(key) {
    var rec = hideBtns[key]; if (!rec) return;
    if (rec.el.hasAttribute("data-extra")) rec.btn.textContent = "Удалить ✕";
    else rec.btn.textContent = rec.el.classList.contains("staw-cms-hidden") ? "Вернуть" : "Скрыть ✕";
  }
  function initHideOn(el) {
    if (VOID_TAGS[el.tagName]) return;
    var key = el.getAttribute("data-hideable");
    if (!key || hideBtns[key]) return;
    var tools = document.createElement("div"); tools.className = "staw-ui staw-tools";
    var del = document.createElement("button");
    del.type = "button"; del.className = "staw-ui staw-del"; del.draggable = false;
    del.addEventListener("click", function (e) {
      e.preventDefault(); e.stopPropagation();
      if (el.hasAttribute("data-extra")) { delete hideBtns[key]; removeExtra(el); return; }
      var nowHidden = el.classList.toggle("staw-cms-hidden");
      updateHideBtn(key); draft("hidden." + key, nowHidden ? "1" : "");
    });
    var anim = document.createElement("button");
    anim.type = "button"; anim.className = "staw-ui staw-anim-btn"; anim.draggable = false; anim.textContent = "✨";
    anim.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); send({ type: "editAnim", key: key, value: currentAnim(el) }); });
    var size = document.createElement("button");
    size.type = "button"; size.className = "staw-ui staw-size-btn"; size.draggable = false;
    size.textContent = el.classList.contains("staw-w-wide") ? "⟷ Обычный" : "⟷ Шире";
    size.addEventListener("click", function (e) {
      e.preventDefault(); e.stopPropagation();
      var wide = el.classList.toggle("staw-w-wide");
      size.textContent = wide ? "⟷ Обычный" : "⟷ Шире";
      draft("size." + key, wide ? "wide" : "");
    });
    tools.appendChild(del); tools.appendChild(anim); tools.appendChild(size);
    el.appendChild(tools);
    hideBtns[key] = { btn: del, el: el };
    updateHideBtn(key);
  }
  function initHide() { [].forEach.call(document.querySelectorAll("[data-hideable]"), initHideOn); }

  // ── Перемещение надписей (как в Photoshop/Figma): drag + умные направляющие ──
  // Тащишь надпись → она смещается (CSS translate, композится с её трансформами).
  // При приближении к краю/центру контейнера или к другой надписи — «прилипание»
  // (snap) + розовая направляющая. Alt+клик — сброс позиции. Позиция → pos.<key>.
  var justDragged = false;
  var POS = {};
  // Пересчитать всё, что зависит от геометрии текста (позиция и выравнивание).
  // Вызывается после правок ширины/высоты/шрифта — и после смены самого текста.
  function regeometry(key) {
    if (!safeId(key)) return;
    var p = POS[key];
    if (p) applyPosByKey(key, p.x + "," + p.y + (p.refW ? "," + p.refW : ""));
  }
  // Ширина контейнера на момент перетаскивания — её запоминаем вместе со сдвигом,
  // чтобы на другой ширине окна он пересчитался пропорционально.
  function posLimits(el) {
    var S = window.__stawPos;
    if (!S) return null;
    return { w: S.container(el).clientWidth };
  }
  function applyPosByKey(key, value) {
    var parts = String(value == null ? "0,0" : value).split(",");
    var x = parseFloat(parts[0]) || 0, y = parseFloat(parts[1]) || 0;
    var refW = parseFloat(parts[2]) || 0;
    POS[key] = { x: x, y: y, refW: refW };
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      // Та же функция, что и на сайте: одинаковый результат в «Смотрим» и
      // «Редактируем» — раньше две копии логики расходились.
      if (window.__stawPos) window.__stawPos.place(el, x, y, refW);
      else el.style.translate = x + "px " + y + "px";
    });
  }
  // Короткое сообщение поверх страницы — почему надпись не двигается.
  var _hintT = null;
  function narrowHint() {
    var el = document.getElementById("staw-narrow-hint");
    if (!el) {
      el = document.createElement("div");
      el.id = "staw-narrow-hint";
      el.className = "staw-ui";
      el.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483000;" +
        "max-width:min(420px,86vw);padding:12px 16px;border-radius:12px;background:#14171c;color:#EEF1F5;" +
        "font:500 13px/1.45 system-ui,sans-serif;box-shadow:0 12px 30px rgba(0,0,0,.35);text-align:center";
      el.textContent = "На узкой ширине сдвиги не применяются — так же и на телефоне. " +
        "Двигайте надписи на широкой ширине.";
      document.body.appendChild(el);
    }
    el.style.display = "block";
    clearTimeout(_hintT);
    _hintT = setTimeout(function () { el.style.display = "none"; }, 3200);
  }

  // Добавленная надпись стоит абсолютно внутри своей секции, и её место задаёт
  // ТОЛЬКО сдвиг от угла этой секции. Утащили в другую секцию — сдвиг становится
  // огромным (у владельца вышло -6300px), а расстояние между секциями на каждой
  // ширине окна своё: на другом экране надпись промахивается на сотни пикселей.
  // Поэтому при отпускании перевешиваем её в ту секцию, над которой она
  // оказалась, и пересчитываем сдвиг относительно неё — он остаётся маленьким.
  // Возвращает новый сдвиг или null, если перевешивать не понадобилось.
  function rehomeLabel(el) {
    var r = el.getBoundingClientRect();
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    var host = null;
    [].forEach.call(document.querySelectorAll("section[id]"), function (s) {
      var b = s.getBoundingClientRect();
      if (cy >= b.top && cy <= b.bottom && cx >= b.left && cx <= b.right) host = s;
    });
    if (!host || host === el.parentElement) return null;
    var keepL = r.left, keepT = r.top;   // куда владелец её поставил — там и оставим
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    el.style.translate = "";
    host.appendChild(el);
    el.style.left = "24px";
    el.style.top = "24px";               // так же, как при загрузке страницы
    var base = el.getBoundingClientRect();
    return {
      x: Math.round(keepL - base.left),
      y: Math.round(keepT - base.top),
      refW: Math.round(host.clientWidth),
    };
  }

  var _guides = null;
  function guideLayer() {
    if (!_guides) { _guides = document.createElement("div"); _guides.className = "staw-ui staw-guides"; document.body.appendChild(_guides); }
    return _guides;
  }
  function clearGuides() { if (_guides) _guides.textContent = ""; }
  function drawGuide(vertical, at, from, to) {
    var g = document.createElement("div"); g.className = "staw-ui staw-guide";
    if (vertical) { g.style.left = at + "px"; g.style.top = from + "px"; g.style.width = "1px"; g.style.height = (to - from) + "px"; }
    else { g.style.top = at + "px"; g.style.left = from + "px"; g.style.height = "1px"; g.style.width = (to - from) + "px"; }
    guideLayer().appendChild(g);
  }
  var SNAP = 6, DRAG_THRESH = 3, mv = null;
  function moveContainer(el) {
    return el.closest("section,[data-sid],[data-hideable],[data-edit-bg],.eco-cover,.eco-card,main,footer,header") || el.parentElement || el;
  }
  function collectTargets(movingEl, container) {
    var xs = [], ys = [];
    function addRect(r) {
      xs.push({ p: r.left, a: r.top, b: r.bottom }, { p: (r.left + r.right) / 2, a: r.top, b: r.bottom }, { p: r.right, a: r.top, b: r.bottom });
      ys.push({ p: r.top, a: r.left, b: r.right }, { p: (r.top + r.bottom) / 2, a: r.left, b: r.right }, { p: r.bottom, a: r.left, b: r.right });
    }
    addRect(container.getBoundingClientRect());
    container.querySelectorAll("[data-edit]").forEach(function (el) {
      if (el === movingEl || el.contains(movingEl) || movingEl.contains(el)) return;
      addRect(el.getBoundingClientRect());
    });
    return { xs: xs, ys: ys };
  }
  function bestSnap(lines, targets) {
    var best = null;
    targets.forEach(function (t) {
      lines.forEach(function (ml) {
        var d = Math.abs(ml - t.p);
        if (d <= SNAP && (!best || d < best.d)) best = { d: d, delta: t.p - ml, t: t };
      });
    });
    return best;
  }
  document.addEventListener("pointerdown", function (e) {
    if (e.button != null && e.button !== 0) return;
    if (!document.documentElement.classList.contains("staw-edit")) return;
    if (e.target.closest(".staw-ui, .staw-tools, input, textarea, select")) return;
    var el = e.target.closest("[data-edit]");
    if (!el || el.hasAttribute("data-edit-ph")) return;
    var key = el.getAttribute("data-edit");
    if (!key || !safeId(key)) return;
    if (e.altKey) { // Alt+клик — сброс позиции
      if (POS[key] && (POS[key].x || POS[key].y)) { applyPosByKey(key, "0,0"); draft("pos." + key, "0,0"); }
      justDragged = true; e.preventDefault(); return;
    }
    // На узкой ширине сдвиги не применяются — ни в предпросмотре, ни на телефоне.
    // Тащить молча нельзя: владелец подвинет надпись, опубликует, а на сайте
    // ничего не изменится.
    if (window.__stawPos && window.__stawPos.narrow && window.__stawPos.narrow()) {
      narrowHint();
      e.preventDefault();
      return;
    }
    var cur = POS[key] || { x: 0, y: 0 };
    mv = { el: el, key: key, sx: e.clientX, sy: e.clientY, bx: cur.x, by: cur.y,
           container: moveContainer(el), moved: false, targets: null, cx: cur.x, cy: cur.y };
    e.preventDefault(); // не даём стартовать нативный drag предков/картинок
  }, true);
  document.addEventListener("pointermove", function (e) {
    if (!mv) return;
    var ddx = e.clientX - mv.sx, ddy = e.clientY - mv.sy;
    if (!mv.moved) {
      if (Math.abs(ddx) < DRAG_THRESH && Math.abs(ddy) < DRAG_THRESH) return;
      mv.moved = true;
      document.documentElement.classList.add("staw-moving");
      mv.targets = collectTargets(mv.el, mv.container);
    }
    var nx = mv.bx + ddx, ny = mv.by + ddy;
    mv.el.style.translate = nx + "px " + ny + "px";
    var r = mv.el.getBoundingClientRect();
    var bx = bestSnap([r.left, (r.left + r.right) / 2, r.right], mv.targets.xs);
    var by = bestSnap([r.top, (r.top + r.bottom) / 2, r.bottom], mv.targets.ys);
    if (bx) nx += bx.delta;
    if (by) ny += by.delta;
    mv.el.style.translate = nx + "px " + ny + "px";
    mv.cx = nx; mv.cy = ny;
    clearGuides();
    var rr = mv.el.getBoundingClientRect();
    if (bx) drawGuide(true, bx.t.p, Math.min(bx.t.a, rr.top), Math.max(bx.t.b, rr.bottom));
    if (by) drawGuide(false, by.t.p, Math.min(by.t.a, rr.left), Math.max(by.t.b, rr.right));
  }, true);
  document.addEventListener("pointerup", function () {
    if (!mv) return;
    var m = mv; mv = null;
    clearGuides();
    document.documentElement.classList.remove("staw-moving");
    if (m.moved) {
      // Запоминаем ширину контейнера: на другой ширине окна сдвиг пересчитается
      // пропорционально, а не уедет в сторону.
      var lim = posLimits(m.el);
      var refW = lim ? Math.round(lim.w) : 0;
      var x = Math.round(m.cx), y = Math.round(m.cy);
      // Добавленную надпись перевешиваем в ту секцию, над которой её отпустили.
      if (m.el.classList.contains("staw-newlabel")) {
        var re = rehomeLabel(m.el);
        if (re) {
          x = re.x; y = re.y; refW = re.refW;
          m.el.style.translate = x + "px " + y + "px";
          draft("xlabels", JSON.stringify(allLabels()));
        }
      }
      POS[m.key] = { x: x, y: y, refW: refW };
      draft("pos." + m.key, x + "," + y + (refW ? "," + refW : ""));
      justDragged = true; // подавить последующий click-правку
    }
  }, true);
  (function () {
    var s = document.createElement("style");
    s.textContent =
      "html.staw-edit [data-edit]:not([data-edit-ph]){cursor:grab}" +
      "html.staw-moving,html.staw-moving *{cursor:grabbing!important;user-select:none!important}" +
      ".staw-guides{position:fixed;inset:0;z-index:2147483000;pointer-events:none}" +
      ".staw-guide{position:absolute;background:#ff2d78;box-shadow:0 0 0 .5px rgba(255,45,120,.4)}" +
      // Пустая надпись (текст удалён) не пропадает: в Конструкторе показываем
      // кликабельный плейсхолдер «+ надпись» — клик открывает правку, вписываешь заново.
      "html.staw-edit [data-edit]:not([data-edit-ph]):empty{display:inline-block;min-width:118px;" +
      "min-height:1.25em;padding:2px 10px;outline:1px dashed rgba(10,132,255,.8);outline-offset:2px;" +
      "border-radius:6px;vertical-align:middle}" +
      "html.staw-edit [data-edit]:not([data-edit-ph]):empty::before{content:'+ надпись';" +
      "color:#0a84ff;font:600 12px/1.25 system-ui,-apple-system,sans-serif;white-space:nowrap;opacity:.85}" +
      // Добавленная надпись: наследует цвет секции (видна и на тёмном, и на светлом фоне).
      ".staw-newlabel{font-weight:600;font-size:18px;line-height:1.3;color:inherit;max-width:82%}" +
      // Плавающая кнопка «➕ Надпись» в превью (только в Конструкторе).
      ".staw-addlabel{position:fixed;left:14px;bottom:14px;z-index:2147483001;background:#0a84ff;" +
      "color:#fff;border:0;border-radius:999px;padding:10px 16px;font:600 13px system-ui,-apple-system,sans-serif;" +
      "cursor:pointer;box-shadow:0 6px 18px rgba(10,132,255,.4)}" +
      ".staw-addlabel:hover{background:#0060df}" +
      // Крестик удаления текста в углу рамки надписи (по наведению).
      ".staw-delx{position:fixed;z-index:2147483002;display:none;width:20px;height:20px;padding:0;" +
      "align-items:center;justify-content:center;border-radius:50%;background:#ef4444;color:#fff;" +
      "border:2px solid #fff;font:700 11px/1 system-ui,-apple-system,sans-serif;cursor:pointer;" +
      "box-shadow:0 2px 8px rgba(0,0,0,.35)}" +
      ".staw-delx:hover{background:#dc2626}";
    document.documentElement.appendChild(s);
  })();
  (function () {
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "staw-ui staw-addlabel"; btn.draggable = false;
    btn.textContent = "➕ Надпись";
    btn.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); addLabelToView(); });
    function mount() { if (document.body) document.body.appendChild(btn); }
    if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
  })();
  // ── Крестик ✕ удаления текста в углу каждой надписи (по наведению) ──
  var _delx = null, _delxTarget = null, _delxTimer = null;
  function hideDelx() { if (_delx) _delx.style.display = "none"; _delxTarget = null; }
  function delxBtn() {
    if (_delx) return _delx;
    _delx = document.createElement("button");
    _delx.type = "button"; _delx.className = "staw-ui staw-delx"; _delx.textContent = "✕";
    _delx.title = "Удалить текст";
    _delx.addEventListener("mouseenter", function () { if (_delxTimer) clearTimeout(_delxTimer); });
    _delx.addEventListener("mouseleave", function () { _delxTimer = setTimeout(hideDelx, 220); });
    _delx.addEventListener("click", function (e) {
      e.preventDefault(); e.stopPropagation();
      var el = _delxTarget; hideDelx();
      if (!el) return;
      if (el.classList.contains("staw-newlabel")) { removeExtra(el); return; } // добавленную — совсем
      var key = el.getAttribute("data-edit");
      if (!key) return;
      el.textContent = "";       // обычную — очищаем (покажется «+ надпись», можно вернуть)
      draft(key, "");
      justDragged = true;        // не открывать правку от возможного click
    });
    if (document.body) document.body.appendChild(_delx);
    return _delx;
  }
  function showDelxFor(el) {
    var r = el.getBoundingClientRect();
    var b = delxBtn();
    b.style.display = "flex";
    b.style.left = Math.round(r.right - 9) + "px";
    b.style.top = Math.round(r.top - 9) + "px";
    _delxTarget = el;
  }
  document.addEventListener("mouseover", function (e) {
    if (!document.documentElement.classList.contains("staw-edit")) return;
    if (e.target.closest(".staw-ui, .staw-tools, input, textarea, select")) return;
    var el = e.target.closest("[data-edit]:not([data-edit-ph])");
    if (el) { if (_delxTimer) clearTimeout(_delxTimer); showDelxFor(el); }
  }, true);
  document.addEventListener("mouseout", function (e) {
    if (!_delxTarget) return;
    var to = e.relatedTarget;
    if (to && to.closest && (to === _delx || to.closest(".staw-delx") || to.closest("[data-edit]") === _delxTarget)) return;
    if (_delxTimer) clearTimeout(_delxTimer);
    _delxTimer = setTimeout(hideDelx, 220);
  }, true);

  // ── Применить черновик от родителя ──
  function reorderChildren(container, order) {
    if (!container || !Array.isArray(order)) return;
    var byId = {}, kids = [].slice.call(container.children);
    kids.forEach(function (ch) { var s = ch.getAttribute && ch.getAttribute("data-sid"); if (s) byId[s] = ch; });
    order.forEach(function (sid) { if (byId[sid]) { container.appendChild(byId[sid]); delete byId[sid]; } });
    kids.forEach(function (ch) { var s = ch.getAttribute && ch.getAttribute("data-sid"); if (s && byId[s]) container.appendChild(ch); });
    var tile = addTileOf(container); if (tile) container.appendChild(tile); // «Добавить» снова в конец
  }
  function materialize(group, val) {
    if (!safeId(group)) return;
    var extras; try { extras = JSON.parse(val); } catch (e) { return; }
    if (!Array.isArray(extras)) return;
    var tpl = templateFor(group), container = document.querySelector('[data-sortable="' + group + '"]');
    if (!tpl || !container || !tpl.content || !tpl.content.firstElementChild) return;
    extras.forEach(function (sid) {
      if (!safeId(sid) || container.querySelector('[data-sid="' + sid + '"]')) return;
      var node = tpl.content.firstElementChild.cloneNode(true);
      replaceTokens(node, sid); node.setAttribute("data-extra", "1");
      var tile = addTileOf(container);
      if (tile) container.insertBefore(node, tile); else container.appendChild(node);
      markDraggable(); initHideOn(node);
    });
  }
  // ── Добавление новых надписей: «➕ Надпись» создаёт надпись в видимой секции,
  // дальше — правка (клик), перемещение (drag), удаление («Удалить ✕»). Список всех
  // добавленных надписей хранится в одном ключе xlabels = [{id, c}] (c — id секции). ──
  function labelContainerKey(el) { var s = el.closest("section[id]"); return s ? s.id : "main"; }
  function sectionForKey(key) { return key === "main" ? (document.querySelector("main") || document.body) : document.getElementById(key); }
  function allLabels() {
    return [].map.call(document.querySelectorAll(".staw-newlabel"), function (el) {
      return { id: el.getAttribute("data-edit").slice(3), c: labelContainerKey(el) };
    });
  }
  function makeLabelEl(sid) {
    var el = document.createElement("div");
    el.className = "staw-newlabel";
    el.setAttribute("data-edit", "xl." + sid);
    el.setAttribute("data-hideable", "xl." + sid);
    el.setAttribute("data-extra", "1");
    el.textContent = "Новая надпись";
    el.style.position = "absolute"; el.style.left = "24px"; el.style.zIndex = "20";
    return el;
  }
  function materializeLabels(list) {
    (list || []).forEach(function (it) {
      if (!it || !it.id || document.querySelector('[data-edit="xl.' + it.id + '"]')) return;
      var section = sectionForKey(it.c || "main");
      if (!section) return;
      if (getComputedStyle(section).position === "static") section.style.position = "relative";
      var el = makeLabelEl(it.id); el.style.top = "24px";
      section.appendChild(el);
      if (typeof initHideOn === "function") initHideOn(el);
    });
  }
  function addLabelToView() {
    var vh = window.innerHeight, best = null, bd = 1e9;
    [].forEach.call(document.querySelectorAll("section[id]"), function (s) {
      var r = s.getBoundingClientRect();
      if (r.bottom < 40 || r.top > vh - 40) return;
      var d = Math.abs((r.top + r.bottom) / 2 - vh / 2);
      if (d < bd) { bd = d; best = s; }
    });
    var key = (best && best.id) ? best.id : "main";
    var section = sectionForKey(key);
    if (getComputedStyle(section).position === "static") section.style.position = "relative";
    var sid = makeSid();
    var el = makeLabelEl(sid);
    var sr = section.getBoundingClientRect();
    el.style.top = Math.max(12, Math.round(vh / 2 - sr.top)) + "px"; // на уровне центра экрана
    section.appendChild(el);
    initHideOn(el);
    draft("xlabels", JSON.stringify(allLabels()));
    draft("xl." + sid, "Новая надпись"); // дефолтный текст → в черновик/публикацию
  }

  function applyContent(key, value) {
    // Любая правка, меняющая геометрию текста (сам текст, шрифт, тень, размеры),
    // требует пересчёта позиции — иначе в правке видно одно, а после перезагрузки
    // другое. Пересчёт ставим в начало: ветки ниже завершаются return'ом.
    if (/^(width|minh|fontsize|font|shadow)\./.test(key)) {
      var _gk = key.slice(key.indexOf(".") + 1);
      setTimeout(function () { regeometry(_gk); }, 0);
    } else if (key.indexOf(".") === -1 || /^[\w.]+$/.test(key)) {
      setTimeout(function () { regeometry(key); }, 0);   // сменился сам текст
    }
    // Отражаем черновик и в STAW_CONTENT — чтобы компоненты, которые строятся из JS
    // позже (экран входа/регистрации), показывали правку/удаление при пересборке.
    try { if (window.STAW_CONTENT && typeof value === "string") window.STAW_CONTENT[key] = { value: value }; } catch (e) {}
    if (key === "xlabels") { try { materializeLabels(JSON.parse(value || "[]")); } catch (e) {} return; }
    if (key.indexOf("extra.") === 0) { materialize(key.slice(6), value); return; }
    if (key.indexOf("order.") === 0) {
      var g = key.slice(6); if (!safeId(g) || !value) return;
      var order; try { order = JSON.parse(value); } catch (e) { return; }
      reorderChildren(document.querySelector('[data-sortable="' + g + '"]'), order); return;
    }
    if (key.indexOf("hidden.") === 0) {
      var hk = key.slice(7); if (!safeId(hk)) return;
      var hide = value === "1";
      document.querySelectorAll('[data-hideable="' + hk + '"]').forEach(function (el) { el.classList.toggle("staw-cms-hidden", hide); });
      updateHideBtn(hk); return;
    }
    if (key.indexOf("pos.") === 0) { var pk = key.slice(4); if (safeId(pk)) applyPosByKey(pk, value); return; }
    if (key.indexOf("align.") === 0) { var ak = key.slice(6); if (safeId(ak)) applyAlignLocal(document.querySelector('[data-align="' + ak + '"]'), value); return; }
    if (key.indexOf("anim.") === 0) { var nk = key.slice(5); if (safeId(nk)) applyAnimLocal(nk, value); return; }
    if (key.indexOf("size.") === 0) { var zk = key.slice(5); if (safeId(zk)) document.querySelectorAll('[data-hideable="' + zk + '"]').forEach(function (el) { el.classList.toggle("staw-w-wide", value === "wide"); }); return; }
    if (key.indexOf("focal.") === 0) { var fk = key.slice(6); if (safeId(fk)) applyImgStyle(fk, "focal", value); return; }
    if (key.indexOf("fit.") === 0) { var itk = key.slice(4); if (safeId(itk)) applyImgStyle(itk, "fit", value); return; }
    if (key.indexOf("bgfocal.") === 0) { setBgField(key.slice(8), "_bgFocal", value); return; }
    if (key.indexOf("bgzoom.") === 0) { setBgField(key.slice(7), "_bgZoom", value); return; }
    if (key.indexOf("bgfit.") === 0) { setBgField(key.slice(6), "_bgFit", value); return; }
    if (key.indexOf("bgvid.") === 0) { setBgField(key.slice(6), "_bgVid", value); return; }
    if (key.indexOf("bgoff.") === 0) { setBgField(key.slice(6), "_bgOff", value); return; }
    if (key.indexOf("bgfade.") === 0) { setBgField(key.slice(7), "_bgFade", value); return; }
    if (key.indexOf("bgloop.") === 0) { setBgField(key.slice(7), "_bgLoop", value); return; }
    if (key.indexOf("color.") === 0) { var ck = key.slice(6); if (safeId(ck)) applyColorLocal(ck, value); return; }
    if (key.indexOf("fontsize.") === 0) { var zk2 = key.slice(9); if (safeId(zk2)) applyFontSizeLocal(zk2, value); return; }
    if (key.indexOf("font.") === 0) { var fk = key.slice(5); if (safeId(fk)) applyFontLocal(fk, value); return; }
    if (key.indexOf("shadow.") === 0) { var shk = key.slice(7); if (safeId(shk)) applyShadowLocal(shk, value); return; }
    if (key.indexOf("talign.") === 0) { var ak = key.slice(7); if (safeId(ak)) applyTextAlignLocal(ak, value); return; }
    // Ширина и высота рамки — той же функцией, что и на сайте.
    if (key.indexOf("width.") === 0) { var wk = key.slice(6); if (safeId(wk) && window.__stawBox) window.__stawBox(wk, "width", value); return; }
    if (key.indexOf("minh.") === 0) { var hk = key.slice(5); if (safeId(hk) && window.__stawBox) window.__stawBox(hk, "minHeight", value); return; }
    if (!safeId(key)) return;
    if (typeof value === "string") {
      document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) { el.textContent = value; });
      document.querySelectorAll('[data-edit-ph="' + key + '"]').forEach(function (el) { el.setAttribute("placeholder", value); });
    }
  }

  function cardById(id) {
    var cards = document.querySelectorAll(".product-card");
    for (var i = 0; i < cards.length; i++) if (cards[i].getAttribute("data-id") === id) return cards[i];
    return null;
  }
  function fmtPrice(v) { return new Intl.NumberFormat("ru-RU").format(Math.round(Number(v))) + " ₽"; }
  function applyCardFields(card, f) {
    if (f.price != null) { var pe = card.querySelector(".product-price"); if (pe) pe.textContent = fmtPrice(f.price); }
    if ("inStock" in f) {
      var se = card.querySelector(".product-stock");
      if (se) { se.textContent = f.inStock ? "В наличии" : "Скоро в продаже"; se.classList.toggle("product-stock--soon", !f.inStock); }
    }
  }

  window.addEventListener("message", function (e) {
    if (e.origin !== CONSOLE_ORIGIN) return;   // команды принимаем только от своего конструктора
    var d = e.data || {};
    if (d.source !== "staw-console") return;
    if (d.type === "reload") { location.reload(); return; }
    if (d.type === "addLabel") { try { addLabelToView(); } catch (e) {} return; }
    // Экран входа/регистрации (строится из JS): консоль просит открыть/закрыть/
    // переключить его — показываем НА МЕСТЕ, как на живом сайте.
    if (d.type === "authScreen") {
      try {
        if (!window.MATA_AUTH) return;
        if (d.op === "close") { window.MATA_AUTH.close(); return; }
        window.MATA_AUTH.open(d.mode === "register" ? "register" : "login");
        // Модалка строится из JS уже после инициализации редактора — до-навешиваем
        // на её элементы кнопки «🖼 Фон» (панель Вход/Регистрация) и drag/фото.
        setTimeout(function () { try { initBg(); markDraggable(); } catch (e) {} }, 60);
      } catch (e) {}
      return;
    }
    if (d.type === "setContent" && d.key) { applyContent(d.key, d.value); return; }
    if (d.type === "setOrder" && d.order && d.order.length) {
      var g = document.querySelector("[data-product-grid]");
      if (g) d.order.forEach(function (id) { var c = cardById(id); if (c) g.appendChild(c); });
      return;
    }
    if (d.type === "updateCard" && d.id && d.fields) { var card = cardById(d.id); if (card) applyCardFields(card, d.fields); return; }
    // ВАЖНО: пустой адрес — это «Удалить фон», а не «нечего делать». Пока условие
    // требовало непустой d.url, команда очистки молча терялась и фон оставался.
    if (d.type === "setImage" && d.key) {
      var url = typeof d.url === "string" ? d.url : "";
      if (d.key.indexOf("bg.") === 0) { setBgImg(d.key.slice(3), url); return; }
      document.querySelectorAll('[data-edit-img="' + d.key + '"]').forEach(function (el) {
        if (el.tagName === "IMG") {
          // Пустой src перезагрузил бы страницу как картинку — ставим прозрачную точку.
          el.src = url || "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
        } else {
          el.style.backgroundImage = url ? "url('" + url + "')" : "";
        }
      });
    }
  });

  // initAlign() убран: стрелки выравнивания больше не нужны — расположение задаётся
  // перетаскиванием (drag). Опубликованные align.* если и есть — применяются пассивно.
  markDraggable(); initHide(); initAdders(); initBg();
  var grid = document.querySelector("[data-product-grid]");
  if (grid && window.MutationObserver) new MutationObserver(markDraggable).observe(grid, { childList: true });
  // Промо-стрип рендерится promo.js асинхронно — перематить баннеры после наполнения.
  var track = document.querySelector("[data-promo-track]");
  if (track && window.MutationObserver) new MutationObserver(markDraggable).observe(track, { childList: true });

  var readySent = false;
  function fireReady() { if (readySent) return; readySent = true; send({ type: "ready", platform: PLATFORM }); }
  window.addEventListener("staw-content-applied", fireReady);
  setTimeout(fireReady, 1600);
})();
