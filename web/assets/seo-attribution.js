/* First-party SEO attribution: paths and source hosts only, never full referrer URLs. */
(function () {
  'use strict';

  var STORAGE_KEY = 'citeaura_seo_attribution_v1';
  var VIEW_KEY = 'citeaura_seo_viewed_v1:' + window.location.pathname;
  var SEARCH_HOSTS = ['google.', 'bing.', 'duckduckgo.', 'search.brave.', 'yahoo.', 'baidu.', 'yandex.'];

  function clean(value, max) {
    return String(value || '').replace(/[\r\n]/g, ' ').trim().slice(0, max || 128);
  }

  function cleanLabel(value, max) {
    var text = clean(value, max);
    if (!text) return '';
    if (text.indexOf('://') >= 0 || text.indexOf('//') === 0) {
      try {
        var parsed = new URL(text.indexOf('://') >= 0 ? text : 'https:' + text);
        return clean(parsed.hostname, max).toLowerCase();
      } catch (error) {}
    }
    return text.split('?')[0].split('#')[0];
  }

  function referrerInfo() {
    try {
      var parsed = new URL(document.referrer);
      if (!parsed.hostname || parsed.hostname === window.location.hostname) return { host: '', isSearch: false };
      var host = parsed.hostname.toLowerCase();
      return { host: host.slice(0, 128), isSearch: SEARCH_HOSTS.some(function (needle) { return host.indexOf(needle) >= 0; }) };
    } catch (error) {
      return { host: '', isSearch: false };
    }
  }

  function readStored() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') || {}; } catch (error) { return {}; }
  }

  var params = new URLSearchParams(window.location.search);
  var referrer = referrerInfo();
  var stored = readStored();
  var utmSource = cleanLabel(params.get('utm_source'), 128);
  var utmMedium = cleanLabel(params.get('utm_medium'), 64);
  var utmCampaign = cleanLabel(params.get('utm_campaign'), 128);
  var storedSource = cleanLabel(stored.source, 128);
  var storedMedium = cleanLabel(stored.medium, 64);
  var storedCampaign = cleanLabel(stored.campaign, 128);
  var source = utmSource || storedSource || (referrer.isSearch ? 'organic' : (referrer.host || 'direct'));
  var medium = utmMedium || storedMedium || (referrer.isSearch ? 'organic' : (referrer.host ? 'referral' : 'none'));
  var campaign = utmCampaign || storedCampaign || '';
  var attribution = {
    source: source,
    medium: medium,
    campaign: campaign,
    first_touch_path: stored.first_touch_path || window.location.pathname,
    referrer_host: referrer.host,
  };

  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(attribution)); } catch (error) {}

  var properties = {
    page_path: window.location.pathname,
    content_id: document.documentElement.getAttribute('data-seo-content') || window.location.pathname,
    source: source,
    medium: medium,
    campaign: campaign,
    referrer_host: referrer.host,
    first_touch_path: attribution.first_touch_path,
    organic_search: medium === 'organic',
  };

  try {
    if (sessionStorage.getItem(VIEW_KEY)) return;
    sessionStorage.setItem(VIEW_KEY, '1');
  } catch (error) {}

  window.fetch('/api/v1/events/product', {
    method: 'POST',
    credentials: 'include',
    keepalive: true,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'seo_page_view', properties: properties }),
  }).catch(function () {});
})();
