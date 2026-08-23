/* CiteAura landing interactions: locale, theme, pricing, and guided workspace preview. */
fetch('/api/v1/events/landing', { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' } }).catch(() => {});

function trackPublicEvent(name, properties) {
  fetch('/api/v1/events/product', {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, properties: properties || {} })
  }).catch(function () {});
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

(function () {
  'use strict';

  var THEME_COLORS = { light: '#f7f9fa', dark: '#15181e' };
  var LOCALES = ['en', 'zh', 'ja', 'ko', 'es', 'fr', 'de'];
  var state = { locale: 'en', theme: 'light', billing: 'monthly', catalog: {}, fallbackCatalog: {}, literalCatalog: {}, activeDomain: 'yourbrand.com' };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ================================================================
      Product locale
     ================================================================ */
  function normalizeLocale(value) {
    var raw = String(value || '').toLowerCase().replace('_', '-');
    var primary = raw.split('-')[0];
    return LOCALES.indexOf(primary) >= 0 ? primary : 'en';
  }

  function detectLocale() {
    var query = new URLSearchParams(location.search).get('lang');
    if (query) return normalizeLocale(query);
    try {
      var stored = localStorage.getItem('ulang');
      if (stored) return normalizeLocale(stored);
    } catch (e) {}
    var languages = navigator.languages || [navigator.language];
    for (var i = 0; i < languages.length; i += 1) {
      var locale = normalizeLocale(languages[i]);
      if (locale !== 'en' || String(languages[i] || '').toLowerCase().indexOf('en') === 0) return locale;
    }
    return 'en';
  }

  function catalogValue(key) {
    return Object.prototype.hasOwnProperty.call(state.catalog, key) ? state.catalog[key] : null;
  }

  function localize(value, params) {
    var text = String(value == null ? '' : value);
    if (state.locale === 'en') return text;
    var key = Object.keys(state.fallbackCatalog).find(function (candidate) {
      return state.fallbackCatalog[candidate] === text;
    });
    var localized = key && state.catalog[key] != null
      ? state.catalog[key]
      : (key && state.locale !== 'en' ? '[[missing:' + key + ']]' : text);
    Object.keys(params || {}).forEach(function (name) {
      localized = localized.replace(new RegExp('\\{' + name + '\\}', 'g'), function () { return String(params[name]); });
    });
    return localized;
  }

  function localizeLegacyText() {
    if (state.locale === 'en') return;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      if (node.parentElement && node.parentElement.closest('script,style,code,pre,[data-i18n]')) return;
      var raw = node.nodeValue || '';
      var trimmed = raw.trim();
      if (!trimmed) return;
      var translated = localize(trimmed);
      if (translated !== trimmed) node.nodeValue = raw.replace(trimmed, translated);
    });
    $$('[title], [aria-label], [placeholder]').forEach(function (node) {
      ['title', 'aria-label', 'placeholder'].forEach(function (attribute) {
        var value = node.getAttribute(attribute);
        var translated = localize(value);
        if (translated !== value) node.setAttribute(attribute, translated);
      });
    });
  }

  function applyI18n() {
    $$('[data-i18n]').forEach(function (node) {
      var key = node.getAttribute('data-i18n');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      if (value != null) {
        if (node.tagName === 'TITLE') { document.title = value; return; }
        node.textContent = value;
      }
    });
    var title = catalogValue('landing.title');
    if (title) document.title = title;
    $$('[data-i18n-content]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-content');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      if (value != null) node.setAttribute('content', value);
    });
    $$('[data-i18n-aria]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-aria');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      if (value != null) node.setAttribute('aria-label', value);
    });
    $$('[data-i18n-alt]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-alt');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      if (value != null) node.setAttribute('alt', value);
    });
    applyBilling();
    renderThemeControl();
    localizeLegacyText();
  }

  function setLocale(locale) {
    state.locale = normalizeLocale(locale);
    document.documentElement.lang = state.locale === 'zh' ? 'zh-CN' : state.locale;
    try { localStorage.setItem('ulang', state.locale); } catch (e) {}
    var selector = $('#site-locale');
    if (selector) selector.value = state.locale;
    Promise.all([
      fetch('/i18n/en.json').then(function (r) { return r.ok ? r.json() : {}; }),
      fetch('/i18n/' + state.locale + '.json').then(function (r) { return r.ok ? r.json() : {}; }),
    ])
      .then(function (catalogs) {
        state.fallbackCatalog = catalogs[0] || {};
        state.catalog = state.locale === 'en' ? state.fallbackCatalog : (catalogs[1] || {});
        applyI18n();
      })
      .catch(function () { state.catalog = {}; state.fallbackCatalog = {}; applyI18n(); });
  }

  /* ================================================================
      (Light / Dark)
     ================================================================ */
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

  /* ================================================================
     
     ================================================================ */
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

  function initLocale() {
    var selector = $('#site-locale');
    if (!selector) return;
    selector.addEventListener('change', function () { setLocale(selector.value); });
  }

  function initHeaderScroll() {
    var header = $('.site-header');
    if (!header) return;
    var ticking = false;
    window.addEventListener('scroll', function () {
      if (!ticking) {
        requestAnimationFrame(function () {
          header.classList.toggle('scrolled', window.scrollY > 10);
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }

  /* ================================================================
     
     ================================================================ */
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

  /* ================================================================
     
     ================================================================ */
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
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.05 });
    nodes.forEach(function (node, index) {
      node.style.transitionDelay = (index % 6) * 60 + 'ms';
      observer.observe(node);
    });
  }

  /* ================================================================
     Hero
     ================================================================ */
/* ================================================================
     Hero  (Canvas Particle & Constellation)
     ================================================================ */
/* ================================================================
      Example workspace preview
     ================================================================ */
  var PREVIEW_BARS = {
    deepseek: { width: '68%', badge: 'Example API trace', value: 'Prompt log' },
    chatgpt: { width: '72%', badge: 'Example grounded run', value: 'Source links' },
    claude: { width: '64%', badge: 'Example answer replay', value: 'Answer diff' },
    gemini: { width: '58%', badge: 'Example retrieval view', value: 'Crawl notes' },
    grok: { width: '61%', badge: 'Example search replay', value: 'Search notes' },
    perplexity: { width: '76%', badge: 'Example research replay', value: 'Citation trail' }
  };

  var isScanning = false;

  function runPreview(domain, onComplete) {
    if (isScanning) return;
    isScanning = true;

    var scannerOverlay = $('#console-scanner');
    var progressBar = $('#scan-progress-fill');
    var pctVal = $('#scan-pct-val');
    var logBox = $('#scan-terminal-log');
    var titleEl = $('.scan-domain-title');
    var submitBtn = $('.hero-scanner-btn');
    var resultBanner = $('#console-result-banner');
    trackPublicEvent('public_audit_started', { source: 'landing_simulator' });
    var auditPromise = fetch('/api/v1/public/audit', {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: 'https://' + domain })
    }).then(function (response) {
      if (!response.ok) throw new Error('public_audit_failed');
      return response.json();
    }).catch(function () { return null; });

    if (resultBanner) resultBanner.classList.add('is-hidden');
    if (titleEl) titleEl.textContent = localize('Preparing {domain} workspace...', { domain: domain });
    if (submitBtn) {
      submitBtn.classList.add('is-loading');
      submitBtn.textContent = localize('Preparing workspace preview...');
    }

    if (scannerOverlay) {
      scannerOverlay.classList.add('is-active');
    }

    var steps = [
      { pct: 20, log: localize('▶ Capturing the requested domain: https://{domain}', { domain: domain }), delay: 50 },
      { pct: 45, log: localize('● [1/4] Opening the guided setup flow and project shell...'), delay: 260 },
      { pct: 70, log: localize('● [2/4] Previewing example report, ticket, and asset views...'), delay: 560 },
      { pct: 88, log: localize('● [3/4] Saving the domain for workspace onboarding...'), delay: 860 },
      { pct: 100, log: localize('✔ [4/4] Preview ready. Run the full audit inside the app.'), delay: 1160 }
    ];

    if (logBox) {
      logBox.innerHTML = '';
    }

    steps.forEach(function (st) {
      setTimeout(function () {
        if (progressBar) progressBar.style.width = st.pct + '%';
        if (pctVal) pctVal.textContent = st.pct + '%';
        if (logBox) {
          var div = document.createElement('div');
          div.className = 'log-line' + (st.pct === 100 ? ' log-ok' : (st.pct > 50 ? ' log-accent' : ''));
          div.textContent = st.log;
          logBox.appendChild(div);
          logBox.scrollTop = logBox.scrollHeight;
        }
      }, st.delay);
    });

    setTimeout(function () {
      isScanning = false;
      if (scannerOverlay) scannerOverlay.classList.remove('is-active');
      if (submitBtn) {
        submitBtn.classList.remove('is-loading');
        submitBtn.textContent = localize('Run free technical audit →');
      }

      auditPromise.then(function (audit) {
        renderAuditResult(domain, audit);
        trackPublicEvent('landing_cta_clicked', { source: 'landing_simulator', result: audit ? 'audit_ready' : 'preview_only' });
        if (typeof onComplete === 'function') onComplete(audit || {});
      });
    }, 1600);
  }

  function renderAuditResult(domain, audit) {
    var input = $('.hero-scanner-input');
    if (input) input.value = domain;

    Object.keys(PREVIEW_BARS).forEach(function (engine) {
      var preview = PREVIEW_BARS[engine];
      var bar = $('[data-radar-bar="' + engine + '"]');
      var val = $('[data-radar-val="' + engine + '"]');
      var badge = $('[data-radar-badge="' + engine + '"]');
      if (bar) bar.style.width = preview.width;
      if (val) val.textContent = localize(preview.value);
      if (badge) badge.textContent = localize(preview.badge);
    });

    var ping = $('.console-live-ping');
    if (ping) ping.textContent = localize('● Example workspace preview · {domain}', { domain: domain });

    var banner = $('#console-result-banner');
    var domainEl = $('#banner-domain-name');
    var gradeEl = $('#banner-grade-val');
    var actionBtn = $('#banner-open-app-btn');

    if (banner) {
      if (domainEl) domainEl.textContent = domain;
      var isLiveAudit = audit && audit.kind === 'public_diagnostic_summary';
      var badge = $('.banner-badge', banner);
      var titlePrefix = $('#banner-title-prefix');
      var openLabel = $('#banner-open-app-label');
      if (badge) badge.textContent = isLiveAudit ? localize('Live technical diagnostic · no AI sampling') : localize('Preview only · continue in workspace');
      if (titlePrefix) titlePrefix.textContent = isLiveAudit ? localize('Technical diagnostic ready ·') : localize('Setup preview loaded');
      if (gradeEl) gradeEl.textContent = isLiveAudit ? String(audit.score || 0) + '/100' : 'Preview ready';
      if (openLabel) openLabel.textContent = isLiveAudit ? localize('Create workspace →') : localize('Open Workspace →');
      var details = $('#banner-audit-details');
      if (details) {
        var checks = isLiveAudit && Array.isArray(audit.checks) ? audit.checks : [];
        details.innerHTML = checks.slice(0, 5).map(function (check) {
          return '<span class="audit-result-chip ' + (check.ok ? 'is-ok' : 'is-fail') + '">' +
            (check.ok ? '✓ ' : '⚠ ') + escapeHtml(check.name || localize('Site check')) + '</span>';
        }).join('');
      }
      if (actionBtn) {
        actionBtn.href = '/app#/onboarding?domain=' + encodeURIComponent(domain);
        actionBtn.addEventListener('click', function () {
          try {
            localStorage.setItem('citeaura_pending_domain', domain);
            sessionStorage.setItem('citeaura_pending_domain', domain);
            if (isLiveAudit && audit.audit_id) {
              sessionStorage.setItem('citeaura_pending_audit_id', audit.audit_id);
              sessionStorage.setItem('citeaura_pending_audit', JSON.stringify(audit));
            }
          } catch(e){}
        });
      }
      banner.classList.remove('is-hidden');
      if (isLiveAudit) trackPublicEvent('public_audit_completed', { source: 'landing_simulator' });
    }
  }

  function initSimulator() {
    $$('.preset-pill').forEach(function (pill) {
      pill.addEventListener('click', function () {
        var domain = pill.getAttribute('data-domain');
        if (domain) {
          var input = $('.hero-scanner-input');
          if (input) input.value = domain;
          runPreview(domain);
        }
      });
    });

    var form = $('.hero-scanner-form');
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = $('.hero-scanner-input');
        var domain = (input && input.value.trim()) || 'yourbrand.com';
        domain = domain.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
        if (!domain) domain = 'yourbrand.com';
        
        try {
          localStorage.setItem('citeaura_pending_domain', domain);
          sessionStorage.setItem('citeaura_pending_domain', domain);
        } catch(e){}

        runPreview(domain);
      });
    }

    var sampleLink = $('.hero-sample-link');
    if (sampleLink) sampleLink.addEventListener('click', function () {
      trackPublicEvent('sample_report_viewed', { source: 'landing' });
    });

    $$('.console-tab-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-target');
        $$('.console-tab-btn').forEach(function (b) { b.classList.remove('is-active'); });
        $$('.console-panel').forEach(function (p) { p.classList.remove('is-active'); });
        btn.classList.add('is-active');
        var panel = $('[data-panel="' + target + '"]');
        if (panel) panel.classList.add('is-active');
      });
    });

    var copyBtn = $('.code-copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        var code = $('.code-preview-box pre');
        if (code && navigator.clipboard) {
          navigator.clipboard.writeText(code.textContent).then(function () {
            var orig = copyBtn.textContent;
            copyBtn.textContent = localize('Copied!');
            setTimeout(function () { copyBtn.textContent = orig; }, 2000);
          });
        }
      });
    }
  }

  /* ================================================================
      /* ================================================================
     
     ================================================================ */
  function init() {
    initTheme();
    initNav();
    initHeaderScroll();
    initBilling();
    initReveal();
    initSimulator();
    initLocale();
    setLocale(detectLocale());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
