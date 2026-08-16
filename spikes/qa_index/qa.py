"""`qa` — the agent-facing surface. One entry point, intent-shaped verbs.

Design rules this obeys, all of them earned the hard way in this spike:

  * The agent expresses INTENT. It never names a token budget, a modality, or a format.
    Efficiency is structural: there is no verb that returns a whole page.
  * Every result carries a SNAPSHOT id. Findings stay re-checkable against exact bytes,
    which is the difference between a QA verdict and an opinion.
  * Nothing falls back silently. A failed read fails.
  * Searching is the SYSTEM's job, not the agent's. `diff` walks regions server-side and
    hands back the localised change — that walk cost 15,581 tokens when it happened in
    agent context and costs nothing here.

Verbs:
    look    <url>                     open a live page, snapshot it, return the index
    inspect --snapshot ID --name N    detail for one thing, attributes included
    diff    --snapshot A --against B  what changed, localised
    list                              snapshots taken so far
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from baselines import token_count
from interrupt import TIERS, handoff_text, probe, tier, tier_banner
from minimal import render_modality

HERE = Path(__file__).parent
SESSIONS = HERE / "sessions"


class _Escalate(Exception):
    """Internal signal: this tier was walled, try the next one — loudly."""

    def __init__(self, tier_name: str) -> None:
        super().__init__(tier_name)
        self.tier_name = tier_name


def _snap_dir(snapshot_id: str) -> Path:
    d = SESSIONS / snapshot_id
    if not d.is_dir():
        raise SystemExit(f"no snapshot {snapshot_id!r}. Run `qa list` to see what exists.")
    return d


def _load(snapshot_id: str) -> dict:
    d = _snap_dir(snapshot_id)
    return {
        "dir": d,
        "outline": (d / "ax_outline.txt").read_text(errors="replace"),
        "dom_index": json.loads((d / "dom_index.json").read_text()),
        "html": (d / "rendered.html").read_text(errors="replace"),
        "meta": json.loads((d / "meta.json").read_text()),
    }


def build_index(snap: dict, *, max_depth: int = 6) -> str:
    return render_modality(
        "ax",
        raw_outline=snap["outline"],
        dom_index=snap["dom_index"],
        samples=3,
        max_depth=max_depth,
        html=snap["html"],
    )


async def cmd_look(
    url: str,
    *,
    wait_for: str | None,
    on_interrupt: str,
    novnc: str,
    vnc: str,
    tier_name: str,
    escalate: bool,
    attach: str | None,
    wait_secs: int,
) -> None:
    from capture import DOM_INDEX_JS, ERROR_TRAP_JS, HEALTH_JS, settle_dom
    from voidcrawl import BrowserConfig, BrowserSession

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = SESSIONS / stamp
    out.mkdir(parents=True, exist_ok=True)

    t = tier(tier_name)
    cfg = {"headless": t["headless"], "stealth": True, "no_sandbox": True}
    if t["cdp_mode"]:
        cfg["cdp_mode"] = t["cdp_mode"]
    if attach:
        # Attach to an ALREADY-RUNNING browser — the one a human can see. Launching our
        # own would put the wall in a window nobody is watching, which is the whole
        # failure this mode exists to avoid.
        cfg["ws_url"] = attach
        cfg.pop("headless", None)
    print(tier_banner(t) + (f"  [attached {attach}]" if attach else ""))
    session = BrowserSession(BrowserConfig(**cfg))
    async with session:
        tab = await session.new_page()
        try:
            await tab.add_init_script(ERROR_TRAP_JS)
            # `goto` waits for NETWORKIDLE, which this spike already established is not a
            # hydration signal — and on pages with polling or analytics beacons it never
            # fires at all (python.org times out at 30s). settle_dom is the real signal:
            # wait for the DOM to stop changing. So navigate without a load gate and let
            # settle_dom decide when the page is done.
            await tab.navigate(url)
            if wait_for:
                await tab.wait_for_network_idle(timeout_secs=5)
            settle = await settle_dom(tab)
            # Probe BEFORE indexing. Indexing a wall produces a confident, well-formed,
            # entirely wrong answer that every downstream number then inherits.
            interrupted = await probe(tab, url)
            if not settle["settled"]:
                raise SystemExit(
                    f"DOM never settled for {url} after {settle['polls']} polls "
                    f"(trajectory {settle['trajectory']}). Snapshot would be mid-render."
                )
            # AX before stamping: DOM_INDEX_JS mutates every element and invalidates the
            # tree. Getting this backwards once produced a whole false finding.
            if interrupted and on_interrupt == "wait":
                print(
                    handoff_text(
                        interrupted,
                        novnc_url=novnc,
                        vnc_url=vnc,
                        headful=bool(attach) or not t["headless"],
                    )
                )
                print(f"\n  waiting up to {wait_secs}s for a human to clear it…\n")

                # POSITIVE resume condition. The previous version resumed when the
                # captcha marker DISAPPEARED, which never fired: a solved Turnstile
                # widget stays in the DOM. Absence of a wall is not evidence of a page.
                #
                # So capture what the walled page looks like, and resume when the page
                # has BECOME SOMETHING ELSE — measured, and reported as the evidence for
                # resuming. Derived from the page itself, so it needs no knowledge of any
                # captcha vendor.
                import difflib

                base_n = int(await tab.eval_js("document.querySelectorAll('*').length"))
                base_outline = str(await tab.ax_tree_outline())
                cleared = False
                for elapsed in range(3, wait_secs + 3, 3):
                    await asyncio.sleep(3)
                    now_n = int(await tab.eval_js("document.querySelectorAll('*').length"))
                    now_outline = str(await tab.ax_tree_outline())
                    grew = abs(now_n - base_n) >= max(5, int(0.05 * base_n))
                    sim = difflib.SequenceMatcher(
                        None, base_outline.splitlines(), now_outline.splitlines()
                    ).ratio()
                    if grew or sim < 0.90:
                        print(
                            f"  RESUMED after ~{elapsed}s — page changed: "
                            f"{base_n} → {now_n} elements, outline similarity "
                            f"{sim:.2f}\n"
                        )
                        cleared = True
                        interrupted = None
                        break
                if not cleared:
                    print(
                        f"  page unchanged after {wait_secs}s "
                        f"({base_n} elements, still the wall) — nothing indexed"
                    )
                    raise SystemExit(2)
                await settle_dom(tab)
            if interrupted and on_interrupt == "fail":
                nxt = (
                    next((x for i, x in enumerate(TIERS) if i > TIERS.index(t)), None)
                    if escalate
                    else None
                )
                if nxt:
                    print(
                        f"\nINTERRUPT  {', '.join(interrupted['kinds'])} at tier "
                        f"{t['name']} → escalating to {nxt['name']}"
                    )
                    raise _Escalate(nxt["name"])
                print(
                    handoff_text(
                        interrupted, novnc_url=novnc, vnc_url=vnc, headful=not t["headless"]
                    )
                )
                raise SystemExit(2)
            outline = str(await tab.ax_tree_outline())
            dom_index = await tab.eval_js(DOM_INDEX_JS)
            health = await tab.eval_js(HEALTH_JS)
            rendered = await tab.content()
        finally:
            await tab.close()

    (out / "ax_outline.txt").write_text(outline)
    (out / "dom_index.json").write_text(json.dumps(dom_index, default=str))
    (out / "rendered.html").write_text(rendered)
    (out / "health.json").write_text(json.dumps(health, default=str))
    meta = {
        "snapshot": stamp,
        "url": url,
        "interrupt": interrupted,
        "settled": settle["settled"],
        "elements": len(dom_index),
        "failed_resources": len(health.get("failed") or []),
        "js_errors": len(health.get("js_errors") or []),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    snap = _load(stamp)
    index = build_index(snap)

    print(f"snapshot   {stamp}")
    print(f"url        {url}")
    print(f"settled    {settle['settled']}  ({settle['polls']} polls, {meta['elements']} elements)")
    if interrupted:
        print(f"INTERRUPT  {', '.join(interrupted['kinds'])} — indexed anyway (--on-interrupt)")
    if meta["failed_resources"] or meta["js_errors"]:
        print(
            f"HEALTH     {meta['failed_resources']} failed requests, "
            f"{meta['js_errors']} js errors  ← page is not clean"
        )
    print(f"\n{index}\n")
    print(f'inspect a name:  uv run python qa.py inspect --snapshot {stamp} --name "<name>"')


def cmd_inspect(snapshot_id: str, name: str, *, unit: bool, budget: int) -> None:
    from zoom import css_path, record_unit, render_subtree, resolve, unique_attr_selector

    snap = _load(snapshot_id)
    index = snap["dom_index"]
    by_idx = {e["idx"]: e for e in index}

    hits = resolve(index, name)
    if not hits:
        raise SystemExit(
            f"nothing named {name!r} in snapshot {snapshot_id}. "
            f"Names come from the index — copy one exactly."
        )
    root = hits[0]
    if unit:
        root, n = record_unit(index, by_idx, root)
        print(f"unit       leaf {hits[0]} → record {root} ({n} repeating siblings)")

    frag, elided = render_subtree(index, root, budget=budget, max_depth=6)
    # Single implementation, shared with zoom.py — a second copy here is how the two
    # drift apart and one of them keeps a stale hardcoded attribute ranking.
    stable = unique_attr_selector(index, root)
    print(f"snapshot   {snapshot_id}")
    print(f"handle     {name!r} → {len(hits)} match(es)\n")
    print(frag)
    print(f"\nselector   {stable or css_path(index, by_idx, root)}")
    if not stable:
        print("           ^ structural path — brittle by nature, prefer a stable attribute")
    if elided:
        print(f"elided     {elided} deeper nodes (raise --budget to see them)")


def cmd_diff(a_id: str, b_id: str, *, budget: int) -> None:
    """Server-side localisation. The agent gets the finding, not the search."""
    from navigate import walk

    a, b = _load(a_id), _load(b_id)
    r = walk(
        {"outline": a["outline"], "dom_index": a["dom_index"], "html": a["html"]},
        {"outline": b["outline"], "dom_index": b["dom_index"], "html": b["html"]},
        modality="ax",
        budget=budget,
        max_depth=6,
        samples=3,
        region_depth=4,
    )
    print(f"a          {a_id}  {a['meta']['url']}")
    print(f"b          {b_id}  {b['meta']['url']}")
    if not r["found"]:
        print(f"\nno difference located ({r['where']}, {r['hops']} regions searched)")
        return
    print(f"\nchanged at {r['where']}  (after {r['hops']} region(s))")

    ia, ib = build_index(a), build_index(b)
    if ia != ib:
        import difflib

        delta = [
            ln
            for ln in difflib.unified_diff(ia.splitlines(), ib.splitlines(), lineterm="", n=0)
            if ln and ln[0] in "+-" and not ln.startswith(("+++", "---"))
        ]
        print(f"\n{chr(10).join(delta[:40])}")
        print(f"\ndelta      {token_count(chr(10).join(delta)):,} tok")
    else:
        print("index is identical — the change is below the index, inspect the region above")


def cmd_list() -> None:
    if not SESSIONS.is_dir():
        print("no snapshots yet — run `qa look <url>`")
        return
    for d in sorted(SESSIONS.iterdir()):
        mp = d / "meta.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text())
        flag = "" if not (m["failed_resources"] or m["js_errors"]) else "  ⚠ unhealthy"
        print(f"  {m['snapshot']}  {m['elements']:>6} els  {m['url'][:60]}{flag}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="qa", description="Agent-facing browser QA surface.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("look", help="open a live page and return its index")
    p.add_argument("url")
    p.add_argument("--wait-for-idle", action="store_true")
    p.add_argument(
        "--on-interrupt",
        choices=["fail", "wait", "index-anyway"],
        default="fail",
        help="default-deny: a captcha/login wall is NOT the page you asked for",
    )
    p.add_argument("--novnc", default="http://127.0.0.1:6080")
    p.add_argument(
        "--attach", default=None, help="CDP url of a running browser, e.g. http://localhost:19222"
    )
    p.add_argument("--wait-secs", type=int, default=180, help="how long to hold for an operator")
    p.add_argument("--vnc", default="vnc://127.0.0.1:5900")
    p.add_argument(
        "--tier",
        choices=[x["name"] for x in TIERS],
        default="headless",
        help="headless -> headful -> stealth; each rung sees less, states what it loses",
    )
    p.add_argument(
        "--escalate",
        action="store_true",
        help="on interrupt, climb to the next tier (reported, never silent)",
    )

    p = sub.add_parser("inspect", help="detail for one named thing")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--unit", action="store_true", help="the repeating record, not the leaf")
    p.add_argument("--budget", type=int, default=800)

    p = sub.add_parser("diff", help="locate what changed between two snapshots")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--against", required=True)
    p.add_argument("--budget", type=int, default=50_000)

    sub.add_parser("list", help="snapshots taken so far")

    args = ap.parse_args()
    if args.cmd == "look":
        # Escalation is a LOOP, not a fallback: each rung is announced with what it
        # costs, and the tier that finally worked is part of the result.
        name = args.tier
        while True:
            try:
                asyncio.run(
                    cmd_look(
                        args.url,
                        wait_for=args.wait_for_idle,
                        on_interrupt=args.on_interrupt,
                        novnc=args.novnc,
                        vnc=args.vnc,
                        tier_name=name,
                        escalate=args.escalate,
                        attach=args.attach,
                        wait_secs=args.wait_secs,
                    )
                )
                break
            except _Escalate as e:
                name = e.tier_name
    elif args.cmd == "inspect":
        cmd_inspect(args.snapshot, args.name, unit=args.unit, budget=args.budget)
    elif args.cmd == "diff":
        cmd_diff(args.snapshot, args.against, budget=args.budget)
    elif args.cmd == "list":
        cmd_list()


if __name__ == "__main__":
    main()
