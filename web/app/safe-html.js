/**
 * 清洗由视图模板生成的 HTML，阻断数据字段注入可执行标记。
 */

const BLOCKED_TAGS = new Set([
  'script', 'iframe', 'object', 'embed', 'base', 'meta', 'link',
  'foreignobject', 'animate', 'animatemotion', 'animatetransform', 'set', 'math',
]);
const URL_ATTRIBUTES = new Set(['href', 'src', 'action', 'formaction', 'poster', 'xlink:href']);
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
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(value ?? ''), 'text/html');
  doc.body.querySelectorAll('*').forEach((element) => {
    const tag = element.tagName.toLowerCase();
    if (BLOCKED_TAGS.has(tag)) {
      element.remove();
      return;
    }
    Array.from(element.attributes).forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      if (name.startsWith('on') || name === 'srcdoc' || name === 'srcset') {
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
  return doc.body.innerHTML;
}

export function setSafeHtml(target, value) {
  if (!target) return;
  const template = document.createElement('template');
  template.innerHTML = sanitizeHtml(value);
  target.replaceChildren(template.content.cloneNode(true));
}
