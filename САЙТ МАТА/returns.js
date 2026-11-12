// Отмена и возврат заказа на сайте (D-123) — те же возможности, что в приложении
// МАТА Store, в стиле окна профиля. Решает сервер МАТА: что можно вернуть, до
// какого срока, нужна ли фотография. Здесь — только показ его ответа и сбор заявки.
//
// Живёт в окне профиля как ещё один экран (prSetView("return")): «Мои заказы» →
// «Отменить или вернуть». Нужны script.js (prModal, prSetView, escapeHtml,
// formatPrice) и ecosystem.js (STAW.api, STAW.upload).
"use strict";

// Причины «не надлежащего качества» — по ним срок 2 года, а не 7 дней.
var RT_QUALITY = { defect: 1, wrong_item: 1, not_as_described: 1 };

// ── Чистые правила (проверяются тестами tools/site_tests/returns.test.js) ──

// После 7 дней сервер примет только претензию по качеству — остальные причины
// не предлагаем, чтобы покупатель не получил отказ уже после отправки.
function rtAllowedReasons(reasons, standardOpen) {
  var out = [];
  Object.keys(reasons || {}).forEach(function (key) {
    if (standardOpen !== false || RT_QUALITY[key]) out.push([key, String(reasons[key])]);
  });
  return out;
}

function rtNeedsComment(reason) {
  return reason === "defect" || reason === "other";
}

// Что не так с заявкой — текст для покупателя, или "" если можно отправлять.
function rtValidate(sel, photos) {
  var keys = Object.keys(sel || {});
  if (!keys.length) return "Отметьте вещи, которые возвращаете";
  var needPhoto = false;
  for (var i = 0; i < keys.length; i++) {
    var line = sel[keys[i]];
    if (rtNeedsComment(line.reason) && String(line.comment || "").trim().length < 5) {
      return "Опишите, что не так с вещью";
    }
    if (line.reason === "defect") needPhoto = true;
  }
  var list = photos || [];
  if (list.some(function (p) { return p.status === "loading"; })) {
    return "Дождитесь, пока загрузятся фото";
  }
  if (needPhoto && !list.some(function (p) { return p.id; })) return "Приложите фото брака";
  return "";
}

// Тело POST /orders/:id/return-requests. Ключ photos — всегда: по нему сервер
// понимает, что клиент умеет фото, и требует снимок при браке.
function rtPayload(method, sel, photos) {
  return {
    method: method === "parcel" ? "parcel" : "store",
    photos: (photos || []).filter(function (p) { return p.id; }).map(function (p) { return p.id; }),
    lines: Object.keys(sel || {}).map(function (k) {
      return {
        index: Number(k),
        reason: sel[k].reason,
        comment: String(sel[k].comment || "").trim(),
      };
    }),
  };
}

function rtDate(iso) {
  var d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

// ── Состояние экрана ──────────────────────────────────────────────────────

var rt = null;

function rtFresh(orderId) {
  return {
    orderId: orderId,
    options: null,
    requests: [],
    sel: {},
    photos: [],
    method: "store",
    loading: true,
    busy: false,
    error: "",
    confirmCancel: false,
    trackFor: null,
  };
}

function rtBox() {
  return typeof prModal !== "undefined" && prModal
    ? prModal.querySelector("[data-pr-return-body]")
    : null;
}

function rtOpen(orderId) {
  rt = rtFresh(orderId);
  prSetView("return");
  rtBind();
  rtLoad();
}

function rtLoad() {
  if (!rt) return Promise.resolve();
  var state = rt;
  var base = "/orders/" + encodeURIComponent(state.orderId);
  state.loading = true;
  rtRender();
  return Promise.all([
    window.STAW.api(base + "/return-options"),
    window.STAW.api(base + "/return-requests"),
  ]).then(
    function (res) {
      if (rt !== state) return;
      state.options = res[0] || {};
      state.requests = Array.isArray(res[1]) ? res[1] : [];
      state.sel = {};
      state.photos = [];
      state.error = "";
      state.loading = false;
      state.confirmCancel = false;
      state.trackFor = null;
      rtRender();
    },
    function (err) {
      if (rt !== state) return;
      state.loading = false;
      state.error = (err && err.message) || "Не удалось загрузить — попробуйте ещё раз";
      rtRender();
    },
  );
}

// Действие на сервере, потом — перечитать экран; ошибку показать текстом.
function rtPost(path, body) {
  var state = rt;
  state.busy = true;
  state.error = "";
  rtRender();
  return window.STAW.api(path, { method: "POST", body: body || {} }).then(
    function () {
      if (rt !== state) return;
      state.busy = false;
      return rtLoad();
    },
    function (err) {
      if (rt !== state) return;
      state.busy = false;
      state.error = (err && err.message) || "Не получилось — попробуйте ещё раз";
      rtRender();
    },
  );
}

function rtAddPhotos(files) {
  var state = rt;
  var max = Number((state.options && state.options.maxPhotos) || 6);
  Array.prototype.slice.call(files || []).forEach(function (file) {
    if (state.photos.length >= max) return;
    var photo = { id: null, url: URL.createObjectURL(file), status: "loading" };
    state.photos.push(photo);
    window.STAW.upload("/return-photos", file).then(
      function (res) {
        photo.id = res && res.id;
        photo.status = photo.id ? "ok" : "failed";
        if (rt === state) rtRender();
      },
      function (err) {
        photo.status = "failed";
        state.error = (err && err.message) || "Фото не загрузилось";
        if (rt === state) rtRender();
      },
    );
  });
  rtRender();
}

// ── Отрисовка ─────────────────────────────────────────────────────────────

function rtEsc(s) {
  return escapeHtml(s == null ? "" : s);
}

function rtRender() {
  var box = rtBox();
  if (!box || !rt) return;
  if (rt.loading && !rt.options) {
    box.innerHTML = '<p class="pr-addr-empty">Загрузка…</p>';
    return;
  }
  var html = "";
  if (rt.options) html += rtCancelHtml(rt.options);
  rt.requests.forEach(function (r) {
    html += rtRequestHtml(r);
  });
  if (rt.options) html += rtFormHtml(rt.options);
  if (rt.error) html += '<p class="rt-error" role="alert">' + rtEsc(rt.error) + "</p>";
  box.innerHTML = html;
}

function rtCancelHtml(o) {
  if (o.cancelRequested && o.cancelNote) {
    return '<p class="rt-note">' + rtEsc(o.cancelNote) + "</p>";
  }
  if (!o.canCancel) return "";
  var busy = rt.busy ? " disabled" : "";
  var body = rt.confirmCancel
    ? '<p class="rt-text">Деньги вернутся туда, откуда платили, списанные баллы — на баланс. ' +
      "Если склад уже собрал заказ, проверим, что он ещё не у курьера, и сообщим.</p>" +
      '<div class="rt-row">' +
      '<button type="button" class="pr-addr-add-btn" data-rt-act="cancel-yes"' + busy + ">Да, отменить заказ</button>" +
      '<button type="button" class="rt-link" data-rt-act="cancel-no">Не отменять</button></div>'
    : '<button type="button" class="rt-outline" data-rt-act="cancel-ask">Отменить заказ</button>';
  return (
    '<section class="rt-block">' +
    '<p class="rt-text">Заказ ещё не передан курьеру — его можно отменить целиком.</p>' +
    body +
    "</section>"
  );
}

function rtFormHtml(o) {
  if (!o.canReturn) {
    // Отменяемый заказ ещё не получен — «вернуть нельзя» тут только путает.
    if (o.canCancel || o.cancelRequested || !o.reason) return "";
    return '<p class="rt-note">' + rtEsc(o.reason) + "</p>";
  }
  var reasons = rtAllowedReasons(o.reasons, o.standardOpen);
  var store = o.store || {};
  var html =
    '<section class="rt-block">' +
    '<h4 class="rt-h">Оформить возврат</h4>' +
    '<p class="rt-text">Вещь без брака можно вернуть в течение 7 дней со дня получения: с ярлыками, ' +
    "в упаковке, без следов носки. Брак — в течение 2 лет. Принесите вещь в магазин МАТА или " +
    "отправьте посылкой за свой счёт. Решение принимаем после осмотра. Если подтвердится брак — " +
    "вернём и расходы на доставку.</p>";
  if (o.standardNote) html += '<p class="rt-note">' + rtEsc(o.standardNote) + "</p>";

  html += '<p class="pr-addr-title">Что возвращаете</p>';
  (o.lines || []).forEach(function (line) {
    var idx = String(line.index);
    var chosen = rt.sel[idx];
    var off = line.available ? "" : " disabled";
    var sub = line.available
      ? formatPrice(Math.round(Number(line.paid) || 0))
      : line.status === "returned" ? "Уже возвращено" : "По вещи уже есть заявка";
    html +=
      '<div class="rt-line' + (chosen ? " is-on" : "") + '">' +
      '<label class="rt-check"><input type="checkbox" data-rt-line="' + rtEsc(idx) + '"' +
      (chosen ? " checked" : "") + off + " />" +
      "<span><b>" + rtEsc(line.name) + "</b><small>" + rtEsc(sub) + "</small></span></label>";
    if (chosen) {
      html += '<select class="rt-select" data-rt-reason="' + rtEsc(idx) + '" aria-label="Причина возврата">';
      reasons.forEach(function (r) {
        html += '<option value="' + rtEsc(r[0]) + '"' + (r[0] === chosen.reason ? " selected" : "") + ">" +
          rtEsc(r[1]) + "</option>";
      });
      html += "</select>";
      if (rtNeedsComment(chosen.reason)) {
        html += '<textarea class="rt-input" rows="2" maxlength="500" data-rt-comment="' + rtEsc(idx) +
          '" placeholder="Что не так с вещью">' + rtEsc(chosen.comment || "") + "</textarea>";
      }
    }
    html += "</div>";
  });

  var needPhoto = Object.keys(rt.sel).some(function (k) { return rt.sel[k].reason === "defect"; });
  var max = Number(o.maxPhotos || 6);
  html +=
    '<p class="pr-addr-title">Фото</p>' +
    '<p class="rt-hint">' + (needPhoto
      ? "При браке нужно фото: сам дефект крупно и вещь целиком."
      : "Необязательно, но так быстрее разберёмся.") + "</p>" +
    '<div class="rt-photos">';
  rt.photos.forEach(function (p, i) {
    html += '<div class="rt-photo is-' + p.status + '"><img src="' + rtEsc(p.url) + '" alt="" />' +
      '<button type="button" data-rt-act="photo-del" data-rt-i="' + i + '" aria-label="Убрать фото">×</button></div>';
  });
  if (rt.photos.length < max) {
    html += '<label class="rt-photo-add" aria-label="Добавить фото">+' +
      '<input type="file" accept="image/*" multiple data-rt-file hidden /></label>';
  }
  html += "</div>";

  html +=
    '<p class="pr-addr-title">Как сдадите</p>' +
    rtRadio("store", "Принесу в магазин", store.description || store.name || "") +
    rtRadio("parcel", "Отправлю посылкой за свой счёт",
      "После отправки впишите здесь трек-номер. Сохраните квитанцию: при подтверждённом браке компенсируем доставку.");

  var empty = !Object.keys(rt.sel).length;
  html +=
    '<button type="button" class="btn btn-primary rt-submit" data-rt-act="submit"' +
    (empty || rt.busy ? " disabled" : "") + ">" + (rt.busy ? "Отправляем…" : "Оформить заявку") + "</button>" +
    "</section>";
  return html;
}

function rtRadio(value, title, sub) {
  return (
    '<label class="rt-radio"><input type="radio" name="rt-method" value="' + value + '" data-rt-method' +
    (rt.method === value ? " checked" : "") + " />" +
    "<span><b>" + rtEsc(title) + "</b>" + (sub ? "<small>" + rtEsc(sub) + "</small>" : "") + "</span></label>"
  );
}

function rtRequestHtml(r) {
  var id = rtEsc(r.id);
  var html =
    '<article class="pr-order rt-req">' +
    '<div class="pr-order-top"><span class="pr-order-id">Заявка ' + rtEsc(r.number) + "</span>" +
    '<span class="pr-order-status ' + rtStatusCls(r.status) + '">' + rtEsc(r.statusLabel) + "</span></div>";
  (r.lines || []).forEach(function (l) {
    html += '<p class="rt-req-line">' + rtEsc(l.name) + " — " + rtEsc(l.reasonLabel) + "</p>";
    (l.rejectReasonLabels || []).forEach(function (x) {
      html += '<p class="rt-req-reject">Отказ: ' + rtEsc(x) + "</p>";
    });
  });
  if (r.status === "awaiting" && r.bringUntil) {
    html += '<p class="rt-hint">' + (r.method === "parcel" ? "Отправьте посылку до " : "Принесите вещь до ") +
      rtEsc(rtDate(r.bringUntil)) + "</p>";
  }
  if (r.trackNumber) html += '<p class="rt-hint">Трек-номер: ' + rtEsc(r.trackNumber) + "</p>";
  if (r.decisionNote) html += '<p class="rt-text">' + rtEsc(r.decisionNote) + "</p>";
  if (r.refundRub != null) {
    html += '<p class="rt-refund">Возвращено: ' + rtEsc(formatPrice(Number(r.refundRub))) + "</p>";
  }
  if ((r.inspectionPhotos || []).length) {
    html += '<p class="rt-hint">Фото с осмотра</p><div class="rt-photos">';
    r.inspectionPhotos.forEach(function (p) {
      html += '<a class="rt-photo" href="' + rtEsc(p.url) + '" target="_blank" rel="noopener">' +
        '<img src="' + rtEsc(p.url) + '" alt="Фото с осмотра" /></a>';
    });
    html += "</div>";
  }
  if (r.needsGoodsBack) {
    html += '<p class="rt-text">Как вернуть вам вещи, по которым отказано?</p><div class="rt-row">' +
      '<button type="button" class="rt-outline" data-rt-act="back" data-rt-id="' + id + '" data-rt-way="pickup">Заберу в магазине</button>' +
      '<button type="button" class="rt-outline" data-rt-act="back" data-rt-id="' + id + '" data-rt-way="ship">Отправьте за мой счёт</button></div>';
  } else if (r.goodsBack && !r.goodsBackDone) {
    html += '<p class="rt-hint">' + (r.goodsBack === "pickup"
      ? "Вещи ждут вас в магазине"
      : "Отправим вещи за ваш счёт — сообщим трек-номер") + "</p>";
  }
  if (rt.trackFor === String(r.id)) {
    html += '<div class="rt-row"><input class="rt-input" data-rt-track maxlength="64" ' +
      'placeholder="Трек-номер посылки" value="' + rtEsc(r.trackNumber || "") + '" />' +
      '<button type="button" class="pr-addr-add-btn" data-rt-act="track-save" data-rt-id="' + id + '">Сохранить</button></div>';
  } else if (r.needsTrack || r.canCancel) {
    html += '<div class="rt-row">';
    if (r.needsTrack) {
      html += '<button type="button" class="rt-link" data-rt-act="track" data-rt-id="' + id + '">' +
        (r.trackNumber ? "Изменить трек-номер" : "Вписать трек-номер") + "</button>";
    }
    if (r.canCancel) {
      html += '<button type="button" class="rt-link" data-rt-act="req-cancel" data-rt-id="' + id + '">Отменить заявку</button>';
    }
    html += "</div>";
  }
  return html + "</article>";
}

function rtStatusCls(s) {
  if (s === "approved") return "is-done";
  if (s === "partial" || s === "received") return "is-pack";
  if (s === "sent") return "is-ship";
  if (s === "awaiting") return "is-new";
  return "";
}

// ── События: один обработчик на весь экран ───────────────────────────────

function rtBind() {
  var box = rtBox();
  if (!box || box.dataset.rtBound) return;
  box.dataset.rtBound = "1";

  box.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-rt-act]");
    if (!btn || !rt || btn.disabled) return;
    var act = btn.getAttribute("data-rt-act");
    var id = btn.getAttribute("data-rt-id");
    if (act === "cancel-ask") { rt.confirmCancel = true; rtRender(); }
    else if (act === "cancel-no") { rt.confirmCancel = false; rtRender(); }
    else if (act === "cancel-yes") rtPost("/orders/" + encodeURIComponent(rt.orderId) + "/cancel");
    else if (act === "req-cancel") rtPost("/return-requests/" + id + "/cancel");
    else if (act === "back") rtPost("/return-requests/" + id + "/goods-back", { way: btn.getAttribute("data-rt-way") });
    else if (act === "track") { rt.trackFor = id; rtRender(); var f = box.querySelector("[data-rt-track]"); if (f) f.focus(); }
    else if (act === "track-save") {
      var input = box.querySelector("[data-rt-track]");
      var track = input ? input.value.trim() : "";
      if (track.length < 5) { rt.error = "Впишите трек-номер посылки"; rtRender(); return; }
      rtPost("/return-requests/" + id + "/sent", { trackNumber: track });
    } else if (act === "photo-del") {
      rt.photos.splice(Number(btn.getAttribute("data-rt-i")), 1);
      rtRender();
    } else if (act === "submit") rtSubmit();
  });

  box.addEventListener("change", function (e) {
    if (!rt) return;
    var t = e.target;
    if (t.hasAttribute("data-rt-line")) {
      var idx = t.getAttribute("data-rt-line");
      if (t.checked) {
        rt.sel[idx] = { reason: rt.options.standardOpen === false ? "defect" : "size", comment: "" };
      } else {
        delete rt.sel[idx];
      }
      rtRender();
    } else if (t.hasAttribute("data-rt-reason")) {
      rt.sel[t.getAttribute("data-rt-reason")].reason = t.value;
      rtRender();
    } else if (t.hasAttribute("data-rt-method")) {
      rt.method = t.value;
    } else if (t.hasAttribute("data-rt-file")) {
      rtAddPhotos(t.files);
    }
  });

  // Комментарий копим без перерисовки — иначе поле теряет курсор.
  box.addEventListener("input", function (e) {
    var t = e.target;
    if (rt && t.hasAttribute("data-rt-comment")) {
      var line = rt.sel[t.getAttribute("data-rt-comment")];
      if (line) line.comment = t.value;
    }
  });
}

function rtSubmit() {
  var problem = rtValidate(rt.sel, rt.photos);
  if (problem) {
    rt.error = problem;
    rtRender();
    return;
  }
  rtPost("/orders/" + encodeURIComponent(rt.orderId) + "/return-requests",
    rtPayload(rt.method, rt.sel, rt.photos));
}

// Заказ, по которому есть смысл открыть экран: оплачен (отмена или возврат —
// решит сервер).
function rtOrderEligible(o) {
  return !!o && (o.paymentStatus === "paid" || o.paymentStatus === "partially_refunded");
}

window.STAW = window.STAW || {};
window.STAW.openReturn = rtOpen;
