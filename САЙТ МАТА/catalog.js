/**
 * Динамическая витрина: подтягивает товары из общего backend и рисует карточки
 * в существующую сетку каталога (вёрстку/классы сайта не меняем — просто наполняем).
 * Если открыть сайт с ?preview=1 — показываются и черновики (для админ-превью).
 * При недоступном API остаются статичные карточки из index.html (фолбэк).
 */
(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var PREVIEW = params.get("preview") === "1";

  // База API — как в ecosystem.js: dev (localhost) → :8000, иначе прод/override.
  var host = location.hostname;
  var isDev = host === "localhost" || host === "127.0.0.1" || host === "";
  var PROD_API = "https://api.mata-club.ru/v1";
  var API =
    (typeof window !== "undefined" && window.STAW_API_BASE) ||
    (isDev ? "http://127.0.0.1:8000/v1" : PROD_API);
  var ORIGIN = API.replace(/\/v1\/?$/, "");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function priceFmt(v) {
    return new Intl.NumberFormat("ru-RU").format(v) + " ₽";
  }
  function imgUrl(p) {
    var u = p.imageUrl || (p.imageUrls && p.imageUrls[0]) || "";
    if (!u) return "";
    if (u.indexOf("http") === 0) return u;
    return u.charAt(0) === "/" ? ORIGIN + u : ORIGIN + "/" + u;
  }

  function cardHtml(p) {
    var img = imgUrl(p);
    var cat = p.categoryId || ""; // для фильтра каталога
    var catLabel = p.categoryLabel || p.brand || "МАТА";
    var sizes = Array.isArray(p.sizes) && p.sizes.length ? p.sizes : ["S", "M", "L", "XL"];
    var colors = Array.isArray(p.colors) && p.colors.length ? p.colors : ["#2b2f36", "#8a93a3"];
    var stock = p.inStock === false ? "Скоро в продаже" : "В наличии";
    var stockCls = p.inStock === false ? " product-stock--soon" : "";
    var colorDots = colors
      .map(function (c) { return '<i style="--c:' + esc(c) + '"></i>'; })
      .join("");
    // Остаток по размерам приходит из 1С (stockBySize). Пусто — разбивки нет,
    // и тогда доступны все размеры: прятать имеющийся хуже, чем показать лишний.
    var bySize = p.stockBySize && typeof p.stockBySize === "object" ? p.stockBySize : null;
    var out = bySize
      ? sizes.filter(function (s) { return !(Number(bySize[s]) > 0); })
      : [];
    var sizeChips = sizes
      .map(function (s) {
        var gone = out.indexOf(s) !== -1;
        return '<span' + (gone ? ' class="is-out"' : "") + ">" + esc(s) + "</span>";
      })
      .join("");
    var desc = p.description || "";
    return (
      '<article class="product-card reveal" data-id="' + esc(p.id) + '" data-category="' + esc(cat) + '"' +
      ' data-name="' + esc(p.name) + '" data-price="' + Number(p.price) + '"' +
      ' data-cat="' + esc(catLabel) + '" data-img="' + esc(img) + '"' +
      ' data-sizes="' + esc(sizes.join(",")) + '" data-colors="' + esc(colors.join(",")) + '"' +
      ' data-outofstock="' + esc(out.join(",")) + '"' +
      ' data-stock="' + esc(stock) + '" data-desc="' + esc(desc) + '">' +
      '<div class="product-media" data-quick-view tabindex="0" role="button" aria-label="Подробнее: ' +
      esc(p.name) + '">' +
      (img ? '<img src="' + esc(img) + '" alt="' + esc(p.name) + '" loading="lazy" />' : "") +
      "</div>" +
      '<div class="product-info">' +
      '<p class="product-cat">' + esc(catLabel) + "</p>" +
      "<h3>" + esc(p.name) + "</h3>" +
      (Number(p.reviewCount) > 0
        ? '<div class="product-rating">★ ' + (Number(p.rating) || 0).toFixed(1) +
          ' <span>(' + Number(p.reviewCount) + ")</span></div>"
        : "") +
      '<div class="product-colors" aria-hidden="true">' + colorDots + "</div>" +
      '<div class="product-sizes" aria-hidden="true">' + sizeChips + "</div>" +
      '<div class="product-bottom">' +
      '<span class="product-price">' + priceFmt(p.price) + "</span>" +
      '<span class="product-stock' + stockCls + '">' + esc(stock) + "</span>" +
      "</div>" +
      '<button class="product-add" type="button" data-add-cart="' + esc(p.name) +
      '" data-price="' + Number(p.price) + '" data-product-id="' + esc(p.id) +
      '">В корзину</button>' +
      "</div></article>"
    );
  }

  function render(products) {
    var grid = document.querySelector("[data-product-grid]");
    if (!grid || !Array.isArray(products) || products.length === 0) return;
    grid.innerHTML = products.map(cardHtml).join("");
    // Переинициализируем интеракции (фильтр/корзина/анимации) для новых карточек.
    if (window.STAW && typeof window.STAW.onCatalogRendered === "function") {
      window.STAW.onCatalogRendered();
    }
    // Товары пришли из API → подтягиваем категории и перестраиваем фильтры под них.
    loadCategories();
  }

  // Динамические фильтры из /categories (id товара == categoryId фильтра).
  function renderFilters(categories) {
    var wrap = document.querySelector("[data-filters]");
    if (!wrap || !Array.isArray(categories) || categories.length === 0) return;
    var html = '<button class="filter is-active" type="button" data-filter="all">Все</button>';
    categories.forEach(function (c) {
      if (!c || !c.id || c.id === "all") return;
      html +=
        '<button class="filter" type="button" data-filter="' +
        esc(c.id) +
        '">' +
        esc(c.name || c.id) +
        "</button>";
    });
    wrap.innerHTML = html;
  }

  function loadCategories() {
    fetch(API + "/categories")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(renderFilters)
      .catch(function () {});
  }

  function load() {
    fetch(API + "/products?platform=site" + (PREVIEW ? "&preview=1" : ""))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(render)
      .catch(function () { /* офлайн/нет API — оставляем статичные карточки */ });
  }

  // ── Отзывы в quick-view (общий бэкенд /products/<id>/reviews) ───────────────
  // Своим кодом, не трогая разметку/скрипты сайта: подвешиваемся на открытие
  // быстрого просмотра и дорисовываем блок отзывов в модалку [data-pv-modal].
  function rvToken() {
    try { return localStorage.getItem("staw_jwt"); } catch (e) { return null; }
  }
  function rvApi(path, opts) {
    opts = opts || {};
    var headers = { "Content-Type": "application/json" };
    var t = rvToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    return fetch(API + path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.text().then(function (x) {
        var d = x ? JSON.parse(x) : null;
        if (!r.ok) throw new Error((d && d.detail) || "Ошибка");
        return d;
      });
    });
  }
  function stars(n, pick) {
    var s = "";
    for (var i = 1; i <= 5; i++)
      s += '<span class="rv-star' + (i <= n ? " on" : "") + '"' +
        (pick ? ' data-star="' + i + '"' : "") + ">★</span>";
    return s;
  }
  // /media/... → абсолютный URL (origin = API без /v1).
  function rvMedia(p) {
    if (!p) return "";
    if (/^https?:/.test(p)) return p;
    return API.replace(/\/v1\/?$/, "") + (p.charAt(0) === "/" ? p : "/" + p);
  }
  // Загрузка фото отзыва (multipart) → URL.
  function rvUploadPhoto(file) {
    var headers = {};
    var t = rvToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    var fd = new FormData();
    fd.append("image", file);
    return fetch(API + "/reviews/photo", {
      method: "POST",
      headers: headers,
      body: fd,
    }).then(function (r) {
      return r.text().then(function (x) {
        var d = x ? JSON.parse(x) : null;
        if (!r.ok) throw new Error((d && d.detail) || "Ошибка загрузки");
        return d.url;
      });
    });
  }
  function rvBox() {
    var modal = document.querySelector("[data-pv-modal]");
    if (!modal) return null;
    var box = modal.querySelector("[data-pv-reviews]");
    if (!box) {
      box = document.createElement("div");
      box.setAttribute("data-pv-reviews", "");
      box.className = "pv-reviews";
      var add = modal.querySelector("[data-pv-add]");
      if (add && add.parentNode) add.parentNode.appendChild(box);
      else modal.appendChild(box);
    }
    return box;
  }
  function rvRender(box, pid, data) {
    var list = (data && data.reviews) || [];
    var html =
      '<div class="rv-head">Отзывы' +
      (data && data.reviewCount
        ? ' <span class="rv-avg">★ ' + (Number(data.rating) || 0).toFixed(1) +
          " · " + data.reviewCount + "</span>"
        : "") +
      "</div>";
    if (!list.length)
      html +=
        '<p class="rv-empty">' +
        (data && data.canReview
          ? "Отзывов пока нет. Будьте первым!"
          : "Отзывов пока нет.") +
        "</p>";
    else
      html += list
        .map(function (r) {
          return (
            '<div class="rv-item"><div class="rv-top"><b>' + esc(r.name) +
            '</b><span class="rv-stars">' + stars(r.rating) + "</span></div>" +
            (r.text ? "<p>" + esc(r.text) + "</p>" : "") +
            (r.photos && r.photos.length
              ? '<div class="rv-shots">' +
                r.photos
                  .map(function (u) {
                    return (
                      '<a href="' + rvMedia(u) + '" target="_blank" rel="noopener">' +
                      '<img src="' + rvMedia(u) + '" alt="фото отзыва"></a>'
                    );
                  })
                  .join("") +
                "</div>"
              : "") +
            "</div>"
          );
        })
        .join("");
    if (data && data.canReview) {
      var mine = list.filter(function (r) { return r.mine; })[0];
      html +=
        '<div class="rv-form">' +
        '<div class="rv-pick" data-pick="' + (mine ? mine.rating : 5) + '">' +
        stars(mine ? mine.rating : 5, true) + "</div>" +
        '<textarea class="rv-text" placeholder="Ваш отзыв…">' +
        esc(mine ? mine.text : "") + "</textarea>" +
        '<div class="rv-photos"></div>' +
        '<label class="rv-attach">📷 Добавить фото' +
        '<input type="file" accept="image/*" class="rv-file" hidden></label>' +
        '<button class="rv-send" type="button">' +
        (mine ? "Изменить отзыв" : "Оставить отзыв") + "</button>" +
        '<p class="rv-err"></p></div>';
    }
    box.innerHTML = html;
    var form = box.querySelector(".rv-form");
    if (!form) return;
    var pick = form.querySelector(".rv-pick");
    pick.addEventListener("click", function (e) {
      var st = e.target.closest("[data-star]");
      if (!st) return;
      var v = Number(st.getAttribute("data-star"));
      pick.setAttribute("data-pick", v);
      pick.querySelectorAll(".rv-star").forEach(function (el, i) {
        el.classList.toggle("on", i < v);
      });
    });
    // Фото (до 5): загружаются сразу, в submit идут как массив URL.
    var formPhotos = mine && mine.photos ? mine.photos.slice() : [];
    var photosBox = form.querySelector(".rv-photos");
    var fileInput = form.querySelector(".rv-file");
    var attach = form.querySelector(".rv-attach");
    function renderThumbs() {
      photosBox.innerHTML = formPhotos
        .map(function (u, i) {
          return (
            '<span class="rv-thumb"><img src="' + rvMedia(u) + '">' +
            '<button type="button" data-rm="' + i + '">×</button></span>'
          );
        })
        .join("");
      photosBox.querySelectorAll("[data-rm]").forEach(function (b) {
        b.addEventListener("click", function () {
          formPhotos.splice(Number(b.getAttribute("data-rm")), 1);
          renderThumbs();
        });
      });
      if (attach) attach.style.display = formPhotos.length >= 5 ? "none" : "";
    }
    renderThumbs();
    if (fileInput)
      fileInput.addEventListener("change", function () {
        var f = fileInput.files && fileInput.files[0];
        fileInput.value = "";
        if (!f || formPhotos.length >= 5) return;
        var err = form.querySelector(".rv-err");
        err.textContent = "Загрузка фото…";
        rvUploadPhoto(f)
          .then(function (url) {
            formPhotos.push(url);
            err.textContent = "";
            renderThumbs();
          })
          .catch(function (e2) {
            err.textContent = e2.message || "Не удалось загрузить фото";
          });
      });
    form.querySelector(".rv-send").addEventListener("click", function () {
      if (!rvToken()) {
        form.querySelector(".rv-err").textContent = "Войдите, чтобы оставить отзыв";
        return;
      }
      var rating = Number(pick.getAttribute("data-pick")) || 5;
      var text = form.querySelector(".rv-text").value.trim();
      var btn = form.querySelector(".rv-send");
      btn.disabled = true;
      rvApi("/products/" + pid + "/reviews", {
        method: "POST",
        body: { rating: rating, text: text, photos: formPhotos },
      })
        .then(function () { rvLoad(box, pid); })
        .catch(function (err) {
          form.querySelector(".rv-err").textContent = err.message || "Не удалось отправить";
          btn.disabled = false;
        });
    });
  }
  function rvLoad(box, pid) {
    box.innerHTML = '<p class="rv-empty">Загрузка отзывов…</p>';
    rvApi("/products/" + pid + "/reviews")
      .then(function (d) { rvRender(box, pid, d); })
      .catch(function () { box.innerHTML = ""; });
  }
  function mountReviews() {
    document.addEventListener("click", function (e) {
      var qv = e.target.closest("[data-quick-view]");
      if (!qv) return;
      var card = qv.closest(".product-card");
      var pid = card && card.getAttribute("data-id");
      if (!pid) return;
      setTimeout(function () {
        var box = rvBox();
        if (box) rvLoad(box, pid);
      }, 40);
    });
  }
  function injectReviewStyles() {
    var css =
      ".pv-reviews{margin-top:18px;border-top:1px solid rgba(0,0,0,.1);padding-top:14px}" +
      ".rv-head{font-weight:700;margin-bottom:10px;display:flex;gap:8px;align-items:center}" +
      ".rv-avg{font-weight:600;opacity:.7;font-size:14px}" +
      ".rv-empty{opacity:.6;font-size:14px;margin:6px 0}" +
      ".rv-item{background:rgba(0,0,0,.04);border-radius:10px;padding:10px 12px;margin-bottom:8px}" +
      ".rv-top{display:flex;justify-content:space-between;align-items:center;gap:8px}" +
      ".rv-item p{margin:5px 0 0;font-size:14px;line-height:1.4}" +
      ".rv-stars,.rv-pick{color:#e8a000;letter-spacing:1px}" +
      ".rv-star{opacity:.3}.rv-star.on{opacity:1}" +
      ".rv-pick .rv-star{cursor:pointer;font-size:22px}" +
      ".rv-form{margin-top:12px}" +
      ".rv-text{width:100%;box-sizing:border-box;min-height:64px;margin:8px 0;padding:10px;" +
      "border:1px solid #d9d6cd;border-radius:10px;font:inherit;resize:vertical}" +
      ".rv-send{padding:10px 16px;border:none;border-radius:10px;background:#20252b;color:#fff;" +
      "font:inherit;font-weight:700;cursor:pointer}.rv-send[disabled]{opacity:.5}" +
      ".rv-err{color:#c0392b;font-size:13px;min-height:16px;margin:6px 0 0}" +
      ".rv-shots{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}" +
      ".rv-shots img{width:64px;height:64px;object-fit:cover;border-radius:8px;display:block}" +
      ".rv-photos{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}" +
      ".rv-thumb{position:relative;display:inline-block}" +
      ".rv-thumb img{width:60px;height:60px;object-fit:cover;border-radius:8px;display:block}" +
      ".rv-thumb button{position:absolute;top:-6px;right:-6px;width:20px;height:20px;border:none;" +
      "border-radius:50%;background:#20252b;color:#fff;font-size:13px;line-height:1;cursor:pointer}" +
      ".rv-attach{display:inline-block;cursor:pointer;font-size:13px;font-weight:600;color:#167a95;" +
      "border:1px dashed #9fc6d4;border-radius:10px;padding:8px 12px;margin:0 0 10px}" +
      ".product-rating{color:#e8a000;font-weight:700;font-size:13px;margin:2px 0 4px}" +
      ".product-rating span{color:inherit;opacity:.6;font-weight:600}";
    var s = document.createElement("style");
    s.setAttribute("data-rv-styles", "");
    s.textContent = css;
    document.head.appendChild(s);
  }

  // Блокировка скролла фона, пока открыт любой оверлей (.is-open у модалок/панелей).
  // Надёжнее CSS :has() — через MutationObserver: ловит любую модалку независимо от
  // поддержки :has() и от того, html или body является скролл-контейнером.
  function lockScrollUnderModals() {
    var MODALS = [
      "pv-modal", "pr-modal", "co-modal", "cart-panel", "mobile-nav", "eco-modal",
    ];
    function anyOpen() {
      for (var i = 0; i < MODALS.length; i++) {
        if (document.querySelector("." + MODALS[i] + ".is-open")) return true;
      }
      return false;
    }
    function sync() {
      var lock = anyOpen();
      document.documentElement.style.overflow = lock ? "hidden" : "";
      document.body.style.overflow = lock ? "hidden" : "";
    }
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var t = muts[i].target;
        if (!t.classList) continue;
        for (var j = 0; j < MODALS.length; j++) {
          if (t.classList.contains(MODALS[j])) { sync(); return; }
        }
      }
    });
    obs.observe(document.body, {
      subtree: true, attributes: true, attributeFilter: ["class"],
    });
    sync();
  }

  function init() {
    injectReviewStyles();
    mountReviews();
    lockScrollUnderModals();
    load();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
