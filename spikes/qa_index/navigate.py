"""Multi-step coverage: how much does it cost to FIND the defect, hops included?

defects.py measured single-shot detection — whether the index alone differs. That is the
wrong question for a multi-shot system, and measuring it was the same mistake as before:
proving something adjacent to the claim.

Nothing is lost by reduction; it is elided, and zoom can pull any of it back. So the real
question is not "is it visible" but "what does it cost to reach". This walks the loop:

    hop 0   compare indexes                      → differ? done.
    hop k   zoom region k, compare fragments     → differ? done.
    stop    when found, or when the budget is spent.

NAVIGATION POLICY — deliberately not cheating. Regions are visited in DOCUMENT ORDER and
the walker never sees where the defect was injected. It only uses what the index itself
exposes. A policy that peeked would make the numbers meaningless.

Cost is cumulative tokens actually read: the index, plus every fragment opened up to and
including the one that revealed the defect.

Usage:
    uv run python navigate.py --budget 4000
    uv run python navigate.py --modality dom --region-depth 4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from baselines import token_count
from cursor import CAPTURES
from defects import DEFECTS, TARGETS
from minimal import render_modality

RESULTS = Path(__file__).parent / "navigation.json"


def load_snapshot(target: str, variant: str) -> dict | None:
    d = CAPTURES / f"_defect_{target}" / variant
    if not d.is_dir():
        return None
    return {
        "outline": (d / "ax_outline.txt").read_text(errors="replace"),
        "dom_index": json.loads((d / "dom_index.json").read_text()),
        "html": (d / "rendered.html").read_text(errors="replace"),
    }


def index_view(snap: dict, modality: str, *, max_depth: int, samples: int) -> str:
    return render_modality(
        modality,
        raw_outline=snap["outline"],
        dom_index=snap["dom_index"],
        samples=samples,
        max_depth=max_depth,
        html=snap["html"],
    )


def regions(dom_index: list[dict], depth: int) -> list[list[dict]]:
    """Split the page into zoomable regions at a fixed structural depth.

    Document order, no knowledge of the defect. Each region is a subtree the agent could
    open from an elision marker.
    """
    by = {e["idx"]: e for e in dom_index}
    depth_of: dict[int, int] = {}

    def d_of(e: dict) -> int:
        if e["idx"] in depth_of:
            return depth_of[e["idx"]]
        n, cur = 0, e["parent"]
        while cur != -1 and cur in by:
            n += 1
            cur = by[cur]["parent"]
        depth_of[e["idx"]] = n
        return n

    roots = [e for e in dom_index if d_of(e) == depth]
    kids: dict[int, list[int]] = {}
    for e in dom_index:
        kids.setdefault(e["parent"], []).append(e["idx"])

    out: list[list[dict]] = []
    for r in roots:
        acc: list[dict] = []
        stack = [r["idx"]]
        while stack:
            i = stack.pop()
            if i in by:
                acc.append(by[i])
                stack.extend(reversed(kids.get(i, [])))
        out.append(acc)
    return out


def fragment_text(region: list[dict]) -> str:
    """Full detail for one region — attributes included, which is what zoom is for."""
    lines = []
    for e in region:
        a = e["attrs"]
        bits = [e["tag"]]
        if a.get("class"):
            bits[0] += "." + ".".join(a["class"].split()[:3])
        for k in ("id", "href", "alt", "title", "aria-label", "data-testid", "role"):
            if a.get(k):
                bits.append(f"{k}={a[k][:60]}")
        if e["text"]:
            bits.append(f'"{e["text"][:80]}"')
        lines.append(" ".join(bits))
    return "\n".join(lines)


def walk(
    clean: dict,
    bad: dict,
    *,
    modality: str,
    budget: int,
    max_depth: int,
    samples: int,
    region_depth: int,
) -> dict:
    idx_clean = index_view(clean, modality, max_depth=max_depth, samples=samples)
    idx_bad = index_view(bad, modality, max_depth=max_depth, samples=samples)
    spent = token_count(idx_clean)

    if idx_clean != idx_bad:
        return {"found": True, "hops": 0, "tokens": spent, "where": "index"}

    rc = regions(clean["dom_index"], region_depth)
    rb = regions(bad["dom_index"], region_depth)

    # A differing region COUNT is itself a signal the index handed us — cheap and honest.
    if len(rc) != len(rb):
        return {"found": True, "hops": 0, "tokens": spent, "where": "region-count"}

    for i, (a, b) in enumerate(zip(rc, rb), start=1):
        fa, fb = fragment_text(a), fragment_text(b)
        spent += token_count(fa)
        if spent > budget:
            return {"found": False, "hops": i, "tokens": spent, "where": "budget-exhausted"}
        if fa != fb:
            return {"found": True, "hops": i, "tokens": spent, "where": f"region[{i}]"}

    return {"found": False, "hops": len(rc), "tokens": spent, "where": "exhausted-regions"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-step coverage with zoom hops.")
    ap.add_argument("--modality", choices=["ax", "dom"], default="ax")
    ap.add_argument("--budget", type=int, default=4000)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--region-depth", type=int, default=4)
    args = ap.parse_args()

    rows = []
    for target in TARGETS:
        clean = load_snapshot(target, "clean")
        if clean is None:
            continue
        for d in DEFECTS:
            bad = load_snapshot(target, d.id)
            if bad is None:
                continue
            r = walk(
                clean,
                bad,
                modality=args.modality,
                budget=args.budget,
                max_depth=args.max_depth,
                samples=args.samples,
                region_depth=args.region_depth,
            )
            r |= {"target": target, "defect": d.id}
            rows.append(r)

    found = [r for r in rows if r["found"]]
    at_index = [r for r in found if r["hops"] == 0]
    print(f"modality {args.modality}   budget {args.budget:,} tok   {len(rows)} pairs\n")
    print(f"  found                {len(found)}/{len(rows)}  ({len(found) / len(rows):.0%})")
    print(f"  found at hop 0       {len(at_index)}/{len(rows)}  (index alone)")
    print(f"  needed zoom hops     {len(found) - len(at_index)}")
    if found:
        toks = sorted(r["tokens"] for r in found)
        print(f"  tokens to find       median {toks[len(toks) // 2]:,}   max {toks[-1]:,}")
        hops = sorted(r["hops"] for r in found)
        print(f"  hops to find         median {hops[len(hops) // 2]}   max {hops[-1]}")

    print(f"\n  {'DEFECT':<18}{'TARGET':<22}{'FOUND':>7}{'HOPS':>6}{'TOKENS':>9}  WHERE")
    for r in rows:
        print(
            f"  {r['defect']:<18}{r['target']:<22}"
            f"{'yes' if r['found'] else 'NO':>7}{r['hops']:>6}{r['tokens']:>9,}  {r['where']}"
        )

    RESULTS.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {RESULTS.name}")


if __name__ == "__main__":
    main()
