/* ================================================================
   CiteAura Landing Page Interactive System
   - Live Interactive GEO Sandbox & Matrix Simulator
   - Particle & Constellation Canvas Engine
   - Trilingual i18n & Theme Controller
   - Annual/Monthly Pricing Switcher & Code Copier
   ================================================================ */

(function () {
  'use strict';

  var LOCALES = ['en'];
  var HTML_LANG = { en: 'en', zh: 'zh-CN', ja: 'ja' };
  var THEME_COLORS = { light: '#f7f9fa', dark: '#15181e' };
  var state = { locale: 'en', theme: 'light', billing: 'monthly', catalog: {}, activeDomain: 'yourbrand.com' };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ================================================================
      i18n 
     ================================================================ */
  function detectLocale() {
    var requested = new URLSearchParams(location.search).get('lang');
    var saved = null;
    try { saved = localStorage.getItem('ulang'); } catch (e) {}
    var nav = (navigator.language || '').toLowerCase();
    var guess = requested || saved || (nav.indexOf('zh') === 0 ? 'zh' : nav.indexOf('ja') === 0 ? 'ja' : 'en');
    return 'en';
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
  var TYPED_SENTENCES = {
    en: [
      'Audit citations across ChatGPT, Claude, and Perplexity.',
      'Generate 13 engineering-grade action tickets.',
      'Close knowledge gaps and competitor blind spots.',
      'Automate before/after verification loops.',
      'Export client-ready white-label delivery packs.'
    ]
  };

  function initTypewriter() {
    var el = $('.hero-typed');
    if (!el) return;
    var sentences = TYPED_SENTENCES[state.locale] || TYPED_SENTENCES.en;
    var sentIdx = 0;
    var charIdx = 0;
    var isDeleting = false;
    var speed = 35;
    var pauseEnd = 2200;
    var pauseStart = 500;

    function tick() {
      var current = sentences[sentIdx];
      if (!isDeleting) {
        charIdx++;
        el.textContent = current.substring(0, charIdx);
        if (charIdx === current.length) {
          isDeleting = true;
          setTimeout(tick, pauseEnd);
          return;
        }
        speed = 25 + Math.random() * 20;
      } else {
        charIdx--;
        el.textContent = current.substring(0, charIdx);
        if (charIdx === 0) {
          isDeleting = false;
          sentIdx = (sentIdx + 1) % sentences.length;
          setTimeout(tick, pauseStart);
          return;
        }
        speed = 15;
      }
      setTimeout(tick, speed);
    }
    setTimeout(tick, 1000);
  }

  /* ================================================================
     Hero  (Canvas Particle & Constellation)
     ================================================================ */
  function initParticles() {
    var canvas = $('.hero-particles');
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    var particles = [];
    var PARTICLE_COUNT = 45;
    var MAX_DIST = 120;
    var animId;
    var mouse = { x: -1000, y: -1000 };

    function resize() {
      var hero = canvas.parentElement;
      if (!hero) return;
      canvas.width = hero.offsetWidth;
      canvas.height = hero.offsetHeight;
    }

    function createParticle() {
      return {
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: 1.5 + Math.random() * 2,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        hue: Math.random() > 0.4 ? 196 : 260
      };
    }

    function init() {
      resize();
      particles = [];
      for (var i = 0; i < PARTICLE_COUNT; i++) particles.push(createParticle());
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var dpr = window.devicePixelRatio || 1;

      // 
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = 'oklch(0.65 0.14 ' + p.hue + ' / 0.45)';
        ctx.fill();

        for (var j = i + 1; j < particles.length; j++) {
          var p2 = particles[j];
          var dx = p.x - p2.x;
          var dy = p.y - p2.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < MAX_DIST) {
            var alpha = (1 - dist / MAX_DIST) * 0.2;
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = 'oklch(0.65 0.14 ' + p.hue + ' / ' + alpha + ')';
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }
      }
      animId = requestAnimationFrame(draw);
    }

    init();
    draw();
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('mousemove', function (e) {
      var rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    }, { passive: true });

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) cancelAnimationFrame(animId);
      else draw();
    });
  }

  /* ================================================================
      GEO  (Interactive Live Scanner System)
     ================================================================ */
  var DOMAIN_PRESETS = {
    'yourbrand.com': {
      grade: 'Grade A', overallScore: 94,
      scores: { deepseek: 98, chatgpt: 95, claude: 97, gemini: 94, perplexity: 99 },
      status: { deepseek: '#1 Cited Source', chatgpt: 'Verified Grounded Link', claude: 'Primary Recommendation', gemini: 'Grounded Fact Citations', perplexity: 'Top Deep Research Citation' },
      gaps: '3 extraction blocks missing /llms.txt',
      tickets: [
        { id: 'GEO-01', title: 'Schema.org JSON-LD Knowledge Graph', impact: 'High', effort: 'Quick' },
        { id: 'GEO-03', title: '/llms.txt LLM Direct Ingestion Specification', impact: 'High', effort: 'Quick' },
        { id: 'GEO-07', title: 'Semantic Markdown Extraction Blocks', impact: 'High', effort: 'Medium' }
      ]
    },
    'linear.app': {
      grade: 'Grade A+', overallScore: 98,
      scores: { deepseek: 99, chatgpt: 97, claude: 98, gemini: 96, perplexity: 100 },
      status: { deepseek: '#1 Issue Tracker', chatgpt: 'Default Rec', claude: 'Top Cited Tool', gemini: 'Grounded Fact', perplexity: '100% Citation' },
      gaps: 'Minor competitor comparison block needed',
      tickets: [
        { id: 'GEO-05', title: 'Competitor Matrix Differentiation Block', impact: 'High', effort: 'Quick' },
        { id: 'GEO-12', title: 'Brand Anchor Entity Cross-Verification', impact: 'Medium', effort: 'Quick' }
      ]
    },
    'supabase.com': {
      grade: 'Grade A', overallScore: 96,
      scores: { deepseek: 98, chatgpt: 96, claude: 97, gemini: 95, perplexity: 99 },
      status: { deepseek: '#1 Firebase Alt', chatgpt: 'Verified Link', claude: 'Primary Choice', gemini: 'Grounded Fact', perplexity: 'Top Citation' },
      gaps: 'Pricing page JSON-LD table refresh needed',
      tickets: [
        { id: 'GEO-02', title: 'Pricing & SLA Structured Table Entity', impact: 'High', effort: 'Quick' },
        { id: 'GEO-09', title: 'Robots.txt AI Bot Whitelist Rules', impact: 'Medium', effort: 'Quick' }
      ]
    },
    'stripe.com': {
      grade: 'Grade A+', overallScore: 99,
      scores: { deepseek: 100, chatgpt: 99, claude: 99, gemini: 98, perplexity: 100 },
      status: { deepseek: '#1 Payment Gateway', chatgpt: 'Gold Standard', claude: 'Primary Choice', gemini: 'Grounded Fact', perplexity: 'Top Citation' },
      gaps: 'Localized market citation alignment',
      tickets: [
        { id: 'GEO-08', title: 'Multi-lingual Fact Mirroring Matrix', impact: 'High', effort: 'Medium' },
        { id: 'GEO-13', title: 'Automated Regression Alert Trigger', impact: 'High', effort: 'Quick' }
      ]
    }
  };

  function getDomainAuditData(domain) {
    if (DOMAIN_PRESETS[domain]) return DOMAIN_PRESETS[domain];
    
    // 
    var hash = 0;
    for (var i = 0; i < domain.length; i++) {
      hash = ((hash << 5) - hash) + domain.charCodeAt(i);
      hash |= 0;
    }
    var posHash = Math.abs(hash);
    var dScore = 86 + (posHash % 12);
    var cScore = 84 + ((posHash >> 2) % 13);
    var clScore = 85 + ((posHash >> 4) % 13);
    var gScore = 82 + ((posHash >> 6) % 14);
    var pScore = 90 + ((posHash >> 8) % 10);
    var overall = Math.round((dScore + cScore + clScore + gScore + pScore) / 5);
    var grade = overall >= 95 ? 'Grade A+' : (overall >= 90 ? 'Grade A' : (overall >= 80 ? 'Grade B+' : 'Grade B'));

    return {
      grade: grade,
      overallScore: overall,
      scores: { deepseek: dScore, chatgpt: cScore, claude: clScore, gemini: gScore, perplexity: pScore },
      status: {
        deepseek: dScore >= 95 ? '#1 Cited Source' : 'Top 3 Citation',
        chatgpt: cScore >= 90 ? 'Verified Grounded Link' : 'Grounded Fact Gap',
        claude: clScore >= 90 ? 'Primary Recommendation' : 'Secondary Choice',
        gemini: gScore >= 90 ? 'Grounded Fact Citation' : 'Search Grounding Gap',
        perplexity: pScore >= 95 ? 'Top Deep Research Citation' : 'Indexed Source'
      },
      gaps: 'Entity schema & /llms.txt missing for 2 core pages',
      tickets: [
        { id: 'GEO-01', title: 'Schema.org JSON-LD Knowledge Graph for ' + domain, impact: 'High', effort: 'Quick' },
        { id: 'GEO-03', title: '/llms.txt LLM Direct Ingestion Specification', impact: 'High', effort: 'Quick' },
        { id: 'GEO-06', title: 'Target Conversational FAQ Answer Units', impact: 'High', effort: 'Medium' }
      ]
    };
  }

  var isScanning = false;

  function runLiveScanner(domain, onComplete) {
    if (isScanning) return;
    isScanning = true;

    var scannerOverlay = $('#console-scanner');
    var progressBar = $('#scan-progress-fill');
    var pctVal = $('#scan-pct-val');
    var logBox = $('#scan-terminal-log');
    var titleEl = $('.scan-domain-title');
    var submitBtn = $('.hero-scanner-btn');
    var resultBanner = $('#console-result-banner');

    if (resultBanner) resultBanner.classList.add('is-hidden');
    if (titleEl) titleEl.textContent = 'Scanning ' + domain + '...';
    if (submitBtn) {
      submitBtn.classList.add('is-loading');
      submitBtn.textContent = 'Scanning across 8 AI engines...';
    }

    if (scannerOverlay) {
      scannerOverlay.classList.add('is-active');
    }

    var steps = [
      { pct: 20, log: '▶ Initializing multi-model audit pipeline for: https://' + domain, delay: 50 },
      { pct: 45, log: '● [1/4] Crawling schema.org JSON-LD graph & /llms.txt protocols...', delay: 280 },
      { pct: 70, log: '● [2/4] Live querying DeepSeek-V4, GPT-5.6, Claude 5, Gemini 3.6, Perplexity...', delay: 620 },
      { pct: 88, log: '● [3/4] Calculating competitor perception gap & citation dropoff...', delay: 980 },
      { pct: 100, log: '✔ [4/4] 100% COMPLETE · 13-point GEO Action Playbook compiled!', delay: 1350 }
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
        submitBtn.textContent = 'Run Instant Audit →';
      }

      var data = getDomainAuditData(domain);
      renderAuditResult(domain, data);

      if (typeof onComplete === 'function') onComplete(data);
    }, 1600);
  }

  function renderAuditResult(domain, data) {
    var input = $('.hero-scanner-input');
    if (input) input.value = domain;

    // 
    Object.keys(data.scores).forEach(function (engine) {
      var score = data.scores[engine];
      var status = data.status[engine];
      var bar = $('[data-radar-bar="' + engine + '"]');
      var val = $('[data-radar-val="' + engine + '"]');
      var badge = $('[data-radar-badge="' + engine + '"]');
      if (bar) bar.style.width = score + '%';
      if (val) val.textContent = score + '%';
      if (badge) badge.textContent = status;
    });

    //  Live Ping
    var ping = $('.console-live-ping');
    if (ping) ping.textContent = '● PING: ' + (12 + Math.floor(Math.random() * 8)) + 'ms · ' + domain;

    // 
    var banner = $('#console-result-banner');
    var domainEl = $('#banner-domain-name');
    var gradeEl = $('#banner-grade-val');
    var actionBtn = $('#banner-open-app-btn');

    if (banner) {
      if (domainEl) domainEl.textContent = domain;
      if (gradeEl) gradeEl.textContent = data.grade + ' (' + data.overallScore + '/100)';
      if (actionBtn) {
        actionBtn.href = '/app#/onboarding?domain=' + encodeURIComponent(domain);
        actionBtn.addEventListener('click', function () {
          try {
            localStorage.setItem('citeaura_pending_domain', domain);
            sessionStorage.setItem('citeaura_pending_domain', domain);
          } catch(e){}
        });
      }
      banner.classList.remove('is-hidden');
    }
  }

  function initSimulator() {
    // ：
    $$('.preset-pill').forEach(function (pill) {
      pill.addEventListener('click', function () {
        var domain = pill.getAttribute('data-domain');
        if (domain) {
          var input = $('.hero-scanner-input');
          if (input) input.value = domain;
          runLiveScanner(domain);
        }
      });
    });

    // ：
    var form = $('.hero-scanner-form');
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = $('.hero-scanner-input');
        var domain = (input && input.value.trim()) || 'yourbrand.com';
        domain = domain.replace(/^https?:\/\//, '').replace(/\/.*$/, '');
        if (!domain) domain = 'yourbrand.com';
        
        // 
        try {
          localStorage.setItem('citeaura_pending_domain', domain);
          sessionStorage.setItem('citeaura_pending_domain', domain);
        } catch(e){}

        runLiveScanner(domain);
      });
    }

    // 
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

    // 
    var copyBtn = $('.code-copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        var code = $('.code-preview-box pre');
        if (code && navigator.clipboard) {
          navigator.clipboard.writeText(code.textContent).then(function () {
            var orig = copyBtn.textContent;
            copyBtn.textContent = 'Copied!';
            setTimeout(function () { copyBtn.textContent = orig; }, 2000);
          });
        }
      });
    }
  }

  /* ================================================================
      (Mouse Spotlight)
     ================================================================ */
  function initMouseGlow() {
    var cards = $$('.price-card, .operations-list > div, .truth-pillar-card, .ticket-full-card, .workflow-card');
    cards.forEach(function (card) {
      card.addEventListener('mousemove', function (e) {
        var rect = card.getBoundingClientRect();
        var x = ((e.clientX - rect.left) / rect.width * 100).toFixed(1);
        var y = ((e.clientY - rect.top) / rect.height * 100).toFixed(1);
        card.style.setProperty('--mouse-x', x + '%');
        card.style.setProperty('--mouse-y', y + '%');
      });
    });
  }

  /* ================================================================
     
     ================================================================ */
  function init() {
    initTheme();
    initNav();
    initHeaderScroll();
    initBilling();
    initReveal();
    initTypewriter();
    initParticles();
    initSimulator();
    initMouseGlow();
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
