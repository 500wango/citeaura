/**
 * CiteAura Internationalization Client (English Baseline)
 * Supports namespaced keys (e.g. 'overview.title', 'nav.diagnostics') with English resolution.
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
  subscribers.forEach((cb) => cb('en'));
}

export async function loadCatalogs(locale = 'en') {
  currentLocale = normalizeLocale(locale);
  try {
    localStorage.setItem('ulang', currentLocale);
  } catch (e) {}

  document.documentElement.lang = HTML_LANG_MAP[currentLocale] || 'en';

  try {
    const [fallbackRes, localeRes] = await Promise.all([
      fetch('/i18n/en.json'),
      fetch(`/i18n/${currentLocale}.json`),
    ]);
    fallbackCatalog = fallbackRes.ok ? await fallbackRes.json() : {};
    currentCatalog = currentLocale === DEFAULT_LOCALE
      ? fallbackCatalog
      : (localeRes.ok ? await localeRes.json() : {});
  } catch (err) {
    console.warn('Failed to load locale catalog, using in-memory fallbacks', err);
  }

  notifySubscribers(currentLocale);
  return currentCatalog;
}

export async function setLocale(locale = DEFAULT_LOCALE) {
  await loadCatalogs(locale);
}

/**
 * Translate key with interpolation and fallback.
 * @param {string} key - Dot-delimited key (e.g. 'nav.overview')
 * @param {object} params - Interpolation parameters { count: 5 }
 * @param {string} fallback - Default English fallback text
 */
export function t(key, params = {}, fallback = '') {
  if (!key) return fallback || '';

  let val = currentCatalog[key];
  if (val === undefined || val === null) {
    val = fallbackCatalog[key];
  }
  if (val === undefined || val === null) {
    val = fallback !== undefined && fallback !== '' ? fallback : key;
  }

  let text = String(val);
  if (params && typeof params === 'object') {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), () => String(v));
    });
  }
  return text;
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
  t,
};
