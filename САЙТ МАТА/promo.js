/**
 * Промо-баннеры из общего backend (/banners) → стрип под hero.
 * Управление — в «Конструкторе» (/admin/merch/): в режиме ?edit=1 баннеры правятся
 * ПРЯМО в стрипе (клик → правка, перетаскивание → порядок, плитка «➕ Добавить баннер»).
 * На живом сайте: пусто/офлайн → секция скрыта, сайт не ломается.
 */
(function () {
  "use strict";

  var host = location.hostname;
  var isDev = host === "localhost" || host === "127.0.0.1" || host === "";
  var PROD_API = "https://api.mata-club.ru/v1";
  var API =
    (typeof window !== "undefined" && window.STAW_API_BASE) ||
    (isDev ? "http://127.0.0.1:8000/v1" : PROD_API);
  var ORIGIN = API.replace(/\/v1\/?$/, "");
  var EDIT = new URLSearchParams(location.search).get("edit") === "1";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Адаптер путей медиа бэкенда.
  function media(u) {
    if (!u) return "";
    if (u.indexOf("http") === 0) return u;
    var m = u.match(/products\/([^/]+)$/);
    if (m) return ORIGIN + "/media/products/" + m[1];
    return u.charAt(0) === "/" ? ORIGIN + u : ORIGIN + "/" + u;
  }

  function render(banners) {
    var sec = document.querySelector("[data-promo]");
    var track = document.querySelector("[data-promo-track]");
    if (!sec || !track) return;
    banners = Array.isArray(banners) ? banners : [];
    if (!banners.length && !EDIT) return; // живой сайт: пусто → скрыто

    var html = banners
      .map(function (b) {
        var img = media(b.imageUrl);
        var title = String(b.title || "").split("\n").map(esc).join("<br>");
        var idAttr = b.id != null ? ' data-banner-id="' + esc(b.id) + '"' + (EDIT ? ' data-sid="' + esc(b.id) + '"' : "") : "";
        // Подгон/фокус фото баннера: contain — фото целиком; focal — какая часть видна.
        var st = "";
        if (img) st += "--bg:url('" + img + "');";
        if (b.imageFit === "contain") st += "--bg-size:contain;";
        var focal = /^\d{1,3}% \d{1,3}%$/.test(b.imageFocal || "") ? b.imageFocal : "";
        if (focal) st += "--bg-pos:" + focal + ";";
        return (
          '<article class="promo-card"' + idAttr +
          (st ? ' style="' + st + '"' : "") +
          ">" +
          '<div class="promo-card-body">' +
          (b.subtitle ? '<p class="promo-sub">' + esc(b.subtitle) + "</p>" : "") +
          '<h3 class="promo-title">' + title + "</h3>" +
          (b.action ? '<span class="promo-cta">' + esc(b.action) + " →</span>" : "") +
          "</div></article>"
        );
      })
      .join("");
    if (EDIT) {
      track.setAttribute("data-sortable", "banners");
      html += '<button type="button" class="promo-add-banner">➕ Добавить баннер</button>';
    }
    track.innerHTML = html;
    sec.hidden = false;
  }

  function load() {
    // В правке показываем и неопубликованные (preview) — чтобы владелец их видел/правил.
    // Пропуск сотрудника (?pt=...) кладёт Конструктор; без него API черновики не отдаёт.
    var pt = EDIT ? new URLSearchParams(location.search).get("pt") || "" : "";
    var url = API + "/banners?platform=site" + (EDIT ? "&preview=1" : "") +
      (pt ? "&preview_token=" + encodeURIComponent(pt) : "");
    fetch(url)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(render)
      .catch(function () { if (EDIT) render([]); /* в правке — пустой стрип с «Добавить баннер» */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
