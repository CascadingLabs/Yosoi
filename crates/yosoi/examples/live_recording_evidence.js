// Browser-side evidence adapter. Target selection stays in Rust's ys::surface.
// Light DOM only; no CSS/XPath selectors or synthetic node.click().
const operation = arguments[0], input = arguments[1];
const state = () => window.__ysArticle;
function visible(node) {
  if (!(node instanceof Element) || !node.isConnected) return false;
  const css = getComputedStyle(node);
  return css.display !== 'none' && !['hidden', 'collapse'].includes(css.visibility)
    && node.getClientRects().length > 0;
}
function signature(node) {
  return JSON.stringify({tag: node.localName, href: node.href ?? null,
    text: node.textContent, value: node.value ?? null, checked: node.checked ?? null,
    attributes: [...node.attributes].map(attribute => [attribute.namespaceURI, attribute.name, attribute.value])
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))});
}
function eligibility(node) {
  if (!(node instanceof Element)) return {eligible: false, reason: 'missing_node'};
  const first = node.getClientRects()[0];
  const left = first ? Math.max(0, first.left) : 0;
  const right = first ? Math.min(innerWidth, first.right) : 0;
  const top = first ? Math.max(0, first.top) : 0;
  const bottom = first ? Math.min(innerHeight, first.bottom) : 0;
  const point = {x: (left + right) / 2, y: (top + bottom) / 2};
  const hit = right > left && bottom > top ? document.elementFromPoint(point.x, point.y) : null;
  let disabled = false;
  for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
    if (ancestor.inert || ancestor.getAttribute('aria-disabled') === 'true' || (ancestor.localName === 'fieldset' && ancestor.disabled)) disabled = true;
  }
  disabled ||= Boolean(node.disabled);
  const same_document = state()?.document === document && node.ownerDocument === document && state()?.url === location.href;
  const unchanged = state()?.signatures?.get(node) === signature(node);
  const shown = visible(node), topmost = hit === node || node.contains(hit);
  return {eligible: same_document && shown && topmost && !disabled,
    connected: node.isConnected, same_document, unchanged, visible: shown, topmost, disabled, readonly: Boolean(node.readOnly),
    point, client_rects: node.getClientRects().length,
    blocker: topmost ? null : hit ? {tag: hit.localName, role: hit.getAttribute('role')} : null,
    tag: node.localName, text: node.innerText?.slice(0, 240), href: node.href ?? null,
    url: location.href};
}
function article() {
  const elements = [...document.getElementsByTagName('*')];
  const h1 = elements.find(node => node.localName === 'h1' && visible(node));
  const gate = elements.find(node => visible(node) && (node.innerText?.length ?? 0) <= 300 &&
    /keep reading with a|unlock unlimited articles|subscribe to continue|sign in to continue/i.test(node.innerText ?? ''));
  const paragraphs = elements.filter(node => node.localName === 'p' && visible(node) &&
    (node.innerText?.trim().length ?? 0) > 80);
  // Body text can exist behind a paywall: explicitly keep that separate.
  const body_characters = paragraphs.reduce((total, node) => total + node.innerText.trim().length, 0);
  return {url: location.href, title: document.title, heading: h1?.innerText ?? null,
    gate: gate?.innerText.slice(0, 240) ?? null, paragraphs: paragraphs.length, body_characters,
    readable: Boolean(h1 && !gate && paragraphs.length >= 3 && body_characters >= 500),
    ready: document.readyState};
}
if (operation === 'capture') {
  const nodes = new Map(), rows = [], normalized_strings = [], signatures = new WeakMap();
  // The v1 DOM wire disallows control characters that real ad srcdoc payloads
  // contain. Preserve those strings reversibly as JSON-string content and
  // report each projected field; never silently drop the attribute or node.
  function wireString(value, id, field) {
    const controls = value.match(/[\u0000-\u0008\u000b\u000e-\u001f\u007f-\u009f]/gu);
    if (!controls) return value;
    normalized_strings.push({id, field, encoding: 'json_string_content', controls: controls.length});
    return JSON.stringify(value).slice(1, -1).replace(/[\u007f-\u009f]/gu,
      character => '\\u' + character.codePointAt(0).toString(16).padStart(4, '0'));
  }
  let next = 0;
  function visit(node, parent) {
    if (![1, 3, 9].includes(node.nodeType)) return null;
    const id = ++next, children = [];
    nodes.set(id, node);
    if (node instanceof Element && (['a', 'button', 'input', 'textarea', 'select', 'summary'].includes(node.localName) || node.getAttribute('role') === 'button')) signatures.set(node, signature(node));
    const item = node.nodeType === 9 ? {kind: 'document', id, parent, children} :
      node.nodeType === 3 ? {kind: 'text', id, parent, children, value: wireString(node.nodeValue, id, 'text')} :
      {kind: 'element', id, parent, children, namespace_uri: node.namespaceURI ?? '', tag_name: node.localName,
        attributes: [...node.attributes].map(a => ({namespace_uri: a.namespaceURI ?? '', name: a.localName, value: wireString(a.value, id, 'attribute:' + (a.namespaceURI ?? '') + ':' + a.localName)}))
          .sort((a, b) => a.namespace_uri.localeCompare(b.namespace_uri) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))};
    rows.push(item);
    for (const child of node.childNodes) { const id = visit(child, item.id); if (id !== null) children.push(id); }
    return id;
  }
  const root = visit(document, null);
  window.__ysArticle = {nodes, signatures, document, url: location.href, epoch: input.epoch};
  return {url: location.href, html: document.documentElement.outerHTML, normalized_strings, wire: {schema: 'yosoi.rendered-dom.v1', document_epoch: input.epoch,
    tree_model: 'document_light_dom', root, nodes: rows}};
}
if (operation === 'eligibility') return eligibility(state()?.nodes.get(input.id));
if (operation === 'element') return state()?.nodes.get(input.id) ?? null;
if (operation === 'article') return article();
if (operation === 'binding') return {current: state()?.document === document && state()?.url === location.href, url: location.href};
if (operation === 'location') return {url: location.href, title: document.title};
if (operation === 'value') return {matches: input.element.value === input.expected, characters: input.element.value?.length ?? 0};
if (operation === 'watch') {
  const done = arguments[arguments.length - 1];
  let finished = false;
  const consent = () => [...document.getElementsByTagName('*')].some(node =>
    node.children.length === 0 && visible(node) && /legal terms and privacy/i.test(node.innerText ?? ''));
  const evaluate = () => {
    if (input.kind === 'text') {
      const present = (document.body?.innerText ?? '').includes(input.text);
      return present === input.present ? {state: 'text_matched', present, url: location.href} : null;
    }
    if (input.kind === 'navigation') {
      if (!input.expected_url) return null;
      const actual = new URL(location.href), expected = new URL(input.expected_url);
      return location.href !== input.before_url && actual.origin === expected.origin && actual.pathname === expected.pathname && actual.search === expected.search
        ? {state: 'navigated', url: location.href, title: document.title} : null;
    }
    if (input.kind === 'home') return consent() ? {state: 'consent_required'} : null;
    if (input.kind === 'consent_gone') return !consent() ? {state: 'consent_gone'} : null;
    const value = article();
    const actual = new URL(value.url), expected = new URL(input.expected_url);
    const destination_matches = actual.origin === expected.origin && actual.pathname === expected.pathname;
    if (value.url !== input.before_url && destination_matches && value.heading && (value.gate || (value.readable && value.ready === 'complete')))
      return {state: value.gate ? 'subscription_required' : 'readable', destination_matches, ...value};
    return null;
  };
  const finish = value => {
    if (finished) return;
    finished = true; observer.disconnect(); clearTimeout(timer);
    removeEventListener('load', update); removeEventListener('pageshow', update);
    done(value);
  };
  const update = () => { const value = evaluate(); if (value) finish(value); };
  const observer = new MutationObserver(update);
  const timer = setTimeout(() => finish({state: 'timeout', ...article()}), input.timeout_ms);
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  addEventListener('load', update); addEventListener('pageshow', update); update();
  return;
}
throw Error('Unknown adapter operation: ' + operation);
