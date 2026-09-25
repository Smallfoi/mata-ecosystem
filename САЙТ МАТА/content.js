/**
 * Мини-CMS: сайт читает редактируемый контент из общего бэкенда (/site/content)
 * и подставляет его в элементы. Всё это задаёт владелец в «Конструкторе».
 * Ключи:
 *   - data-edit / data-edit-img → текст / фото;
 *   - order.<group>   → порядок карточек в [data-sortable="<group>"];
 *   - hidden.<key>    → скрытые блоки [data-hideable="<key>"] ("1");
 *   - extra.<group>   → ДОБАВЛЕННЫЕ блоки (репитеры): JSON-массив новых sid,
 *                       каждый клонируется из <template data-block-template="<group>">;
 *   - align.<key>     → выравнивание группы [data-align="<key>"] (left/center/right);
 *   - anim.<key>      → анимация блока [data-hideable="<key>"] (fade-up/…).
 * Нет контента — остаётся HTML по умолчанию. Офлайн/нет API — сайт не ломается.
 *
 * В режиме правки (?edit=1) скрытые блоки не убираются, а приглушаются (editor.js
 * покажет кнопку «Вернуть»). Порядок/тексты/фото/блоки применяются как база, поверх
 * которой editor.js кладёт черновик; чтобы не затереть — по событию staw-content-applied.
 */
(function () {
  "use strict";

  // Конструктор держит сайт в iframe и не может прочитать его адрес — другой
  // origin. Поэтому страница сама сообщает, где она: это нужно, чтобы
  // переключение «Смотрим ⇄ Редактируем» осталось на той же странице.
  if (window.parent !== window) {
    try {
      window.parent.postMessage(
        { source: "staw-site", type: "path", path: location.pathname },
        "*"
      );
    } catch (e) {}
  }
  var host = location.hostname;
  var isDev = host === "localhost" || host === "127.0.0.1" || host === "";
  var PROD_API = "https://api.mata-club.ru/v1";
  var API =
    (typeof window !== "undefined" && window.STAW_API_BASE) ||
    (isDev ? "http://127.0.0.1:8000/v1" : PROD_API);
  var ORIGIN = API.replace(/\/v1\/?$/, "");
  var EDIT = new URLSearchParams(location.search).get("edit") === "1";

  function mediaUrl(u) { return !u ? "" : (u.indexOf("http") === 0 ? u : ORIGIN + u); }
  function safeId(s) { return typeof s === "string" && /^[\w.-]+$/.test(s); }
  function parseArr(v) { try { var a = JSON.parse(v); return Array.isArray(a) ? a : null; } catch (e) { return null; } }

  // ── Анимации: CSS-пресеты (инъекция один раз; на живом сайте эффекта нет, пока не задан anim.<key>) ──
  // Удалённая владельцем надпись убирается из потока целиком: иначе на её месте
  // остаётся пустая строка с отступами.
  function injectErasedCss() {
    if (document.getElementById("staw-erased-css")) return;
    var s = document.createElement("style");
    s.id = "staw-erased-css";
    s.textContent = ".staw-erased{display:none!important}";
    (document.head || document.documentElement).appendChild(s);
  }

  function injectAnimCss() {
    injectErasedCss();
    injectLabelCss();
    if (document.getElementById("staw-anim-css")) return;
    var st = document.createElement("style");
    st.id = "staw-anim-css";
    st.textContent =
      "@keyframes staw-fu{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:none}}" +
      ".staw-anim-fade-up{animation:staw-fu .7s ease both}" +
      "@keyframes staw-fi{from{opacity:0}to{opacity:1}}" +
      ".staw-anim-fade-in{animation:staw-fi .9s ease both}" +
      "@keyframes staw-sl{from{opacity:0;transform:translateX(-40px)}to{opacity:1;transform:none}}" +
      ".staw-anim-slide-left{animation:staw-sl .7s ease both}" +
      "@keyframes staw-sr{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:none}}" +
      ".staw-anim-slide-right{animation:staw-sr .7s ease both}" +
      "@keyframes staw-zm{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:none}}" +
      ".staw-anim-zoom{animation:staw-zm .7s ease both}" +
      "@keyframes staw-pl{0%,100%{transform:scale(1)}50%{transform:scale(1.04)}}" +
      ".staw-anim-pulse{animation:staw-pl 1.8s ease-in-out infinite}" +
      // Ширина блока: «шире» = занять 2 колонки грид-сетки (в 1-колоночных секциях — без эффекта).
      ".staw-w-wide{grid-column:span 2}" +
      // Фон блока: слой видео (за контентом) + затемнение для читаемости; контент поднимаем над видео.
      // position:relative только когда включён видео-фон (staw-bg-on) — не трогаем верстку остальных секций.
      "[data-edit-bg].staw-bg-on{position:relative}" +
      ".staw-bg-layer{position:absolute;inset:0;z-index:0;overflow:hidden;pointer-events:none;border-radius:inherit}" +
      ".staw-bg-layer video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .6s ease}" +
      ".staw-bg-layer::after{content:'';position:absolute;inset:0;background:linear-gradient(rgba(0,0,0,.15),rgba(0,0,0,.5))}" +
      // Пока видео грузится — мягкий бегущий «шиммер», чтобы место не выглядело пустым.
      ".staw-bg-layer.staw-bg-loading::before{content:'';position:absolute;inset:0;z-index:1;background:linear-gradient(110deg,rgba(255,255,255,.03) 8%,rgba(255,255,255,.10) 18%,rgba(255,255,255,.03) 33%);background-size:220% 100%;animation:staw-bg-shimmer 1.25s linear infinite}" +
      "@keyframes staw-bg-shimmer{0%{background-position:220% 0}100%{background-position:-120% 0}}" +
      "@media (prefers-reduced-motion: reduce){.staw-bg-layer.staw-bg-loading::before{animation:none}}" +
      "[data-edit-bg].staw-bg-on>:not(.staw-bg-layer){position:relative;z-index:1}" +
      // Исключение: НАМЕРЕННО абсолютные декоративные слои (бегущая строка «МАТА») НЕ
      // переводим в relative — иначе они начинают занимать место в grid и высота секции
      // растёт + перекрывает текст (баг «видео на motion → текст исчезает + высота»).
      "[data-edit-bg].staw-bg-on>.brand-motion-word{position:absolute!important}";
    (document.head || document.documentElement).appendChild(st);
  }

  // ── Фон блока: фото (с затемнением) / видео (URL) / убрать (вернуть градиент из CSS) ──
  // Фоновое видео. Флаги (тумблеры в «Конструкторе», по умолчанию ВКЛ):
  //  fade     — плавное появление (opacity 0→1, «свечение»); иначе мгновенно;
  //  seamless — бесшовная петля (два видео с кроссфейдом, без скачка); иначе обычный loop.
  //  poster   — URL картинки-постера (первый кадр): виден мгновенно, видео сменит его
  //             нативно по готовности; если пусто — вместо постера шиммер-загрузка.
  function setupBgVideo(layer, src, fit, focal, fade, seamless, poster) {
    var need = seamless ? 2 : 1;
    var vs = layer.querySelectorAll("video");
    var fresh = vs.length !== need;
    if (fresh) {
      layer.textContent = "";
      for (var i = 0; i < need; i++) {
        var v = document.createElement("video");
        v.muted = true; v.defaultMuted = true;
        v.setAttribute("muted", ""); v.setAttribute("playsinline", ""); v.setAttribute("preload", "auto");
        // Нативный loop ВСЕГДА — страховка от «зависло на последнем кадре и стало фото»
        // (даже в seamless-режиме, если кроссфейд-переключение вдруг не сработает).
        v.loop = true; v.setAttribute("loop", "");
        layer.appendChild(v);
      }
      vs = layer.querySelectorAll("video");
    }
    var a = vs[0], b = vs[1] || null;
    var newSrc = a.getAttribute("src") !== src;
    if (newSrc) { a.setAttribute("src", src); if (b) b.setAttribute("src", src); }
    [a, b].forEach(function (v) {
      if (!v) return;
      v.style.objectFit = fit; v.style.objectPosition = focal;
      if (poster) v.setAttribute("poster", poster); else v.removeAttribute("poster");
    });
    if (fresh || newSrc) {
      layer._active = a;
      if (poster) {
        // Вариант «постер-кадр»: картинка видна мгновенно (нативный poster видео), сам
        // ролик сменит её по готовности. Шиммер и fade-с-нуля не нужны — без пустоты.
        layer.classList.remove("staw-bg-loading");
        a.style.transition = "none";
        a.style.opacity = "1";
      } else {
        // Постера нет — индикатор загрузки: шиммер, пока не готов первый кадр видео.
        layer.classList.add("staw-bg-loading");
        var clearLoading = function () { layer.classList.remove("staw-bg-loading"); };
        if (a.readyState >= 2) clearLoading();
        else { a.addEventListener("loadeddata", clearLoading, { once: true }); a.addEventListener("canplay", clearLoading, { once: true }); }
        a.style.transition = fade ? "opacity .6s ease" : "none";
        a.style.opacity = fade ? "0" : "1";
        if (fade && !a._faded) {
          a._faded = 1;
          var showA = function () { a.style.opacity = "1"; };
          // Показываем по ПЕРВОМУ КАДРУ (loadeddata) — раньше всего и не зависит от autoplay.
          if (a.readyState >= 2) showA();
          else { a.addEventListener("loadeddata", showA, { once: true }); a.addEventListener("canplay", showA, { once: true }); }
        }
      }
      if (b) { b.style.transition = fade ? "opacity .6s ease" : "none"; b.style.opacity = "0"; try { b.pause(); } catch (e) {} }
      if (seamless && b) {
        var XF = 0.55; // сек кроссфейда у петли
        [a, b].forEach(function (v) {
          if (v._wrap) return; v._wrap = 1;
          v.addEventListener("timeupdate", function () {
            if (v !== layer._active || !v.duration || v.duration === Infinity) return;
            if (v.currentTime >= v.duration - XF && !v._switching) {
              v._switching = 1;
              var other = (v === a) ? b : a;
              try { other.currentTime = 0; } catch (e) {}
              // Гасим текущее ТОЛЬКО когда второе реально заиграло. Если play() отклонён
              // (автоплей-политика) — не свапаем: текущее видео зациклится нативным loop,
              // и никакого «застыло в кадре» не будет. На следующем timeupdate попробуем снова.
              var swap = function () {
                layer._active = other;
                other.style.opacity = "1"; v.style.opacity = "0";
                setTimeout(function () { try { v.pause(); } catch (e) {} v._switching = 0; }, (XF + 0.12) * 1000);
              };
              var p = other.play();
              if (p && p.then) p.then(swap).catch(function () { v._switching = 0; });
              else swap();
            }
          });
        });
      }
    }
    var pp = (layer._active || a).play(); if (pp && pp.catch) pp.catch(function () {});
  }
  function bgEl(key) { return safeId(key) ? document.querySelector('[data-edit-bg="' + key + '"]') : null; }
  // Масштаб фото-фона: 1 = «Заполнить» (cover), >1 = приближение. cover×Z нельзя выразить
  // одним CSS-значением, поэтому раскладываем cover на ведущую сторону (сравнив соотношение
  // элемента и картинки) и умножаем на Z: `{100Z}% auto` или `auto {100Z}%`. Соотношение
  // картинки кэшируем на элементе (_bgNatAspect); при первой загрузке — дозагружаем и
  // переприменяем. При ресайзе ведущая сторона может смениться → пересчитываем (ниже).
  function parseZoom(v) { var z = parseFloat(v); return (z && z > 1 && z <= 6) ? z : 1; }
  function bgImgSize(el, fit, zoom) {
    if (fit === "contain") return "contain";
    if (zoom <= 1) return "cover";
    var a = el._bgNatAspect, ew = el.clientWidth, eh = el.clientHeight;
    if (!a || !ew || !eh) return "cover"; // пока не знаем соотношение — обычный cover
    var elA = ew / eh;
    return (elA >= a) ? (100 * zoom) + "% auto" : "auto " + (100 * zoom) + "%";
  }
  // Постер рядом с роликом: бэкенд кладёт первый кадр под именем `<ролик>_poster.jpg`.
  // Файла может не быть (ролик залит до этой правки) — тогда браузер просто не покажет
  // постер, и останется прежняя загрузка. Проверять существование заранее незачем.
  function posterFor(video) {
    var clean = String(video || "").split("?")[0];
    return /\.(mp4|webm|ogg|mov)$/i.test(clean)
      ? clean.replace(/\.[^.]+$/, "_poster.jpg")
      : "";
  }

  function refreshBg(el) {
    if (!el) return;
    var off = el._bgOff === "1";
    var vid = el._bgVid || "";
    var img = el._bgImg || "";
    var focal = /^\d{1,3}% \d{1,3}%$/.test(el._bgFocal || "") ? el._bgFocal : "50% 50%";
    var fit = el._bgFit === "contain" ? "contain" : "cover";
    var zoom = parseZoom(el._bgZoom);
    var layer = el.querySelector(":scope > .staw-bg-layer");
    if (!off && vid) {
      el.style.backgroundImage = ""; el.style.backgroundSize = ""; el.style.backgroundPosition = "";
      if (!layer) { layer = document.createElement("div"); layer.className = "staw-bg-layer"; el.insertBefore(layer, el.firstChild); }
      // Постер-кадр: пока ролик грузится, на его месте стоит неподвижная картинка,
      // а не мерцание (решение владельца). Берём картинку-фон блока, если её задали;
      // иначе — первый кадр, который бэкенд снял при загрузке видео и положил рядом
      // по имени `<ролик>_poster.jpg`. Нет и его (старые ролики) → прежний шиммер.
      setupBgVideo(layer, vid, fit, focal, el._bgFade !== "0", el._bgLoop !== "0",
                   img || posterFor(vid));
      el.classList.add("staw-bg-on");
    } else if (!off && img) {
      if (layer) layer.remove(); el.classList.remove("staw-bg-on");
      // Для зума нужно соотношение картинки — если ещё не знаем, дозагрузим и переприменим.
      if (zoom > 1 && fit !== "contain" && !el._bgNatAspect) {
        var probe = new Image();
        probe.onload = function () {
          if (probe.naturalWidth && probe.naturalHeight) { el._bgNatAspect = probe.naturalWidth / probe.naturalHeight; refreshBg(el); }
        };
        probe.src = img;
      }
      el.style.backgroundImage = "linear-gradient(rgba(0,0,0,.15),rgba(0,0,0,.5)), url('" + img + "')";
      el.style.backgroundSize = "cover, " + bgImgSize(el, fit, zoom);
      el.style.backgroundPosition = "center, " + focal;
      el.style.backgroundRepeat = "no-repeat";
    } else {
      if (layer) layer.remove(); el.classList.remove("staw-bg-on");
      el.style.backgroundImage = ""; el.style.backgroundSize = ""; el.style.backgroundPosition = "";
    }
  }
  // Ресайз: у зумленных фото-фонов ведущая сторона cover могла смениться (портрет↔ландшафт
  // брейкпоинты) → пересчитать background-size. Дебаунс, только по зумленным элементам.
  var bgResizeT = null;
  window.addEventListener("resize", function () {
    clearTimeout(bgResizeT);
    bgResizeT = setTimeout(function () {
      document.querySelectorAll("[data-edit-bg]").forEach(function (el) {
        if (parseZoom(el._bgZoom) > 1 && el._bgImg && el._bgFit !== "contain") refreshBg(el);
      });
    }, 150);
  });
  function setBgField(key, field, val) { var el = bgEl(key); if (!el) return; el[field] = val; refreshBg(el); }
  function setBgImg(key, imageUrl) { var el = bgEl(key); if (!el) return; el._bgImg = imageUrl ? mediaUrl(imageUrl) : ""; refreshBg(el); }

  // Точечно применить фон/видео из общего контента к элементу [data-edit-bg="key"].
  // Нужно модалкам, которые строятся из JS ПОСЛЕ загрузки контента (напр. экран входа):
  // они зовут это, когда их data-edit-bg уже в DOM. Переиспользует ту же bg-логику.
  window.STAW_applyBg = function (key) {
    var C = window.STAW_CONTENT; if (!C || !safeId(key)) return;
    var g = function (k) { return (C[k] || {}).value; };
    if (C["bgoff." + key] !== undefined) setBgField(key, "_bgOff", g("bgoff." + key));
    if (C["bgfocal." + key] !== undefined) setBgField(key, "_bgFocal", g("bgfocal." + key));
    if (C["bgzoom." + key] !== undefined) setBgField(key, "_bgZoom", g("bgzoom." + key));
    if (C["bgfit." + key] !== undefined) setBgField(key, "_bgFit", g("bgfit." + key));
    if (C["bgfade." + key] !== undefined) setBgField(key, "_bgFade", g("bgfade." + key));
    if (C["bgloop." + key] !== undefined) setBgField(key, "_bgLoop", g("bgloop." + key));
    if (C["bgvid." + key] !== undefined) setBgField(key, "_bgVid", g("bgvid." + key));
    if (C["bg." + key] !== undefined) setBgImg(key, (C["bg." + key] || {}).imageUrl);
  };

  // Прогрев: заранее (на загрузке) грузим видео экрана входа, чтобы при клике «Войти»
  // оно было готово и играло сразу. Работает при кэшируемом медиа (превью/прод).
  var _warm = {};
  function preloadVideo(url) {
    if (!url || _warm[url]) return; _warm[url] = 1;
    var pv = document.createElement("video");
    pv.muted = true; pv.setAttribute("muted", ""); pv.setAttribute("playsinline", ""); pv.setAttribute("preload", "auto");
    pv.style.cssText = "position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
    pv.src = url;
    (document.body || document.documentElement).appendChild(pv);
    try { pv.load(); } catch (e) {}
  }
  window.STAW_preloadAuthVideos = function () {
    var C = window.STAW_CONTENT; if (!C) return;
    ["bgvid.auth.panelReg", "bgvid.auth.panelLogin"].forEach(function (k) {
      var u = (C[k] || {}).value; if (u) preloadVideo(u.indexOf("http") === 0 ? u : ORIGIN + u);
    });
  };

  // ── Репитеры: клонировать добавленные блоки из <template> ──
  function replaceTokens(node, sid) {
    var all = [node].concat([].slice.call(node.querySelectorAll ? node.querySelectorAll("*") : []));
    all.forEach(function (el) {
      ["data-sid", "data-hideable", "data-edit", "data-edit-img", "data-edit-bg"].forEach(function (a) {
        var v = el.getAttribute && el.getAttribute(a);
        if (v && v.indexOf("{sid}") >= 0) el.setAttribute(a, v.replace(/\{sid\}/g, sid));
      });
    });
  }
  function materialize(group, val) {
    if (!safeId(group)) return;
    var extras = parseArr(val);
    if (!extras) return;
    var tpl = document.querySelector('template[data-block-template="' + group + '"]');
    var container = document.querySelector('[data-sortable="' + group + '"]');
    if (!tpl || !container || !tpl.content || !tpl.content.firstElementChild) return;
    extras.forEach(function (sid) {
      if (!safeId(sid)) return;
      if (container.querySelector('[data-sid="' + sid + '"]')) return; // уже есть
      var node = tpl.content.firstElementChild.cloneNode(true);
      replaceTokens(node, sid);
      node.setAttribute("data-extra", "1");
      container.appendChild(node);
    });
  }

  function reorderChildren(container, order) {
    if (!container || !Array.isArray(order)) return;
    var byId = {}, kids = [].slice.call(container.children);
    kids.forEach(function (ch) { var s = ch.getAttribute && ch.getAttribute("data-sid"); if (s) byId[s] = ch; });
    order.forEach(function (sid) { if (byId[sid]) { container.appendChild(byId[sid]); delete byId[sid]; } });
    kids.forEach(function (ch) { var s = ch.getAttribute && ch.getAttribute("data-sid"); if (s && byId[s]) container.appendChild(ch); });
  }
  function applyOrder(group, val) {
    if (!safeId(group)) return;
    var order = parseArr(val);
    if (order) reorderChildren(document.querySelector('[data-sortable="' + group + '"]'), order);
  }
  function applyHidden(key, val) {
    if (!safeId(key)) return;
    var hide = val === "1";
    document.querySelectorAll('[data-hideable="' + key + '"]').forEach(function (el) {
      if (EDIT) { el.classList.toggle("staw-cms-hidden", hide); el.style.display = ""; }
      else { el.style.display = hide ? "none" : ""; }
    });
  }
  var ALIGN = { left: "flex-start", center: "center", right: "flex-end", start: "flex-start", end: "flex-end" };
  function applyAlign(key, val) {
    if (!safeId(key)) return;
    var el = document.querySelector('[data-align="' + key + '"]');
    if (!el) return;
    var j = ALIGN[val];
    el.style.justifyContent = j || "";
    el.style.textAlign = val === "right" ? "right" : val === "center" ? "center" : val === "left" ? "left" : "";
  }
  function applyAnim(key, val) {
    if (!safeId(key)) return;
    // Анимация применяется к блокам (data-hideable), к фото (data-edit-img) И к фону (data-edit-bg).
    document.querySelectorAll('[data-hideable="' + key + '"], [data-edit-img="' + key + '"], [data-edit-bg="' + key + '"]').forEach(function (el) {
      el.className = el.className.replace(/\s*\bstaw-anim-[\w-]+/g, "").trim();
      if (val && /^[\w-]+$/.test(val) && val !== "none") el.classList.add("staw-anim-" + val);
    });
  }
  function applyTextAlign(key, value, hasOwnWidth) {
    // Выравнивание текста: слева, по центру, справа, по ширине.
    //
    // Тонкость, из-за которой это выглядело как «не работает»: у заголовка рамка
    // обтягивает сам текст (он ребёнок flex-контейнера или просто короткий), и
    // центрировать внутри неё нечего — визуально ничего не меняется. Поэтому,
    // если владелец сам не задал ширину, при выравнивании раздвигаем рамку на
    // всю ширину родителя: тогда «по центру» действительно ставит текст в центр.
    if (!safeId(key)) return;
    var v = (value || "").trim();
    if (v && ["left", "center", "right", "justify"].indexOf(v) === -1) return;
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.textAlign = v;
      if (!v) {
        if (el.dataset.stawAlignWidth) { el.style.width = ""; delete el.dataset.stawAlignWidth; }
        var box0 = el.parentElement;
        if (box0 && box0.dataset.stawAlignFlex) { box0.style.flex = ""; delete box0.dataset.stawAlignFlex; }
        return;
      }
      if (hasOwnWidth) return;                 // ширину задал владелец — не трогаем
      if (!el.style.width) {
        el.style.width = "100%";
        el.dataset.stawAlignWidth = "1";       // пометка: ширина наша, снимем вместе с выравниванием
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

  function applySize(key, val) {
    if (!safeId(key)) return;
    document.querySelectorAll('[data-hideable="' + key + '"]').forEach(function (el) {
      el.classList.toggle("staw-w-wide", val === "wide");
    });
  }
  // Фокус-область фото: object-position (какая часть фото видна). val = "x% y%".
  function applyFocal(key, val) {
    if (!safeId(key)) return;
    var ok = /^\d{1,3}% \d{1,3}%$/.test(val || "");
    document.querySelectorAll('[data-edit-img="' + key + '"]').forEach(function (el) {
      if (el.tagName === "IMG") el.style.objectPosition = ok ? val : "";
      else el.style.backgroundPosition = ok ? val : "";
    });
  }
  // Цвет текста: val = "#rrggbb"/"rgb(...)" или "" (сброс к цвету темы). Ставим и
  // webkit-text-fill-color, чтобы перебить брендовые gradient-заголовки, если они есть.
  var COLOR_OK = /^#[0-9a-fA-F]{3,8}$|^rgba?\([\d.,\s%]+\)$/;
  function applyColor(key, val) {
    if (!safeId(key)) return;
    var ok = COLOR_OK.test(val || "");
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.color = ok ? val : "";
      el.style.webkitTextFillColor = ok ? val : "";
    });
  }
  // Шрифт/размер/тень текста (правятся в конструкторе). Токен шрифта → семейство сайта.
  function stawFontFamily(t) {
    if (t === "unbounded") return "'Unbounded','Manrope','Inter',sans-serif";
    if (t === "manrope") return "'Manrope','Inter',sans-serif";
    if (t === "inter") return "'Inter','Segoe UI',Arial,sans-serif";
    return "";
  }
  function applyFont(key, val) {
    if (!safeId(key)) return;
    var f = stawFontFamily(val);
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.fontFamily = f;
      if (val) { el.dataset.stawFont = val; } else { delete el.dataset.stawFont; }
    });
  }
  function applyFontSize(key, val) {
    if (!safeId(key)) return;
    var n = parseInt(val, 10);
    // Размер из Конструктора — жёсткие пиксели, а вёрстка сайта резиновая
    // (clamp по ширине). Заголовок в 105px, поставленный на мониторе, на телефоне
    // занимал бы экран целиком. Крупные кегли на узком экране пересчитываем по
    // ширине окна, мелкие оставляем как есть — их уменьшать некуда.
    var css = "";
    if (n && n > 0) {
      css = n + "px";
      if (n > 30 && narrowScreen()) {
        css = "clamp(" + Math.round(n * 0.3) + "px, " + (n / 9).toFixed(2) + "vw, " + n + "px)";
      }
    }
    _fontVals[key] = val;
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.fontSize = css;
    });
  }
  function stawShadowCss(v) {
    var n = parseInt(v, 10) || 0;
    if (n <= 0) return "";
    var k = n / 100;
    return "0 " + (1 + 3 * k).toFixed(1) + "px " + (2 + 10 * k).toFixed(1) +
      "px rgba(0,0,0," + (0.25 + 0.5 * k).toFixed(2) + ")";
  }
  var _fontVals = {};  // key → кегль, чтобы пересчитать при смене ширины окна
  var _boxVals = {};   // "key|prop" → значение, чтобы вернуть его при расширении окна

  function applyBoxSize(key, prop, value) {
    // Размер рамки текста: ширина в процентах родителя, высота в пикселях.
    // Пустое значение — вернуться к вёрстке.
    if (!safeId(key)) return;
    var v = (value || "").trim();
    if (v && !/^\d{1,3}(\.\d+)?(%|px)$/.test(v)) return;
    _boxVals[key + "|" + prop] = v;
    // На телефоне рамку не навязываем: 17% ширины — это нормальная надпись на
    // десктопе и колонка в 60px на экране 390px. См. narrowScreen().
    if (narrowScreen()) v = "";
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style[prop] = v;
      // Строчным элементам ширина не применяется — переводим в строчно-блочный,
      // иначе растягивание визуально ничего не делает.
      if (prop === "width") {
        if (v) {
          if (getComputedStyle(el).display === "inline") el.style.display = "inline-block";
        } else if (el.style.display === "inline-block") {
          el.style.display = "";
        }
      }
    });
  }

  function applyShadow(key, val) {
    if (!safeId(key)) return;
    var css = stawShadowCss(val);
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      el.style.textShadow = css;
      if (parseInt(val, 10) > 0) { el.dataset.stawShadow = val; } else { delete el.dataset.stawShadow; }
    });
  }
  // Подгон фото: "contain" — фото целиком (не обрезается); иначе — заполнение (cover из CSS).
  function applyFit(key, val) {
    if (!safeId(key)) return;
    var contain = val === "contain";
    document.querySelectorAll('[data-edit-img="' + key + '"]').forEach(function (el) {
      if (el.tagName === "IMG") el.style.objectFit = contain ? "contain" : "";
      else el.style.backgroundSize = contain ? "contain" : "";
    });
  }

  // Позиция надписи (перемещение в «Конструкторе»).
  // Значение: "dx,dy" или "dx,dy,refW" — третье число это ширина контейнера, при
  // которой сдвиг задавали. CSS translate композится с трансформами элемента
  // (напр. центрированием watermark).
  //
  // Почему не просто пиксели. Шрифты у нас резиновые (clamp), ширины в процентах —
  // поэтому один и тот же сдвиг в пикселях на другой ширине окна ставит надпись
  // в другое место. Плюс сдвиг вверх утаскивал её за пределы секции, под шапку,
  // и верхние строки пропадали. Ниже: масштабируем по ширине контейнера,
  // ограничиваем рамками контейнера и вовсе не применяем на узких экранах.
  var POS_MIN_W = 900;   // ниже этой ширины окна правки геометрии игнорируем (телефон)
  // Одно место, которое решает «экран узкий». Правило из PITFALLS «Абсолютные
  // пиксели в правках вёрстки»: телефон переживёт отсутствие сдвига, но не
  // сломанную вёрстку. Редактор зовёт ту же функцию — в предпросмотре на узкой
  // ширине видно ровно то же, что на телефоне.
  function narrowScreen() { return window.innerWidth < POS_MIN_W; }

  // Добавленная в Конструкторе надпись стоит абсолютно и держится ТОЛЬКО на
  // сдвиге, а сдвиги на узком экране мы не применяем — надпись прилипала к углу
  // своей секции поверх другого текста. На телефоне ставим её в поток: она
  // окажется в конце своей секции — читаемая и никому не мешающая.
  function injectLabelCss() {
    if (document.getElementById("staw-xl-css")) return;
    var s = document.createElement("style");
    s.id = "staw-xl-css";
    s.textContent = "@media (max-width:" + (POS_MIN_W - 1) + "px){" +
      ".staw-newlabel{position:static!important;max-width:100%!important;" +
      // Поля как у остальных секций: в потоке надпись — прямой ребёнок секции и
      // иначе прилипает к самому краю экрана, мимо колонки текста.
      "margin:18px 0 0!important;padding:0 var(--pad-x,20px)!important;" +
      "box-sizing:border-box!important;translate:none!important}}";
    (document.head || document.documentElement).appendChild(s);
  }
  var _posVals = {};     // key → "dx,dy[,refW]", чтобы пересчитать при resize

  // Границы хода — по секции, а не по ближайшему родителю: родитель часто
  // обтягивает саму надпись, и тогда двигать было бы некуда. Тот же набор
  // селекторов, что у перетаскивания в редакторе (moveContainer).
  function posContainer(el) {
    var box = el.closest("section,[data-sid],[data-hideable],[data-edit-bg],.eco-cover,.eco-card,main,footer,header");
    if (!box || box === el) box = el.parentElement || document.body;
    while (box && box !== document.body && box.clientWidth === 0) box = box.parentElement;
    return box || document.body;
  }

  function clamp(v, lo, hi) { return lo > hi ? 0 : Math.min(hi, Math.max(lo, v)); }

  // Ставит сдвиг одному элементу. Где стоять надписи — решает владелец: он видит
  // страницу и двигает её сам. Никаких «поправок» здесь нет, иначе его правки
  // молча откатываются при каждой загрузке.
  //
  // От перекоса на других экранах защищает масштаб: сдвиг хранится вместе с
  // шириной контейнера, при которой его задали («388,-431,1905»), и здесь
  // пересчитывается пропорционально. На узком экране он уменьшается сам.
  function posPlace(el, x, y, refW) {
    // Сдвиг задан на широкой раскладке, где текст занимал другое число строк.
    // Пересчёт по ширине спасает от перекоса, но не от того, что заголовок из
    // двух строк стал пятистрочным: сдвиг вверх утаскивает его под шапку.
    if (narrowScreen()) { el.style.translate = ""; return; }
    var box = posContainer(el);
    var k = (refW && box.clientWidth) ? box.clientWidth / refW : 1;
    var nx = x * k, ny = y * k;
    el.style.translate = (nx ? nx.toFixed(1) + "px" : "0px") + " " +
                         (ny ? ny.toFixed(1) + "px" : "0px");
  }

  function applyPos(key, val) {
    if (!safeId(key)) return;
    _posVals[key] = val;
    var parts = String(val == null ? "0,0" : val).split(",");
    var x = parseFloat(parts[0]) || 0, y = parseFloat(parts[1]) || 0;
    var refW = parseFloat(parts[2]) || 0;
    document.querySelectorAll('[data-edit="' + key + '"]').forEach(function (el) {
      posPlace(el, x, y, refW);
    });
  }

  // Пересчёт после подгрузки шрифтов и при изменении размера окна: до загрузки
  // шрифта метрики текста другие, и без пересчёта надпись «прыгает» после
  // перезагрузки страницы.
  function reapplyGeometry() {
    Object.keys(_fontVals).forEach(function (k) { applyFontSize(k, _fontVals[k]); });
    Object.keys(_posVals).forEach(function (k) { applyPos(k, _posVals[k]); });
    Object.keys(_boxVals).forEach(function (k) {
      var i = k.lastIndexOf("|");
      applyBoxSize(k.slice(0, i), k.slice(i + 1), _boxVals[k]);
    });
  }
  // Пересчитываем не только после шрифтов, но и после полной загрузки страницы:
  // в момент первого применения шапка и картинки ещё не разложены, и границы
  // считаются по неготовой раскладке — надпись оставалась под шапкой.
  try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(reapplyGeometry); } catch (e) {}
  window.addEventListener("load", function () {
    reapplyGeometry();
    requestAnimationFrame(function () { requestAnimationFrame(reapplyGeometry); });
  });
  (function () {
    var t = null;
    window.addEventListener("resize", function () {
      clearTimeout(t);
      t = setTimeout(reapplyGeometry, 120);
    });
  })();

  // Режим правки переиспользует ЭТУ логику — вторая копия уже однажды разъехалась
  // с первой (см. PITFALLS про функции-двойники).
  window.__stawPos = { place: posPlace, container: posContainer, clamp: clamp, minWidth: POS_MIN_W, narrow: narrowScreen };
  // Размеры рамки текста — тоже одна реализация на сайт и на редактор.
  window.__stawBox = applyBoxSize;
  // И выравнивание: в редакторе была своя копия без проверки «ширину задал
  // владелец», из-за чего оно растягивало родителя и проценты ширины врали.
  window.__stawAlign = applyTextAlign;

  // Добавленные в «Конструкторе» надписи: воссоздаём пустые элементы в их секциях,
  // текст (xl.<sid>) и позицию (pos.xl.<sid>) заполнит основной проход apply().
  function labelSection(key) { return key === "main" ? (document.querySelector("main") || document.body) : document.getElementById(key); }
  function materializeLabels(list) {
    (list || []).forEach(function (it) {
      if (!it || !it.id || document.querySelector('[data-edit="xl.' + it.id + '"]')) return;
      var section = labelSection(it.c || "main");
      if (!section) return;
      if (getComputedStyle(section).position === "static") section.style.position = "relative";
      var el = document.createElement("div");
      el.className = "staw-newlabel";
      el.setAttribute("data-edit", "xl." + it.id);
      el.setAttribute("data-hideable", "xl." + it.id);
      el.style.cssText = "position:absolute;left:24px;top:24px;z-index:20;font-weight:600;font-size:18px;line-height:1.3;max-width:82%";
      section.appendChild(el);
    });
  }

  // Порядок применения ключей. Меньше — раньше. Правило простое: сначала то, от чего
  // зависит геометрия (текст, картинки, шрифт, размеры), и только потом то, что по этой
  // геометрии считается (выравнивание, позиция).
  function applyRank(key) {
    if (key.indexOf("pos.") === 0) return 60;        // позиция — самой последней
    if (key.indexOf("talign.") === 0) return 50;     // выравнивание — после ширины
    if (key.indexOf("width.") === 0) return 40;
    if (key.indexOf("minh.") === 0) return 40;
    if (key.indexOf("fontsize.") === 0) return 30;   // типографика меняет размеры блока
    if (key.indexOf("font.") === 0) return 30;
    if (key.indexOf("shadow.") === 0) return 30;
    if (key.indexOf("color.") === 0) return 30;
    if (key.indexOf("order.") === 0) return 20;      // перестановки и скрытия — до замеров
    if (key.indexOf("hidden.") === 0) return 20;
    if (key.indexOf("size.") === 0) return 20;
    if (key.indexOf("align.") === 0) return 20;
    if (key.indexOf("anim.") === 0) return 20;
    return 10;                                        // текст, картинки, фоны — первыми
  }

  function apply(content) {
    if (!content) return;
    // Публикуем контент глобально: модалки/элементы, которые строятся из JS позже
    // (напр. экран входа в ecosystem.js), читают переопределения отсюда.
    try { window.STAW_CONTENT = content; } catch (e) {}
    try { window.STAW_preloadAuthVideos(); } catch (e) {} // прогрев видео экрана входа
    injectAnimCss();
    // 1) сначала материализуем добавленные блоки — чтобы их ключи было куда применять
    Object.keys(content).forEach(function (k) {
      if (k.indexOf("extra.") === 0) { try { materialize(k.slice(6), (content[k] || {}).value); } catch (e) {} }
    });
    try { if (content["xlabels"]) materializeLabels(JSON.parse((content["xlabels"] || {}).value || "[]")); } catch (e) {}
    // 2) основной проход — СТРОГО по зависимостям (см. applyRank): позиция считается
    // последней, когда текст, шрифт и размеры уже встали. Иначе границы считаются по
    // чужой геометрии, и на разных загрузках страница выглядит по-разному.
    Object.keys(content).sort(function (a, b) {
      return applyRank(a) - applyRank(b);
    }).forEach(function (key) {
      try {
        var c = content[key] || {};
        if (key.indexOf("order.") === 0) { applyOrder(key.slice(6), c.value); return; }
        if (key.indexOf("hidden.") === 0) { applyHidden(key.slice(7), c.value); return; }
        if (key.indexOf("align.") === 0) { applyAlign(key.slice(6), c.value); return; }
        if (key.indexOf("anim.") === 0) { applyAnim(key.slice(5), c.value); return; }
        if (key.indexOf("size.") === 0) { applySize(key.slice(5), c.value); return; }
        if (key.indexOf("pos.") === 0) { applyPos(key.slice(4), c.value); return; }
        if (key.indexOf("focal.") === 0) { applyFocal(key.slice(6), c.value); return; }
        if (key.indexOf("fit.") === 0) { applyFit(key.slice(4), c.value); return; }
        if (key.indexOf("color.") === 0) { applyColor(key.slice(6), c.value); return; }
        if (key.indexOf("fontsize.") === 0) { applyFontSize(key.slice(9), c.value); return; }
        if (key.indexOf("font.") === 0) { applyFont(key.slice(5), c.value); return; }
        if (key.indexOf("shadow.") === 0) { applyShadow(key.slice(7), c.value); return; }
        if (key.indexOf("talign.") === 0) {
          var tk = key.slice(7);
          // Если ширина этого текста задана владельцем — выравнивание её не переопределяет.
          applyTextAlign(tk, c.value, !!(content["width." + tk] && content["width." + tk].value));
          return;
        }
        if (key.indexOf("width.") === 0) { applyBoxSize(key.slice(6), "width", c.value); return; }
        if (key.indexOf("minh.") === 0) { applyBoxSize(key.slice(5), "minHeight", c.value); return; }
        if (key.indexOf("bgfocal.") === 0) { setBgField(key.slice(8), "_bgFocal", c.value); return; }
        if (key.indexOf("bgzoom.") === 0) { setBgField(key.slice(7), "_bgZoom", c.value); return; }
        if (key.indexOf("bgfit.") === 0) { setBgField(key.slice(6), "_bgFit", c.value); return; }
        if (key.indexOf("bgvid.") === 0) { setBgField(key.slice(6), "_bgVid", c.value); return; }
        if (key.indexOf("bgoff.") === 0) { setBgField(key.slice(6), "_bgOff", c.value); return; }
        if (key.indexOf("bgfade.") === 0) { setBgField(key.slice(7), "_bgFade", c.value); return; }
        if (key.indexOf("bgloop.") === 0) { setBgField(key.slice(7), "_bgLoop", c.value); return; }
        if (key.indexOf("bg.") === 0) { setBgImg(key.slice(3), c.imageUrl); return; }
        if (key.indexOf("extra.") === 0) { return; } // уже применили выше
        if (key === "xlabels") { return; } // список надписей — материализован выше
        if (safeId(key)) {
          var texts = document.querySelectorAll('[data-edit="' + key + '"]');
          if (c.value) {
            texts.forEach(function (el) { el.textContent = c.value; el.classList.remove("staw-erased"); });
          } else if (!c.imageUrl) {
            // Пустое значение — это «владелец удалил надпись», а не «правки нет».
            // Раньше пустое просто игнорировалось, и текст из вёрстки возвращался
            // после публикации: удалить надпись было невозможно.
            // В режиме правки не скрываем — там на её месте плейсхолдер «+ надпись»,
            // чтобы текст можно было вернуть.
            texts.forEach(function (el) {
              el.textContent = "";
              if (!EDIT) el.classList.add("staw-erased");
            });
          }
        }
        if (c.imageUrl && safeId(key)) {
          var url = mediaUrl(c.imageUrl);
          document.querySelectorAll('[data-edit-img="' + key + '"]').forEach(function (el) {
            if (el.tagName === "IMG") el.src = url; else el.style.backgroundImage = "url('" + url + "')";
          });
        }
      } catch (e) { /* один плохой ключ не ломает остальные */ }
    });
  }

  function done() { try { if (EDIT) window.dispatchEvent(new Event("staw-content-applied")); } catch (e) {} }

  injectAnimCss(); // на случай пустого ответа — пресеты уже есть

  // Снять прятание, которое поставил boot.js (см. его заголовок): элементы с
  // правками скрыты, пока правки не применены — иначе видно исходную вёрстку.
  function unveil() {
    try {
      clearTimeout(window.__stawFoucTimer);
      var s = document.getElementById("staw-fouc");
      if (s) s.remove();
    } catch (e) {}
  }

  // Запомнить ответ, чтобы в следующий раз применить его до сети.
  function remember(data) {
    try { localStorage.setItem("staw-content-cache", JSON.stringify(data)); } catch (e) {}
    return data;
  }

  // 1) Сначала — прошлый ответ из памяти браузера: страница сразу получает вид,
  //    который владелец опубликовал, без ожидания сети.
  try {
    if (window.__stawCache) { apply(window.__stawCache); unveil(); }
  } catch (e) {}

  // 2) Затем — свежий ответ. Запрос стартовал ещё в <head> (boot.js), поэтому
  //    ждать конца страницы не нужно.
  var early = window.__stawEarly ||
    fetch(API + "/site/content").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });

  early
    .then(function (data) {
      if (!data) return null;
      remember(data);
      apply(data);
      return data;
    })
    .then(done)
    .catch(function () { done(); })
    .then(unveil, unveil);
})();
