/**
 *  HTML，。
 */

const BLOCKED_TAGS = new Set([
  'script', 'style', 'iframe', 'object', 'embed', 'base', 'meta', 'link',
  'foreignobject', 'animate', 'animatemotion', 'animatetransform', 'set', 'math',
  // Inert-content containers hide markup from the attribute/tag walk below and
  // are a classic mutation-XSS bypass, so they are dropped entirely.
  'template', 'noscript',
  // Obsolete text scroller: no legitimate use in this app, only abuse surface.
  'marquee',
]);
// These tags are required by the SPA's controlled forms and action surfaces.
// Keep them outside the denylist so a future sanitizer change cannot silently
// remove the controls that mounted handlers depend on.
const INTERACTIVE_TAGS = new Set(['form', 'input', 'button', 'select', 'textarea']);
const URL_ATTRIBUTES = new Set(['href', 'src', 'action', 'formaction', 'poster', 'xlink:href']);
// Attributes removed from every element, regardless of value.
const BLOCKED_ATTRIBUTES = new Set(['srcdoc', 'srcset', 'ping', 'formaction', 'xlink:href']);
// `name` on these tags lets markup shadow/overwrite document properties and
// built-in globals (DOM clobbering), so it is stripped from them.
const CLOBBER_NAME_TAGS = new Set(['input', 'form', 'button', 'select', 'textarea', 'object', 'img', 'a']);
const UNSAFE_STYLE = /(?:expression\s*\(|url\s*\(|@import|behavior\s*:|-moz-binding|position\s*:\s*(?:fixed|sticky))/i;

function isSafeUrl(value, attribute, element) {
  const compact = String(value || '').replace(/[\u0000-\u0020\u007f]+/g, '');
  if (!compact || compact.startsWith('#')) return true;
  if (attribute === 'src' && element.tagName.toLowerCase() === 'img' && /^data:image\/(?:png|jpeg|webp|gif);base64,/i.test(compact)) {
    return true;
  }
  try {
    const parsed = new URL(compact, document.baseURI);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return true;
    return attribute === 'href' && (parsed.protocol === 'mailto:' || parsed.protocol === 'tel:');
  } catch (e) {
    return false;
  }
}

export function sanitizeHtml(value) {
  const template = document.createElement('template');
  template.innerHTML = String(value ?? '');
  template.content.querySelectorAll('*').forEach((element) => {
    const tag = element.tagName.toLowerCase();
    if (BLOCKED_TAGS.has(tag) && !INTERACTIVE_TAGS.has(tag)) {
      element.remove();
      return;
    }
    Array.from(element.attributes).forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      if (name.startsWith('on')) {
        element.removeAttribute(attribute.name);
        return;
      }
      // SVG <use> may only reference an in-document fragment.
      if (tag === 'use' && (name === 'href' || name === 'xlink:href')) {
        if (!String(attribute.value || '').trim().startsWith('#')) element.removeAttribute(attribute.name);
        return;
      }
      if (BLOCKED_ATTRIBUTES.has(name)) {
        element.removeAttribute(attribute.name);
        return;
      }
      if (name === 'name' && CLOBBER_NAME_TAGS.has(tag)) {
        element.removeAttribute(attribute.name);
        return;
      }
      // A bare `open` would let injected markup paint a full-screen dialog
      // overlay; the element itself is kept so DOM lookups stay valid.
      if (tag === 'dialog' && name === 'open') {
        element.removeAttribute(attribute.name);
        return;
      }
      if (name === 'style' && UNSAFE_STYLE.test(attribute.value)) {
        element.removeAttribute(attribute.name);
        return;
      }
      if (URL_ATTRIBUTES.has(name) && !isSafeUrl(attribute.value, name, element)) {
        element.removeAttribute(attribute.name);
      }
    });
    if (tag === 'a' && element.getAttribute('target') === '_blank') {
      element.setAttribute('rel', 'noopener noreferrer');
    }
  });
  return template.content;
}

export function setSafeHtml(target, value) {
  if (!target) return;
  target.replaceChildren(sanitizeHtml(value));
}

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

export function safeHttpUrl(value) {
  const compact = String(value || '').replace(/[\u0000-\u0020\u007f]+/g, '').trim();
  if (!compact) return '';
  try {
    const parsed = new URL(compact);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.href;
  } catch (e) {}
  return '';
}
