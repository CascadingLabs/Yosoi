"""L0 — freeze the corpus.

Every later stage reads these artifacts and never touches the network. That is the
point: iterations become sub-minute and deterministic, so we iterate on the index
instead of debugging network flake.

Network traces are recorded HERE even though they are not indexed until L4. They are
only recordable at capture time; they cannot be retroactively added to an index that
already exists, and re-crawling to backfill is the exact cost we are avoiding.

Usage:
    uv run python capture.py --lane gate
    uv run python capture.py --only books_toscrape realworld_conduit
    uv run python capture.py --lane dirty --no-requests
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.toml"
CAPTURES = HERE / "captures"

# Broad enough to see the app's own traffic without hoovering every font and pixel.
# Named patterns are what voidcrawl's expect_responses takes.
RESPONSE_PATTERNS = {
    "xhr": "*",
}

# Installed BEFORE navigation so it catches errors thrown during hydration — the window
# where framework islands fail silently and leave a page that looks fine but is not.
ERROR_TRAP_JS = """
(() => {
  window.__qa = { errors: [], rejections: [] };
  window.addEventListener('error', (e) => {
    window.__qa.errors.push({
      message: String(e.message || ''),
      source: String(e.filename || ''),
      line: e.lineno || 0,
    });
  }, true);
  window.addEventListener('unhandledrejection', (e) => {
    window.__qa.rejections.push(String((e.reason && e.reason.message) || e.reason || ''));
  });
})()
"""

# Per-request status without a CDP bridge: Resource Timing exposes responseStatus in
# modern Chrome, so a failed bundle (the react-window defect class) is visible as data
# rather than inferred from a small DOM.
HEALTH_JS = """
(() => {
  const res = performance.getEntriesByType('resource').map((r) => ({
    url: String(r.name).slice(0, 300),
    kind: r.initiatorType,
    status: typeof r.responseStatus === 'number' ? r.responseStatus : null,
    ms: Math.round(r.duration),
    bytes: r.transferSize || 0,
    cached: r.transferSize === 0 && r.decodedBodySize > 0,
  }));
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const qa = window.__qa || { errors: [], rejections: [] };
  return {
    ready_state: document.readyState,
    resources: res,
    failed: res.filter((r) => r.status !== null && r.status >= 400),
    status_unknown: res.filter((r) => r.status === null).length,
    js_errors: qa.errors,
    rejections: qa.rejections,
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
    load_ms: Math.round(nav.loadEventEnd || 0),
    element_count: document.querySelectorAll('*').length,
    // Framework-island hydration markers: present but unhydrated is the silent failure.
    islands: document.querySelectorAll('astro-island').length,
    islands_hydrated: document.querySelectorAll('astro-island[ssr]').length === 0
      ? document.querySelectorAll('astro-island').length
      : 0,
  };
})()
"""

# Stamps data-qa-idx on every element in document order and returns a flat index
# carrying the attributes a selector can actually be written against. `parent` makes it
# a tree without nesting the JSON, so a zoom can pull a subtree by slicing.
DOM_INDEX_JS = """
(() => {
  const MAX = 20000;
  const els = document.querySelectorAll('*');
  const out = [];
  const seen = new Map();
  for (let i = 0; i < els.length && i < MAX; i++) {
    const el = els[i];
    el.setAttribute('data-qa-idx', String(i));
    seen.set(el, i);
    // EVERY attribute, discovered — not an allowlist. An allowlist can only report what
    // it was told to look for, and this one had already silently dropped `title`/`alt`
    // (which is where accessible names come from when own-text is truncated), breaking
    // handle resolution until it was noticed by hand. A source index elsewhere surfaced
    // a malformed `<meta name="Andrew Berg">` for the same reason: you cannot find the
    // thing you did not predict.
    const attrs = {};
    for (const a of el.getAttributeNames()) {
      if (a === 'data-qa-idx') continue;  // our own stamp, not the page's
      const v = el.getAttribute(a);
      if (v) attrs[a] = v.length > 200 ? v.slice(0, 200) : v;
    }
    let own = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) own += n.nodeValue;
    }
    own = own.replace(/\\s+/g, ' ').trim();
    const p = el.parentElement;
    out.push({
      idx: i,
      tag: el.tagName.toLowerCase(),
      parent: p && seen.has(p) ? seen.get(p) : -1,
      attrs,
      text: own.length > 160 ? own.slice(0, 160) : own,
      nth: p ? Array.prototype.indexOf.call(p.children, el) + 1 : 1,
    });
  }
  return out;
})()
"""


@dataclass
class Target:
    id: str
    url: str
    axis: str
    lane: str
    pin: str
    verified: bool
    predict: str


@dataclass
class CaptureResult:
    target_id: str
    tier: str
    ok: bool
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


class _NotSettled(Exception):
    """Internal retry signal: the DOM is still changing."""


async def settle_dom(
    tab: Any, *, stable_rounds: int = 3, max_attempts: int = 25, wait_s: float = 0.4
) -> dict[str, Any]:
    """Poll the element count until it stops changing.

    A capture taken mid-hydration is not merely incomplete, it is silently wrong: the
    index looks small and confident. Settling on the observable (element count) rather
    than on a network event is what makes repeated captures comparable at all.
    """
    counts: list[int] = []
    stable = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_fixed(wait_s),
            retry=retry_if_exception_type(_NotSettled),
            reraise=True,
        ):
            with attempt:
                raw = await tab.eval_js("document.querySelectorAll('*').length")
                n = int(raw) if str(raw).isdigit() else 0
                stable = stable + 1 if counts and n == counts[-1] else 0
                counts.append(n)
                if stable < stable_rounds:
                    raise _NotSettled
    except _NotSettled:
        pass  # ran out of attempts — reported as settled=False, not raised
    return {
        "final_elements": counts[-1] if counts else 0,
        "polls": len(counts),
        "settled": stable >= stable_rounds,
        "trajectory": counts[:12],
    }


def load_corpus(path: Path = CORPUS) -> list[Target]:
    raw = tomllib.loads(path.read_text())
    return [Target(**t) for t in raw["target"]]


def _write(out_dir: Path, name: str, data: str | bytes) -> str:
    """Write an artifact and return its sha256. Content-addressed so drift is visible."""
    out_dir.mkdir(parents=True, exist_ok=True)
    blob = data.encode() if isinstance(data, str) else data
    (out_dir / name).write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()[:16]


async def capture_static(target: Target, out_dir: Path) -> CaptureResult:
    """L1 — server HTML, no JS. The reference for the L1->L2 hydration delta."""
    res = CaptureResult(target_id=target.id, tier="l1_static", ok=False)
    try:
        # A default httpx UA gets 403'd by some origins (Wikipedia among them), which
        # would silently zero out the L1->L2 delta rather than fail loudly.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30.0, headers=headers
        ) as client:
            resp = await client.get(target.url)
        res.artifacts["raw.html"] = _write(out_dir, "raw.html", resp.text)
        res.notes = {
            "status_code": resp.status_code,
            "final_url": str(resp.url),
            "bytes": len(resp.content),
        }
        res.ok = True
    except Exception as exc:  # a failed capture is data, not a crash
        res.error = f"{type(exc).__name__}: {exc}"
    return res


async def capture_headless(
    target: Target, out_dir: Path, session: Any, *, requests: bool = True
) -> CaptureResult:
    """L2 — rendered DOM + AX tree + network.

    ``requests=False`` is not merely a config flag: the delta between the two runs is
    where loading / empty / error states live, and those are the states nobody QAs.

    Uses ``BrowserSession.new_page()`` rather than the pool: ``PooledTab`` does not
    expose ``expect_responses`` (only ``Page`` does), so pooled tabs cannot capture
    response bodies at all. Logged as a VoidCrawl API asymmetry, worked around here.
    """
    tier = "l2_headless" if requests else "l2_headless_noreq"
    res = CaptureResult(target_id=target.id, tier=tier, ok=False)
    tab = None
    try:
        tab = await session.new_page()
        if tab is not None:
            try:
                await tab.add_init_script(ERROR_TRAP_JS)
            except Exception as exc:  # trap is additive
                res.notes["error_trap_error"] = f"{type(exc).__name__}: {exc}"
            captured: dict[str, Any] = {}
            if requests:
                try:
                    async with tab.expect_responses(RESPONSE_PATTERNS, timeout=30.0) as exp:
                        page_resp = await tab.goto(target.url, timeout=30.0, capture_endpoints=True)
                    # ``ResponseExpectation.value`` is a Future — it resolves only
                    # after the context exits and the triggering action has settled.
                    captured = await exp.value or {}
                except Exception as exc:  # body capture is best-effort
                    res.notes["response_capture_error"] = f"{type(exc).__name__}: {exc}"
                    page_resp = await tab.goto(target.url, timeout=30.0, capture_endpoints=True)
            else:
                page_resp = await tab.goto(target.url, timeout=30.0)

            # Stamp every element with a stable ordinal BEFORE grabbing the HTML, and
            # emit a flat DOM index alongside it. This is the zoom substrate: the AX
            # outline says WHICH node, the DOM index says how to ADDRESS it, and the
            # attributes it carries (id/class/data-testid) are exactly what the AX tree
            # does not have and selector authoring cannot do without.
            #
            # VoidCrawl exposes no backendDOMNodeId -> outerHTML bridge, so capturing
            # the mapping here is the alternative to changing VoidCrawl.
            # networkidle is NOT a hydration signal. qscrape /l2/eshop ("L2 · Shuffled
            # Islands") returned 53 elements on three consecutive runs and 535 on an
            # earlier one — same page, same code, different hydration progress. Waiting
            # for the element count to stop changing is the actual settle condition.
            res.notes["settle"] = await settle_dom(tab)

            try:
                health = await tab.eval_js(HEALTH_JS)
                res.artifacts["health.json"] = _write(
                    out_dir, "health.json", json.dumps(health, default=str)
                )
                res.notes["health"] = {
                    "ready_state": health.get("ready_state"),
                    "resources": len(health.get("resources") or []),
                    "failed": len(health.get("failed") or []),
                    "status_unknown": health.get("status_unknown"),
                    "js_errors": len(health.get("js_errors") or []),
                    "rejections": len(health.get("rejections") or []),
                    "islands": health.get("islands"),
                }
            except Exception as exc:
                res.notes["health_error"] = f"{type(exc).__name__}: {exc}"

            # ORDER IS LOAD-BEARING: read the AX tree BEFORE stamping the DOM.
            # DOM_INDEX_JS sets data-qa-idx on every element; doing that first made the
            # AX tree read back nearly empty on qscrape /l2/eshop (17 named nodes), which
            # I initially mis-diagnosed as "AX is blind on astro-islands". Reading AX
            # first shows the AX tree sees the products fine. The blindness was my own
            # instrumentation invalidating the tree.
            ax_nodes = await tab.get_full_ax_tree()
            res.artifacts["ax.json"] = _write(
                out_dir, "ax.json", json.dumps(ax_nodes, indent=None, default=str)
            )
            outline = await tab.ax_tree_outline()
            res.artifacts["ax_outline.txt"] = _write(out_dir, "ax_outline.txt", str(outline))

            try:
                dom_index = await tab.eval_js(DOM_INDEX_JS)
                res.artifacts["dom_index.json"] = _write(
                    out_dir, "dom_index.json", json.dumps(dom_index, default=str)
                )
                res.notes["dom_index_count"] = (
                    len(dom_index) if hasattr(dom_index, "__len__") else None
                )
            except Exception as exc:  # index is additive, not required
                res.notes["dom_index_error"] = f"{type(exc).__name__}: {exc}"

            html = await tab.content()
            res.artifacts["rendered.html"] = _write(out_dir, "rendered.html", html)

            endpoints = list(getattr(page_resp, "endpoints", None) or [])
            res.artifacts["endpoints.json"] = _write(
                out_dir, "endpoints.json", json.dumps(endpoints, indent=2, default=str)
            )

            if captured:
                lines = []
                for name, cr in captured.items():
                    lines.append(
                        json.dumps(
                            {
                                "pattern": name,
                                "url": getattr(cr, "url", None),
                                "status": getattr(cr, "status", None),
                                "mime_type": getattr(cr, "mime_type", None),
                                "resource_type": getattr(cr, "resource_type", None),
                                "headers": getattr(cr, "headers", None),
                                "truncated": getattr(cr, "truncated", None),
                            },
                            default=str,
                        )
                    )
                res.artifacts["network.jsonl"] = _write(out_dir, "network.jsonl", "\n".join(lines))

            res.notes.update(
                {
                    "status_code": getattr(page_resp, "status_code", None),
                    "final_url": getattr(page_resp, "url", None),
                    "rendered_bytes": len(html),
                    "ax_node_count": len(ax_nodes) if hasattr(ax_nodes, "__len__") else None,
                    "endpoint_count": len(endpoints),
                    "antibot": str(getattr(page_resp, "antibot", None)),
                }
            )
            res.ok = True
    except Exception as exc:
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        if tab is not None:
            try:
                await tab.close()
            except Exception:  # teardown must not mask the result
                pass
    return res


async def capture_target(target: Target, session: Any, *, requests: bool) -> list[CaptureResult]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = CAPTURES / target.id / stamp
    # A capture that produces zero artifacts is a result, not a crash — the dir must
    # exist so the failure is recorded in meta.json rather than lost.
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [
        await capture_static(target, out_dir),
        await capture_headless(target, out_dir, session, requests=requests),
    ]
    meta = {
        "target": target.__dict__,
        "captured_at": stamp,
        "results": [r.__dict__ for r in results],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return results


async def main() -> None:
    ap = argparse.ArgumentParser(description="L0 — freeze corpus captures.")
    ap.add_argument("--lane", default="gate", choices=["gate", "dirty", "selfhost", "all"])
    ap.add_argument("--only", nargs="*", default=None, help="target ids")
    ap.add_argument("--no-requests", action="store_true", help="capture with network blocked")
    args = ap.parse_args()

    targets = load_corpus()
    if args.only:
        targets = [t for t in targets if t.id in args.only]
    elif args.lane != "all":
        targets = [t for t in targets if t.lane == args.lane]
    if not targets:
        raise SystemExit("no targets matched")

    from voidcrawl import BrowserConfig, BrowserSession

    print(f"capturing {len(targets)} target(s) — requests={'off' if args.no_requests else 'on'}")
    session = BrowserSession(BrowserConfig(headless=True, stealth=True, no_sandbox=True))
    async with session:
        for t in targets:
            results = await capture_target(t, session, requests=not args.no_requests)
            for r in results:
                mark = "ok " if r.ok else "FAIL"
                detail = r.error or json.dumps(r.notes, default=str)[:160]
                print(f"  [{mark}] {t.id:<26} {r.tier:<20} {detail}")


if __name__ == "__main__":
    asyncio.run(main())
