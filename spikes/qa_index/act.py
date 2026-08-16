"""Episodes: drive actions live and index the DELTA, not the page.

Everything before this reads one snapshot. QA assertions live in state CHANGES, so the
unit here is an episode:

    action → settle → re-index → diff

The bet being tested: the diff between two minimal outlines is far smaller than either
outline, so the assertion surface is cheaper than the observation surface. If a click
causes a large re-render that bet fails, and the episode framing loses its advantage.

Reuses capture.py's settle (networkidle is not a hydration signal) and the same
AX-vs-DOM source selection, because an episode diff over a blind index is meaningless.

Usage:
    uv run python act.py --url https://qscrape.dev/l2/eshop --plan plans/eshop.json
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
from pathlib import Path
from typing import Any

from capture import DOM_INDEX_JS, ERROR_TRAP_JS, HEALTH_JS, settle_dom
from baselines import token_count
from reducers import ax_is_thin, dom_outline

HERE = Path(__file__).parent


async def observe(tab: Any, *, source: str) -> dict[str, Any]:
    """Settle, then produce the outline the agent would actually walk."""
    settle = await settle_dom(tab)
    # No silent swallow: a failed AX read is a failure, not a reason to quietly
    # switch modality. Masking this is exactly what hid the stamp-ordering bug.
    ax_text = str(await tab.ax_tree_outline())
    dom_index = await tab.eval_js(DOM_INDEX_JS)
    health = await tab.eval_js(HEALTH_JS)

    # Statistic only — never a switch. See minimal.render_modality.
    _, stats = ax_is_thin(ax_text, dom_index)
    chosen = source
    outline = dom_outline(dom_index) if chosen == "dom" else ax_text
    return {
        "outline": outline,
        "source": chosen,
        "thin_stats": stats,
        "settle": settle,
        "elements": len(dom_index),
        "failed_resources": len(health.get("failed") or []),
        "js_errors": len(health.get("js_errors") or []),
        "tokens": token_count(outline),
    }


def diff_outlines(before: str, after: str) -> dict[str, Any]:
    """Line diff between two outlines — the episode's actual payload."""
    b, a = before.splitlines(), after.splitlines()
    delta = [
        line
        for line in difflib.unified_diff(b, a, lineterm="", n=0)
        if line and line[0] in "+-" and not line.startswith(("+++", "---"))
    ]
    added = [line for line in delta if line.startswith("+")]
    removed = [line for line in delta if line.startswith("-")]
    text = "\n".join(delta)
    return {
        "added": len(added),
        "removed": len(removed),
        "tokens": token_count(text),
        "text": text,
    }


async def do_step(tab: Any, step: dict) -> str:
    kind = step.get("action", "click")
    if kind == "click":
        if "role" in step:
            await tab.click_by_role(step["role"], step["name"], step.get("nth", 0))
            return f"click_by_role({step['role']!r}, {step['name']!r})"
        await tab.click_element(step["css"])
        return f"click({step['css']!r})"
    if kind == "type":
        await tab.type_into(step["css"], step["text"])
        return f"type({step['css']!r})"
    raise SystemExit(f"unknown action {kind!r}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="Drive actions and index the delta.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--plan", required=True, help="JSON list of steps")
    ap.add_argument(
        "--modality",
        choices=["ax", "dom"],
        required=True,
        help="explicit view; never auto-swapped",
    )
    ap.add_argument("--show", type=int, default=14, help="delta lines to print")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())

    from voidcrawl import BrowserConfig, BrowserSession

    session = BrowserSession(BrowserConfig(headless=True, stealth=True, no_sandbox=True))
    episodes: list[dict] = []
    async with session:
        tab = await session.new_page()
        try:
            await tab.add_init_script(ERROR_TRAP_JS)
            await tab.goto(args.url, timeout=30.0)
            state = await observe(tab, source=args.modality)
            print(f"source     {state['source']}  (thin ratio {state['thin_stats']['ratio']})")
            print(
                f"episode 0  load                       "
                f"{state['tokens']:>7,} tok  {state['elements']:>5} els  "
                f"settled={state['settle']['settled']}"
            )
            base_tokens = state["tokens"]

            for i, step in enumerate(plan, start=1):
                label = await do_step(tab, step)
                after = await observe(tab, source=args.modality)
                d = diff_outlines(state["outline"], after["outline"])
                episodes.append({"step": label, "delta": d, "state": after})
                pct = (d["tokens"] / after["tokens"] * 100) if after["tokens"] else 0
                print(
                    f"episode {i}  {label[:34]:<34} "
                    f"Δ{d['tokens']:>6,} tok  ({pct:>4.1f}% of full index)  "
                    f"+{d['added']}/-{d['removed']}"
                )
                state = after
        finally:
            await tab.close()

    print(f"\nfull index {base_tokens:,} tok — deltas above are what an assertion costs\n")
    for ep in episodes:
        print("─" * 78)
        print(f"{ep['step']}   Δ{ep['delta']['tokens']:,} tok")
        for line in ep["delta"]["text"].splitlines()[: args.show]:
            print(f"  {line[:110]}")
    print("─" * 78)


if __name__ == "__main__":
    asyncio.run(main())
