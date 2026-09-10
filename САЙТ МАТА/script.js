const header = document.querySelector("[data-header]");
const filters = document.querySelectorAll("[data-filter]");
const cartPanel = document.querySelector("[data-cart-panel]");
const overlay = document.querySelector("[data-overlay]");
const cartToggles = document.querySelectorAll("[data-cart-toggle]");
const cartItems = document.querySelector("[data-cart-items]");
const cartCount = document.querySelector("[data-cart-count]");
const cartTotal = document.querySelector("[data-cart-total]");

const cart = [];
let currentFilter = "all";
let currentSearch = "";

function updateHeader() {
  header.classList.toggle("is-scrolled", window.scrollY > 24);
}

// Фильтр по категории + текстовый поиск (по названию). Перезапрашиваем DOM,
// т.к. фильтры/карточки могут перерисовываться из API (catalog.js).
function applyCatalog() {
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.filter === currentFilter);
  });
  const q = currentSearch.trim().toLowerCase();
  document.querySelectorAll(".product-card").forEach((card) => {
    const cats = (card.dataset.category || "").split(" ");
    const okCat = currentFilter === "all" || cats.indexOf(currentFilter) !== -1;
    const h3 = card.querySelector("h3");
    const name = (card.dataset.name || (h3 ? h3.textContent : "") || "").toLowerCase();
    const okSearch = !q || name.indexOf(q) !== -1;
    card.classList.toggle("is-hidden", !(okCat && okSearch));
  });
}

function applyFilter(category) {
  currentFilter = category;
  applyCatalog();
}

function toggleCart() {
  cartPanel.classList.toggle("is-open");
  overlay.classList.toggle("is-open");
}

function formatPrice(value) {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// Добавление с группировкой одинаковых позиций (увеличиваем количество).
// id товара уходит в заказ: по нему сервер сверяет цену с каталогом (D-37, D-72).
function addToCart(name, price, id) {
  const existing = cart.find((i) => (id ? i.id === id : i.name === name));
  if (existing) existing.qty += 1;
  else cart.push({ id: id || "", name: name, price: Number(price), qty: 1 });
  renderCart();
}

function renderCart() {
  const totalQty = cart.reduce((sum, i) => sum + i.qty, 0);
  cartCount.textContent = totalQty;

  const cb = document.querySelector("[data-checkout]");
  if (cb) cb.disabled = cart.length === 0;

  if (cart.length === 0) {
    cartItems.innerHTML = '<p class="empty-cart">Корзина пуста</p>';
    cartTotal.textContent = "0 ₽";
    return;
  }

  const total = cart.reduce((sum, i) => sum + i.price * i.qty, 0);

  cartItems.innerHTML = cart
    .map(
      (item, idx) => `
        <div class="cart-item">
          <div class="cart-item-main">
            <p>${escapeHtml(item.name)}</p>
            <div class="cart-qty">
              <button type="button" data-qty-dec="${idx}" aria-label="Уменьшить количество">−</button>
              <span>${item.qty}</span>
              <button type="button" data-qty-inc="${idx}" aria-label="Увеличить количество">+</button>
            </div>
          </div>
          <div class="cart-item-side">
            <span>${formatPrice(item.price * item.qty)}</span>
            <button type="button" class="cart-remove" data-remove="${idx}" aria-label="Удалить из корзины">×</button>
          </div>
        </div>
      `,
    )
    .join("");

  cartTotal.textContent = formatPrice(total);

  cartItems.querySelectorAll("[data-qty-inc]").forEach((b) =>
    b.addEventListener("click", () => {
      cart[Number(b.dataset.qtyInc)].qty += 1;
      renderCart();
    }),
  );
  cartItems.querySelectorAll("[data-qty-dec]").forEach((b) =>
    b.addEventListener("click", () => {
      const i = Number(b.dataset.qtyDec);
      cart[i].qty -= 1;
      if (cart[i].qty <= 0) cart.splice(i, 1);
      renderCart();
    }),
  );
  cartItems.querySelectorAll("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => {
      cart.splice(Number(b.dataset.remove), 1);
      renderCart();
    }),
  );
}

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        settleReveal(entry.target);
        revealObserver.unobserve(entry.target);
      }
    });
  },
  {
    rootMargin: "0px 0px -12% 0px",
    threshold: 0.18,
  },
);

// Снять фильтр появления, когда переход доиграл. `filter: blur(0)` — это не
// «фильтра нет»: он остаётся на блоке и сплющивает 3D внутри него (у карт
// лояльности из-за этого просвечивала лицевая сторона сквозь перевёрнутую).
// Ждём именно переход фильтра; таймер — страховка на случай, когда события нет
// (блок уже виден при загрузке, вкладка в фоне, prefers-reduced-motion).
function settleReveal(el) {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    el.classList.add("is-settled");
    el.removeEventListener("transitionend", onEnd);
  };
  const onEnd = (e) => { if (e.target === el && e.propertyName === "filter") finish(); };
  el.addEventListener("transitionend", onEnd);
  setTimeout(finish, 1600);
}

// Привязки, переживающие пере-рендер каталога (помечаем элементы, чтобы не дублировать).
function observeReveals() {
  document.querySelectorAll(".reveal:not([data-revealed])").forEach((item, index) => {
    item.setAttribute("data-revealed", "1");
    item.style.setProperty("--delay", `${Math.min(index % 4, 3) * 90}ms`);
    revealObserver.observe(item);
  });
}

function bindAddButtons() {
  document.querySelectorAll("[data-add-cart]:not([data-bound])").forEach((button) => {
    button.setAttribute("data-bound", "1");
    button.addEventListener("click", () => {
      addToCart(button.dataset.addCart, button.dataset.price, button.dataset.productId);
      if (!cartPanel.classList.contains("is-open")) {
        toggleCart();
      }
    });
  });
}

// Делегирование: работает и для динамических фильтров из /categories.
const catalogBar = document.querySelector(".catalog-bar");
if (catalogBar) {
  catalogBar.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-filter]");
    if (btn) applyFilter(btn.dataset.filter);
  });
}

const searchInput = document.querySelector("[data-search]");
if (searchInput) {
  searchInput.addEventListener("input", () => {
    currentSearch = searchInput.value;
    applyCatalog();
  });
}

cartToggles.forEach((button) => {
  button.addEventListener("click", toggleCart);
});

// ── Мобильное меню (гамбургер) ───────────────────────────────────────────────
const navToggle = document.querySelector("[data-nav-toggle]");
const mobileNav = document.querySelector("[data-mobile-nav]");
const navBackdrop = document.querySelector("[data-nav-backdrop]");

function setMobileNav(open) {
  if (!mobileNav) return;
  mobileNav.classList.toggle("is-open", open);
  if (navBackdrop) navBackdrop.classList.toggle("is-open", open);
  if (navToggle) {
    navToggle.classList.toggle("is-open", open);
    navToggle.setAttribute("aria-expanded", String(open));
  }
}

if (navToggle) {
  navToggle.addEventListener("click", () =>
    setMobileNav(!mobileNav.classList.contains("is-open")),
  );
}
if (navBackdrop) navBackdrop.addEventListener("click", () => setMobileNav(false));
document.querySelectorAll("[data-mobile-link]").forEach((link) => {
  link.addEventListener("click", () => setMobileNav(false));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && mobileNav && mobileNav.classList.contains("is-open")) {
    setMobileNav(false);
  }
});

// ── Подписка в футере (демо, без бэкенда) ────────────────────────────────────
const subForm = document.querySelector("[data-sub-form]");
if (subForm) {
  subForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const email = subForm.querySelector("[data-sub-email]");
    const note = document.querySelector("[data-sub-note]");
    const val = ((email && email.value) || "").trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(val)) {
      if (note) note.textContent = "Введите корректный email";
      return;
    }
    if (note) note.textContent = "Готово! Вы подписаны.";
    subForm.reset();
  });
}

// CTA «Войти в аккаунт» (блок лояльности, мобильное меню) → модалка входа экосистемы.
document.querySelectorAll("[data-eco-login-cta]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (window.STAW && typeof window.STAW.openLogin === "function") {
      window.STAW.openLogin();
    }
  });
});

// CTA «Мой профиль» (виден только в аккаунте) → профиль.
document.querySelectorAll("[data-eco-profile-cta]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (window.STAW && typeof window.STAW.openProfile === "function") {
      window.STAW.openProfile();
    }
  });
});

// ── Быстрый просмотр товара (quick view) ─────────────────────────────────────
const pvModal = document.querySelector("[data-pv-modal]");
let pvCurrent = null; // {name, price}
let pvSize = null;

function pvBuildColors(card) {
  const wrap = pvModal.querySelector("[data-pv-colors]");
  const colors = (card.dataset.colors || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  wrap.innerHTML = colors.map((c) => `<i style="--c:${c}"></i>`).join("");
}

function pvBuildSizes(card) {
  const wrap = pvModal.querySelector("[data-pv-sizes]");
  const sizes = (card.dataset.sizes || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  // Размеры, которых нет на складе (остаток по размерам из 1С): показываем, но
  // выбрать нельзя. Спрятать их — значит заставить человека гадать, был ли его размер.
  const out = (card.dataset.outofstock || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  pvSize = null;
  wrap.innerHTML = sizes
    .map((s) => {
      const gone = out.includes(s);
      return `<button type="button" data-size="${s}"${
        gone ? ' class="is-out" disabled aria-disabled="true"' : ""
      }>${s}</button>`;
    })
    .join("");
  wrap.querySelectorAll("button:not([disabled])").forEach((b) => {
    b.addEventListener("click", () => {
      wrap.querySelectorAll("button").forEach((x) => x.classList.remove("is-selected"));
      b.classList.add("is-selected");
      pvSize = b.dataset.size;
    });
  });
}

function openQuickView(card) {
  if (!pvModal || !card) return;
  pvCurrent = { name: card.dataset.name, price: Number(card.dataset.price) };
  const img = pvModal.querySelector("[data-pv-img]");
  img.src = card.dataset.img || "";
  img.alt = card.dataset.name || "";
  pvModal.querySelector("[data-pv-cat]").textContent = card.dataset.cat || "";
  pvModal.querySelector("[data-pv-name]").textContent = card.dataset.name || "";
  pvModal.querySelector("[data-pv-price]").textContent = formatPrice(Number(card.dataset.price));
  pvModal.querySelector("[data-pv-desc]").textContent = card.dataset.desc || "";
  const stockEl = pvModal.querySelector("[data-pv-stock]");
  const stock = card.dataset.stock || "В наличии";
  stockEl.textContent = stock;
  stockEl.style.color = /скоро/i.test(stock) ? "var(--muted)" : "#2e8b6f";
  pvBuildColors(card);
  pvBuildSizes(card);
  pvModal.classList.add("is-open");
  pvModal.setAttribute("aria-hidden", "false");
}

function closeQuickView() {
  if (!pvModal) return;
  pvModal.classList.remove("is-open");
  pvModal.setAttribute("aria-hidden", "true");
}

function bindQuickView() {
  document.querySelectorAll("[data-quick-view]:not([data-bound])").forEach((el) => {
    el.setAttribute("data-bound", "1");
    const card = el.closest(".product-card");
    el.addEventListener("click", () => openQuickView(card));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openQuickView(card);
      }
    });
  });
}

if (pvModal) {
  pvModal.querySelectorAll("[data-pv-close]").forEach((b) =>
    b.addEventListener("click", closeQuickView),
  );
  pvModal.querySelector("[data-pv-add]").addEventListener("click", () => {
    if (!pvCurrent) return;
    const label = pvCurrent.name + (pvSize ? " · " + pvSize : "");
    addToCart(label, pvCurrent.price);
    closeQuickView();
    if (!cartPanel.classList.contains("is-open")) toggleCart();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && pvModal.classList.contains("is-open")) closeQuickView();
  });
}

// ── Оформление заказа (checkout) ─────────────────────────────────────────────
const coModal = document.querySelector("[data-co-modal]");
const checkoutBtn = document.querySelector("[data-checkout]");
let coPointsApplied = 0;
// Нажали «Оформить», не войдя: после входа форма заказа откроется сама (D-72).
let checkoutAfterLogin = false;

function cartTotalValue() {
  return cart.reduce((s, i) => s + i.price * i.qty, 0);
}

function isLoggedIn() {
  try {
    return !!localStorage.getItem("staw_jwt");
  } catch (e) {
    return false;
  }
}

function availablePoints() {
  if (!isLoggedIn()) return 0;
  // Только настоящий баланс: демо-значение давало скидку баллами, которых нет.
  return (window.STAW && window.STAW.ecoPoints) || 0;
}

function coRecompute() {
  if (!coModal) return;
  const goods = cartTotalValue();
  const maxByOrder = Math.floor(goods * 0.3);
  const avail = availablePoints();
  const toggle = coModal.querySelector("[data-co-points-toggle]");
  const wantPoints = toggle && toggle.checked;
  // Правила списания — как на сервере (D-72): от 50 баллов, не больше 30% заказа.
  const canApply = Math.min(avail, maxByOrder);
  coPointsApplied = wantPoints && canApply >= 50 ? canApply : 0;
  const total = goods - coPointsApplied;

  coModal.querySelector("[data-co-goods]").textContent = formatPrice(goods);
  const discRow = coModal.querySelector("[data-co-discount-row]");
  if (coPointsApplied > 0) {
    discRow.hidden = false;
    coModal.querySelector("[data-co-discount]").textContent = "−" + formatPrice(coPointsApplied);
  } else {
    discRow.hidden = true;
  }
  coModal.querySelector("[data-co-total]").textContent = formatPrice(total);

  const note = coModal.querySelector("[data-co-points-note]");
  if (note) {
    note.textContent =
      "Списываем до 30% заказа — максимум " + formatPrice(Math.min(avail, maxByOrder));
  }
}

function openCheckout() {
  if (!coModal || cart.length === 0) return;
  const pb = coModal.querySelector("[data-co-points-block]");
  const avail = availablePoints();
  if (pb) {
    pb.hidden = !(isLoggedIn() && avail > 0);
    coModal.querySelector("[data-co-points-avail]").textContent = avail;
    const t = coModal.querySelector("[data-co-points-toggle]");
    if (t) t.checked = false;
  }
  coModal.querySelector('[data-co-view="form"]').hidden = false;
  coModal.querySelector('[data-co-view="success"]').hidden = true;
  coModal.querySelector("[data-co-err]").textContent = "";
  coRecompute();
  coModal.classList.add("is-open");
  coModal.setAttribute("aria-hidden", "false");
}

function closeCheckout() {
  if (!coModal) return;
  coModal.classList.remove("is-open");
  coModal.setAttribute("aria-hidden", "true");
}

if (coModal) {
  coModal.querySelectorAll("[data-co-close]").forEach((b) =>
    b.addEventListener("click", closeCheckout),
  );
  const ptoggle = coModal.querySelector("[data-co-points-toggle]");
  if (ptoggle) ptoggle.addEventListener("change", coRecompute);

  coModal.querySelector("[data-co-submit]").addEventListener("click", () => {
    const name = (coModal.querySelector("[data-co-name]").value || "").trim();
    const phone = (coModal.querySelector("[data-co-phone]").value || "").trim();
    const email = (coModal.querySelector("[data-co-email]").value || "").trim();
    const err = coModal.querySelector("[data-co-err]");
    if (!name) {
      err.textContent = "Укажите имя";
      return;
    }
    if (phone.replace(/\D/g, "").length < 10) {
      err.textContent = "Укажите телефон";
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      err.textContent = "Укажите корректный email";
      return;
    }
    err.textContent = "";

    const submitBtn = coModal.querySelector("[data-co-submit]");
    const orderId = "МАТА-" + String(Math.floor(Math.random() * 900000) + 100000);
    const goods = cartTotalValue();
    const delivery = (coModal.querySelector('input[name="co-delivery"]:checked') || {}).value || "courier";
    const pay = "sbp"; // единственный способ оплаты (D-72)
    const address = (coModal.querySelector("[data-co-address]").value || "").trim();
    const payload = {
      id: orderId,
      total: goods - coPointsApplied,
      subtotal: goods,
      deliveryCost: 0,
      pointsRedeemed: coPointsApplied,
      status: "pending",
      items: cart.map((i) => ({
        productId: i.id,
        productName: i.name,
        price: i.price,
        quantity: i.qty,
      })),
      checkoutData: {
        name: name,
        phone: phone,
        email: email,
        deliveryType: delivery,
        paymentType: pay,
        address: address,
        source: "Сайт",
      },
    };

    function done(finalId) {
      coModal.querySelector("[data-co-order-id]").textContent = finalId;
      coModal.querySelector('[data-co-view="form"]').hidden = true;
      coModal.querySelector('[data-co-view="success"]').hidden = false;
      cart.length = 0;
      renderCart();
      // Сервер начислил баллы за покупку — обновляем баланс/профиль.
      if (window.STAW && typeof window.STAW.refreshAccount === "function") {
        window.STAW.refreshAccount();
      }
      submitBtn.disabled = false;
      submitBtn.textContent = "Подтвердить заказ";
    }

    // ── Оплата ────────────────────────────────────────────────────────────
    // Заказ уже принят сервером; здесь только деньги. Если оплата на бэкенде
    // выключена (dev), сервер отвечает status: "paid" — тогда сразу «оформлен».
    let payPoll = null;

    function stopPoll() {
      if (payPoll) {
        clearInterval(payPoll);
        payPoll = null;
      }
    }

    function showPayView(finalId, url) {
      coModal.querySelector("[data-co-pay-order]").textContent = "Заказ " + finalId;
      coModal.querySelector('[data-co-view="form"]').hidden = true;
      coModal.querySelector('[data-co-view="payment"]').hidden = false;
      cart.length = 0;
      renderCart();
      submitBtn.disabled = false;
      submitBtn.textContent = "Подтвердить заказ";

      const open = coModal.querySelector("[data-co-pay-open]");
      const status = coModal.querySelector("[data-co-pay-status]");
      const check = coModal.querySelector("[data-co-pay-check]");
      const openPay = () => window.open(url, "_blank", "noopener");

      open.onclick = openPay;
      check.onclick = () => checkPay(finalId, status, true);
      openPay(); // сразу ведём на оплату: клик по «Подтвердить» — это и был жест

      stopPoll();
      payPoll = setInterval(() => checkPay(finalId, status, false), 3000);
      // Через 15 минут перестаём опрашивать: ссылка на оплату всё равно протухнет.
      setTimeout(stopPoll, 15 * 60 * 1000);
    }

    function checkPay(finalId, status, manual) {
      window.STAW
        .api("/orders/" + encodeURIComponent(finalId) + "/payment")
        .then((s) => {
          const st = (s && s.status) || "pending";
          if (st === "paid") {
            stopPoll();
            coModal.querySelector('[data-co-view="payment"]').hidden = true;
            done(finalId);
          } else if (st === "canceled") {
            stopPoll();
            status.textContent = "Оплата не прошла. Попробуйте ещё раз.";
          } else if (manual) {
            status.textContent = "Пока не видим оплату. Проверим ещё раз через минуту.";
          }
        })
        .catch(() => {
          if (manual) status.textContent = "Не удалось проверить. Попробуйте ещё раз.";
        });
    }

    function startPayment(finalId) {
      window.STAW
        .api("/orders/" + encodeURIComponent(finalId) + "/pay", {
          method: "POST",
          body: {},
        })
        .then((r) => {
          const url = (r && r.confirmationUrl) || "";
          if ((r && r.status) === "paid" || !url) {
            done(finalId); // оплата не требуется (dev) — сразу «оформлен»
          } else {
            showPayView(finalId, url);
          }
        })
        .catch(() => {
          // Заказ создан, а платёж не стартовал: не врём про успех — заказ можно
          // оплатить позже из профиля.
          err.textContent = "Заказ сохранён, но оплата недоступна. Попробуйте позже.";
          submitBtn.disabled = false;
          submitBtn.textContent = "Подтвердить заказ";
        });
    }

    const loggedIn =
      window.STAW && typeof window.STAW.token === "function" && window.STAW.token();
    if (loggedIn && typeof window.STAW.api === "function") {
      submitBtn.disabled = true;
      submitBtn.textContent = "Оформляем…";
      window.STAW
        .api("/orders", { method: "POST", body: payload })
        .then((o) => startPayment((o && o.id) || orderId))
        .catch(() => {
          // Заказ не дошёл до сервера — «оформлен» не показываем (D-72): человек
          // ждал бы посылку, которой нет. Корзина цела, можно повторить.
          err.textContent = "Не удалось оформить заказ. Проверьте соединение и попробуйте ещё раз.";
          submitBtn.disabled = false;
          submitBtn.textContent = "Подтвердить заказ";
        });
    } else {
      // Без входа заказ не оформляем (D-72) — например, вышли из аккаунта, пока форма
      // была открыта. Возвращаем ко входу; после него форма откроется снова.
      closeCheckout();
      requireLoginForCheckout();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && coModal.classList.contains("is-open")) closeCheckout();
  });
}

// Приход со второй страницы («Философия» → корзина): открываем панель сразу,
// иначе человек попадает на главную и ищет корзину заново.
if (new URLSearchParams(location.search).get("cart") === "1") {
  window.addEventListener("load", function () {
    if (cartPanel && !cartPanel.classList.contains("is-open")) toggleCart();
    // Убираем параметр из адреса: обновление страницы не должно снова открывать корзину.
    try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {}
  });
}

// Оформить заказ можно только из аккаунта (D-72): корзину собирают и без входа,
// но перед вводом данных и оплатой — регистрация или вход по номеру телефона.
function requireLoginForCheckout() {
  if (!window.STAW || typeof window.STAW.openRegister !== "function") return;
  checkoutAfterLogin = true;
  window.STAW.openRegister();
}

if (checkoutBtn) {
  checkoutBtn.addEventListener("click", () => {
    if (cartPanel.classList.contains("is-open")) toggleCart();
    if (!isLoggedIn()) {
      requireLoginForCheckout();
      return;
    }
    openCheckout();
  });
}

// Вошли после нажатия «Оформить» — продолжаем с того же места.
window.addEventListener("staw-auth", () => {
  if (!checkoutAfterLogin) return;
  checkoutAfterLogin = false;
  openCheckout();
});

// ── Сортировка каталога ──────────────────────────────────────────────────────
const sortSelect = document.querySelector("[data-sort]");
function applySort(mode) {
  const grid = document.querySelector("[data-product-grid]");
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll(".product-card"));
  cards.forEach((c, i) => {
    if (c.dataset.order === undefined) c.dataset.order = String(i);
  });
  cards.sort((a, b) => {
    const pa = Number(a.dataset.price) || 0;
    const pb = Number(b.dataset.price) || 0;
    if (mode === "price-asc") return pa - pb;
    if (mode === "price-desc") return pb - pa;
    if (mode === "name") {
      return (a.dataset.name || "").localeCompare(b.dataset.name || "", "ru");
    }
    return Number(a.dataset.order) - Number(b.dataset.order);
  });
  cards.forEach((c) => grid.appendChild(c));
}
if (sortSelect) {
  sortSelect.addEventListener("change", () => applySort(sortSelect.value));
}

// ── Профиль аккаунта ─────────────────────────────────────────────────────────
const prModal = document.querySelector("[data-pr-modal]");

function prGetUser() {
  if (window.STAW && typeof window.STAW.getUser === "function") {
    return window.STAW.getUser() || {};
  }
  return {};
}

// Под-экраны профиля: menu | edit | levels | orders.
function prSetView(view) {
  prModal.querySelector("[data-pr-menu]").hidden = view !== "menu";
  prModal.querySelector("[data-pr-edit-form]").hidden = view !== "edit";
  const lv = prModal.querySelector("[data-pr-levels]");
  if (lv) lv.hidden = view !== "levels";
  const ov = prModal.querySelector("[data-pr-orders-view]");
  if (ov) ov.hidden = view !== "orders";
  const gear = prModal.querySelector("[data-pr-gear]");
  if (gear) {
    gear.textContent = view === "menu" ? "⚙" : "←";
    gear.setAttribute("aria-label", view === "menu" ? "Редактировать профиль" : "Назад к профилю");
  }
}

// Демо-заказы (фолбэк, если бэкенд недоступен).
const PR_ORDERS_DEMO = [
  { id: "МАТА-205990", source: "Сайт", date: "сегодня", items: "Everyday Training Layer", total: 3190, status: "Принят" },
  { id: "МАТА-198003", source: "Приложение «Квартал»", date: "18 июня", items: "City Motion Tee ×2", total: 2980, status: "Доставлен" },
  { id: "SS-191244", source: "МАТА Store", date: "5 июня", items: "Marathon Training Shorts", total: 2490, status: "Доставлен" },
];

function prStatusMap(s) {
  s = String(s || "").toLowerCase();
  if (s === "delivered" || /доставлен/.test(s)) return { label: "Доставлен", cls: "is-done" };
  if (s === "shipped" || /доставля/.test(s)) return { label: "Доставляется", cls: "is-ship" };
  if (s === "processing" || /собира/.test(s)) return { label: "Собирается", cls: "is-pack" };
  if (s === "cancelled" || /отмен/.test(s)) return { label: "Отменён", cls: "" };
  return { label: "Принят", cls: "is-new" };
}

function prOrderSource(o) {
  if (o.source) return o.source;
  var cd = o.checkoutData || {};
  if (cd.source) return cd.source;
  var id = String(o.id || "");
  if (/^SS-/i.test(id)) return "МАТА Store";
  if (/^(STAW|МАТА)-/i.test(id)) return "Сайт";
  return "Экосистема";
}

function prOrderItems(o) {
  if (typeof o.items === "string") return o.items;
  if (Array.isArray(o.items)) {
    return o.items
      .map(function (i) {
        var n = i.productName || i.name || "Товар";
        return i.quantity > 1 ? n + " ×" + i.quantity : n;
      })
      .join(", ");
  }
  return "";
}

function prOrderDate(o) {
  if (o.date) return o.date;
  if (o.createdAt) {
    try {
      return new Date(o.createdAt).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
    } catch (e) {}
  }
  return "";
}

function prRenderOrders(orders) {
  const list = prModal.querySelector("[data-pr-orders-list]");
  if (!list) return;
  if (!Array.isArray(orders) || !orders.length) {
    list.innerHTML = '<p class="pr-addr-empty">Заказов пока нет.</p>';
    return;
  }
  list.innerHTML = orders
    .map(function (o) {
      var st = prStatusMap(o.status);
      return (
        '<div class="pr-order">' +
        '<div class="pr-order-top">' +
        '<span class="pr-order-id">' + escapeHtml(o.id || "") + "</span>" +
        '<span class="pr-order-status ' + st.cls + '">' + st.label + "</span>" +
        "</div>" +
        '<p class="pr-order-items">' + escapeHtml(prOrderItems(o)) + "</p>" +
        '<div class="pr-order-bot">' +
        '<span class="pr-order-src">' + escapeHtml(prOrderSource(o)) + " · " + escapeHtml(prOrderDate(o)) + "</span>" +
        '<span class="pr-order-total">' + formatPrice(o.total || 0) + "</span>" +
        "</div></div>"
      );
    })
    .join("");
}

function prShowOrders() {
  prSetView("orders");
  const list = prModal.querySelector("[data-pr-orders-list]");
  if (list) list.innerHTML = '<p class="pr-addr-empty">Загрузка…</p>';
  if (window.STAW && typeof window.STAW.api === "function") {
    window.STAW
      .api("/orders")
      .then(prRenderOrders)
      .catch(function () {
        prRenderOrders(PR_ORDERS_DEMO);
      });
  } else {
    prRenderOrders(PR_ORDERS_DEMO);
  }
}

// Человекочитаемая строка из структурного адреса {city,street,house,building,apartment}
// (или из старой строки — обратная совместимость).
function prAddrLine(a) {
  if (typeof a === "string") return a;
  if (!a || typeof a !== "object") return "Адрес";
  let line = [a.city, a.street, a.house].filter(Boolean).join(", ");
  if (a.building) line += ", корп. " + a.building;
  if (a.apartment) line += ", кв. " + a.apartment;
  return line || a.label || "Адрес";
}

// Адреса доставки — единые в экосистеме (структурные объекты). Отдаём как есть.
function prGetAddresses() {
  const u = prGetUser();
  if (u && Array.isArray(u.addresses) && u.addresses.length) {
    return u.addresses.slice();
  }
  // Фолбэк (демо, до первого входа): локально добавленные.
  try {
    return JSON.parse(localStorage.getItem("staw_addresses") || "[]");
  } catch (e) {
    return [];
  }
}

function prSaveAddresses(arr) {
  try {
    localStorage.setItem("staw_addresses", JSON.stringify(arr));
  } catch (e) {}
}

// Рабочий список адресов в редакторе; сохраняется в бэкенд по кнопке «Сохранить».
let prEditAddr = [];

function prRenderAddresses() {
  const list = prModal.querySelector("[data-pr-addr-list]");
  if (!list) return;
  if (!prEditAddr.length) {
    list.innerHTML = '<p class="pr-addr-empty">Пока нет сохранённых адресов.</p>';
    return;
  }
  list.innerHTML = prEditAddr
    .map(
      (a, i) => `
      <div class="pr-addr-row">
        <span>${escapeHtml(prAddrLine(a))}</span>
        <button type="button" class="pr-addr-del" data-addr-del="${i}" aria-label="Удалить адрес">×</button>
      </div>`,
    )
    .join("");
  list.querySelectorAll("[data-addr-del]").forEach((b) =>
    b.addEventListener("click", () => {
      prEditAddr.splice(Number(b.dataset.addrDel), 1);
      prRenderAddresses();
    }),
  );
}

function prShowMenu() {
  prSetView("menu");
}

function prShowEdit() {
  const u = prGetUser();
  prModal.querySelector("[data-pr-edit-name]").value = u.name || "";
  prModal.querySelector("[data-pr-edit-phone]").value = u.phone || "";
  prModal.querySelector("[data-pr-edit-email]").value = u.email || "";
  prEditAddr = prGetAddresses().slice();
  prRenderAddresses();
  prSetView("edit");
}

function prCurrentLevelKey(points) {
  if (points >= 1000) return "platinum";
  if (points >= 500) return "gold";
  if (points >= 200) return "silver";
  return "basic";
}

function prShowLevels() {
  const points = (window.STAW && window.STAW.ecoPoints) || 0;
  const cur = prCurrentLevelKey(points);
  prRenderCard(points);
  prModal.querySelectorAll("[data-level-key]").forEach((el) => {
    el.classList.toggle("is-current", el.getAttribute("data-level-key") === cur);
  });
  prSetView("levels");
}

// ── Единая карта лояльности МАТА (дизайн-проект v5): живое лицо в профиле ────
// Словомарка (М·А·А + акцентная Т) и знак (три луча) — точные пути бренда,
// те же, что в LoyaltyCard3D приложений. Материал/анимации — styles.css (.lc-*).
const LC_WM =
  '<svg class="lc-wm" viewBox="312 580 656 112" xmlns="http://www.w3.org/2000/svg">' +
  '<path class="m" d="M327.996 580H324.857H312V691.964H327.996V585.434L389.495 691.964H407.964L343.326 580H327.996Z"/>' +
  '<path class="m" d="M487.937 580H472.606L407.964 691.964H426.432L487.937 585.434V691.964H503.933V580H491.075H487.937Z"/>' +
  '<path class="m" d="M619.03 580H612.759H600.562L535.924 691.964H554.393L563.625 675.969H633.446L642.678 659.973H572.861L615.897 585.434L677.397 691.964H695.866L631.228 580H619.03Z"/>' +
  '<path class="t" d="M814.324 580H688.838L679.605 595.996H743.583H759.579H823.556L814.324 580Z"/>' +
  '<path class="t" d="M759.848 611.991H743.853V691.964H759.848V611.991Z"/>' +
  '<path class="m" d="M903.402 580H890.135H884.933H871.666L807.023 691.964H825.492L887.534 584.504L931.103 659.973H860.485L869.717 675.969H940.339L949.571 691.964H968.04L903.402 580Z"/>' +
  "</svg>";
const LC_SIGN =
  '<svg class="lc-sign" viewBox="490 472 300 336" xmlns="http://www.w3.org/2000/svg">' +
  '<path d="M502.371 500.66L578.165 632.29L599.723 632.311L562.451 567.578L513.177 482L502.371 500.66Z"/>' +
  '<path d="M769.167 632.534L617.277 632.359L606.477 651.019L681.175 651.109L779.925 651.221L769.167 632.534Z"/>' +
  '<path d="M521.563 797.65L597.66 666.195L586.902 647.509L549.471 712.156L500 797.623L521.563 797.65Z"/>' +
  "</svg>";
const LC_METAL =
  '<svg width="0" height="0" style="position:absolute"><defs>' +
  '<linearGradient id="lcPlatMetal" x1="0" y1="0" x2="0" y2="1">' +
  '<stop offset="0" stop-color="#F6FAFE"/><stop offset=".45" stop-color="#C9D5E2"/>' +
  '<stop offset=".55" stop-color="#93A2B3"/><stop offset=".7" stop-color="#DCE6F0"/>' +
  '<stop offset="1" stop-color="#AEBCCB"/></linearGradient></defs></svg>';

function prRenderCard(points) {
  const slot = prModal && prModal.querySelector("[data-pr-card]");
  if (!slot) return;
  const lv = prComputeLevel(points);
  const u = prGetUser();
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const name = esc(((u && u.name) || "Гость МАТА").toUpperCase());
  slot.innerHTML =
    LC_METAL +
    '<div class="lc lc-' + lv.key + '"><div class="lc-tilt"><div class="lc-card">' +
    (lv.key === "platinum" ? '<div class="lc-aur"><i></i><i></i><i></i></div>' : "") +
    (lv.key !== "basic" ? LC_SIGN : "") +
    (lv.key === "platinum" ? LC_SIGN.replace('class="lc-sign"', 'class="lc-signGlow"') : "") +
    (lv.key === "platinum" ? '<div class="lc-edge"></div>' : "") +
    '<div class="lc-rowTop">' + LC_WM +
    '<span class="lc-lvl">' + esc(lv.name.toUpperCase()) + "</span></div>" +
    '<div class="lc-pts"><span class="n">' + points + '</span><span class="l">' +
    prPtsWord(points) + "</span></div>" +
    '<div class="lc-rowBot"><span class="lc-holder"><span class="cap">ДЕРЖАТЕЛЬ</span>' +
    '<span class="nm">' + name + "</span></span>" +
    '<span class="lc-uni">ЕДИНАЯ КАРТА</span></div>' +
    "</div></div></div>";
  // 3D-наклон платины за курсором (как в дизайн-проекте; в приложениях — гироскоп).
  if (lv.key === "platinum") {
    const scene = slot.querySelector(".lc");
    const tilt = slot.querySelector(".lc-tilt");
    scene.addEventListener("mousemove", (e) => {
      const r = scene.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      tilt.style.transform =
        "rotateX(" + (-py * 10).toFixed(2) + "deg) rotateY(" + (px * 14).toFixed(2) + "deg)";
    });
    scene.addEventListener("mouseleave", () => { tilt.style.transform = ""; });
  }
}

const PR_TIERS = [
  { key: "basic", name: "Базовый", min: 0 },
  { key: "silver", name: "Серебро", min: 200 },
  { key: "gold", name: "Золото", min: 500 },
  { key: "platinum", name: "Платина", min: 1000 },
];

function prPtsWord(n) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return "баллов";
  if (b === 1) return "балл";
  if (b >= 2 && b <= 4) return "балла";
  return "баллов";
}

// Реальный уровень из баланса баллов + прогресс до следующего.
function prComputeLevel(points) {
  let i = 0;
  for (let j = PR_TIERS.length - 1; j >= 0; j--) {
    if (points >= PR_TIERS[j].min) {
      i = j;
      break;
    }
  }
  const cur = PR_TIERS[i];
  const next = PR_TIERS[i + 1] || null;
  let progress = 100;
  let toNext = 0;
  if (next) {
    progress = Math.max(0, Math.min(100, ((points - cur.min) / (next.min - cur.min)) * 100));
    toNext = next.min - points;
  }
  return { key: cur.key, name: cur.name, next: next, toNext: toNext, progress: progress };
}

function prPopulate() {
  if (!prModal) return;
  const u = prGetUser();
  const name = u.name || "Профиль";
  prModal.querySelector("[data-pr-name]").textContent = name;
  prModal.querySelector("[data-pr-phone]").textContent = u.phone || "";

  // Единый аватар экосистемы: фото с сервера (если есть), иначе инициал.
  const avEl = prModal.querySelector("[data-pr-initial]");
  const avUrl =
    window.STAW && window.STAW.avatarUrl ? window.STAW.avatarUrl(u) : "";
  if (avEl) {
    if (avUrl) {
      avEl.style.backgroundImage = "url('" + avUrl + "')";
      avEl.textContent = "";
      avEl.classList.add("has-photo");
    } else {
      avEl.style.backgroundImage = "";
      avEl.textContent = (name.trim().charAt(0) || "S").toUpperCase();
      avEl.classList.remove("has-photo");
    }
    if (!avEl.dataset.avBound) {
      avEl.dataset.avBound = "1";
      avEl.title = "Сменить фото";
      avEl.addEventListener("click", () => {
        if (window.STAW && window.STAW.changeAvatar) {
          window.STAW.changeAvatar(() => prPopulate());
        }
      });
    }
  }
  // Ссылка «Убрать фото» — только когда фото есть.
  const head = prModal.querySelector(".pr-head");
  let rm = prModal.querySelector("[data-pr-avatar-remove]");
  if (avUrl && head) {
    if (!rm) {
      rm = document.createElement("button");
      rm.setAttribute("data-pr-avatar-remove", "");
      rm.className = "pr-avatar-remove";
      rm.type = "button";
      rm.textContent = "Убрать фото";
      rm.addEventListener("click", (e) => {
        e.stopPropagation();
        if (window.STAW && window.STAW.removeAvatar) {
          window.STAW.removeAvatar(() => prPopulate());
        }
      });
      head.appendChild(rm);
    }
    rm.style.display = "";
  } else if (rm) {
    rm.style.display = "none";
  }

  // Реальные баллы пользователя (из /loyalty/account через ecosystem.js).
  const points = (window.STAW && window.STAW.ecoPoints) || 0;
  const lv = prComputeLevel(points);
  prModal.querySelector("[data-pr-points]").textContent = points;
  prModal.querySelector("[data-pr-level]").textContent = lv.name;
  const bar = prModal.querySelector("[data-pr-progress]");
  if (bar) bar.style.setProperty("--p", lv.progress + "%");
  const nextEl = prModal.querySelector("[data-pr-next]");
  if (nextEl) {
    nextEl.textContent = lv.next
      ? "До уровня «" + lv.next.name + "» — ещё " + lv.toNext + " " + prPtsWord(lv.toNext)
      : "Максимальный уровень достигнут";
  }
}

function openProfile() {
  if (!prModal) return;
  prPopulate();
  prShowMenu();
  prModal.classList.add("is-open");
  prModal.setAttribute("aria-hidden", "false");
}

function closeProfile() {
  if (!prModal) return;
  prModal.classList.remove("is-open");
  prModal.setAttribute("aria-hidden", "true");
}

if (prModal) {
  prModal.querySelectorAll("[data-pr-close]").forEach((b) =>
    b.addEventListener("click", closeProfile),
  );
  prModal.querySelectorAll("[data-pr-edit]").forEach((b) =>
    b.addEventListener("click", prShowEdit),
  );
  const prGear = prModal.querySelector("[data-pr-gear]");
  if (prGear)
    prGear.addEventListener("click", () => {
      const onMenu = !prModal.querySelector("[data-pr-menu]").hidden;
      if (onMenu) prShowEdit();
      else prShowMenu();
    });
  const prLevelsBtn = prModal.querySelector("[data-pr-levels-open]");
  if (prLevelsBtn)
    prLevelsBtn.addEventListener("click", () => {
      // Повторный клик по плите баллов = назад в меню профиля (как стрелка ←).
      const onLevels = !prModal.querySelector("[data-pr-levels]").hidden;
      if (onLevels) prShowMenu();
      else prShowLevels();
    });

  // Уровни открываются кликом по плитке баллов (data-pr-levels-open).
  // Дублирующий пункт меню «Баллы и уровень» убран.

  const prOrdersBtn = prModal.querySelector("[data-pr-orders]");
  if (prOrdersBtn) prOrdersBtn.addEventListener("click", prShowOrders);

  const prAddrAdd = prModal.querySelector("[data-pr-addr-add]");
  if (prAddrAdd)
    prAddrAdd.addEventListener("click", () => {
      const fieldVal = (sel) => {
        const el = prModal.querySelector(sel);
        return el ? (el.value || "").trim() : "";
      };
      const city = fieldVal("[data-pr-addr-city]");
      const street = fieldVal("[data-pr-addr-street]");
      const house = fieldVal("[data-pr-addr-house]");
      const building = fieldVal("[data-pr-addr-building]");
      const apartment = fieldVal("[data-pr-addr-apt]");
      // Для корректной доставки требуем город + улицу + дом; корпус/кв — опционально.
      const required = [
        ["[data-pr-addr-city]", city],
        ["[data-pr-addr-street]", street],
        ["[data-pr-addr-house]", house],
      ];
      const missing = required.some(([, v]) => !v);
      required.forEach(([sel, v]) => {
        const el = prModal.querySelector(sel);
        if (el) el.style.borderColor = v ? "" : "#c0392b";
      });
      if (missing) return;
      prEditAddr.push({ city, street, house, building, apartment });
      [
        "[data-pr-addr-city]",
        "[data-pr-addr-street]",
        "[data-pr-addr-house]",
        "[data-pr-addr-building]",
        "[data-pr-addr-apt]",
      ].forEach((sel) => {
        const el = prModal.querySelector(sel);
        if (el) {
          el.value = "";
          el.style.borderColor = "";
        }
      });
      prRenderAddresses();
    });
  const prCancel = prModal.querySelector("[data-pr-edit-cancel]");
  if (prCancel) prCancel.addEventListener("click", prShowMenu);

  const prSave = prModal.querySelector("[data-pr-save]");
  if (prSave)
    prSave.addEventListener("click", () => {
      const profile = {
        name: prModal.querySelector("[data-pr-edit-name]").value.trim(),
        email: prModal.querySelector("[data-pr-edit-email]").value.trim(),
        addresses: prEditAddr.slice(),
      };

      function localSave() {
        const merged = Object.assign({}, prGetUser(), {
          name: profile.name,
          phone: prModal.querySelector("[data-pr-edit-phone]").value.trim(),
          email: profile.email,
          addresses: profile.addresses,
        });
        if (window.STAW && typeof window.STAW.setUser === "function") window.STAW.setUser(merged);
        prSaveAddresses(profile.addresses);
        prPopulate();
        prShowMenu();
      }

      const token = window.STAW && typeof window.STAW.token === "function" && window.STAW.token();
      if (token && typeof window.STAW.api === "function") {
        prSave.disabled = true;
        prSave.textContent = "Сохраняем…";
        window.STAW
          .api("/profile", { method: "PATCH", body: profile })
          .then((u) => {
            if (u && typeof window.STAW.setUser === "function") window.STAW.setUser(u);
            prPopulate();
            prShowMenu();
          })
          .catch(localSave)
          .then(() => {
            prSave.disabled = false;
            prSave.textContent = "Сохранить";
          });
      } else {
        localSave();
      }
    });

  const prLogout = prModal.querySelector("[data-pr-logout]");
  if (prLogout)
    prLogout.addEventListener("click", () => {
      if (window.STAW && typeof window.STAW.logout === "function") window.STAW.logout();
      closeProfile();
    });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && prModal.classList.contains("is-open")) closeProfile();
  });
}

window.STAW = window.STAW || {};
window.STAW.openProfile = openProfile;

// ── Анимированная карточка лояльности: на hover листает уровни ────────────────
(function () {
  const card = document.querySelector("[data-loyalty-card]");
  if (!card) return;
  const reduce =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const LEVELS = [
    { name: "Базовый", range: "0–199 баллов", cashback: "Кэшбэк 1%", color: "#b9856b", p: 18, num: 120 },
    { name: "Серебро", range: "200–499 баллов", cashback: "Кэшбэк 2% · ранний доступ", color: "#c7ccd4", p: 45, num: 430 },
    { name: "Золото", range: "500–999 баллов", cashback: "Кэшбэк 3% · бесплатная доставка", color: "#e3c06a", p: 73, num: 760 },
    { name: "Платина", range: "1000+ баллов", cashback: "Кэшбэк 5% · VIP-поддержка", color: "#9fb4c9", p: 100, num: 1200 },
  ];
  const DEFAULT = 1;
  const elLevel = card.querySelector("[data-lc-level]");
  const elNum = card.querySelector("[data-lc-num]");
  const elCash = card.querySelector("[data-lc-cashback]");
  const elBar = card.querySelector("[data-lc-bar]");
  const elRange = card.querySelector("[data-lc-range]");
  const tiers = card.querySelectorAll("[data-tier]");

  let timer = null;
  let rafId = null;
  let idx = DEFAULT;
  let shownNum = LEVELS[DEFAULT].num;

  function animateNum(to) {
    cancelAnimationFrame(rafId);
    const from = shownNum;
    const startT = performance.now();
    const dur = 600;
    function step(t) {
      const k = Math.min(1, (t - startT) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      shownNum = Math.round(from + (to - from) * e);
      if (elNum) elNum.textContent = shownNum;
      if (k < 1) rafId = requestAnimationFrame(step);
    }
    rafId = requestAnimationFrame(step);
  }

  function setTier(i, withCount) {
    const lv = LEVELS[i];
    card.style.setProperty("--tier-color", lv.color);
    if (elLevel) elLevel.textContent = lv.name;
    if (elCash) elCash.textContent = lv.cashback;
    if (elRange) elRange.textContent = lv.range;
    if (elBar) elBar.style.setProperty("--p", lv.p + "%");
    tiers.forEach((t) => t.classList.toggle("is-active", Number(t.dataset.tier) === i));
    if (withCount) animateNum(lv.num);
    else {
      shownNum = lv.num;
      if (elNum) elNum.textContent = lv.num;
    }
  }

  function start() {
    if (timer || reduce) return;
    idx = 0;
    setTier(0, true);
    timer = setInterval(() => {
      idx = (idx + 1) % LEVELS.length;
      setTier(idx, true);
    }, 1300);
  }
  function stop() {
    clearInterval(timer);
    timer = null;
    cancelAnimationFrame(rafId);
    setTier(DEFAULT, true);
  }

  card.addEventListener("mouseenter", start);
  card.addEventListener("mouseleave", stop);
  card.addEventListener("focus", start);
  card.addEventListener("blur", stop);

  setTier(DEFAULT, false);
})();

// ── Карты лояльности МАТА — окно-портал (одобрено 2026-08-23) ──
// Колода уровней стоит ЗА окном, передняя карта («герой») выходит к зрителю.
(function () {
  const stage = document.querySelector("[data-ml-loyalty]");
  if (!stage) return;
  const deckEl = stage.querySelector("[data-ml-deck]");
  const heroEl = stage.querySelector("[data-ml-hero]");
  const dotsBox = stage.querySelector("[data-ml-dots]");
  const capT = stage.querySelector("[data-ml-cap] .ml-cap-t");
  const capS = stage.querySelector("[data-ml-cap] .ml-cap-s");
  if (!deckEl || !heroEl) return;
  const reduce =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const WM = '<svg class="ml-wm" viewBox="312 580 656 112" xmlns="http://www.w3.org/2000/svg">' +
    '<path class="m" d="M327.996 580H324.857H312V691.964H327.996V585.434L389.495 691.964H407.964L343.326 580H327.996Z"/>' +
    '<path class="m" d="M487.937 580H472.606L407.964 691.964H426.432L487.937 585.434V691.964H503.933V580H491.075H487.937Z"/>' +
    '<path class="m" d="M619.03 580H612.759H600.562L535.924 691.964H554.393L563.625 675.969H633.446L642.678 659.973H572.861L615.897 585.434L677.397 691.964H695.866L631.228 580H619.03Z"/>' +
    '<path class="t" d="M814.324 580H688.838L679.605 595.996H743.583H759.579H823.556L814.324 580Z"/>' +
    '<path class="t" d="M759.848 611.991H743.853V691.964H759.848V611.991Z"/>' +
    '<path class="m" d="M903.402 580H890.135H884.933H871.666L807.023 691.964H825.492L887.534 584.504L931.103 659.973H860.485L869.717 675.969H940.339L949.571 691.964H968.04L903.402 580Z"/>' +
    '</svg>';
  const SIGN = '<svg class="ml-sign" viewBox="490 472 300 336" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M502.371 500.66L578.165 632.29L599.723 632.311L562.451 567.578L513.177 482L502.371 500.66Z"/>' +
    '<path d="M769.167 632.534L617.277 632.359L606.477 651.019L681.175 651.109L779.925 651.221L769.167 632.534Z"/>' +
    '<path d="M521.563 797.65L597.66 666.195L586.902 647.509L549.471 712.156L500 797.623L521.563 797.65Z"/>' +
    '</svg>';
  const QR = '<rect width="29" height="29" fill="#fff"/><path fill="#111" d="M0 0h7v7H0zM2 2h3v3H2zM22 0h7v7h-7zM24 2h3v3h-3zM0 22h7v7H0zM2 24h3v3H2zM10 0h2v2h-2zM14 2h2v2h-2zM10 6h4v2h-4zM18 4h2v4h-2zM9 9h3v3H9zM14 10h4v2h-4zM20 9h3v3h-3zM25 10h2v4h-2zM10 14h2v4h-2zM14 14h3v3h-3zM19 15h4v2h-4zM9 20h4v2H9zM15 19h2v4h-2zM22 20h3v3h-3zM26 18h2v3h-2zM10 24h3v3h-3zM15 25h4v2h-4zM21 25h2v2h-2zM25 24h3v3h-3z"/>';

  const CARDS = [
    { cls: "ml-platinum", name: "Платина", pts: "3 852", cash: "кэшбэк 5%", range: "от 1000 баллов", sign: true },
    { cls: "ml-gold",     name: "Золото",  pts: "742",   cash: "кэшбэк 3%", range: "от 500 баллов",  sign: true },
    { cls: "ml-silver",   name: "Серебро", pts: "368",   cash: "кэшбэк 2%", range: "от 200 баллов",  sign: true },
    { cls: "ml-basic",    name: "Базовый", pts: "140",   cash: "кэшбэк 1%", range: "0–199 баллов",   sign: false },
  ];

  function faces(c) {
    return '<div class="ml-face ml-front">' +
        (c.cls === "ml-platinum" ? '<div class="ml-aur"><i></i><i></i><i></i></div>' : "") +
        (c.sign ? SIGN : "") +
        (c.cls === "ml-platinum" ? SIGN.replace('class="ml-sign"', 'class="ml-signGlow"') : "") +
        (c.cls === "ml-platinum" ? '<div class="ml-edge"></div>' : "") +
        '<div class="ml-rowTop">' + WM + '<span class="ml-lvl">' + c.name.toUpperCase() + "</span></div>" +
        '<div class="ml-pts"><span class="ml-n">' + c.pts + '</span><span class="ml-l">баллов</span></div>' +
        '<div class="ml-rowBot"><span class="ml-hname">ДЕРЖАТЕЛЬ КАРТЫ</span><span class="ml-uni">ЕДИНАЯ КАРТА</span></div>' +
      "</div>" +
      '<div class="ml-face ml-back">' +
        '<div class="ml-stripe"></div>' +
        '<div class="ml-backBody"><div class="ml-backTxt"><div class="ml-bcap">ПОКАЖИ НА КАССЕ</div><div class="ml-bd">Баллы спишутся со счёта. Код лояльности в QR.</div></div><div class="ml-qr"><svg viewBox="0 0 29 29">' + QR + "</svg></div></div>" +
      "</div>";
  }

  deckEl.innerHTML = CARDS.map(function (c, i) {
    return '<div class="ml-card ' + c.cls + '" data-i="' + i + '"><div class="ml-flip">' + faces(c) + "</div></div>";
  }).join("");
  const cards = [].slice.call(deckEl.querySelectorAll(".ml-card"));
  const N = CARDS.length;

  const dots = [];
  if (dotsBox) {
    CARDS.forEach(function (_, i) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", "Показать уровень " + CARDS[i].name);
      b.addEventListener("click", function () { setFront(i); });
      dotsBox.appendChild(b);
      dots.push(b);
    });
  }

  let front = 0;
  let timer = null;

  function buildHero(c) {
    heroEl.className = "ml-hero " + c.cls;
    heroEl.innerHTML = '<div class="ml-tilt"><div class="ml-flip">' + faces(c) + "</div></div>";
    if (!reduce) { heroEl.classList.remove("pop"); void heroEl.offsetWidth; heroEl.classList.add("pop"); }
    heroEl.onclick = function () { if (swallowClick()) return; heroEl.classList.toggle("flipped"); stop(); };
  }
  function render() {
    cards.forEach(function (el, i) {
      const pos = (i - front + N) % N;
      el.className = el.className.replace(/\bpos-\d\b/g, "").trim() + " pos-" + pos;
    });
    dots.forEach(function (d, i) { d.classList.toggle("on", i === front); });
    const c = CARDS[front];
    if (capT) capT.innerHTML = "Уровень <b>" + c.name + "</b>";
    if (capS) capS.textContent = c.cash + " · " + c.range;
    buildHero(c);
  }
  function setFront(i) { front = ((i % N) + N) % N; render(); restart(); }
  function tick() { front = (front + 1) % N; render(); }
  function start() { if (!timer && !reduce) timer = setInterval(tick, 5000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function restart() { stop(); start(); }

  cards.forEach(function (el) {
    el.addEventListener("click", function (e) { if (swallowClick()) return; setFront(+el.dataset.i); e.stopPropagation(); });
  });

  // Свайп по сцене листает уровни. После свайпа браузер всё равно шлёт click —
  // его надо съесть, иначе палец заодно перевернёт карту.
  var swiped = false;
  function swallowClick() { if (!swiped) return false; swiped = false; return true; }

  var tx = 0, ty = 0, tracking = false;
  stage.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) { tracking = false; return; }
    tx = e.touches[0].clientX; ty = e.touches[0].clientY; tracking = true; swiped = false;
  }, { passive: true });
  stage.addEventListener("touchend", function (e) {
    if (!tracking) return;
    tracking = false;
    var t = e.changedTouches[0];
    var dx = t.clientX - tx, dy = t.clientY - ty;
    // Вертикальный жест оставляем прокрутке страницы.
    if (Math.abs(dx) < 45 || Math.abs(dx) < Math.abs(dy) * 1.6) return;
    swiped = true;
    setFront(front + (dx < 0 ? 1 : -1));
  }, { passive: true });

  // Параллакс — только на вышедшей карте (герой); колода за окном неподвижна.
  stage.addEventListener("mousemove", function (e) {
    const t = heroEl.querySelector(".ml-tilt");
    if (!t) return;
    const r = stage.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    t.style.transform = "rotateX(" + (-py * 10).toFixed(2) + "deg) rotateY(" + (px * 14).toFixed(2) + "deg)";
  });
  stage.addEventListener("mouseleave", function () { const t = heroEl.querySelector(".ml-tilt"); if (t) t.style.transform = ""; });
  stage.addEventListener("focusin", stop);
  stage.addEventListener("focusout", start);

  render();
  setTimeout(start, 200);
})();

observeReveals();
bindAddButtons();
bindQuickView();

// Вызывается из catalog.js после отрисовки товаров из API.
window.STAW = window.STAW || {};
window.STAW.onCatalogRendered = function () {
  observeReveals();
  bindAddButtons();
  bindQuickView();
  applyCatalog();
};

window.addEventListener("scroll", updateHeader, { passive: true });
updateHeader();
renderCart();
