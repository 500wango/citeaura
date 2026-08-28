/**
 * CiteAura Internationalization Client.
 * Every user-facing key must exist in every supported catalog.
 */

// Product UI is intentionally English-only until multilingual demand is validated.
// The dormant catalog files remain available for a future, explicit relaunch.
export const SUPPORTED_LOCALES = ['en'];
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
const subscribers = [];

function normalizeLocale(locale) {
  const value = String(locale || '').trim().toLowerCase().replace('_', '-');
  const primary = value.split('-', 1)[0];
  return SUPPORTED_LOCALES.includes(primary) ? primary : DEFAULT_LOCALE;
}

export function detectLocale() {
  // Do not infer product language from browser, URL, or stale localStorage.
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
  currentLocale = DEFAULT_LOCALE;
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
    fallbackCatalog = fallbackRes.ok ? await fallbackRes.json() : {};
    reverseFallbackCatalog = Object.entries(fallbackCatalog).reduce((result, [key, value]) => {
      if (typeof value === 'string' && !Object.prototype.hasOwnProperty.call(result, value)) result[value] = key;
      return result;
    }, {});
    currentCatalog = currentLocale === DEFAULT_LOCALE
      ? fallbackCatalog
      : (localeRes.ok ? await localeRes.json() : {});
    if (currentLocale !== DEFAULT_LOCALE) {
      const missing = Object.keys(fallbackCatalog).filter((key) => !Object.prototype.hasOwnProperty.call(currentCatalog, key));
      if (missing.length) console.error(`Incomplete ${currentLocale} catalog: ${missing.length} missing keys`, missing);
    }
  } catch (err) {
    console.warn('Failed to load locale catalog, using in-memory fallbacks', err);
  }

  notifySubscribers(currentLocale);
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

/**
 * Translate key with interpolation. English fallback is intentionally disabled
 * for non-English locales so missing copy is visible in development and CI.
 * @param {string} key - Dot-delimited key (e.g. 'nav.overview')
 * @param {object} params - Interpolation parameters { count: 5 }
 * @param {string} fallback - Default English fallback text
 */
export function t(key, params = {}, fallback = '') {
  if (!key) return fallback || '';

  let val = currentCatalog[key];
  if ((val === undefined || val === null) && currentLocale === DEFAULT_LOCALE) {
    val = fallbackCatalog[key];
  }
  if (val === undefined || val === null) {
    val = currentLocale === DEFAULT_LOCALE && fallback !== undefined && fallback !== ''
      ? fallback
      : `[[missing:${key}]]`;
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
  return currentCatalog[key] || `[[missing:${key}]]`;
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
  localizeRenderedText,
  hasCatalogKey,
  tError,
  t,
};
