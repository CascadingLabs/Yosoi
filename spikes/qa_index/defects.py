"""Inject known defects into a pinned snapshot, then measure whether each modality
still shows them.

This is the gate written in README.md on iteration 1 and never run.

WHY THIS IS CHEAP. Hand-labeling Minimal Defect Sets is expensive, and treating it as
expensive is what let this go unmeasured while everything else got built. But we INJECT
the defect, so its ground-truth location is known for free.

DETECTION, defined so it cannot inherit the fill-rate weakness:

    detected  ==  reduced(clean_snapshot) != reduced(defective_snapshot)

If a reduction is lossy exactly where the defect lives, the two reduced views are
byte-identical and the defect is invisible — no selector, no oracle, no LLM involved.
"Detection" here means the EVIDENCE SURVIVED THE REDUCTION, which is the only thing the
index can be responsible for. It is emphatically not "a selector returned something".

FIDELITY. Defects are applied to the snapshot's rendered HTML, scripts are stripped, and
the result is re-captured through the normal pipeline over file://. So the AX tree for a
defective page is computed by Chrome for real rather than simulated by editing the
outline text. Stripping scripts is what makes that reload deterministic: rendered.html is
already post-hydration DOM, and re-running its scripts would re-render it.

Usage:
    uv run python defects.py --inject           # build defective snapshots
    uv run python defects.py --measure          # coverage table
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from lxml import etree, html as lxml_html

from baselines import prune_ax, token_count
from cursor import CAPTURES, resolve
from minimal import render_modality

HERE = Path(__file__).parent
DEFECT_PAGES = HERE / "defect_pages"
RESULTS = HERE / "coverage.json"

# 4 targets, all with verified specs. Record/field selectors come from specs/.
TARGETS = {
    "books_toscrape": {"record": "article.product_pod", "price": "p.price_color"},
    "realworld_conduit": {"record": "app-article-preview", "price": "h1"},
    "gmaps_arbys": {"record": "div[role=article]", "price": "div.qBF1Pd"},
    "qscrape_eshop_l2": {"record": "article", "price": "h3"},
}


@dataclass(frozen=True)
class Defect:
    id: str
    kind: str
    description: str


DEFECTS = [
    Defect("blank_price", "blank_text", "empty the price/label text of record 0"),
    Defect("drop_record", "remove_node", "delete record 1 entirely"),
    Defect("break_href", "break_href", "point record 0's first link at a dead anchor"),
    Defect("null_alt", "null_alt", "strip alt from record 0's image (kills its a11y name)"),
    Defect("duplicate_record", "duplicate", "duplicate record 0 in place"),
    Defect("corrupt_value", "corrupt_text", "replace record 0's price text with garbage"),
    Defect("empty_record", "empty_node", "keep record 2's element but remove its children"),
    Defect("remove_last", "remove_node", "delete the final record"),
]


def _records(root, css: str):
    from parsel import Selector

    sel = Selector(root=root)
    return [n.root for n in sel.css(css)]


def apply_defect(html_text: str, defect: Defect, sels: dict) -> tuple[str, bool]:
    """Return (mutated_html, applied). `applied=False` means the target node was absent."""
    root = lxml_html.fromstring(html_text)
    recs = _records(root, sels["record"])
    if not recs:
        return html_text, False

    def nth(i):
        return recs[i] if i < len(recs) else None

    if defect.kind == "blank_text":
        n = nth(0)
        tgt = n.cssselect(sels["price"]) if n is not None else []
        if not tgt:
            return html_text, False
        tgt[0].text = ""
        for c in list(tgt[0]):
            tgt[0].remove(c)

    elif defect.kind == "remove_node":
        n = nth(1) if defect.id == "drop_record" else recs[-1]
        if n is None:
            return html_text, False
        n.getparent().remove(n)

    elif defect.kind == "break_href":
        n = nth(0)
        links = n.cssselect("a[href]") if n is not None else []
        if not links:
            return html_text, False
        links[0].set("href", "#qa-broken")

    elif defect.kind == "null_alt":
        n = nth(0)
        imgs = n.cssselect("img") if n is not None else []
        # pop("alt", None) silently no-ops on an img that never had alt, producing a
        # byte-identical "defective" page and a fake not-found. An injection that did not
        # inject must report failure, not shrug.
        imgs = [i for i in imgs if "alt" in i.attrib]
        if not imgs:
            return html_text, False
        del imgs[0].attrib["alt"]

    elif defect.kind == "duplicate":
        n = nth(0)
        if n is None:
            return html_text, False
        import copy

        n.getparent().insert(list(n.getparent()).index(n) + 1, copy.deepcopy(n))

    elif defect.kind == "corrupt_text":
        n = nth(0)
        tgt = n.cssselect(sels["price"]) if n is not None else []
        if not tgt:
            return html_text, False
        tgt[0].text = "??!!"
        for c in list(tgt[0]):
            tgt[0].remove(c)

    elif defect.kind == "empty_node":
        n = nth(2)
        if n is None:
            return html_text, False
        for c in list(n):
            n.remove(c)
        n.text = ""

    else:
        raise SystemExit(f"unknown defect kind {defect.kind!r}")

    return etree.tostring(root, encoding="unicode", method="html"), True


def strip_scripts(html_text: str) -> str:
    root = lxml_html.fromstring(html_text)
    for tag in ("script", "noscript"):
        for n in root.findall(f".//{tag}"):
            n.getparent().remove(n)
    return etree.tostring(root, encoding="unicode", method="html")


async def inject() -> None:
    from capture import DOM_INDEX_JS, settle_dom
    from voidcrawl import BrowserConfig, BrowserSession

    DEFECT_PAGES.mkdir(exist_ok=True)
    session = BrowserSession(BrowserConfig(headless=True, stealth=True, no_sandbox=True))
    made = 0
    async with session:
        for target, sels in TARGETS.items():
            cur = resolve(target)
            clean_html = cur.artifact("rendered.html").read_text(errors="replace")
            variants: list[tuple[str, str]] = [("clean", strip_scripts(clean_html))]
            for d in DEFECTS:
                mutated, applied = apply_defect(clean_html, d, sels)
                if not applied:
                    print(f"  skip {target}/{d.id}: target node absent")
                    continue
                variants.append((d.id, strip_scripts(mutated)))

            for name, page_html in variants:
                page = DEFECT_PAGES / f"{target}__{name}.html"
                page.write_text(page_html)
                out = CAPTURES / f"_defect_{target}" / name
                out.mkdir(parents=True, exist_ok=True)

                tab = await session.new_page()
                try:
                    await tab.goto(f"file://{page.resolve()}", timeout=30.0)
                    await settle_dom(tab)
                    outline = str(await tab.ax_tree_outline())
                    dom_index = await tab.eval_js(DOM_INDEX_JS)
                    rendered = await tab.content()
                finally:
                    await tab.close()

                (out / "ax_outline.txt").write_text(outline)
                (out / "dom_index.json").write_text(json.dumps(dom_index, default=str))
                (out / "rendered.html").write_text(rendered)
                made += 1
                print(f"  {target}/{name}: {len(dom_index)} els, outline {len(outline)} B")
    print(f"\nbuilt {made} snapshots under captures/_defect_*")


def truncate_to(text: str, budget: int) -> str:
    """Cut a representation to a token budget — the equal-footing rule for comparison."""
    lines = text.splitlines()
    out, total = [], 0
    for ln in lines:
        t = token_count(ln) + 1
        if total + t > budget:
            break
        out.append(ln)
        total += t
    return "\n".join(out)


def views(cap: Path, *, max_depth: int | None, samples: int) -> dict[str, str]:
    outline = (cap / "ax_outline.txt").read_text(errors="replace")
    dom_index = json.loads((cap / "dom_index.json").read_text())
    html_text = (cap / "rendered.html").read_text(errors="replace")
    return {
        "pruned_ax(baseline)": prune_ax(outline),
        "ax(minimal)": render_modality(
            "ax",
            raw_outline=outline,
            dom_index=dom_index,
            samples=samples,
            max_depth=max_depth,
            html=html_text,
        ),
        "dom(minimal)": render_modality(
            "dom",
            raw_outline=outline,
            dom_index=dom_index,
            samples=samples,
            max_depth=max_depth,
            html=html_text,
        ),
        "html(raw)": html_text,
    }


def measure(budgets: list[int], *, max_depth: int | None, samples: int) -> dict:
    results: dict = {"budgets": budgets, "rows": []}
    for target in TARGETS:
        base = CAPTURES / f"_defect_{target}"
        clean_dir = base / "clean"
        if not clean_dir.is_dir():
            print(f"  no injected snapshots for {target} — run --inject")
            continue
        clean_views = views(clean_dir, max_depth=max_depth, samples=samples)

        for d in DEFECTS:
            dd = base / d.id
            if not dd.is_dir():
                continue
            defect_views = views(dd, max_depth=max_depth, samples=samples)
            for rep in clean_views:
                for b in budgets:
                    a = truncate_to(clean_views[rep], b)
                    c = truncate_to(defect_views[rep], b)
                    results["rows"].append(
                        {
                            "target": target,
                            "defect": d.id,
                            "representation": rep,
                            "budget": b,
                            "detected": a != c,
                            "clean_tokens": token_count(clean_views[rep]),
                        }
                    )
    return results


def report(results: dict) -> None:
    rows = results["rows"]
    reps = ["pruned_ax(baseline)", "ax(minimal)", "dom(minimal)", "html(raw)"]
    budgets = results["budgets"]
    print(f"\n{'':<22}" + "".join(f"{f'@{b}tok':>16}" for b in budgets))
    print(f"{'REPRESENTATION':<22}" + "".join(f"{'coverage':>16}" for _ in budgets))
    print("-" * (22 + 16 * len(budgets)))
    for rep in reps:
        cells = ""
        for b in budgets:
            sub = [r for r in rows if r["representation"] == rep and r["budget"] == b]
            if not sub:
                cells += f"{'-':>16}"
                continue
            hit = sum(1 for r in sub if r["detected"])
            cells += f"{f'{hit}/{len(sub)}  {hit / len(sub):.0%}':>16}"
        print(f"{rep:<22}{cells}")

    print("\nper-defect detection at the tightest budget:")
    b = min(budgets)
    defects = sorted({r["defect"] for r in rows})
    print(f"  {'DEFECT':<18}" + "".join(f"{r.split('(')[0]:>13}" for r in reps))
    for d in defects:
        cells = ""
        for rep in reps:
            sub = [
                r
                for r in rows
                if r["defect"] == d and r["representation"] == rep and r["budget"] == b
            ]
            hit = sum(1 for r in sub if r["detected"])
            cells += f"{f'{hit}/{len(sub)}':>13}"
        print(f"  {d:<18}{cells}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Inject defects and measure coverage.")
    ap.add_argument("--inject", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--budgets", type=int, nargs="*", default=[300, 1000, 4000])
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    if args.inject:
        asyncio.run(inject())
    if args.measure:
        res = measure(args.budgets, max_depth=args.max_depth, samples=args.samples)
        RESULTS.write_text(json.dumps(res, indent=2))
        report(res)
        print(f"\nwrote {RESULTS.name}  ({len(res['rows'])} observations)")


if __name__ == "__main__":
    main()
