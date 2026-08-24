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
  var LOCALE_ASSET_VERSION = '3.4';
  var state = { locale: 'en', theme: 'light', billing: 'monthly', catalog: {}, fallbackCatalog: {}, literalCatalog: {}, defaults: new WeakMap(), activeDomain: 'yourbrand.com' };

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

  // Public pages use a separate catalog so marketing copy does not expand the
  // authenticated product locale contract. Keep dynamic preview strings on
  // explicit keys instead of relying on fragile English text reverse lookup.
  function publicValue(key, fallback, params) {
    var localized = catalogValue(key);
    var text = localized != null ? localized : fallback;
    Object.keys(params || {}).forEach(function (name) {
      text = text.replace(new RegExp('\\{' + name + '\\}', 'g'), function () { return String(params[name]); });
    });
    return text;
  }

  function rememberDefault(node, kind, value) {
    var defaults = state.defaults.get(node);
    if (!defaults) {
      defaults = {};
      state.defaults.set(node, defaults);
    }
    if (!Object.prototype.hasOwnProperty.call(defaults, kind)) defaults[kind] = value;
    return defaults[kind];
  }

  function normalizeText(str) {
    return String(str || '').replace(/\s+/g, ' ').trim();
  }

  function localize(value, params) {
    var text = String(value == null ? '' : value);
    if (state.locale === 'en') return text;
    var norm = normalizeText(text);
    if (!norm) return text;
    var key = state.reverseMap ? (state.reverseMap[norm] || state.reverseMap[text]) : null;
    if (!key) {
      key = Object.keys(state.fallbackCatalog).find(function (candidate) {
        var cVal = state.fallbackCatalog[candidate];
        return cVal === text || normalizeText(cVal) === norm;
      });
    }
    var localized = key && state.catalog[key] != null ? state.catalog[key] : text;
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
      if (node.parentElement && node.parentElement.closest('script,style,code,pre,[data-i18n],.plan-name')) return;
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
      var defaultHtml = rememberDefault(node, 'html', node.innerHTML);
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      if (value != null) {
        if (node.tagName === 'TITLE') { document.title = value; return; }
        if (value.indexOf('<') >= 0 && value.indexOf('>') >= 0) {
          node.innerHTML = value;
        } else {
          node.textContent = value;
        }
      } else node.innerHTML = defaultHtml;
    });
    $$('[data-i18n-html]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-html');
      var defaultHtml = rememberDefault(node, 'html', node.innerHTML);
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.innerHTML = value != null ? value : defaultHtml;
    });
    var title = catalogValue('landing.title');
    if (title && !document.querySelector('title[data-i18n]')) document.title = title;
    $$('[data-i18n-content]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-content');
      var defaultValue = rememberDefault(node, 'content', node.getAttribute('content') || '');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.setAttribute('content', value != null ? value : defaultValue);
    });
    $$('[data-i18n-aria]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-aria');
      var defaultValue = rememberDefault(node, 'aria', node.getAttribute('aria-label') || '');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.setAttribute('aria-label', value != null ? value : defaultValue);
    });
    $$('[data-i18n-alt]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-alt');
      var defaultValue = rememberDefault(node, 'alt', node.getAttribute('alt') || '');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.setAttribute('alt', value != null ? value : defaultValue);
    });
    $$('[data-i18n-placeholder]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-placeholder');
      var defaultValue = rememberDefault(node, 'placeholder', node.getAttribute('placeholder') || '');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.setAttribute('placeholder', value != null ? value : defaultValue);
    });
    $$('[data-i18n-title]').forEach(function (node) {
      var key = node.getAttribute('data-i18n-title');
      var defaultValue = rememberDefault(node, 'title', node.getAttribute('title') || '');
      var value = catalogValue(key);
      if (value == null && state.locale === 'en') value = state.fallbackCatalog[key];
      node.setAttribute('title', value != null ? value : defaultValue);
    });
    applyBilling();
    renderThemeControl();
    refreshPreviewLocale();
    localizeLegacyText();
  }

  function setLocale(locale) {
    state.locale = normalizeLocale(locale);
    document.documentElement.lang = state.locale === 'zh' ? 'zh-CN' : state.locale;
    try { localStorage.setItem('ulang', state.locale); } catch (e) {}
    var selector = $('#site-locale');
    if (selector) selector.value = state.locale;
      var catalogRequests = [
        fetch('/i18n/en.json?v=' + LOCALE_ASSET_VERSION).then(function (r) { return r.ok ? r.json() : {}; }),
      ];
      if (state.locale !== 'en') {
        catalogRequests.push(fetch('/i18n/' + state.locale + '.json?v=' + LOCALE_ASSET_VERSION).then(function (r) { return r.ok ? r.json() : {}; }));
      }
      if (state.locale === 'zh') {
        catalogRequests.push(fetch('/i18n/public/zh.json?v=' + LOCALE_ASSET_VERSION).then(function (r) { return r.ok ? r.json() : {}; }));
      }
      Promise.all(catalogRequests)
      .then(function (catalogs) {
        state.fallbackCatalog = catalogs[0] || {};
        state.catalog = state.locale === 'en' ? state.fallbackCatalog : Object.assign({}, catalogs[1] || {}, catalogs[2] || {});
        state.reverseMap = {};
        Object.keys(state.fallbackCatalog).forEach(function (k) {
          var val = state.fallbackCatalog[k];
          if (typeof val === 'string') {
            state.reverseMap[val] = k;
            state.reverseMap[normalizeText(val)] = k;
          }
        });
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
    fetch('/api/v1/billing/plans', { credentials: 'omit', cache: 'force-cache' })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        (payload && payload.plans || []).forEach(function (plan) {
          var card = $('[data-plan-code="' + plan.code + '"]');
          if (!card || !plan.prices) return;
          var monthly = plan.prices.monthly && plan.prices.monthly.usd;
          var annual = plan.prices.annual && plan.prices.annual.usd;
          var price = card.querySelector('.price strong');
          if (typeof monthly === 'number' && price) {
            price.setAttribute('data-monthly', '$' + monthly);
            price.textContent = '$' + monthly;
          }
          if (typeof annual === 'number' && price) price.setAttribute('data-annual', '$' + annual);
        });
        applyBilling();
      })
      .catch(function () { /* static prices remain the offline fallback */ });
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
    deepseek: { width: '68%', badge: ['public.landing.radar_deepseek_badge', 'Example API trace'], value: ['public.landing.radar_prompt_log', 'Prompt log'] },
    chatgpt: { width: '72%', badge: ['public.landing.radar_chatgpt_badge', 'Example grounded run'], value: ['public.landing.radar_source_links', 'Source links'] },
    claude: { width: '64%', badge: ['public.landing.radar_claude_badge', 'Example answer replay'], value: ['public.landing.radar_answer_diff', 'Answer diff'] },
    gemini: { width: '58%', badge: ['public.landing.radar_gemini_badge', 'Example retrieval view'], value: ['public.landing.radar_crawl_notes', 'Crawl notes'] },
    grok: { width: '61%', badge: ['public.landing.radar_grok_badge', 'Example search replay'], value: ['public.landing.radar_search_notes', 'Search notes'] },
    perplexity: { width: '76%', badge: ['public.landing.radar_perplexity_badge', 'Example research replay'], value: ['public.landing.radar_citation_trail', 'Citation trail'] }
  };

  var isScanning = false;
  var previewState = { audit: null, hasResult: false, scanSteps: [] };

  function renderRadarPreview() {
    if (!previewState.hasResult && state.locale !== 'zh') return;
    Object.keys(PREVIEW_BARS).forEach(function (engine) {
      var preview = PREVIEW_BARS[engine];
      var bar = $('[data-radar-bar="' + engine + '"]');
      var val = $('[data-radar-val="' + engine + '"]');
      var badge = $('[data-radar-badge="' + engine + '"]');
      if (bar) bar.style.width = preview.width;
      if (val) val.textContent = publicValue(preview.value[0], preview.value[1]);
      if (badge) badge.textContent = publicValue(preview.badge[0], preview.badge[1]);
    });
  }

  function refreshPreviewLocale() {
    var domain = state.activeDomain || 'yourbrand.com';
    var titleEl = $('.scan-domain-title');
    var submitBtn = $('.hero-scanner-btn');
    var ping = $('.console-live-ping');
    if (titleEl) titleEl.textContent = publicValue('public.landing.preview_preparing', 'Preparing {domain} workspace...', { domain: domain });
    if (submitBtn) submitBtn.textContent = isScanning ? publicValue('public.landing.preview_button_loading', catalogValue('landing.scan_btn') || 'Preparing workspace preview...') : (catalogValue('landing.scan_btn') || publicValue('public.landing.preview_button_run', 'Run free technical audit →'));
    if (ping) ping.textContent = publicValue('public.landing.preview_live_ping', '● Example workspace preview · {domain}', { domain: domain });
    renderRadarPreview();

    previewState.scanSteps.forEach(function (step, index) {
      var line = $('.scan-terminal-log .log-line[data-preview-step="' + index + '"]');
      if (line) line.textContent = publicValue(step.key, step.fallback, step.params);
    });
    if (previewState.hasResult) renderAuditResult(domain, previewState.audit, { track: false });
  }

  function runPreview(domain, onComplete) {
    if (isScanning) return;
    isScanning = true;
    state.activeDomain = domain;
    previewState.audit = null;
    previewState.hasResult = false;

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
    }).catch(function () { return { error: 'public_audit_failed' }; });

    if (resultBanner) resultBanner.classList.add('is-hidden');
    if (titleEl) titleEl.textContent = publicValue('public.landing.preview_preparing', 'Preparing {domain} workspace...', { domain: domain });
    if (submitBtn) {
      submitBtn.classList.add('is-loading');
      submitBtn.textContent = publicValue('public.landing.preview_button_loading', 'Preparing workspace preview...');
    }

    if (scannerOverlay) {
      scannerOverlay.classList.add('is-active');
    }

    var steps = [
      { pct: 20, key: 'public.landing.preview_log_capture', fallback: '▶ Capturing the requested domain: https://{domain}', params: { domain: domain }, delay: 50 },
      { pct: 45, key: 'public.landing.preview_log_setup', fallback: '● [1/4] Opening the guided setup flow and project shell...', params: {}, delay: 260 },
      { pct: 70, key: 'public.landing.preview_log_report', fallback: '● [2/4] Previewing example report, ticket, and asset views...', params: {}, delay: 560 },
      { pct: 88, key: 'public.landing.preview_log_save', fallback: '● [3/4] Saving the domain for workspace onboarding...', params: {}, delay: 860 },
      { pct: 100, key: 'public.landing.preview_log_ready', fallback: '✔ [4/4] Preview ready. Run the full audit inside the app.', params: {}, delay: 1160 }
    ];
    previewState.scanSteps = steps;

    if (logBox) {
      logBox.innerHTML = '';
    }

    steps.forEach(function (st, index) {
      setTimeout(function () {
        if (progressBar) progressBar.style.width = st.pct + '%';
        if (pctVal) pctVal.textContent = st.pct + '%';
        if (logBox) {
          var div = document.createElement('div');
          div.className = 'log-line' + (st.pct === 100 ? ' log-ok' : (st.pct > 50 ? ' log-accent' : ''));
          div.dataset.previewStep = String(index);
          div.textContent = publicValue(st.key, st.fallback, st.params);
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
        submitBtn.textContent = publicValue('public.landing.preview_button_run', 'Run free technical audit →');
      }

      auditPromise.then(function (audit) {
        renderAuditResult(domain, audit, { track: true });
        trackPublicEvent('landing_cta_clicked', { source: 'landing_simulator', result: audit && audit.kind === 'public_diagnostic_summary' ? 'audit_ready' : 'audit_failed' });
        if (typeof onComplete === 'function') onComplete(audit || {});
      });
    }, 1600);
  }

  function renderAuditResult(domain, audit, options) {
    options = options || {};
    state.activeDomain = domain;
    previewState.audit = audit || {};
    previewState.hasResult = true;
    var input = $('.hero-scanner-input');
    if (input) input.value = domain;

    renderRadarPreview();

    var ping = $('.console-live-ping');
    if (ping) ping.textContent = publicValue('public.landing.preview_live_ping', '● Example workspace preview · {domain}', { domain: domain });

    var banner = $('#console-result-banner');
    var domainEl = $('#banner-domain-name');
    var gradeEl = $('#banner-grade-val');
    var actionBtn = $('#banner-open-app-btn');

    if (banner) {
      if (domainEl) domainEl.textContent = domain;
      var isLiveAudit = audit && audit.kind === 'public_diagnostic_summary';
      var isAuditFailure = audit && audit.error;
      var badge = $('.banner-badge', banner);
      var titlePrefix = $('#banner-title-prefix');
      var openLabel = $('#banner-open-app-label');
      if (badge) badge.textContent = isLiveAudit ? publicValue('public.landing.preview_live_badge', 'Live technical diagnostic · no AI sampling') : (isAuditFailure ? publicValue('public.landing.preview_diagnostic_unavailable', 'Diagnostic unavailable · retry') : publicValue('public.landing.preview_only_badge', 'Preview only · continue in workspace'));
      if (titlePrefix) titlePrefix.textContent = isLiveAudit ? publicValue('public.landing.preview_live_title', 'Technical diagnostic ready ·') : (isAuditFailure ? publicValue('public.landing.preview_diagnostic_unavailable_title', 'Technical diagnostic unavailable') : publicValue('public.landing.preview_loaded_title', 'Setup preview loaded'));
      if (gradeEl) gradeEl.textContent = isLiveAudit ? String(audit.score || 0) + '/100' : (isAuditFailure ? publicValue('public.landing.preview_unavailable', 'Unavailable') : publicValue('public.landing.preview_ready', 'Preview ready'));
      if (openLabel) openLabel.textContent = isLiveAudit ? publicValue('public.landing.preview_create_workspace', 'Create workspace →') : publicValue('public.landing.preview_open_workspace', 'Open Workspace →');
      var details = $('#banner-audit-details');
      if (details) {
        var checks = isLiveAudit && Array.isArray(audit.checks) ? audit.checks : [];
        if (isAuditFailure) checks = [{ name: publicValue('public.landing.preview_diagnostic_failed_body', 'The live audit could not be completed. Please retry or continue to the workspace.'), ok: false }];
        details.innerHTML = checks.slice(0, 5).map(function (check) {
          return '<span class="audit-result-chip ' + (check.ok ? 'is-ok' : 'is-fail') + '">' +
            (check.ok ? '✓ ' : '⚠ ') + escapeHtml(check.name || publicValue('public.landing.preview_site_check', 'Site check')) + '</span>';
        }).join('');
      }
      if (actionBtn) {
        actionBtn.href = '/app#/onboarding?domain=' + encodeURIComponent(domain);
        if (actionBtn.__citeAuraPreviewHandler) actionBtn.removeEventListener('click', actionBtn.__citeAuraPreviewHandler);
        actionBtn.__citeAuraPreviewHandler = function () {
          try {
            localStorage.setItem('citeaura_pending_domain', domain);
            sessionStorage.setItem('citeaura_pending_domain', domain);
            if (isLiveAudit && audit.audit_id) {
              sessionStorage.setItem('citeaura_pending_audit_id', audit.audit_id);
              sessionStorage.setItem('citeaura_pending_audit', JSON.stringify(audit));
            }
          } catch(e){}
        };
        actionBtn.addEventListener('click', actionBtn.__citeAuraPreviewHandler);
      }
      banner.classList.remove('is-hidden');
      if (isLiveAudit && options.track !== false) trackPublicEvent('public_audit_completed', { source: 'landing_simulator' });
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
            copyBtn.textContent = publicValue('public.landing.preview_copied', 'Copied!');
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
