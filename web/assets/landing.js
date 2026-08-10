/* CiteAura 落地页交互：i18n、主题、导航、定价切换、滚动渐显 */
(function () {
  'use strict';

  var LOCALES = ['en', 'zh', 'ja'];
  var HTML_LANG = { en: 'en', zh: 'zh-CN', ja: 'ja' };
  var THEME_COLORS = { light: '#f7f9fa', dark: '#1a1e24' };
  var state = { locale: 'en', theme: 'light', billing: 'monthly', catalog: {} };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------- 语言 ---------- */
  function detectLocale() {
    var requested = new URLSearchParams(location.search).get('lang');
    var saved = null;
    try { saved = localStorage.getItem('ulang'); } catch (e) {}
    var nav = (navigator.language || '').toLowerCase();
    var guess = requested || saved || (nav.indexOf('zh') === 0 ? 'zh' : nav.indexOf('ja') === 0 ? 'ja' : 'en');
    return LOCALES.indexOf(guess) >= 0 ? guess : 'en';
  }

  function catalogValue(key) {
    return Object.prototype.hasOwnProperty.call(state.catalog, key) ? state.catalog[key] : null;
  }

  function applyI18n() {
    $$('[data-i18n]').forEach(function (node) {
      var value = catalogValue(node.getAttribute('data-i18n'));
      if (value != null) {
        if (node.tagName === 'TITLE') { document.title = value; return; }
        node.textContent = value;
      }
    });
    var title = catalogValue('landing.title');
    if (title) document.title = title;
    $$('[data-i18n-content]').forEach(function (node) {
      var value = catalogValue(node.getAttribute('data-i18n-content'));
      if (value != null) node.setAttribute('content', value);
    });
    $$('[data-i18n-aria]').forEach(function (node) {
      var value = catalogValue(node.getAttribute('data-i18n-aria'));
      if (value != null) node.setAttribute('aria-label', value);
    });
    $$('[data-i18n-alt]').forEach(function (node) {
      var value = catalogValue(node.getAttribute('data-i18n-alt'));
      if (value != null) node.setAttribute('alt', value);
    });
    applyBilling();
    applyLocaleImages();
    renderThemeControl();
  }

  function applyLocaleImages() {
    $$('img[data-locale-src-en]').forEach(function (img) {
      var src = img.getAttribute('data-locale-src-' + state.locale) || img.getAttribute('data-locale-src-en');
      if (src && img.getAttribute('src') !== src) img.setAttribute('src', src);
    });
  }

  function setLocale(locale, push) {
    state.locale = LOCALES.indexOf(locale) >= 0 ? locale : 'en';
    try { localStorage.setItem('ulang', state.locale); } catch (e) {}
    document.documentElement.lang = HTML_LANG[state.locale] || 'en';
    $$('.lang-btn').forEach(function (btn) {
      var active = btn.getAttribute('data-lang') === state.locale;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (push) {
      var url = new URL(location.href);
      url.searchParams.set('lang', state.locale);
      history.replaceState({}, '', url.toString());
    }
    if (state.locale === 'en') {
      state.catalog = {};
      applyI18n();
      return;
    }
    fetch('/i18n/' + state.locale + '.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { state.catalog = data || {}; applyI18n(); })
      .catch(function () { state.catalog = {}; applyI18n(); });
  }

  /* ---------- 主题 ---------- */
  function renderThemeControl() {
    var toggle = $('.theme-toggle');
    var meta = $('[data-theme-color]');
    if (meta) meta.setAttribute('content', THEME_COLORS[state.theme] || THEME_COLORS.light);
    if (!toggle) return;
    var dark = state.theme === 'dark';
    toggle.setAttribute('aria-pressed', dark ? 'true' : 'false');
    var key = dark ? 'theme.to_light' : 'theme.to_dark';
    var label = catalogValue(key) || toggle.getAttribute('aria-label');
    if (label) toggle.setAttribute('aria-label', label);
  }

  function setTheme(theme, persist) {
    state.theme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = state.theme;
    if (persist) { try { localStorage.setItem('utheme', state.theme); } catch (e) {} }
    renderThemeControl();
  }

  function initTheme() {
    var param = new URLSearchParams(location.search).get('theme');
    var saved = null;
    try { saved = localStorage.getItem('utheme'); } catch (e) {}
    setTheme(param || saved || (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'), false);
    var toggle = $('.theme-toggle');
    if (toggle) {
      toggle.addEventListener('click', function () {
        setTheme(state.theme === 'dark' ? 'light' : 'dark', true);
      });
    }
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (event) {
        var stored = null;
        try { stored = localStorage.getItem('utheme'); } catch (e) {}
        if (!stored) setTheme(event.matches ? 'dark' : 'light', false);
      });
    }
  }

  /* ---------- 移动导航 ---------- */
  function initNav() {
    var header = $('.site-header');
    var toggle = $('.nav-menu-toggle');
    if (!header || !toggle) return;
    toggle.addEventListener('click', function () {
      var open = header.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      var key = open ? 'nav.close' : 'nav.open';
      var label = catalogValue(key);
      if (label) toggle.setAttribute('aria-label', label);
    });
    $$('.nav-links a').forEach(function (link) {
      link.addEventListener('click', function () {
        header.classList.remove('nav-open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* ---------- 定价切换 ---------- */
  function applyBilling() {
    var interval = state.billing;
    $$('[data-' + interval + ']').forEach(function (node) {
      var i18nKey = node.getAttribute('data-i18n-' + interval);
      var localized = i18nKey ? catalogValue(i18nKey) : null;
      node.textContent = localized != null ? localized : node.getAttribute('data-' + interval);
    });
    $$('.billing-toggle [data-billing]').forEach(function (btn) {
      var active = btn.getAttribute('data-billing') === interval;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function initBilling() {
    $$('.billing-toggle [data-billing]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.billing = btn.getAttribute('data-billing') === 'annual' ? 'annual' : 'monthly';
        applyBilling();
      });
    });
  }

  /* ---------- 滚动渐显 ---------- */
  function initReveal() {
    var nodes = $$('.reveal');
    if (!nodes.length) return;
    if (!('IntersectionObserver' in window)) {
      nodes.forEach(function (node) { node.classList.add('is-visible'); });
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    nodes.forEach(function (node, index) {
      node.style.transitionDelay = (index % 5) * 60 + 'ms';
      observer.observe(node);
    });
  }

  /* ---------- 启动 ---------- */
  function init() {
    initTheme();
    initNav();
    initBilling();
    initReveal();
    setLocale(detectLocale(), false);
    $$('.lang-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { setLocale(btn.getAttribute('data-lang'), true); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
