(function () {
  var root = document.documentElement;
  var themeButton = document.querySelector(".theme-toggle");
  var themeLabel = document.querySelector(".theme-label");
  var themeMeta = document.querySelector('meta[name="theme-color"]');
  var catalog = {};
  var locale = "en";
  var billingInterval = "monthly";
  var menuButton = document.querySelector(".nav-menu-toggle");
  var siteHeader = document.querySelector(".site-header");
  var SUPPORTED = ["en", "zh", "ja"];
  var HTML_LANG = { en: "en", zh: "zh-CN", ja: "ja" };

  function detectLocale() {
    var params = new URLSearchParams(location.search);
    var requested = params.get("lang");
    var saved = null;
    try {
      saved = localStorage.getItem("ulang");
    } catch (error) {
      saved = null;
    }
    var browser = (navigator.language || "").toLowerCase();
    var raw = requested || saved || (browser.indexOf("zh") === 0 ? "zh" : browser.indexOf("ja") === 0 ? "ja" : "en");
    return SUPPORTED.indexOf(raw) >= 0 ? raw : "en";
  }

  if (menuButton && siteHeader) {
    menuButton.addEventListener("click", function () {
      var open = siteHeader.classList.toggle("nav-open");
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.textContent = open ? t("nav.close") : t("nav.menu");
      menuButton.setAttribute("aria-label", t(open ? "nav.close" : "nav.open"));
    });
  }

  function t(key) {
    if (!key) return "";
    if (catalog[key] != null) return catalog[key];
    return key;
  }

  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      var value = t(key);
      if (!value || value === key) return;
      if (el.tagName === "TITLE") {
        document.title = value;
        return;
      }
      if (el.tagName === "META") {
        el.setAttribute("content", value);
        return;
      }
      el.textContent = value;
    });
    document.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
      var value = t(el.getAttribute("data-i18n-aria"));
      if (value) el.setAttribute("aria-label", value);
    });
    document.querySelectorAll("[data-i18n-alt]").forEach(function (el) {
      var value = t(el.getAttribute("data-i18n-alt"));
      if (value) el.setAttribute("alt", value);
    });
    document.querySelectorAll("[data-i18n-monthly]").forEach(function (el) {
      el.setAttribute("data-monthly", t(el.getAttribute("data-i18n-monthly")));
      el.setAttribute("data-annual", t(el.getAttribute("data-i18n-annual")));
    });
    applyBillingLabels();
    renderThemeControl();
    document.querySelectorAll(".lang-btn").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-lang") === locale));
    });
  }

  function applyLocaleImages() {
    document.querySelectorAll("[data-locale-src-en]").forEach(function (image) {
      var source = image.getAttribute("data-locale-src-" + locale) || image.getAttribute("data-locale-src-en");
      if (source && image.getAttribute("src") !== source) image.setAttribute("src", source);
    });
  }

  function applyBillingLabels() {
    document.querySelectorAll("[data-monthly][data-annual]").forEach(function (item) {
      item.textContent = item.getAttribute("data-" + billingInterval) || item.textContent;
    });
  }

  function setLocale(next) {
    if (SUPPORTED.indexOf(next) < 0) next = "en";
    locale = next;
    applyLocaleImages();
    try {
      localStorage.setItem("ulang", locale);
    } catch (error) {
      // ignore
    }
    root.lang = HTML_LANG[locale] || "en";
    return fetch("/i18n/" + locale + ".json")
      .then(function (response) {
        if (!response.ok) throw new Error("i18n_load_failed");
        return response.json();
      })
      .then(function (data) {
        catalog = data || {};
        applyI18n();
      })
      .catch(function () {
        catalog = {};
        applyI18n();
      });
  }

  var storedTheme;
  try {
    storedTheme = window.localStorage.getItem("disvorai-site-theme");
  } catch (error) {
    storedTheme = null;
  }
  if (storedTheme === "light" || storedTheme === "dark") {
    root.dataset.theme = storedTheme;
  }

  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function renderThemeControl() {
    if (!themeButton || !themeLabel || !themeMeta) return;
    var dark = currentTheme() === "dark";
    themeButton.setAttribute("aria-pressed", String(dark));
    themeLabel.textContent = dark ? t("theme.light") : t("theme.dark");
    themeButton.setAttribute("aria-label", dark ? t("theme.to_light") : t("theme.to_dark"));
    themeMeta.setAttribute("content", dark ? "#121318" : "#f5f5f3");
  }

  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        window.localStorage.setItem("disvorai-site-theme", next);
      } catch (error) {
        // ignore
      }
      renderThemeControl();
    });
  }

  var systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  systemTheme.addEventListener("change", function () {
    if (!root.dataset.theme) renderThemeControl();
  });

  document.querySelectorAll("[data-billing]").forEach(function (button) {
    button.addEventListener("click", function () {
      billingInterval = button.dataset.billing;
      document.querySelectorAll("[data-billing]").forEach(function (item) {
        var active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      applyBillingLabels();
    });
  });

  document.querySelectorAll(".lang-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      setLocale(button.getAttribute("data-lang"));
      var url = new URL(location.href);
      url.searchParams.set("lang", locale);
      history.replaceState({}, "", url);
    });
  });

  var revealItems = document.querySelectorAll(".reveal");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (item) {
      item.classList.add("is-visible");
    });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8%", threshold: 0.08 });
    revealItems.forEach(function (item) {
      observer.observe(item);
    });
  }

  setLocale(detectLocale());
}());
