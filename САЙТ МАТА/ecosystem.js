/**
 * МАТА сайт — подключение к общей экосистеме (единый аккаунт + баллы).
 *
 * Это самодостаточный модуль: он сам внедряет свой виджет в шапку, свои стили
 * и всю логику. Дизайн (вёрстку/CSS сайта) не трогает — «красоту» можно навести
 * потом, а виджет аккаунта легко перенести/перестилизовать (классы .eco-*).
 *
 * Бэкенд экосистемы (общий с Кварталом и SportStore):
 *   - POST /v1/auth/phone/verify {phone, code}  (dev-код: 1234) → {token, user}
 *   - GET  /v1/auth/me            (Bearer)       → профиль
 *   - GET  /v1/loyalty/account    (Bearer)       → {balance, level, transactions}
 *
 * ВАЖНО (dev): открывать сайт через локальный http-сервер (например
 *   `python -m http.server` в папке сайта), НЕ как file:// — иначе браузер
 *   заблокирует запросы к API. На том же ПК, где поднят backend на :8000.
 */
(function () {
  "use strict";

  // Базовый URL API экосистемы:
  //  - dev (сайт открыт на localhost/127.0.0.1) → локальный backend :8000;
  //  - прод → PROD_API ниже (заменить на реальный домен при деплое) либо
  //    переопределить, задав window.STAW_API_BASE ДО подключения ecosystem.js.
  var PROD_API = "https://api.mata-club.ru/v1"; // TODO: реальный домен API при деплое
  var host = location.hostname;
  var isDev = host === "localhost" || host === "127.0.0.1" || host === "";
  var API =
    (typeof window !== "undefined" && window.STAW_API_BASE) ||
    (isDev ? "http://127.0.0.1:8000/v1" : PROD_API);
  var LS_TOKEN = "staw_jwt";
  var LS_USER = "staw_user";

  // ── storage ────────────────────────────────────────────────────────────────
  function getToken() {
    try { return localStorage.getItem(LS_TOKEN); } catch (e) { return null; }
  }
  function setSession(token, user) {
    try {
      localStorage.setItem(LS_TOKEN, token);
      localStorage.setItem(LS_USER, JSON.stringify(user || {}));
    } catch (e) {}
  }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(LS_USER) || "null"); }
    catch (e) { return null; }
  }
  function clearSession() {
    try { localStorage.removeItem(LS_TOKEN); localStorage.removeItem(LS_USER); }
    catch (e) {}
  }

  // ── api ──────────────────────────────────────────────────────────────────
  function api(path, opts) {
    opts = opts || {};
    var headers = { "Content-Type": "application/json" };
    var t = getToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    return fetch(API + path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.text().then(function (txt) {
        var data = txt ? JSON.parse(txt) : null;
        if (!r.ok) {
          var msg = (data && data.detail) ? data.detail : "Ошибка сервера";
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  // Подсказка после отправки кода: боевой ли вход и каким каналом придёт код (D-50).
  function codeHint(data) {
    if (!data || !data.smsEnabled) return "Тестовый режим: код 1234";
    var type = String((data.channel && data.channel.type) || "").toLowerCase();
    if (type.indexOf("call") >= 0) return "Сейчас позвоним — код это последние 4 цифры номера";
    return "Код отправлен по SMS";
  }

  // ── styles (инжектим, чтобы не трогать styles.css сайта) ────────────────────
  function injectStyles() {
    var css = ""
      + ".eco-account{display:flex;align-items:center;gap:10px;font-family:inherit}"
      + ".eco-account-btn{display:inline-flex;align-items:center;gap:8px;cursor:pointer;"
      + "border:1px solid rgba(17,19,23,.14);background:transparent;color:inherit;font:inherit;"
      + "padding:5px 10px 5px 6px;border-radius:999px}"
      + ".eco-account-btn:hover{border-color:rgba(17,19,23,.32)}"
      + ".eco-btn{cursor:pointer;border:1px solid currentColor;background:transparent;"
      + "color:inherit;font:inherit;font-weight:600;padding:8px 14px;border-radius:999px;"
      + "letter-spacing:.02em}"
      + ".eco-points{display:inline-flex;align-items:center;gap:6px;font-weight:700;"
      + "padding:8px 12px;border-radius:999px;background:rgba(0,0,0,.06)}"
      + ".eco-user{font-weight:600;opacity:.85;max-width:140px;overflow:hidden;"
      + "text-overflow:ellipsis;white-space:nowrap}"
      + ".eco-avatar{width:26px;height:26px;border-radius:50%;object-fit:cover;flex:0 0 auto}"
      + ".eco-avatar--ini{display:inline-flex;align-items:center;justify-content:center;"
      + "background:rgba(0,0,0,.12);font-weight:700;font-size:12px;color:inherit}"
      // Аватар в панели профиля — кликабелен (смена фото), фото фоном.
      + ".pr-avatar{cursor:pointer;background-size:cover;background-position:center;position:relative}"
      + ".pr-avatar::after{content:'📷';position:absolute;right:-2px;bottom:-2px;font-size:11px;"
      + "background:#20252b;border-radius:50%;width:18px;height:18px;display:flex;align-items:center;"
      + "justify-content:center;box-shadow:0 0 0 2px #fffdf8}"
      + ".pr-avatar.has-photo{color:transparent;text-shadow:none}"
      + ".pr-avatar-remove{display:block;background:none;border:none;color:#c0392b;font:inherit;"
      + "font-size:12px;cursor:pointer;padding:4px 0 0;text-decoration:underline}"
      + ".eco-link{cursor:pointer;background:none;border:none;color:inherit;font:inherit;"
      + "opacity:.6;text-decoration:underline}"
      + ".eco-modal{position:fixed;inset:0;z-index:9999;display:none;align-items:center;"
      + "justify-content:center;background:rgba(10,12,16,.55);backdrop-filter:blur(4px)}"
      + ".eco-modal.is-open{display:flex}"
      + ".eco-card{background:#fffdf8;color:#20252b;border-radius:18px;"
      + "box-shadow:0 24px 60px rgba(0,0,0,.3)}"
      // ── Карточка-слайдер «Auth Slider» (эталон: панель 600мс ease-in-out-sine,
      //    параллакс текста ±200%, формы только opacity 220мс delay 360мс) ──
      + ".eco-card--slider{--dur:600ms;--ease:cubic-bezier(.37,0,.63,1);--pad:10px;"
      // Высота — под самый высокий шаг (регистрация с кодом ≈553px) с запасом на шрифты:
      // раньше пропорция 1089/724 давала ≈505px, и на шаге кода появлялась прокрутка
      // (замечание владельца 11.09.2026). На низких экранах — не выше окна браузера.
      + "position:relative;width:min(94vw,760px);height:min(600px,calc(100vh - 24px));"
      + "box-sizing:border-box;padding:var(--pad);overflow:hidden}"
      + ".eco-card--slider .eco-close{position:absolute;top:8px;right:12px;z-index:9;float:none;"
      + "color:#fff;mix-blend-mode:difference;opacity:.8;font-size:22px}"
      + ".eco-half{position:absolute;top:var(--pad);bottom:var(--pad);width:calc(50% - var(--pad));"
      + "display:flex;align-items:center;justify-content:center;overflow-y:auto;"
      + "transition:opacity 220ms ease 360ms}"
      + ".eco-half--login{left:var(--pad);opacity:0}"
      + ".eco-half--reg{right:var(--pad);opacity:1}"
      + ".eco-half>.eco-form{margin-top:auto;margin-bottom:auto}"
      + ".eco-card--slider.isLogin .eco-half--login{opacity:1}"
      + ".eco-card--slider.isLogin .eco-half--reg{opacity:0}"
      + ".eco-form{width:100%;max-width:330px;padding:0 22px;text-align:center}"
      + ".eco-cover{position:absolute;top:var(--pad);left:var(--pad);bottom:var(--pad);"
      + "width:calc(50% - var(--pad));border-radius:14px;overflow:hidden;z-index:5;"
      + "transform:translateX(0);transition:transform var(--dur) var(--ease)}"
      + ".eco-card--slider.isLogin .eco-cover{transform:translateX(100%)}"
      // Слой панели: !important держит геометрию, даже когда видео-фон Конструктора
      // (staw-bg-on) пытается сделать элемент position:relative.
      + ".eco-photo{position:absolute!important;inset:0!important;background:linear-gradient(160deg,#2b3240,#171a22 55%,#0c0e13);background-size:cover;background-position:center;pointer-events:none}"
      + ".eco-photo--reg{opacity:1;transition:opacity var(--dur) var(--ease)}"
      + ".eco-photo--login{opacity:0;transition:opacity var(--dur) var(--ease)}"
      + ".eco-card--slider.isLogin .eco-photo--reg{opacity:0}"
      + ".eco-card--slider.isLogin .eco-photo--login{opacity:1}"
      // Кликабелен (для «🖼 Фон») только видимый слой — чтобы правился нужный экран.
      + ".eco-card--slider:not(.isLogin) .eco-photo--reg{pointer-events:auto}"
      + ".eco-card--slider.isLogin .eco-photo--login{pointer-events:auto}"
      + ".eco-photo-wm{position:absolute;left:50%;top:13%;transform:translateX(-50%);"
      + "font-size:64px;font-weight:800;letter-spacing:10px;color:#fff;opacity:.09;pointer-events:none;white-space:nowrap}"
      // В «Конструкторе» надпись-watermark кликабельна: поднимаем НАД .eco-side
      // (иначе тот перекрывает её и перехватывает клик) и делаем заметнее для правки.
      + "html.staw-edit .eco-photo-wm{pointer-events:auto;cursor:pointer;z-index:2;opacity:.3}"
      + ".eco-shade{position:absolute;inset:0;pointer-events:none;background:linear-gradient(180deg,rgba(10,12,10,.18),rgba(10,12,10,.42))}"
      + ".eco-side{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;"
      + "justify-content:center;padding:0 26px;text-align:center;color:#fff;"
      + "transition:transform var(--dur) var(--ease)}"
      + ".eco-sideA{transform:translateX(0)}"
      + ".eco-sideB{transform:translateX(200%)}"
      + ".eco-card--slider.isLogin .eco-sideA{transform:translateX(-200%)}"
      + ".eco-card--slider.isLogin .eco-sideB{transform:translateX(0)}"
      + ".eco-side h3{margin:0 0 10px;font-size:24px}"
      + ".eco-side p{margin:0 0 20px;font-size:13.5px;line-height:1.55;color:rgba(255,255,255,.92)}"
      + ".eco-ghost{height:44px;padding:0 36px;border-radius:22px;cursor:pointer;background:transparent;"
      + "border:1.5px solid rgba(255,255,255,.85);color:#fff;font:inherit;font-weight:600;"
      + "letter-spacing:1.4px;font-size:12.5px;transition:background .22s,transform .18s}"
      + ".eco-ghost:hover{background:rgba(255,255,255,.14);transform:translateY(-2px)}"
      + ".eco-ghost:active{transform:scale(.97)}"
      // мобильный столбик: панель сверху, движение панели отключено (по спеке)
      + "@media(max-width:719px){"
      + ".eco-card--slider{display:flex;flex-direction:column;aspect-ratio:auto;height:auto;"
      + "width:min(92vw,380px);max-height:92vh;overflow-y:auto}"
      + ".eco-cover{position:relative;order:-1;top:0;left:0;bottom:auto;width:100%;height:118px;"
      + "flex:0 0 auto;transform:none!important;border-radius:12px}"
      + ".eco-half{position:static;width:100%;opacity:1!important;transition:none;display:none;"
      + "padding:18px 0 8px;flex:0 0 auto;overflow:visible}"
      + ".eco-card--slider.isLogin .eco-half--login{display:flex}"
      + ".eco-card--slider:not(.isLogin) .eco-half--reg{display:flex}"
      + ".eco-side{transform:none!important;transition:opacity 220ms ease}"
      + ".eco-sideA{opacity:1}.eco-sideB{opacity:0}"
      + ".eco-card--slider.isLogin .eco-sideA{opacity:0}"
      + ".eco-card--slider.isLogin .eco-sideB{opacity:1}"
      + ".eco-side p{display:none}.eco-side h3{font-size:17px;margin:0 0 8px}"
      + ".eco-ghost{height:36px;padding:0 26px;font-size:11.5px}"
      + ".eco-photo-wm{font-size:40px;top:16%}}"
      + "@media(prefers-reduced-motion:reduce){"
      + ".eco-cover,.eco-side,.eco-half{transition-duration:.01ms!important;transition-delay:0ms!important}}"
      + ".eco-card h3{margin:0 0 4px;font-size:20px}"
      + ".eco-card p.eco-sub{margin:0 0 16px;opacity:.6;font-size:13px}"
      + ".eco-card input{width:100%;box-sizing:border-box;margin:6px 0;padding:12px 14px;"
      + "border:1px solid #d9d6cd;border-radius:12px;font:inherit;background:#fff}"
      + ".eco-card .eco-primary{width:100%;margin-top:10px;padding:13px;border:none;"
      + "border-radius:12px;background:#20252b;color:#fff;font:inherit;font-weight:700;cursor:pointer}"
      + ".eco-card .eco-primary[disabled]{opacity:.5;cursor:default}"
      + ".eco-card .eco-link{display:inline-block;margin-top:10px;background:none;border:none;"
      + "color:#6f7278;font:inherit;font-size:13px;text-decoration:underline;cursor:pointer}"
      + ".eco-card .eco-link:hover{color:#20252b}"
      + ".eco-err{color:#c0392b;font-size:13px;min-height:18px;margin:6px 0 0}"
      // «Глазок» в поле пароля: кнопка внутри поля справа, текст под неё не заезжает.
      + ".eco-pass{position:relative;margin:6px 0}"
      + ".eco-card .eco-pass input{margin:0;padding-right:48px}"
      + ".eco-eye{position:absolute;right:4px;top:50%;transform:translateY(-50%);width:40px;height:40px;"
      + "display:flex;align-items:center;justify-content:center;padding:0;background:none;border:0;"
      + "border-radius:10px;color:#8a8d92;cursor:pointer;transition:color .2s}"
      + ".eco-eye:hover{color:#20252b}"
      + ".eco-eye:focus-visible{outline:2px solid #20252b;outline-offset:-2px}"
      + ".eco-eye svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;"
      + "stroke-linecap:round;stroke-linejoin:round}"
      + ".eco-eye .eye-off{display:none}"
      + ".eco-eye[aria-pressed=\"true\"] .eye-on{display:none}"
      + ".eco-eye[aria-pressed=\"true\"] .eye-off{display:block}"
      + ".eco-card .eco-close{float:right;background:none;border:none;font-size:20px;cursor:pointer;opacity:.5}"
      // ── Ввод кода: хореография «OTP V5» (стандарт анимаций экосистемы) ──
      // Поле телефона: несъёмный «+7» виден ВСЕГДА (тем же начертанием, что
      // и вводимые цифры), пользователь набирает только 10 цифр.
      + ".eco-phone{display:flex;align-items:center;margin:6px 0;border:1px solid #d9d6cd;"
      + "border-radius:12px;background:#fff}"
      + ".eco-phone:focus-within{border-color:#20252b}"
      + ".eco-phone-prefix{padding:12px 0 12px 14px;color:#20252b;font:inherit}"
      + ".eco-card .eco-phone input{border:0;margin:0;flex:1;min-width:0;background:transparent;"
      + "padding:12px 14px 12px 6px;border-radius:12px;outline:none}"
      // Постоянная маска телефона: образец «___ ___-__-__» виден СРАЗУ и остаётся до
      // последней цифры — введённые цифры (в input, поверх) закрывают свои позиции,
      // незаполненные позиции остаются прозрачно-серыми. Слои выровнены по шрифту/паддингу.
      + ".eco-phone-field{position:relative;flex:1;min-width:0;display:flex}"
      + ".eco-phone-mask{position:absolute;inset:0;display:flex;align-items:center;"
      + "padding:12px 14px 12px 6px;font:inherit;white-space:pre;pointer-events:none;overflow:hidden}"
      + ".eco-phone-mask .t{color:transparent}"
      + ".eco-phone-mask .r{color:#bdbab1}"
      + ".eco-otp{position:relative;height:196px;margin:10px 0 0;cursor:text}"
      + ".eco-card input.eco-otp-input{position:absolute;left:50%;top:50%;width:1px;height:1px;"
      + "opacity:0;border:0;padding:0;margin:0;background:transparent}"
      + ".eco-otp-cell{position:absolute;left:50%;top:50%;width:52px;height:62px;"
      + "margin:-31px 0 0 -26px;border-radius:14px;background:#fff;border:1px solid #d9d6cd;"
      + "display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;"
      + "color:#20252b;will-change:transform;transition:border-color .25s,box-shadow .25s,background .3s}"
      + ".eco-otp-cell.has{border-color:#20252b;border-width:2px}"
      + ".eco-otp-cell.active{border-color:#20252b;border-width:2px;box-shadow:0 0 14px rgba(32,37,43,.18)}"
      + ".eco-otp-cell.err{border-color:#c0392b;color:#c0392b}"
      + ".eco-otp-cell.ok{border-color:#16a34a;background:#eefaf1;box-shadow:0 0 22px rgba(22,163,74,.35)}"
      + ".eco-otp-caret{width:2px;height:24px;background:#20252b;animation:ecoBlink 1s steps(1) infinite}"
      + "@keyframes ecoBlink{50%{opacity:0}}"
      + ".eco-otp-ring{position:absolute;left:50%;top:50%;width:70px;height:70px;margin:-35px 0 0 -35px;"
      + "border-radius:50%;border:1.5px solid #16a34a;pointer-events:none;"
      + "animation:ecoRipple 1.2s cubic-bezier(.22,1,.36,1) forwards}"
      + ".eco-otp-ring.d2{animation-delay:.22s;opacity:0}"
      + "@keyframes ecoRipple{0%{transform:scale(.55);opacity:.9}100%{transform:scale(3.2);opacity:0}}"
      + ".eco-otp-spark{position:absolute;left:50%;top:50%;width:4px;height:4px;border-radius:50%;"
      + "background:#4ade80;opacity:0;animation:ecoFly .9s ease-out forwards;animation-delay:var(--d)}"
      + "@keyframes ecoFly{0%{opacity:0;transform:rotate(var(--a)) translateX(18px) scale(.4)}"
      + "35%{opacity:1}100%{opacity:0;transform:rotate(var(--a)) translateX(84px) scale(.2)}}"
      + ".eco-otp-check{stroke-dasharray:30;stroke-dashoffset:30;"
      + "animation:ecoDraw .45s .1s cubic-bezier(.65,0,.35,1) forwards}"
      + "@keyframes ecoDraw{to{stroke-dashoffset:0}}"
      + ".eco-otp.shake{animation:ecoShake .32s ease}"
      + "@keyframes ecoShake{10%,90%{transform:translateX(-2px)}20%,80%{transform:translateX(3px)}"
      + "30%,50%,70%{transform:translateX(-4px)}40%,60%{transform:translateX(4px)}}"
      + "@media(prefers-reduced-motion:reduce){.eco-otp-ring,.eco-otp-spark{animation:none;opacity:0}"
      + ".eco-otp.shake{animation:none}.eco-otp-check{animation:none;stroke-dashoffset:0}}";
    var s = document.createElement("style");
    s.setAttribute("data-eco-styles", "");
    s.textContent = css;
    document.head.appendChild(s);
  }

  // ── widget в шапке ──────────────────────────────────────────────────────────
  var widget;
  function mountWidget() {
    // Контейнер действий шапки (.header-actions), иначе сама шапка/боди.
    var header =
      document.querySelector(".header-actions") ||
      document.querySelector(".site-header") ||
      document.body;
    widget = document.createElement("div");
    widget.className = "eco-account";
    widget.setAttribute("data-eco-account", "");
    // вставляем перед кнопкой корзины, если она есть
    var cartBtn = header.querySelector(".cart-button");
    if (cartBtn) header.insertBefore(widget, cartBtn);
    else header.appendChild(widget);
  }

  function renderLoggedOut() {
    widget.innerHTML = '<button class="eco-btn" type="button" data-eco-login>Войти</button>';
    widget.querySelector("[data-eco-login]").addEventListener("click", function () {
      openModal("login");
    });
    updateAuthUI(false);
  }

  function renderLoggedIn(user, balance) {
    // В шапке — только имя (полное имя видно в профиле).
    var full = (user && user.name) ? String(user.name).trim() : "";
    var name = full ? full.split(/\s+/)[0] : "Профиль";
    widget.innerHTML =
      '<button class="eco-account-btn" type="button" data-eco-profile aria-label="Открыть профиль">' +
      avatarHtml(user) +
      '<span class="eco-points" title="Баллы экосистемы">★ ' + balance + "</span>" +
      '<span class="eco-user">' + escapeHtml(name) + "</span>" +
      "</button>";
    widget.querySelector("[data-eco-profile]").addEventListener("click", function () {
      if (window.STAW && typeof window.STAW.openProfile === "function") {
        window.STAW.openProfile();
      }
    });
    updateAuthUI(true);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Единый аватар экосистемы: /media/... → абсолютный URL (origin API без /v1).
  function avatarUrl(user) {
    var p = user && user.avatarPath;
    if (!p) return "";
    if (/^https?:/.test(p)) return p;
    return API.replace(/\/v1\/?$/, "") + (p.charAt(0) === "/" ? p : "/" + p);
  }
  // Аватар-кружок: фото с сервера, иначе инициал имени.
  function avatarHtml(user) {
    var av = avatarUrl(user);
    if (av) return '<img class="eco-avatar" src="' + av + '" alt="">';
    var full = (user && user.name) ? String(user.name).trim() : "";
    var ini = full ? full.charAt(0).toUpperCase() : "?";
    return '<span class="eco-avatar eco-avatar--ini">' + escapeHtml(ini) + "</span>";
  }

  // ── login / register modal: карточка-слайдер (эталон Auth Slider) ─────────
  // Панель-«фото» едет ровно на свою ширину (600 мс, cubic-bezier(.37,0,.63,1)),
  // текст панели — параллакс ±200% (вдвое быстрее, в обратную сторону),
  // формы не двигаются вообще — только opacity 220 мс с задержкой 360 мс.
  // Вся анимация — три CSS-перехода; JS лишь переключает класс isLogin.
  var modal, card;
  var ecoMode = "login"; // "login" | "register"
  var otpLogin = null, otpReg = null;

  function setMode(m) {
    ecoMode = m === "register" ? "register" : "login";
    if (!card) return;
    card.classList.toggle("isLogin", ecoMode === "login");
    modal.querySelectorAll(".eco-err").forEach(function (e) { e.textContent = ""; });
    if (otpLogin) otpLogin.softReset();
    if (otpReg) otpReg.softReset();
  }

  // Телефон: пользователь вводит ТОЛЬКО 10 цифр после несъёмного «+7».
  // Ведущие «7»/«8» (набор или вставка «89148278470», «+7914…») отбрасываются —
  // мобильные номера РФ начинаются с 9.
  // Маска телефона: шаблон «### ###-##-##» (# — слот цифры), образец — реальный пример
  // номера PHONE_EX. Введённые цифры идут в «typed» (видны в input поверх), незаполненные
  // позиции показывают цифры образца в «rest» (прозрачно-серые) — образец не исчезает и
  // остаётся до последней цифры. Разделитель — в typed, пока есть введённые цифры, иначе в rest.
  var PHONE_TPL = "### ###-##-##";
  var PHONE_EX = "9123456789"; // пример-образец → «912 345-67-89»
  function phoneMaskParts(digits) {
    var typed = "", rest = "", di = 0;
    for (var i = 0; i < PHONE_TPL.length; i++) {
      var ch = PHONE_TPL.charAt(i);
      if (ch === "#") {
        if (di < digits.length) { typed += digits.charAt(di); }
        else { rest += PHONE_EX.charAt(di); }
        di++;
      } else {
        if (di < digits.length) { typed += ch; } else { rest += ch; }
      }
    }
    return { typed: typed, rest: rest };
  }
  function setupPhoneInput(input) {
    var field = input.parentNode;
    var mask = field ? field.querySelector(".eco-phone-mask") : null;
    function render() {
      var d = input.value.replace(/\D/g, "");
      if (d.charAt(0) === "7" || d.charAt(0) === "8") d = d.slice(1); // РФ-мобильные с 9
      d = d.slice(0, 10);
      var p = phoneMaskParts(d);
      if (input.value !== p.typed) input.value = p.typed;
      if (mask) {
        mask.firstChild
          ? (mask.childNodes[0].textContent = p.typed,
             mask.childNodes[1].textContent = p.rest)
          : (mask.innerHTML = '<span class="t"></span><span class="r"></span>',
             mask.childNodes[0].textContent = p.typed,
             mask.childNodes[1].textContent = p.rest);
      }
    }
    input.addEventListener("input", render);
    render(); // старт: показать полный прозрачный образец «___ ___-__-__»
  }
  function phoneDigits(input) {
    return input.value.replace(/\D/g, "");
  }

  function focusActive() {
    var el = modal.querySelector(
      ecoMode === "register" ? "[data-reg-name]" : "[data-login-phone]"
    );
    if (el) el.focus();
  }

  function buildModal() {
    modal = document.createElement("div");
    modal.className = "eco-modal";
    modal.innerHTML =
      '<div class="eco-card eco-card--slider" role="dialog" aria-label="Вход и регистрация МАТА">' +
      '<button class="eco-close" type="button" data-eco-x aria-label="Закрыть">×</button>' +
      // левая половина — Вход (видна, когда панель уехала вправо).
      // data-edit / data-edit-ph — ключи «Конструктора» (правка текста / плейсхолдера).
      '<div class="eco-half eco-half--login"><div class="eco-form">' +
      '<h3 data-edit="auth.loginTitle" data-login-h>Вход в МАТА</h3>' +
      '<p class="eco-sub" data-edit="auth.loginSub" data-login-sub>Баллы «Квартала», магазина и сайта — общие.</p>' +
      '<div class="eco-phone"><span class="eco-phone-prefix">+7</span>' +
      '<span class="eco-phone-field"><input data-login-phone data-edit-ph="auth.phonePh" type="tel" inputmode="tel" autocomplete="tel" />' +
      '<span class="eco-phone-mask" aria-hidden="true"></span></span></div>' +
      '<div class="eco-pass"><input data-login-pass type="password" placeholder="Пароль" autocomplete="current-password" />' +
      '<button class="eco-eye" type="button" data-eye aria-label="Показать пароль" aria-pressed="false">' +
      '<svg class="eye-on" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>' +
      '<svg class="eye-off" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.9 17.9A10.1 10.1 0 0 1 12 19c-6.4 0-10-7-10-7a18.5 18.5 0 0 1 5.1-5.9"/><path d="M9.9 4.2A9.1 9.1 0 0 1 12 4c6.4 0 10 7 10 7a18.5 18.5 0 0 1-2.2 3.2"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="M2 2l20 20"/></svg>' +
      '</button></div>' +
      // OTP-шаг — только для «Забыл пароль?» (по умолчанию скрыт).
      '<div class="eco-otp" data-login-otp style="display:none">' +
      '<input data-login-code class="eco-otp-input" type="text" inputmode="numeric" maxlength="4" autocomplete="one-time-code" aria-label="Код подтверждения" /></div>' +
      '<p class="eco-err" data-login-err></p>' +
      '<button class="eco-primary" type="button" data-login-submit data-edit="auth.loginBtn">Войти</button>' +
      '<button class="eco-link" type="button" data-login-forgot>Забыл пароль?</button>' +
      "</div></div>" +
      // правая половина — Регистрация (видна в исходном положении панели)
      '<div class="eco-half eco-half--reg"><div class="eco-form">' +
      '<h3 data-edit="auth.regTitle">Регистрация в МАТА</h3>' +
      '<p class="eco-sub" data-edit="auth.regSub" data-reg-sub>Единый аккаунт экосистемы. Подтвердим телефон кодом.</p>' +
      '<input data-reg-name data-edit-ph="auth.namePh" type="text" placeholder="Имя и фамилия" autocomplete="name" />' +
      '<div class="eco-phone"><span class="eco-phone-prefix">+7</span>' +
      '<span class="eco-phone-field"><input data-reg-phone data-edit-ph="auth.phonePh" type="tel" inputmode="tel" autocomplete="tel" />' +
      '<span class="eco-phone-mask" aria-hidden="true"></span></span></div>' +
      '<div class="eco-pass"><input data-reg-pass type="password" placeholder="Пароль (мин. 4 символа)" autocomplete="new-password" />' +
      '<button class="eco-eye" type="button" data-eye aria-label="Показать пароль" aria-pressed="false">' +
      '<svg class="eye-on" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>' +
      '<svg class="eye-off" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.9 17.9A10.1 10.1 0 0 1 12 19c-6.4 0-10-7-10-7a18.5 18.5 0 0 1 5.1-5.9"/><path d="M9.9 4.2A9.1 9.1 0 0 1 12 4c6.4 0 10 7 10 7a18.5 18.5 0 0 1-2.2 3.2"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="M2 2l20 20"/></svg>' +
      '</button></div>' +
      // OTP-шаг регистрации — появляется после отправки SMS.
      '<div class="eco-otp" data-reg-otp style="display:none">' +
      '<input data-reg-code class="eco-otp-input" type="text" inputmode="numeric" maxlength="4" autocomplete="one-time-code" aria-label="Код подтверждения" /></div>' +
      '<p class="eco-err" data-reg-err></p>' +
      '<button class="eco-primary" type="button" data-reg-submit data-edit="auth.regBtn">Получить код</button>' +
      "</div></div>" +
      // панель: тёмный бренд-фон вместо фото (утверждённых фото пока нет),
      // стороны A/B — параллакс ±200%
      '<div class="eco-cover">' +
      // Медиа-панель: два слоя (Регистрация/Вход) с кроссфейдом при переключении +
      // редактируемая фоновая надпись. Каждый слой — data-edit-bg (фото/видео через «🖼 Фон»).
      '<div class="eco-photo eco-photo--reg" data-edit-bg="auth.panelReg"></div>' +
      '<div class="eco-photo eco-photo--login" data-edit-bg="auth.panelLogin"></div>' +
      '<div class="eco-photo-wm" data-edit="auth.panelText">МАТА</div>' +
      '<div class="eco-shade"></div>' +
      '<div class="eco-side eco-sideA">' +
      '<h3 data-edit="auth.sideAtitle">С возвращением!</h3>' +
      '<p data-edit="auth.sideAtext">Войди в единый аккаунт — баллы за бег и покупки уже ждут.</p>' +
      '<button class="eco-ghost" type="button" data-go-login data-edit="auth.sideAbtn">ВОЙТИ</button></div>' +
      '<div class="eco-side eco-sideB">' +
      '<h3 data-edit="auth.sideBtitle">Впервые в МАТА?</h3>' +
      '<p data-edit="auth.sideBtext">Создай единый аккаунт — «Квартал», магазин и сайт в одном.</p>' +
      '<button class="eco-ghost" type="button" data-go-signup data-edit="auth.sideBbtn">РЕГИСТРАЦИЯ</button></div>' +
      "</div></div>";
    document.body.appendChild(modal);
    card = modal.querySelector(".eco-card--slider");
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal();
    });
    modal.querySelector("[data-eco-x]").addEventListener("click", closeModal);
    // «Глазок»: показать или скрыть пароль (просьба владельца 11.09.2026).
    function setPasswordShown(btn, shown) {
      var input = btn.parentNode.querySelector("input");
      input.type = shown ? "text" : "password";
      btn.setAttribute("aria-pressed", shown ? "true" : "false");
      btn.setAttribute("aria-label", shown ? "Скрыть пароль" : "Показать пароль");
    }
    modal.querySelectorAll("[data-eye]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var input = btn.parentNode.querySelector("input");
        setPasswordShown(btn, input.type === "password");
        input.focus();
      });
    });
    modal.querySelector("[data-go-login]").addEventListener("click", function () {
      setMode("login"); focusActive();
    });
    modal.querySelector("[data-go-signup]").addEventListener("click", function () {
      setMode("register"); focusActive();
    });
    var q = function (s) { return modal.querySelector(s); };
    function regPayload() {
      var name = q("[data-reg-name]").value.trim();
      var digits = phoneDigits(q("[data-reg-phone]"));
      var pass = q("[data-reg-pass]").value;
      if (!name) return { error: "Введите имя" };
      if (digits.length < 10) return { error: "Введите номер полностью" };
      if (pass.length < 4) return { error: "Пароль мин. 4 символа" };
      return { phone: "+7" + digits, name: name, password: pass };
    }
    function loginResetPayload() {
      var digits = phoneDigits(q("[data-login-phone]"));
      var pass = q("[data-login-pass]").value;
      if (digits.length < 10) return { error: "Введите номер полностью" };
      if (pass.length < 4) return { error: "Новый пароль мин. 4 символа" };
      return { phone: "+7" + digits, password: pass };
    }
    // Регистрация: код подтверждает телефон один раз, аккаунт создаётся с паролем.
    otpReg = createOtpField({
      stage: q("[data-reg-otp]"), input: q("[data-reg-code]"),
      errEl: q("[data-reg-err]"), btn: q("[data-reg-submit]"),
      getPayload: regPayload,
      verify: function (p, code) {
        return api("/auth/register", { method: "POST", body: { phone: p.phone, code: code, password: p.password, name: p.name } });
      }
    });
    // Сброс пароля (в половине «Вход»): телефон+код+новый пароль.
    otpLogin = createOtpField({
      stage: q("[data-login-otp]"), input: q("[data-login-code]"),
      errEl: q("[data-login-err]"), btn: q("[data-login-submit]"),
      getPayload: loginResetPayload,
      verify: function (p, code) {
        return api("/auth/password/reset", { method: "POST", body: { phone: p.phone, code: code, password: p.password } });
      }
    });
    setupPhoneInput(q("[data-login-phone]"));
    setupPhoneInput(q("[data-reg-phone]"));

    // ── Регистрация: 1-й клик — отправить SMS и показать OTP; далее — проверить код ──
    var regSmsSent = false;
    q("[data-reg-submit]").addEventListener("click", function () {
      var btn = q("[data-reg-submit]"), err = q("[data-reg-err]");
      if (regSmsSent) { otpReg.trySubmit(); return; }
      var p = regPayload();
      err.textContent = "";
      if (p.error) { err.textContent = p.error; return; }
      btn.disabled = true;
      api("/auth/phone/request", { method: "POST", body: { phone: p.phone } })
        .then(function (data) {
          regSmsSent = true;
          q("[data-reg-otp]").style.display = "";
          btn.textContent = "Зарегистрироваться";
          // Подсказка — в подзаголовок, серым: красным в строке ошибок она выглядела как сбой.
          q("[data-reg-sub]").textContent = codeHint(data);
          err.textContent = "";
          q("[data-reg-code]").focus();
        })
        .catch(function (e) { err.textContent = e.message || "Не удалось отправить код"; })
        .then(function () { btn.disabled = false; });
    });

    // ── Вход: телефон+пароль. «Забыл пароль?» → режим сброса (SMS-код) ──
    var loginMode = "login", loginResetSmsSent = false;
    q("[data-login-submit]").addEventListener("click", function () {
      var btn = q("[data-login-submit]"), err = q("[data-login-err]");
      err.textContent = "";
      if (loginMode === "login") {
        var digits = phoneDigits(q("[data-login-phone]"));
        var pass = q("[data-login-pass]").value;
        if (digits.length < 10) { err.textContent = "Введите номер полностью"; return; }
        if (!pass) { err.textContent = "Введите пароль"; return; }
        btn.disabled = true;
        api("/auth/login", { method: "POST", body: { phone: "+7" + digits, password: pass } })
          .then(function (data) { authDone(data, ""); })
          .catch(function (e) { err.textContent = /401/.test(e.message || "") ? "Неверный телефон или пароль" : (e.message || "Не удалось войти"); })
          .then(function () { btn.disabled = false; });
        return;
      }
      // режим сброса
      if (loginResetSmsSent) { otpLogin.trySubmit(); return; }
      var p = loginResetPayload();
      if (p.error) { err.textContent = p.error; return; }
      btn.disabled = true;
      api("/auth/phone/request", { method: "POST", body: { phone: p.phone } })
        .then(function (data) {
          loginResetSmsSent = true;
          q("[data-login-otp]").style.display = "";
          q("[data-login-sub]").textContent = codeHint(data);
          err.textContent = "";
          q("[data-login-code]").focus();
        })
        .catch(function (e) { err.textContent = e.message || "Не удалось"; })
        .then(function () { btn.disabled = false; });
    });
    q("[data-login-forgot]").addEventListener("click", function () {
      loginMode = "reset";
      q("[data-login-h]").textContent = "Сброс пароля";
      q("[data-login-sub]").textContent = "Подтвердим телефон кодом и зададим новый пароль.";
      q("[data-login-pass]").placeholder = "Новый пароль (мин. 4)";
      q("[data-login-pass]").value = "";
      q("[data-login-submit]").textContent = "Получить код";
      this.style.display = "none";
    });

    // Каждое открытие окна — с чистого листа: обычный вход и регистрация без
    // начатых шагов. Раньше состояние переживало закрытие: после сброса пароля,
    // выхода и нового «Войти» окно открывалось снова на «Сбросе пароля» с
    // введённым паролем (замечание владельца 11.09.2026). Телефон и имя не
    // стираем — вводить их заново незачем.
    function resetForms() {
      loginMode = "login";
      loginResetSmsSent = false;
      regSmsSent = false;
      q("[data-login-h]").textContent = "Вход в МАТА";
      q("[data-login-sub]").textContent = "Баллы «Квартала», магазина и сайта — общие.";
      q("[data-reg-sub]").textContent = "Единый аккаунт экосистемы. Подтвердим телефон кодом.";
      q("[data-login-pass]").placeholder = "Пароль";
      q("[data-login-submit]").textContent = "Войти";
      q("[data-login-forgot]").style.display = "";
      q("[data-reg-submit]").textContent = "Получить код";
      ["[data-login-pass]", "[data-login-code]", "[data-reg-pass]", "[data-reg-code]"].forEach(function (s) {
        q(s).value = "";
      });
      q("[data-login-otp]").style.display = "none";
      q("[data-reg-otp]").style.display = "none";
      q("[data-login-err]").textContent = "";
      q("[data-reg-err]").textContent = "";
      q("[data-login-submit]").disabled = false;
      q("[data-reg-submit]").disabled = false;
      // Пароли при новом открытии окна снова скрыты.
      modal.querySelectorAll("[data-eye]").forEach(function (btn) { setPasswordShown(btn, false); });
      applyAuthOverrides(); // вернуть тексты, заданные в «Конструкторе»
    }
    modal._resetForms = resetForms;

    applyAuthOverrides(); // тексты/плейсхолдеры, заданные в «Конструкторе»
    // Медиа панели (фото/видео Вход/Регистрация) — тоже из общего контента.
    if (window.STAW_applyBg) {
      window.STAW_applyBg("auth.panelReg");
      window.STAW_applyBg("auth.panelLogin");
    }
  }

  // Переопределения экрана входа из «Конструктора» (общий контент /site/content).
  // Модалка строится из JS уже после загрузки контента, поэтому применяем вручную
  // (content.js применяет только к элементам, присутствующим на странице при загрузке).
  function applyAuthOverride(key, el, isPh) {
    try {
      var c = window.STAW_CONTENT && window.STAW_CONTENT[key];
      // Различаем «переопределение задано» (пусть даже пустое — надпись удалили) и
      // «переопределения нет» (оставляем дефолт). Иначе пустой текст игнорировался и
      // хардкод (напр. фоновая «МАТА») возвращался при каждой пересборке модалки.
      if (!c || typeof c.value !== "string") return;
      if (isPh) el.setAttribute("placeholder", c.value); else el.textContent = c.value;
    } catch (e) {}
  }
  function applyAuthOverrides() {
    if (!modal) return;
    modal.querySelectorAll("[data-edit]").forEach(function (el) {
      applyAuthOverride(el.getAttribute("data-edit"), el, false);
    });
    modal.querySelectorAll("[data-edit-ph]").forEach(function (el) {
      applyAuthOverride(el.getAttribute("data-edit-ph"), el, true);
    });
  }

  function openModal(mode) {
    if (!modal) buildModal();
    else if (modal._resetForms) modal._resetForms();
    // Класс режима ставим до показа: пока modal display:none, переходы не
    // играют — карточка сразу в нужном положении, анимация только внутри.
    setMode(mode === "register" ? "register" : "login");
    modal.classList.add("is-open");
    focusActive();
  }
  function closeModal() {
    if (!modal) return;
    modal.classList.remove("is-open");
    // Закрыли на середине хореографии — остановить и вернуть строку.
    if (otpLogin) otpLogin.hardReset();
    if (otpReg) otpReg.hardReset();
  }

  // ── Ввод кода «OTP V5»: фабрика — по экземпляру на каждую форму ────────────
  // Стандарт анимаций верификации экосистемы МАТА (директива владельца).
  // Движение пишется прямо в style.transform из rAF — без перерисовок DOM.
  var OTP_LEN = 4, OTP_GAP = 66, OTP_R = 56, OTP_TURNS = 2;

  function otpReduced() {
    return window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }
  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }
  function easeInBack(t) { return 2.2 * t * t * t - 1.2 * t * t; }

  // Успешный вход/регистрация: сохранить сессию и обновить шапку.
  function authDone(data, name) {
    var user = data.user || {};
    if (name) user = Object.assign({}, user, { name: name });
    setSession(data.token, user);
    closeModal();
    refresh();
    // Сообщить странице о входе: оформление заказа ждёт его, чтобы продолжить (D-72).
    try {
      window.dispatchEvent(new CustomEvent("staw-auth", { detail: { user: user } }));
    } catch (e) {}
  }

  // cfg: {stage, input, errEl, btn, getPayload}
  // getPayload() → {phone, name} либо {error: "текст"} (валидация формы).
  function createOtpField(cfg) {
    var stage = cfg.stage, input = cfg.input;
    var cells = [];
    var phase = "input"; // input|explode|spin|spinwait|collapse|reverse
    var t0 = 0, extra = 0, raf = 0, busy = false;
    var result = null; // null=ждём, {ok:true,data,name}|{ok:false,msg}

    for (var i = 0; i < OTP_LEN; i++) {
      var c = document.createElement("div");
      c.className = "eco-otp-cell";
      stage.appendChild(c);
      cells.push(c);
    }
    stage.addEventListener("click", function () {
      if (!busy) input.focus();
    });
    input.addEventListener("input", function () {
      input.value = input.value.replace(/\D/g, "").slice(0, OTP_LEN);
      render();
      if (input.value.length === OTP_LEN && !busy) trySubmit();
    });
    input.addEventListener("focus", function () { render(); });
    input.addEventListener("blur", function () { render(); });
    layoutRow();
    render();

    // Статичная строка (когда rAF не крутится).
    function layoutRow() {
      for (var i = 0; i < OTP_LEN; i++) {
        var x = (i - (OTP_LEN - 1) / 2) * OTP_GAP;
        cells[i].style.transform = "translate(" + x + "px,0)";
        cells[i].style.opacity = 1;
      }
    }

    // Цифры/каретка/классы ячеек.
    function render(errFlag) {
      var v = input.value;
      var focused = document.activeElement === input;
      for (var i = 0; i < OTP_LEN; i++) {
        var cell = cells[i];
        var ch = i < v.length ? v.charAt(i) : "";
        var isCur = !busy && focused && i === v.length;
        cell.textContent = ch;
        if (isCur && !ch) {
          var caret = document.createElement("span");
          caret.className = "eco-otp-caret";
          cell.appendChild(caret);
        }
        cell.classList.toggle("has", !!ch);
        cell.classList.toggle("active", isCur);
        cell.classList.toggle("err", !!errFlag);
        cell.classList.remove("ok");
      }
    }

    // Один кадр хореографии: позиции всех ячеек из текущей фазы.
    function frame(now) {
      var el = now - t0;
      var p = 1, spin = 0, shrink = 0;

      if (phase === "explode") {
        p = easeOutCubic(Math.min(el / 380, 1));
        if (el >= 380) { phase = "spin"; t0 = now; }
      } else if (phase === "spin") {
        spin = easeInOutCubic(Math.min(el / 1250, 1)) * 360 * OTP_TURNS;
        if (el >= 1250) {
          t0 = now;
          phase = result === null
            ? "spinwait"
            : result.ok ? "collapse" : "reverse";
        }
      } else if (phase === "spinwait") {
        // Сервер ещё думает: докручиваем по обороту (вращение = «загрузка»).
        spin = 360 * OTP_TURNS + extra +
          easeInOutCubic(Math.min(el / 800, 1)) * 360;
        if (el >= 800) {
          extra += 360;
          t0 = now;
          if (result !== null) {
            phase = result.ok ? "collapse" : "reverse";
          }
        }
      } else if (phase === "collapse") {
        var t = Math.min(el / 420, 1);
        spin = 360 * OTP_TURNS + extra + easeOutCubic(t) * 40;
        shrink = easeInBack(t);
        if (el >= 420) { finishSuccess(); return; }
      } else if (phase === "reverse") {
        // Ошибка: быстрая обратная раскрутка в строку.
        var r = 1 - easeInOutCubic(Math.min(el / 420, 1));
        p = r;
        spin = (360 * OTP_TURNS + extra) * r;
        if (el >= 420) { finishError(); return; }
      }

      for (var i = 0; i < OTP_LEN; i++) {
        var rowX = (i - (OTP_LEN - 1) / 2) * OTP_GAP;
        var a = ((-90 + i * (360 / OTP_LEN) + spin) * Math.PI) / 180;
        var x = (rowX + (Math.cos(a) * OTP_R - rowX) * p) * (1 - shrink);
        var y = Math.sin(a) * OTP_R * p * (1 - shrink);
        var rot = spin * p;
        var sc = 1 - shrink * 0.12;
        var op = shrink > 0.75 && i !== 0 ? 1 - (shrink - 0.75) / 0.25 : 1;
        cells[i].style.transform =
          "translate(" + x.toFixed(2) + "px," + y.toFixed(2) + "px)" +
          " rotate(" + rot.toFixed(2) + "deg) scale(" + sc.toFixed(3) + ")";
        cells[i].style.opacity = op;
      }
      raf = requestAnimationFrame(frame);
    }

    function finishSuccess() {
      raf = 0;
      // Схлопнуто: остаётся первая ячейка — зелёная, с прорисовкой галочки.
      for (var i = 1; i < OTP_LEN; i++) cells[i].style.opacity = 0;
      var c0 = cells[0];
      c0.style.transform = "translate(0,0) scale(.92)";
      c0.classList.remove("err", "active", "has");
      c0.classList.add("ok");
      c0.innerHTML =
        '<svg viewBox="0 0 24 24" width="26" height="26">' +
        '<path class="eco-otp-check" d="M5 12.5l4.5 4.5L19 7.5" fill="none" ' +
        'stroke="#16a34a" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      for (var r = 0; r < 2; r++) {
        var ring = document.createElement("div");
        ring.className = "eco-otp-ring" + (r ? " d2" : "");
        stage.appendChild(ring);
      }
      for (var s = 0; s < 6; s++) {
        var sp = document.createElement("span");
        sp.className = "eco-otp-spark";
        sp.style.setProperty("--a", (s * 60 + 20) + "deg");
        sp.style.setProperty("--d", (s * 60) + "ms");
        stage.appendChild(sp);
      }
      setTimeout(function () {
        if (!result || !result.ok) return; // сброшено (модалку закрыли раньше)
        var done = result;
        hardReset();
        authDone(done.data, done.name);
      }, 1100);
    }

    function finishError() {
      raf = 0;
      busy = false;
      layoutRow();
      input.value = "";
      render(true);
      stage.classList.add("shake");
      setTimeout(function () { stage.classList.remove("shake"); }, 360);
      cfg.errEl.textContent = (result && result.msg) || "Не удалось войти";
      cfg.btn.disabled = false;
      result = null;
      extra = 0;
      phase = "input";
      input.focus();
    }

    function hardReset() {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      busy = false;
      result = null;
      extra = 0;
      phase = "input";
      input.value = "";
      // убрать кольца/искры финала
      var fx = stage.querySelectorAll(".eco-otp-ring,.eco-otp-spark");
      for (var i = 0; i < fx.length; i++) fx[i].parentNode.removeChild(fx[i]);
      layoutRow();
      render();
      cfg.btn.disabled = false;
    }
    // Сброс только в покое (не рвать идущую проверку при переключении форм).
    function softReset() {
      if (!busy && !raf) hardReset();
    }

    function trySubmit() {
      if (busy) return;
      var payload = cfg.getPayload();
      cfg.errEl.textContent = "";
      if (payload.error) { cfg.errEl.textContent = payload.error; return; }
      if (input.value.length < OTP_LEN) {
        cfg.errEl.textContent = "Введите код из 4 цифр";
        return;
      }
      busy = true;
      result = null;
      extra = 0;
      cfg.btn.disabled = true;
      input.blur();
      render();

      // Проверка кода. Эндпоинт задаёт форма (cfg.verify): регистрация →
      // /auth/register (с паролем/именем), сброс → /auth/password/reset. По
      // умолчанию — legacy phone/verify. Запрос идёт ПАРАЛЛЕЛЬНО хореографии.
      var verifyCall = cfg.verify
        ? cfg.verify(payload, input.value)
        : api("/auth/phone/verify", { method: "POST", body: { phone: payload.phone, code: input.value } });
      verifyCall
        .then(function (data) {
          result = { ok: true, data: data, name: payload.name || "" };
        })
        .catch(function (e) {
          var msg = e.message || "Не удалось";
          if (/invalid verification/i.test(msg)) {
            msg = "Неверный код. Попробуй ещё раз";
          }
          result = { ok: false, msg: msg };
        });

      if (otpReduced()) {
        // Без движения: просто ждём результат и мгновенно показываем состояние.
        var wait = setInterval(function () {
          if (result === null) return;
          clearInterval(wait);
          if (result.ok) { finishSuccess(); } else { finishError(); }
        }, 60);
        return;
      }

      setTimeout(function () {
        if (!busy) return; // сброшено закрытием модалки
        phase = "explode";
        t0 = performance.now();
        raf = requestAnimationFrame(frame);
      }, 260);
    }

    return {
      trySubmit: trySubmit,
      softReset: softReset,
      hardReset: hardReset,
      isBusy: function () { return busy; }
    };
  }

  // Показ/скрытие элементов по состоянию входа (CTA «Войти» прячем в аккаунте).
  function updateAuthUI(loggedIn) {
    document.querySelectorAll("[data-eco-login-cta]").forEach(function (el) {
      el.hidden = !!loggedIn;
    });
    document.querySelectorAll("[data-eco-auth-only]").forEach(function (el) {
      el.hidden = !loggedIn;
    });
  }

  // ── refresh state ──────────────────────────────────────────────────────────
  function refresh() {
    if (!getToken()) { renderLoggedOut(); return; }
    // показываем кэш пока грузим
    renderLoggedIn(getUser(), "…");
    // Полный профиль из бэкенда (имя/email/телефон/адреса) → обновляем сессию.
    api("/auth/me")
      .then(function (me) {
        if (me && me.id) {
          setSession(getToken(), me);
          renderLoggedIn(me, (window.STAW && window.STAW.ecoPoints) || "…");
        }
      })
      .catch(function () {});
    api("/loyalty/account")
      .then(function (acc) {
        var bal = (acc && typeof acc.balance === "number") ? acc.balance : 0;
        window.STAW = window.STAW || {};
        window.STAW.ecoPoints = bal;
        window.STAW.ecoLevel = (acc && acc.level) ? acc.level : null;
        renderLoggedIn(getUser(), bal);
      })
      .catch(function (e) {
        // 401 → токен протух/неверен: разлогиниваем
        if (/токен/i.test(e.message) || /401/.test(e.message)) {
          clearSession();
          renderLoggedOut();
        } else {
          // сеть недоступна — оставляем имя, баллы «—»
          renderLoggedIn(getUser(), "—");
        }
      });
  }

  // ── единый аватар: смена/удаление прямо с сайта ─────────────────────────────
  function uploadAvatarFile(file) {
    var headers = {};
    var t = getToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    var fd = new FormData();
    fd.append("image", file);
    return fetch(API + "/profile/avatar", {
      method: "POST",
      headers: headers,
      body: fd,
    }).then(function (r) {
      return r.text().then(function (x) {
        var d = x ? JSON.parse(x) : null;
        if (!r.ok) throw new Error((d && d.detail) || "Ошибка загрузки");
        return d;
      });
    });
  }
  // Выбрать фото и загрузить как единый аватар; затем обновить шапку и вызвать onDone.
  function changeAvatar(onDone) {
    if (!getToken()) return;
    var inp = document.createElement("input");
    inp.type = "file";
    inp.accept = "image/*";
    inp.style.display = "none";
    document.body.appendChild(inp);
    inp.addEventListener("change", function () {
      var f = inp.files && inp.files[0];
      if (inp.parentNode) inp.parentNode.removeChild(inp);
      if (!f) return;
      uploadAvatarFile(f)
        .then(function (user) {
          setSession(getToken(), user);
          refresh();
          if (typeof onDone === "function") onDone(user);
        })
        .catch(function (err) {
          window.alert(err.message || "Не удалось загрузить фото");
        });
    });
    inp.click();
  }
  function removeAvatar(onDone) {
    if (!getToken()) return;
    var headers = {};
    var t = getToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    fetch(API + "/profile/avatar", { method: "DELETE", headers: headers })
      .then(function (r) {
        return r.text().then(function (x) {
          var d = x ? JSON.parse(x) : null;
          if (!r.ok) throw new Error((d && d.detail) || "Ошибка");
          return d;
        });
      })
      .then(function (user) {
        setSession(getToken(), user);
        refresh();
        if (typeof onDone === "function") onDone(user);
      })
      .catch(function (err) {
        window.alert(err.message || "Не удалось убрать фото");
      });
  }

  // ── init ─────────────────────────────────────────────────────────────────
  function init() {
    injectStyles();
    mountWidget();
    refresh();
    // Внешние хуки экосистемы (вход/профиль/выход/данные).
    window.STAW = window.STAW || {};
    window.STAW.api = api; // авторизованный fetch к бэкенду (Bearer) для других модулей
    window.STAW.token = getToken;
    window.STAW.refreshAccount = refresh; // обновить баллы/профиль (напр. после заказа)
    window.STAW.openLogin = function () { openModal("login"); };
    window.STAW.openRegister = function () { openModal("register"); };
    window.STAW.getUser = getUser;
    // Единый аватар экосистемы: показать/сменить/убрать с сайта.
    window.STAW.avatarUrl = avatarUrl;
    window.STAW.changeAvatar = changeAvatar;
    window.STAW.removeAvatar = removeAvatar;
    window.STAW.logout = function () {
      clearSession();
      window.STAW.ecoPoints = 0;
      renderLoggedOut();
    };
    window.STAW.setUser = function (u) {
      try {
        localStorage.setItem(LS_USER, JSON.stringify(u || {}));
      } catch (e) {}
      if (getToken()) renderLoggedIn(u, (window.STAW && window.STAW.ecoPoints) || 0);
    };

    // Хук «Конструктора»: открыть/закрыть/переключить экран входа. Команды шлёт
    // editor.js по сообщению из консоли (кнопка «Экран входа»). Модалка открывается
    // НА МЕСТЕ — ровно как на живом сайте (по центру), без отдельного экрана.
    window.MATA_AUTH = {
      open: function (mode) { openModal(mode); },
      close: closeModal,
      setMode: function (mode) { openModal(mode); },
    };
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
