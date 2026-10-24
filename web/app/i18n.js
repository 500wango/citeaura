/**
 * CiteAura Internationalization Client.
 * Every user-facing key must exist in every supported catalog.
 */

export const SUPPORTED_LOCALES = ['en', 'zh', 'ja', 'ko', 'es', 'fr', 'de'];
export const DEFAULT_LOCALE = 'en';

const HTML_LANG_MAP = {
  en: 'en',
  zh: 'zh-CN',
  ja: 'ja',
  ko: 'ko',
  es: 'es',
  fr: 'fr',
  de: 'de',
};

export const LOCALE_LABELS = {
  en: 'English',
  zh: '简体中文',
  ja: '日本語',
  ko: '한국어',
  es: 'Español',
  fr: 'Français',
  de: 'Deutsch',
};

let currentLocale = 'en';
let currentCatalog = {};
let fallbackCatalog = {};
let reverseFallbackCatalog = {};
let catalogRequest = 0;
const subscribers = [];

function normalizeLocale(locale) {
  const value = String(locale || '').trim().toLowerCase().replace('_', '-');
  const primary = value.split('-', 1)[0];
  return SUPPORTED_LOCALES.includes(primary) ? primary : DEFAULT_LOCALE;
}

export function detectLocale() {
  const query = new URLSearchParams(window.location.search).get('lang');
  if (query) return normalizeLocale(query);
  try {
    const stored = localStorage.getItem('ulang');
    if (stored) return normalizeLocale(stored);
  } catch (e) {}
  const browser = Array.isArray(navigator.languages) ? navigator.languages : [navigator.language];
  for (const value of browser) {
    const locale = normalizeLocale(value);
    if (locale !== DEFAULT_LOCALE || String(value || '').toLowerCase().startsWith('en')) return locale;
  }
  return DEFAULT_LOCALE;
}

export function getLocale() {
  return currentLocale;
}

export function subscribeLocale(callback) {
  subscribers.push(callback);
  return () => {
    const idx = subscribers.indexOf(callback);
    if (idx >= 0) subscribers.splice(idx, 1);
  };
}

function notifySubscribers() {
  subscribers.forEach((cb) => cb(currentLocale));
}

export async function loadCatalogs(locale = 'en') {
  currentLocale = normalizeLocale(locale);
  const requestId = ++catalogRequest;
  try {
    localStorage.setItem('ulang', currentLocale);
  } catch (e) {}

  document.documentElement.lang = HTML_LANG_MAP[currentLocale] || 'en';

  try {
    const requests = currentLocale === DEFAULT_LOCALE
      ? [fetch('/i18n/en.json', { cache: 'force-cache' })]
      : [
        fetch('/i18n/en.json', { cache: 'force-cache' }),
        fetch(`/i18n/${currentLocale}.json`, { cache: 'force-cache' }),
      ];
    const responses = await Promise.all(requests);
    const fallbackRes = responses[0];
    const localeRes = responses[1] || fallbackRes;
    const loadedFallback = fallbackRes.ok ? await fallbackRes.json() : {};
    const loadedLocale = currentLocale === DEFAULT_LOCALE
      ? loadedFallback
      : (localeRes.ok ? await localeRes.json() : {});
    if (requestId !== catalogRequest) return loadedLocale;
    fallbackCatalog = loadedFallback;
    reverseFallbackCatalog = Object.entries(fallbackCatalog).reduce((result, [key, value]) => {
      if (typeof value === 'string' && !Object.prototype.hasOwnProperty.call(result, value)) result[value] = key;
      return result;
    }, {});
    currentCatalog = loadedLocale;
    if (currentLocale !== DEFAULT_LOCALE) {
      const missing = Object.keys(fallbackCatalog).filter((key) => !Object.prototype.hasOwnProperty.call(currentCatalog, key));
      if (missing.length) console.error(`Incomplete ${currentLocale} catalog: ${missing.length} missing keys`, missing);
    }
  } catch (err) {
    console.warn('Failed to load locale catalog, using in-memory fallbacks', err);
    if (requestId === catalogRequest) {
      currentCatalog = {};
      fallbackCatalog = {};
      reverseFallbackCatalog = {};
    }
  }

  if (requestId === catalogRequest) notifySubscribers(currentLocale);
  return currentCatalog;
}

export async function setLocale(locale = DEFAULT_LOCALE) {
  await loadCatalogs(locale);
}

export function hasCatalogKey(key) {
  if (!key) return false;
  if (Object.prototype.hasOwnProperty.call(currentCatalog, key)) return true;
  return currentLocale === DEFAULT_LOCALE && Object.prototype.hasOwnProperty.call(fallbackCatalog, key);
}

const warnedMissingKeys = new Set();

/** Development is detected without a build step: local dev servers only. */
function isDevelopment() {
  try {
    const host = String(window.location.hostname || '').toLowerCase();
    const protocol = String(window.location.protocol || '').toLowerCase();
    return protocol === 'file:'
      || host === 'localhost'
      || host === '127.0.0.1'
      || host === '0.0.0.0'
      || host === '[::1]'
      || host.endsWith('.localhost');
  } catch (e) {
    return false;
  }
}

/**
 * Translate key with interpolation. Fallback chain: current locale catalog →
 * English catalog → `fallback` argument → the key itself. A literal
 * `[[missing:key]]` marker used to reach end users, so missing copy now
 * degrades to readable text and only warns in development (once per key).
 * @param {string} key - Dot-delimited key (e.g. 'nav.overview')
 * @param {object} params - Interpolation parameters { count: 5 }
 * @param {string} fallback - Default English fallback text
 */
export function t(key, params = {}, fallback = '') {
  if (!key) return fallback || '';

  let val = Object.prototype.hasOwnProperty.call(currentCatalog, key) ? currentCatalog[key] : undefined;
  if (val === undefined || val === null) {
    val = Object.prototype.hasOwnProperty.call(fallbackCatalog, key) ? fallbackCatalog[key] : undefined;
  }
  if (val === undefined || val === null) {
    val = typeof fallback === 'string' && fallback !== '' ? fallback : undefined;
  }
  if (val === undefined || val === null) {
    if (isDevelopment() && !warnedMissingKeys.has(key)) {
      warnedMissingKeys.add(key);
      console.warn(`[i18n] missing key "${key}" for locale "${currentLocale}"`);
    }
    val = key;
  }

  let text = String(val);
  if (params && typeof params === 'object') {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), () => String(v));
    });
  }
  return text;
}

export function tError(err, fallbackKey = 'error.generic') {
  const code = typeof err?.error === 'string' ? err.error.trim() : '';
  if (code && hasCatalogKey(code)) return t(code);
  if (code && hasCatalogKey(`error.${code}`)) return t(`error.${code}`);
  if (fallbackKey && hasCatalogKey(fallbackKey)) return t(fallbackKey);
  if (currentLocale === DEFAULT_LOCALE && err?.detail) return String(err.detail);
  return t('error.generic', {}, 'Request failed');
}

/** Translate a legacy literal while a view is being migrated to a stable key. */
export function translateText(value) {
  if (typeof value !== 'string' || currentLocale === DEFAULT_LOCALE) return value;
  const key = reverseFallbackCatalog[value];
  if (!key) return value;
  // 兜底顺序与 t() 保持一致：当前语言 → 英文目录 → 原字面量。
  return currentCatalog[key] || fallbackCatalog[key] || value;
}

const BACKEND_LABEL_KEYS = {
  'Representative baseline': 'overview.baseline_representative',
  'Limited baseline': 'overview.baseline_limited',
  'Single baseline': 'overview.baseline_single',
  'No baseline': 'overview.no_baseline',
};

export function translateBackendLabel(value) {
  const key = BACKEND_LABEL_KEYS[value];
  return key ? t(key, {}, value) : value;
}

export function ticketField(ticket, field, enField, fallback = '') {
  const locale = getLocale();
  const localized = locale === 'en' ? '' : ticket?.[`${field}_${locale}`];
  const source = localized || ticket?.[enField] || ticket?.[field] || fallback;
  if (!source) return '';
  return t(source, {}, source);
}

function issueParams(issue) {
  const message = String(issue?.message || '');
  if (issue?.code === 'crawl_limited') {
    const found = message.match(/Only (\d+)\/(\d+) pages accessible/);
    if (found) return { ok: found[1], crawled: found[2] };
  }
  if (issue?.code === 'question_evidence_limited') {
    const found = message.match(/(\d+) question\(s\) are missing (\d+) comparable/);
    if (found) return { questions: found[1], samples: found[2] };
  }
  if (issue?.code === 'sampling_insufficient') {
    const found = message.match(/Currently only (\d+) valid samples/);
    if (found) {
      const minimum = String(issue?.action || '').match(/at least (\d+)/);
      return { count: found[1], minimum: minimum ? minimum[1] : '20' };
    }
  }
  if (issue?.code === 'sampling_platforms_limited') {
    const found = message.match(/Currently only (\d+) sampled platform/);
    if (found) {
      const minimum = String(issue?.action || '').match(/at least (\d+)/);
      return { count: found[1], minimum: minimum ? minimum[1] : '2' };
    }
  }
  if (issue?.code === 'sampling_failure_high') {
    const found = message.match(/failure rate is ([0-9.]+%)/);
    if (found) return { rate: found[1] };
  }
  return {};
}

/** Localize a report-quality issue while preserving its original message as fallback. */
export function issueText(issue, field = 'message') {
  const code = issue?.code;
  if (!code) return issue?.[field] || '';
  let variant = code;
  if (code === 'sampling_insufficient') {
    if (/does not record/i.test(issue.message || '')) variant = 'sampling_insufficient_unrecorded';
    else if (/Currently only/i.test(issue.message || '')) variant = 'sampling_insufficient_limited';
  }
  const key = `report.issue.${variant}.${field}`;
  if (!hasCatalogKey(key)) return issue?.[field] || '';
  return t(key, issueParams(issue), issue?.[field] || '');
}

/** Localize exact legacy literals left in older view templates. */
export function localizeRenderedText(root = document) {
  if (currentLocale === DEFAULT_LOCALE || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    if (node.parentElement?.closest('script,style,code,pre')) return;
    const raw = node.nodeValue || '';
    const trimmed = raw.trim();
    if (!trimmed) return;
    const translated = translateText(trimmed);
    if (translated !== trimmed) node.nodeValue = raw.replace(trimmed, translated);
  });
  root.querySelectorAll?.('[title],[aria-label],[placeholder]').forEach((node) => {
    ['title', 'aria-label', 'placeholder'].forEach((attribute) => {
      const value = node.getAttribute(attribute);
      const translated = translateText(value);
      if (translated !== value) node.setAttribute(attribute, translated);
    });
  });
}

export default {
  SUPPORTED_LOCALES,
  LOCALE_LABELS,
  DEFAULT_LOCALE,
  detectLocale,
  getLocale,
  loadCatalogs,
  setLocale,
  subscribeLocale,
  translateText,
  translateBackendLabel,
  ticketField,
  issueText,
  localizeRenderedText,
  hasCatalogKey,
  tError,
  t,
};
