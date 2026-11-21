/**
 * МАТА — motion-слой (premium feel).
 *
 * Прогрессивное улучшение поверх готового сайта:
 *   - Lenis        → «масляный» плавный скролл (тот самый дорогой ощущение);
 *   - GSAP timeline→ кинематографичный вход hero (eyebrow → буквы → текст → CTA);
 *   - ScrollTrigger→ параллакс hero-медиа при скролле.
 *
 * Принципы безопасности:
 *   - НИЧЕГО не ломает, если GSAP/Lenis не загрузились (CDN/офлайн) — добавляем
 *     html.motion-off и контент просто виден без анимаций.
 *   - Уважаем prefers-reduced-motion: полностью отключаем motion.
 *   - Не трогаем script.js/catalog.js/ecosystem.js — секционные reveal остаются на
 *     IntersectionObserver и работают вместе с Lenis (Lenis скроллит нативно).
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var hasGsap = typeof window.gsap !== "undefined";
  var hasLenis = typeof window.Lenis !== "undefined";

  // Фолбэк: нет GSAP или пользователь просит меньше движения — показываем всё как есть.
  if (reduceMotion || !hasGsap) {
    root.classList.add("motion-on", "motion-off");
    return;
  }

  var gsap = window.gsap;

  // Телефоны и планшеты (сенсор): лёгкий режим (этап 6 оптимизации, 21.11.2026).
  // Палец и так прокручивает нативно и плавно — Lenis на сенсоре ничего не даёт,
  // но крутит тикер GSAP на каждом кадре. Параллакс, привязанный к прокрутке,
  // пересчитывает стили на каждом кадре прокрутки — на телефоне это и было
  // подтормаживание (Lighthouse: ~5 с главного потока на GSAP). Появление героя
  // при загрузке оставляем — оно короткое. На компьютере всё как было.
  var touch = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  var ScrollTrigger = touch ? null : window.ScrollTrigger;
  // Регистрируем только там, где используем: зарегистрированный плагин сам вешает
  // слушатели прокрутки и пересчёты, даже если сцен нет.
  if (ScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  // ── Плавный скролл (Lenis) ────────────────────────────────────────────────
  var lenis = null;
  if (hasLenis && !touch) {
    lenis = new window.Lenis({
      duration: 1.1,
      easing: function (t) {
        return Math.min(1, 1.001 - Math.pow(2, -10 * t));
      },
      smoothWheel: true,
    });

    if (ScrollTrigger) {
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add(function (time) {
        lenis.raf(time * 1000);
      });
      gsap.ticker.lagSmoothing(0);
    } else {
      var raf = function (time) {
        lenis.raf(time);
        requestAnimationFrame(raf);
      };
      requestAnimationFrame(raf);
    }

    // Плавный переход по якорным ссылкам в той же эстетике. Один обработчик на
    // документ: motion.js стоит первым из скриптов (герой не ждёт остальных), и
    // ссылки, которые другие скрипты добавят позже, тоже должны ехать плавно.
    document.addEventListener("click", function (e) {
      var link = e.target && e.target.closest && e.target.closest('a[href^="#"]');
      if (!link) return;
      var href = link.getAttribute("href");
      if (!href || href === "#") return;
      var target;
      try { target = document.querySelector(href); } catch (err) { return; }
      if (!target) return;
      e.preventDefault();
      lenis.scrollTo(target, { offset: -8 });
    });
  }

  // ── Скролл-лок под модалкой (Lenis-совместимо) ─────────────────────────────
  // Lenis крутит страницу в обход overflow:hidden. Пока открыт оверлей — стопим
  // Lenis (фон замирает), а внутренний скролл окна идёт нативно через
  // data-lenis-prevent на самих окнах/панелях.
  if (lenis) {
    var MODALS = [
      "pv-modal", "pr-modal", "co-modal", "cart-panel", "mobile-nav", "eco-modal",
      "lg-modal",
    ];
    // Помечаем существующие окна/панели, чтобы их колесо не перехватывал Lenis.
    document
      .querySelectorAll("." + MODALS.join(", ."))
      .forEach(function (el) { el.setAttribute("data-lenis-prevent", ""); });

    var lenisStopped = false;
    function syncModalScroll() {
      var open = false;
      for (var i = 0; i < MODALS.length; i++) {
        if (document.querySelector("." + MODALS[i] + ".is-open")) { open = true; break; }
      }
      if (open && !lenisStopped) { lenis.stop(); lenisStopped = true; }
      else if (!open && lenisStopped) { lenis.start(); lenisStopped = false; }
    }
    var modalObs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var t = muts[i].target;
        if (!t.classList) continue;
        for (var j = 0; j < MODALS.length; j++) {
          if (t.classList.contains(MODALS[j])) {
            // На случай динамически добавленной модалки (eco-modal) — пометим её.
            if (!t.hasAttribute("data-lenis-prevent")) {
              t.setAttribute("data-lenis-prevent", "");
            }
            syncModalScroll();
            return;
          }
        }
      }
    });
    modalObs.observe(document.body, {
      subtree: true, attributes: true, attributeFilter: ["class"],
    });
    syncModalScroll();
  }

  // ── Вход hero (кинематографичный timeline) ─────────────────────────────────
  function initHero() {
    var hero = document.querySelector(".hero");
    if (!hero) return;

    var media = hero.querySelector(".hero-media");
    var eyebrow = hero.querySelector(".eyebrow");
    var letters = hero.querySelectorAll(".brand-wordmark span");
    var copy = hero.querySelector(".hero-copy");
    var actions = hero.querySelector(".hero-actions");
    var scrollCue = hero.querySelector(".hero-scroll");

    // Вход на загрузке: всё появляется сразу (eyebrow → STAW → описание → кнопки),
    // без пиннинга/долгого скролла.
    var tl = gsap.timeline({ defaults: { ease: "power3.out", duration: 0.9 } });

    if (media) {
      tl.fromTo(
        media,
        { opacity: 0, scale: 1.06 },
        { opacity: 1, scale: 1, duration: 1.3, ease: "power2.out" },
        0,
      );
    }
    if (eyebrow) tl.fromTo(eyebrow, { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.7 }, 0.15);
    if (letters.length)
      tl.fromTo(
        letters,
        { opacity: 0, yPercent: 60 },
        { opacity: 1, yPercent: 0, stagger: 0.08, duration: 0.85 },
        0.25,
      );
    if (copy) tl.fromTo(copy, { opacity: 0, y: 26 }, { opacity: 1, y: 0 }, 0.5);
    if (actions) tl.fromTo(actions, { opacity: 0, y: 26 }, { opacity: 1, y: 0 }, 0.62);
    if (scrollCue) tl.fromTo(scrollCue, { opacity: 0, y: 18 }, { opacity: 1, y: 0 }, 0.78);

    // Лёгкий параллакс фото героя при скролле (без пиннинга).
    if (ScrollTrigger) {
      var heroImg = hero.querySelector(".hero-media img, .hero-media video");
      if (heroImg) {
        gsap.to(heroImg, {
          yPercent: 12,
          scale: 1.08,
          ease: "none",
          scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true },
        });
      }
    }
  }

  // ── Доп. scroll-сцены (Этап 2, motion-first product story) ─────────────────
  // Параллакс изображений в cinema-карточках. Анимируем только <img> (у самих
  // карточек своя reveal-логика на IntersectionObserver — не конфликтуем).
  function initScenes() {
    if (!ScrollTrigger) return;
    gsap.utils.toArray(".cinema-card img").forEach(function (img) {
      var card = img.closest(".cinema-card");
      gsap.set(img, { scale: 1.12 }); // запас под смещение, чтобы не открывались края
      gsap.fromTo(
        img,
        { yPercent: -6 },
        {
          yPercent: 6,
          ease: "none",
          scrollTrigger: { trigger: card, start: "top bottom", end: "bottom top", scrub: true },
        },
      );
    });
  }

  // motion активен → снимаем «скрытое» состояние hero и анимируем.
  root.classList.add("motion-on");
  initHero();
  initScenes();

  // После полной загрузки (шрифты/картинки могли сдвинуть верстку) — пересчёт триггеров.
  window.addEventListener("load", function () {
    if (ScrollTrigger) ScrollTrigger.refresh();
  });
})();
