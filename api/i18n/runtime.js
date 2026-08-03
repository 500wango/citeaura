/* DisvorAI i18n runtime — locale-equal catalogs, English fallback (not Chinese).
   Injected after engine UI_D / uiTranslate. Chinese strings in engine HTML are
   opaque message ids for lookup, not the display source of truth. */
(function () {
  const I18N_DEFAULT = 'en';
  const I18N_SUPPORTED = ['en', 'zh', 'ja'];
  window.I18N_DEFAULT = I18N_DEFAULT;
  window.I18N_SUPPORTED = I18N_SUPPORTED;

  // Seeded by server: window.__I18N_CATALOGS = {en:{...},zh:{...},ja:{...}}
  const serverCatalogs = (typeof window.__I18N_CATALOGS === 'object' && window.__I18N_CATALOGS) || {};
  const catalogs = { en: {}, zh: {}, ja: {} };
  I18N_SUPPORTED.forEach(function (locale) {
    catalogs[locale] = Object.assign({}, serverCatalogs[locale] || {});
  });

  // Merge legacy UI_D: Chinese key is message id; values are locale strings.
  if (typeof UI_D === 'object' && UI_D) {
    Object.keys(UI_D.en || {}).forEach(function (id) {
      catalogs.en[id] = UI_D.en[id];
      if (catalogs.zh[id] == null) catalogs.zh[id] = id;
    });
    Object.keys(UI_D.ja || {}).forEach(function (id) {
      catalogs.ja[id] = UI_D.ja[id];
      if (catalogs.zh[id] == null) catalogs.zh[id] = id;
      if (catalogs.en[id] == null && UI_D.en && UI_D.en[id] != null) catalogs.en[id] = UI_D.en[id];
    });
  }
  window.__I18N_MERGED = catalogs;

  function activeLocale() {
    if (typeof ULANG === 'string' && I18N_SUPPORTED.indexOf(ULANG) >= 0) return ULANG;
    return I18N_DEFAULT;
  }

  function t(messageId) {
    if (messageId == null) return messageId;
    const key = String(messageId);
    if (!key) return key;
    const locale = activeLocale();
    const local = catalogs[locale] || {};
    if (local[key] != null) return local[key];
    if (locale !== I18N_DEFAULT && catalogs[I18N_DEFAULT] && catalogs[I18N_DEFAULT][key] != null) {
      return catalogs[I18N_DEFAULT][key];
    }
    // Keep identity for zh (legacy ids are Chinese). For other locales, do not invent Chinese chrome.
    return key;
  }

  function localePick(map, fallback) {
    if (!map || typeof map !== 'object') return fallback || '';
    const locale = activeLocale();
    if (map[locale] != null && map[locale] !== '') return map[locale];
    if (map[I18N_DEFAULT] != null && map[I18N_DEFAULT] !== '') return map[I18N_DEFAULT];
    if (map.zh != null && map.zh !== '' && locale === 'zh') return map.zh;
    return fallback != null ? fallback : (map.en || map.zh || '');
  }

  window.t = t;
  window.localePick = localePick;

  // Prefer catalog + English fallback over Chinese identity.
  window.uiText = function (value) {
    return t(value);
  };

  window.uiMsg = function (message) {
    if (activeLocale() === 'zh' || message == null) return message;
    const text = String(message);
    if (!text) return text;
    const exact = t(text);
    if (exact !== text) return exact;
    const locale = activeLocale();
    const rxList = (typeof UI_RX !== 'undefined' && UI_RX[locale]) || (typeof UI_RX !== 'undefined' && UI_RX[I18N_DEFAULT]) || [];
    for (let i = 0; i < rxList.length; i++) {
      if (rxList[i][0].test(text)) return text.replace(rxList[i][0], rxList[i][1]);
    }
    const pairs = ((typeof UI_SUB !== 'undefined' && UI_SUB[locale]) || []).slice();
    const enCat = catalogs[I18N_DEFAULT] || {};
    const locCat = catalogs[locale] || {};
    Object.keys(locCat).sort(function (a, b) { return b.length - a.length; }).forEach(function (key) {
      if (key && key.length >= 2) pairs.push([key, locCat[key]]);
    });
    if (locale !== I18N_DEFAULT) {
      Object.keys(enCat).sort(function (a, b) { return b.length - a.length; }).forEach(function (key) {
        if (key && key.length >= 2 && locCat[key] == null) pairs.push([key, enCat[key]]);
      });
    }
    let probe = text;
    for (let i = 0; i < pairs.length; i++) probe = probe.split(pairs[i][0]).join('');
    if (/[\u3040-\u30ff\u4e00-\u9fff]/.test(probe)) return text;
    let out = text;
    for (let i = 0; i < pairs.length; i++) out = out.split(pairs[i][0]).join(pairs[i][1]);
    return out;
  };

  if (typeof toast === 'function' && !toast.__disvoraiLocalized) {
    const engineToast = toast;
    toast = function (m, k) { return engineToast(uiMsg(m), k); };
    toast.__disvoraiLocalized = true;
  }
  if (!window.__disvoraiConfirmLocalized) {
    const engineConfirm = window.confirm.bind(window);
    window.confirm = function (m) { return engineConfirm(uiMsg(m)); };
    window.__disvoraiConfirmLocalized = true;
  }

  window.adminText = function (value) {
    return localePick(value, '');
  };

  // Override DOM translator: locale → en, never "keep Chinese" for missing en/ja chrome.
  window.uiTranslate = function (root) {
    if (activeLocale() === 'zh' || !root) return;
    const locale = activeLocale();
    const d = catalogs[locale] || {};
    const en = catalogs[I18N_DEFAULT] || {};
    const subs = (typeof UI_SUB !== 'undefined' && UI_SUB[locale]) || [];
    const rxList = (typeof UI_RX !== 'undefined' && UI_RX[locale]) || [];

    function translateText(raw) {
      const t0 = raw.trim();
      if (!t0) return raw;
      if (d[t0] != null) return raw.replace(t0, d[t0]);
      if (en[t0] != null) return raw.replace(t0, en[t0]);
      for (let i = 0; i < rxList.length; i++) {
        if (rxList[i][0].test(t0)) return raw.replace(t0, t0.replace(rxList[i][0], rxList[i][1]));
      }
      if (t0.length <= 40) {
        let probe = t0;
        for (let i = 0; i < subs.length; i++) probe = probe.split(subs[i][0]).join('');
        // Also strip known catalog ids so pure chrome+numbers can be substituted
        const dictKeys = Object.keys(d).concat(Object.keys(en)).sort(function (a, b) { return b.length - a.length; });
        for (let i = 0; i < dictKeys.length; i++) {
          if (dictKeys[i].length >= 2) probe = probe.split(dictKeys[i]).join('');
        }
        if (!/[\u3040-\u30ff\u4e00-\u9fff]/.test(probe)) {
          let v = raw;
          for (let i = 0; i < subs.length; i++) v = v.split(subs[i][0]).join(subs[i][1]);
          for (let i = 0; i < dictKeys.length; i++) {
            const key = dictKeys[i];
            if (key.length < 2) continue;
            const rep = d[key] != null ? d[key] : en[key];
            if (rep != null) v = v.split(key).join(rep);
          }
          return v;
        }
      }
      return raw;
    }

    if (root.nodeType === 3) {
      root.nodeValue = translateText(root.nodeValue);
      return;
    }
    if (root.nodeType !== 1) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) { node.nodeValue = translateText(node.nodeValue); });
    if (root.querySelectorAll) {
      root.querySelectorAll('[title],[placeholder],[aria-label]').forEach(function (el) {
        ['title', 'placeholder', 'aria-label'].forEach(function (attr) {
          const value = el.getAttribute(attr);
          if (!value) return;
          const next = translateText(value);
          if (next !== value) el.setAttribute(attr, next);
        });
      });
    }
  };

  if (activeLocale() !== 'zh' && typeof uiTranslate === 'function' && document.body) {
    setTimeout(function () { uiTranslate(document.body); }, 0);
  }
})();
