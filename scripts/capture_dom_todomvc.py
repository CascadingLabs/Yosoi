"""Capture a small live TodoMVC DOM episode through VoidCrawl."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from voidcrawl import BrowserPool, PoolConfig

from yosoi.observations.models.dom import DomSnapshot, serialize_dom_snapshot

URL = 'https://todomvc.com/examples/javascript-es6/dist/'
OUTPUT = Path('tests/boss_fights/dom/todomvc_live')
CAPTURE_JS = r"""
(() => {
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const boolAttr = (el, name) => {
    const value = el.getAttribute(name);
    if (value === null) return null;
    if (value === '' || value === name || value === 'true') return true;
    if (value === 'false') return false;
    return null;
  };
  const ownText = (el) => Array.from(el.childNodes)
    .filter(node => node.nodeType === Node.TEXT_NODE)
    .map(node => node.textContent || '')
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
  const runtime = (el) => {
    const state = {};
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) state.value = el.value;
    if ('checked' in el) state.checked = !!el.checked;
    if (el.tagName === 'OPTION') state.selected = !!el.selected;
    const expanded = boolAttr(el, 'aria-expanded');
    const pressed = boolAttr(el, 'aria-pressed');
    if (expanded !== null) state.expanded = expanded;
    if (pressed !== null) state.pressed = pressed;
    if ('disabled' in el) state.disabled = !!el.disabled;
    if (document.activeElement === el) state.focused = true;
    return Object.keys(state).length ? state : null;
  };
  const visibility = (el, rect) => {
    const style = getComputedStyle(el);
    if (style.display === 'none') return 'display_none';
    if (style.visibility === 'hidden') return 'hidden';
    const inViewport = rect.bottom > 0 && rect.right > 0 && rect.top < viewport.height && rect.left < viewport.width;
    return inViewport ? 'visible' : 'offscreen';
  };
  const declaredCount = (el) => {
    for (const name of ['aria-rowcount', 'aria-setsize', 'data-total-count']) {
      const raw = el.getAttribute(name);
      if (raw !== null && /^\d+$/.test(raw)) return Number(raw);
    }
    return null;
  };
  const walk = (el, nodeId) => {
    const rect = el.getBoundingClientRect();
    const shadow = el.shadowRoot ? walkRoot(el.shadowRoot, `${nodeId}:shadow`) : null;
    return {
      node_id: nodeId,
      tag: el.tagName.toLowerCase(),
      attributes: Array.from(el.attributes).map(attr => ({ name: attr.name, value: attr.value })),
      text: ownText(el),
      visibility: visibility(el, rect),
      geometry: {
        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        in_viewport: rect.bottom > 0 && rect.right > 0 && rect.top < viewport.height && rect.left < viewport.width,
      },
      runtime: runtime(el),
      declared_count: declaredCount(el),
      children: Array.from(el.children).map((child, index) => walk(child, `${nodeId}.${index}`)),
      shadow_root: shadow,
      portal_target_id: null,
    };
  };
  const walkRoot = (root, nodeId) => ({
    node_id: nodeId,
    tag: '#shadow-root',
    attributes: [],
    text: '',
    visibility: 'visible',
    geometry: null,
    runtime: null,
    declared_count: null,
    children: Array.from(root.children).map((child, index) => walk(child, `${nodeId}.${index}`)),
    shadow_root: null,
    portal_target_id: null,
  });
  const root = document.documentElement;
  return {
    schema_version: 'dom1',
    kind: 'rendered_dom',
    snapshot_id: 'placeholder',
    root: walk(root, 'n0'),
    capabilities: [
      { kind: 'visibility', available: true },
      { kind: 'geometry', available: true },
      { kind: 'runtime_state', available: true },
      { kind: 'shadow_dom', available: true },
      { kind: 'portals', available: true },
      { kind: 'declared_counts', available: true },
    ],
    viewport_width: viewport.width,
    viewport_height: viewport.height,
  };
})()
"""


class CaptureManifest(BaseModel):
    """Small provenance record written beside frozen live artifacts."""

    source_url: str
    captured_at: str
    status_code: int
    final_url: str
    files: dict[str, str]


def _snapshot(payload: object, snapshot_id: str) -> bytes:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise TypeError(f'expected DOM object from browser, got {type(payload).__name__}')
    payload['snapshot_id'] = snapshot_id
    return serialize_dom_snapshot(DomSnapshot.model_validate(payload))


def _write_capture(states: dict[str, bytes], *, status_code: int, final_url: str) -> None:
    """Write frozen artifacts and their digests after the browser session closes."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = OUTPUT / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    files: dict[str, str] = {}
    for name, data in states.items():
        path = artifacts / f'{name}.json'
        path.write_bytes(data)
        files[path.name] = hashlib.sha256(data).hexdigest()

    manifest = CaptureManifest(
        source_url=URL,
        captured_at=datetime.now(timezone.utc).isoformat(),
        status_code=status_code,
        final_url=final_url,
        files=files,
    )
    (OUTPUT / 'capture_manifest.json').write_text(manifest.model_dump_json(indent=2) + '\\n', encoding='utf-8')


async def main() -> None:
    """Capture a deterministic TodoMVC state episode with a live VoidCrawl tab."""
    async with BrowserPool(PoolConfig()) as pool, pool.acquire() as tab:
        await tab.goto(URL, capture_endpoints=True)
        await tab.evaluate_js('localStorage.clear(); sessionStorage.clear();')
        response = await tab.goto(URL, capture_endpoints=True)
        states: dict[str, bytes] = {}

        states['s0_empty'] = _snapshot(await tab.evaluate_js(CAPTURE_JS), 'todomvc-s0-empty')

        for title in ('Buy milk', 'Read design', 'Ship beta'):
            await tab.type_into('.new-todo', title)
            await tab.evaluate_js(
                "document.querySelector('.new-todo').dispatchEvent(new Event('change', {bubbles: true}))"
            )
        states['s1_three_active'] = _snapshot(await tab.evaluate_js(CAPTURE_JS), 'todomvc-s1-three-active')

        await tab.click_element('.todo-list li:nth-child(2) .toggle')
        states['s2_one_completed'] = _snapshot(await tab.evaluate_js(CAPTURE_JS), 'todomvc-s2-one-completed')

        await tab.click_element('a[href="#/completed"]')
        await asyncio.sleep(0.5)
        states['s3_completed_filter'] = _snapshot(await tab.evaluate_js(CAPTURE_JS), 'todomvc-s3-completed-filter')

        if response.status_code is None:
            raise RuntimeError('TodoMVC live capture returned no HTTP status')
        _write_capture(states, status_code=response.status_code, final_url=response.url or URL)


if __name__ == '__main__':
    asyncio.run(main())
