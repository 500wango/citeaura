/**
 * CiteAura Internationalization Client (English Baseline)
 * Supports namespaced keys (e.g. 'overview.title', 'nav.diagnostics') with English resolution.
 */

export const SUPPORTED_LOCALES = ['en'];
export const DEFAULT_LOCALE = 'en';

const HTML_LANG_MAP = {
  en: 'en',
};

let currentLocale = 'en';
let currentCatalog = {};
let fallbackCatalog = {};
const subscribers = [];

export function detectLocale() {
  return 'en';
}

export function getLocale() {
  return 'en';
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
  currentLocale = 'en';
  try {
    localStorage.setItem('ulang', 'en');
  } catch (e) {}

  document.documentElement.lang = 'en';

  try {
    const res = await fetch('/i18n/en.json');
    if (res.ok) {
      currentCatalog = await res.json();
      fallbackCatalog = currentCatalog;
    }
  } catch (err) {
    console.warn('Failed to load English catalog, using in-memory fallbacks', err);
  }

  notifySubscribers();
  return currentCatalog;
}

export async function setLocale(locale = 'en') {
  await loadCatalogs('en');
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
  DEFAULT_LOCALE,
  detectLocale,
  getLocale,
  loadCatalogs,
  setLocale,
  subscribeLocale,
  t,
};
