/* CiteAura Landing - Refactored 2026 - Simplified & Performance Optimized */
(function() {
  'use strict';

  var state = {
    theme: 'dark',
    scrolled: false
  };

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

  /* ================================================================
     Theme Management
     ================================================================ */
  function setTheme(theme, persist) {
    state.theme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = state.theme;
    if (persist) {
      try { localStorage.setItem('utheme', state.theme); } catch (e) {}
    }
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem('utheme'); } catch (e) {}
    var initial = saved || (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    setTheme(initial, false);

    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        var stored = null;
        try { stored = localStorage.getItem('utheme'); } catch (e) {}
        if (!stored) setTheme(e.matches ? 'dark' : 'light', false);
      });
    }
  }

  /* ================================================================
     Header Scroll Effect
     ================================================================ */
  function initHeaderScroll() {
    var header = $('.site-header');
    if (!header) return;

    var ticking = false;
    window.addEventListener('scroll', function() {
      if (!ticking) {
        requestAnimationFrame(function() {
          var scrolled = window.scrollY > 10;
          if (state.scrolled !== scrolled) {
            state.scrolled = scrolled;
            header.style.boxShadow = scrolled ? '0 2px 12px rgba(0,0,0,0.3)' : 'none';
          }
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }

  /* ================================================================
     Smooth Scroll for Anchor Links
     ================================================================ */
  function initSmoothScroll() {
    $$('a[href^="#"]').forEach(function(link) {
      link.addEventListener('click', function(e) {
        var href = link.getAttribute('href');
        if (href === '#' || href.length <= 1) return;

        var target = $(href);
        if (target) {
          e.preventDefault();
          var headerHeight = $('.site-header') ? $('.site-header').offsetHeight : 0;
          var targetPosition = target.getBoundingClientRect().top + window.scrollY - headerHeight - 20;

          window.scrollTo({
            top: targetPosition,
            behavior: 'smooth'
          });
        }
      });
    });
  }

  /* ================================================================
     Intersection Observer for Fade-in Animations
     ================================================================ */
  function initRevealAnimations() {
    if (!('IntersectionObserver' in window)) return;

    var observerOptions = {
      rootMargin: '0px 0px -100px 0px',
      threshold: 0.1
    };

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
          observer.unobserve(entry.target);
        }
      });
    }, observerOptions);

    // Animate sections on scroll
    $$('.section-header, .step-card, .product-shot, .price-card, .faq-item').forEach(function(el, index) {
      el.style.opacity = '0';
      el.style.transform = 'translateY(30px)';
      el.style.transition = 'opacity 0.6s ease-out ' + (index % 3 * 0.1) + 's, transform 0.6s ease-out ' + (index % 3 * 0.1) + 's';
      observer.observe(el);
    });
  }

  /* ================================================================
     FAQ Toggle Enhancement
     ================================================================ */
  function initFAQ() {
    $$('.faq-item').forEach(function(item) {
      item.addEventListener('toggle', function() {
        if (item.open) {
          // Close other FAQs (optional accordion behavior)
          // $$('.faq-item[open]').forEach(function(other) {
          //   if (other !== item) other.removeAttribute('open');
          // });

          // Track FAQ open
          trackEvent('faq_opened', { question: item.querySelector('summary').textContent });
        }
      });
    });
  }

  /* ================================================================
     CTA Click Tracking
     ================================================================ */
  function initCTATracking() {
    $$('.btn-primary').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var location = 'unknown';
        if (btn.closest('.hero')) location = 'hero';
        else if (btn.closest('.pricing-section')) location = 'pricing';
        else if (btn.closest('.final-cta')) location = 'final-cta';

        trackEvent('cta_clicked', { location: location, text: btn.textContent.trim() });
      });
    });
  }

  /* ================================================================
     Analytics Event Tracking
     ================================================================ */
  function trackEvent(eventName, properties) {
    try {
      fetch('/api/v1/events/product', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: eventName,
          properties: properties || {}
        })
      }).catch(function() {});
    } catch (e) {}
  }

  /* ================================================================
     Number Counter Animation (Hero Metrics)
     ================================================================ */
  function animateCounter(element, target, suffix) {
    var current = 0;
    var increment = target / 60;
    var duration = 1500;
    var stepTime = duration / 60;

    var timer = setInterval(function() {
      current += increment;
      if (current >= target) {
        element.textContent = target + (suffix || '');
        clearInterval(timer);
      } else {
        element.textContent = Math.floor(current) + (suffix || '');
      }
    }, stepTime);
  }

  function initMetricCounters() {
    if (!('IntersectionObserver' in window)) return;

    var metrics = [
      { selector: '.hero-metrics .metric-value:nth-of-type(1)', target: 84, suffix: '%' },
      { selector: '.hero-metrics .metric-value:nth-of-type(2)', target: 13, suffix: '' },
      { selector: '.hero-metrics .metric-value:nth-of-type(3)', target: 72, suffix: 'h' }
    ];

    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          metrics.forEach(function(metric) {
            var el = $(metric.selector);
            if (el && !el.dataset.animated) {
              el.dataset.animated = 'true';
              animateCounter(el, metric.target, metric.suffix);
            }
          });
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    var metricsContainer = $('.hero-metrics');
    if (metricsContainer) observer.observe(metricsContainer);
  }

  /* ================================================================
     Lazy Load Images
     ================================================================ */
  function initLazyLoad() {
    if ('loading' in HTMLImageElement.prototype) {
      // Browser supports native lazy loading
      $$('img[loading="lazy"]').forEach(function(img) {
        img.src = img.src;
      });
    } else if ('IntersectionObserver' in window) {
      // Fallback to IntersectionObserver
      var imageObserver = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
          if (entry.isIntersecting) {
            var img = entry.target;
            img.src = img.dataset.src || img.src;
            imageObserver.unobserve(img);
          }
        });
      });

      $$('img[loading="lazy"]').forEach(function(img) {
        imageObserver.observe(img);
      });
    }
  }

  /* ================================================================
     Initialize All Features
     ================================================================ */
  function init() {
    initTheme();
    initHeaderScroll();
    initSmoothScroll();
    initRevealAnimations();
    initFAQ();
    initCTATracking();
    initMetricCounters();
    initLazyLoad();

    // Track page view
    trackEvent('landing_viewed', { version: 'refactored_2026' });

    // Log ready state
    console.log('[CiteAura] Landing page initialized - Refactored 2026');
  }

  /* ================================================================
     DOM Ready
     ================================================================ */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ================================================================
     Export for testing/debugging
     ================================================================ */
  window.CiteAuraLanding = {
    version: '2.0.0-refactored',
    trackEvent: trackEvent,
    setTheme: setTheme
  };

})();
