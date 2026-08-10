/**
 * CiteAura 统一多语言国际化客户端
 * 支持点号命名空间 key (e.g. 'overview.title', 'nav.diagnostics')，回退至 en 基线。
 */

export const SUPPORTED_LOCALES = ['en', 'zh', 'ja'];
export const DEFAULT_LOCALE = 'en';

const HTML_LANG_MAP = {
  en: 'en',
  zh: 'zh-CN',
  ja: 'ja',
};

let currentLocale = detectLocale();
let currentCatalog = {};
let fallbackCatalog = {};
const subscribers = [];

export function detectLocale() {
  const urlParam = new URLSearchParams(location.search).get('lang');
  let saved = null;
  try {
    saved = localStorage.getItem('ulang');
  } catch (e) {}
  const nav = (navigator.language || '').toLowerCase();
  const guess = urlParam || saved || (nav.startsWith('zh') ? 'zh' : nav.startsWith('ja') ? 'ja' : 'en');
  return SUPPORTED_LOCALES.includes(guess) ? guess : DEFAULT_LOCALE;
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

export async function loadCatalogs(locale = currentLocale) {
  currentLocale = SUPPORTED_LOCALES.includes(locale) ? locale : DEFAULT_LOCALE;
  try {
    localStorage.setItem('ulang', currentLocale);
  } catch (e) {}

  document.documentElement.lang = HTML_LANG_MAP[currentLocale] || 'en';

  try {
    // 始终加载 en 作为回退
    if (currentLocale !== 'en' && Object.keys(fallbackCatalog).length === 0) {
      const fbRes = await fetch('/i18n/en.json');
      if (fbRes.ok) fallbackCatalog = await fbRes.json();
    }

    const res = await fetch(`/i18n/${currentLocale}.json`);
    if (res.ok) {
      currentCatalog = await res.json();
    } else {
      currentCatalog = {};
    }
  } catch (err) {
    console.error('Failed to load i18n catalog:', err);
  }

  notifySubscribers();
  return currentCatalog;
}

export function setLocale(locale) {
  return loadCatalogs(locale);
}

/**
 * 翻译方法 t()
 * @param {string} key - 点号 key (如 'nav.overview')
 * @param {Object} [params] - 插值变量 {name: 'Brand', count: 5}
 * @param {string} [fallback] - 缺失时的回退文案
 */
export function t(key, params = {}, fallback = null) {
  if (!key) return '';

  let template = currentCatalog[key];
  if (template == null && currentLocale !== 'en') {
    template = fallbackCatalog[key];
  }
  if (template == null) {
    template = fallback != null ? fallback : key;
  }

  if (typeof template !== 'string') {
    return String(template);
  }

  // 变量插值: {key} 或 :key
  return template.replace(/\{([^{}]+)\}/g, (_, name) => {
    return params[name] !== undefined ? params[name] : `{${name}}`;
  });
}

export default {
  SUPPORTED_LOCALES,
  DEFAULT_LOCALE,
  detectLocale,
  getLocale,
  setLocale,
  loadCatalogs,
  subscribeLocale,
  t,
};
