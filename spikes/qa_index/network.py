"""Network as a QA modality — aggregated, not logged.

The DOM is downstream of the network. For an SPA, "what did clicking this actually ask
the server for" is often the real question, and it is invisible in every other modality
we have.

TWO DESIGN CHOICES, both about not drowning the agent:

  * AGGREGATED, NOT A LOG. A raw HAR of an SPA is tens of thousands of tokens and mostly
    noise. This groups by normalised endpoint (ids and query values masked), and reports
    count / status set / bytes / timing. A page with 123 requests becomes a dozen rows.
  * DELTAS PER ACTION. Resource Timing is cumulative, so snapshotting it before and after
    an action yields exactly the requests that action caused. No CDP body capture needed,
    which matters because VoidCrawl's expect_responses only resolves ONE response per
    pattern and cannot stand in for a full request log.

What this deliberately does NOT do: capture response bodies. Status, timing, size and
shape of traffic are cheap and cover the failure classes that matter (4xx/5xx, CORS,
N+1, duplicate fetches, background polling). Bodies need a real CDP path and are a
separate problem.

Usage:
    uv run python network.py --url https://demo.realworld.show/
    uv run python network.py --url https://demo.realworld.show/ --click "Global Feed"
"""

from __future__ import annotations

import argparse
import asyncio
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

TIMING_JS = """
(() => performance.getEntriesByType('resource').map((r) => ({
  url: String(r.name),
  kind: r.initiatorType,
  status: typeof r.responseStatus === 'number' ? r.responseStatus : null,
  ms: Math.round(r.duration),
  bytes: r.transferSize || 0,
  start: Math.round(r.startTime),
})))()
"""

# No kind allowlist. Which initiatorTypes count as "noise" was a judgement call that
# could hide the request you needed; a static-asset URL is instead RECOGNISED by shape
# (it ends in a file extension), and nothing is dropped — only ranked.
ID_SEG = re.compile(r"^([0-9a-f]{8,}|\d+|[0-9a-f-]{20,})$", re.I)
# Static bundles are content-hashed, so every filename is unique and NOTHING groups.
# Measured on vercel.com: 80+ single-count rows, which defeats the point of an index.
# Collapse them by directory + extension; keep data endpoints granular, since those are
# the ones a QA question is ever actually about.
HASHY = re.compile(r"[a-z0-9_-]{8,}", re.I)
STATIC_EXT = re.compile(r"\.[a-z0-9]{2,5}$", re.I)


def is_static(url: str) -> bool:
    """A path ending in a file extension is a static asset — derived, not enumerated."""
    from urllib.parse import urlsplit

    return bool(STATIC_EXT.search(urlsplit(url).path))


def normalise(url: str) -> str:
    """Collapse ids and query values so N calls to one endpoint group into one row."""
    try:
        from urllib.parse import urlsplit

        u = urlsplit(url)
    except ValueError:
        return url[:120]
    segs = [":id" if ID_SEG.match(s) else s for s in u.path.split("/")]
    keys = sorted({p.split("=")[0] for p in u.query.split("&") if p}) if u.query else []
    q = f"?{'&'.join(k + '=*' for k in keys)}" if keys else ""
    host = u.netloc
    return f"{host}{'/'.join(segs)}{q}"[:140]


def normalise_asset(url: str) -> str:
    """Collapse a content-hashed bundle to its directory + extension."""
    from urllib.parse import urlsplit

    u = urlsplit(url)
    parts = u.path.rsplit("/", 1)
    if len(parts) != 2:
        return f"{u.netloc}{u.path}"[:140]
    d, fname = parts
    ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
    stem = fname.rsplit(".", 1)[0]
    if HASHY.fullmatch(stem) and any(c.isdigit() for c in stem):
        fname = f"*.{ext}" if ext else "*"
    return f"{u.netloc}{d}/{fname}"[:140]


def index_requests(entries: list[dict], *, include_noise: bool) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in entries:
        static = is_static(e["url"])
        if static and not include_noise and not e["url"].endswith((".js", ".mjs")):
            # Still grouped and counted, just folded — never silently discarded.
            pass
        key = normalise_asset(e["url"]) if static else normalise(e["url"])
        groups[(e["kind"], key)].append(e)

    rows = []
    for (kind, ep), items in groups.items():
        statuses = sorted({i["status"] for i in items if i["status"] is not None})
        ms = sorted(i["ms"] for i in items)
        rows.append(
            {
                "kind": kind,
                "endpoint": ep,
                "count": len(items),
                "statuses": statuses or ["?"],
                "bytes": sum(i["bytes"] for i in items),
                "p50_ms": ms[len(ms) // 2] if ms else 0,
                "max_ms": ms[-1] if ms else 0,
                "failed": any(s is not None and s >= 400 for s in (i["status"] for i in items)),
            }
        )
    # Rank rather than filter: failures first, then DATA endpoints (no file extension —
    # the requests a QA question is actually about), then volume.
    return sorted(
        rows,
        key=lambda r: (
            -r["failed"],
            STATIC_EXT.search(r["endpoint"]) is not None,
            -r["count"],
            -r["max_ms"],
        ),
    )


def findings(rows: list[dict], *, settled_extra: list[dict] | None = None) -> list[str]:
    """Deterministic detectors. No model needed to notice any of these."""
    out = []
    for r in rows:
        if r["failed"]:
            out.append(f"FAILED   {r['statuses']} {r['kind']:<8} {r['endpoint']}")
    for r in rows:
        if r["count"] >= 4 and not STATIC_EXT.search(r["endpoint"]) and ":id" not in r["endpoint"]:
            out.append(
                f"N+1?     {r['count']}x {r['endpoint']} — repeated data fetch, "
                f"often a render loop or missing cache"
            )
    for r in rows:
        if r["max_ms"] >= 1500:
            out.append(f"SLOW     {r['max_ms']}ms {r['endpoint']}")
    if settled_extra:
        eps = {normalise(e["url"]) for e in settled_extra}
        if eps:
            out.append(
                f"POLLING  {len(eps)} endpoint(s) still requesting after the DOM settled: "
                f"{', '.join(sorted(eps)[:3])}"
            )
    return out


def render(rows: list[dict], title: str) -> str:
    lines = [f"{title}  ({sum(r['count'] for r in rows)} requests, {len(rows)} endpoints)"]
    lines.append(f"  {'CNT':>4} {'STATUS':<10} {'p50':>6} {'KB':>7}  ENDPOINT")
    for r in rows:
        st = ",".join(str(s) for s in r["statuses"])
        flag = "!" if r["failed"] else " "
        lines.append(
            f" {flag}{r['count']:>4} {st:<10} {r['p50_ms']:>5}ms {r['bytes'] / 1024:>6.1f}  {r['endpoint']}"
        )
    return "\n".join(lines)


async def run(url: str, click: str | None, click_role: str, *, include_noise: bool) -> dict:
    from capture import ERROR_TRAP_JS, settle_dom
    from voidcrawl import BrowserConfig, BrowserSession

    session = BrowserSession(BrowserConfig(headless=True, stealth=True, no_sandbox=True))
    async with session:
        tab = await session.new_page()
        try:
            await tab.add_init_script(ERROR_TRAP_JS)
            await tab.navigate(url)
            await settle_dom(tab)
            load = await tab.eval_js(TIMING_JS)

            # Anything that arrives AFTER the DOM has settled is background traffic —
            # polling, analytics, prefetch. Worth separating from the load itself.
            await asyncio.sleep(2.0)
            after_idle = await tab.eval_js(TIMING_JS)
            polling = after_idle[len(load) :]

            delta = []
            if click:
                before = len(after_idle)
                await tab.click_by_role(click_role, click)
                await settle_dom(tab)
                await asyncio.sleep(1.0)
                delta = (await tab.eval_js(TIMING_JS))[before:]
        finally:
            await tab.close()

    return {
        "url": url,
        "load": index_requests(load, include_noise=include_noise),
        "polling_raw": polling,
        "delta": index_requests(delta, include_noise=include_noise) if delta else [],
        "click": click,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Network modality — aggregated request index.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--click", default=None, help="accessible name to click, then diff traffic")
    ap.add_argument("--click-role", default="button", help="AX role of the thing to click")
    ap.add_argument("--noise", action="store_true", help="include css/img/font requests")
    args = ap.parse_args()

    r = asyncio.run(run(args.url, args.click, args.click_role, include_noise=args.noise))
    print(render(r["load"], "PAGE LOAD"))
    if r["delta"]:
        print()
        print(render(r["delta"], f"AFTER CLICK {r['click']!r}"))

    f = findings(r["load"], settled_extra=r["polling_raw"])
    print("\nFINDINGS" if f else "\nno deterministic findings")
    for line in f:
        print(f"  {line}")


if __name__ == "__main__":
    main()
