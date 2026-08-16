"""Emit the minimal outline for a captured target.

This is the artifact, not a benchmark row. It writes `minimal_outline.txt` next to the
capture it came from so the thing an agent would actually walk is on disk and readable.

Usage:
    uv run python minimal.py --target wikipedia_united_states
    uv run python minimal.py --target saleor_storefront --samples 5 --show 60
"""

from __future__ import annotations

import argparse
import json

from baselines import parse_outline, prune_ax, token_count
from cursor import resolve
from reducers import ax_is_thin, dom_outline, skeleton_dedup, source_outline


def elide_below(text: str, max_depth: int) -> str:
    """Replace runs of deeper-than-max_depth lines with an explicit elision marker.

    This is the flat-index/one-hop design made concrete: the resident outline stops at
    max_depth, and everything beneath it is a zoom target rather than context. The marker
    is the point — nothing is dropped silently, so the agent can see there is more and
    ask for it.
    """
    out: list[str] = []
    elided = 0
    for line in text.splitlines():
        depth = (len(line) - len(line.lstrip())) // 2
        if depth > max_depth:
            elided += 1
            continue
        if elided:
            out.append("  " * (max_depth + 1) + f"… {elided:,} nodes elided")
            elided = 0
        out.append(line)
    if elided:
        out.append("  " * (max_depth + 1) + f"… {elided:,} nodes elided")
    return "\n".join(out)


def build_minimal(
    outline_text: str,
    *,
    samples: int,
    max_depth: int | None = None,
    ax_nodes: list[dict] | None = None,
) -> str:
    """Prune unnamed structure, collapse repeated subtrees, then cut below max_depth."""
    pruned = prune_ax(outline_text, ax_nodes)
    text = skeleton_dedup(pruned, parse_outline, samples=samples)
    if max_depth is not None:
        text = elide_below(text, max_depth)
    return text


def render_modality(
    modality: str,
    *,
    raw_outline: str,
    dom_index: list[dict],
    samples: int,
    max_depth: int | None,
    html: str,
    ax_nodes: list[dict] | None = None,
) -> str:
    """Render one modality. Complementary views, never fallbacks for one another.

        ax     — role + accessible name.  What the page MEANS.
        dom    — tag.class + text.        What the page IS.
        source — head + attribute surface. What the page DECLARES (SEO, resources).
        html   — raw markup.              Everything, at full price.

    Each answers a different question, and each is blind where another sees. Choosing
    between them is the caller's job; a heuristic that swaps them silently turns a
    blind spot into a confident-looking number.
    """
    if modality == "ax":
        return build_minimal(raw_outline, samples=samples, max_depth=max_depth, ax_nodes=ax_nodes)
    if modality == "dom":
        return dom_outline(dom_index, max_depth=max_depth or 8)
    if modality == "html":
        return html
    if modality == "source":
        return source_outline(html)
    raise SystemExit(f"unknown modality {modality!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Emit the minimal outline for a capture.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--samples", type=int, default=3, help="names kept per collapsed group")
    ap.add_argument("--show", type=int, default=40, help="lines to print")
    ap.add_argument("--max-depth", type=int, default=None, help="elide below this depth")
    ap.add_argument(
        "--modality",
        choices=["ax", "dom", "html", "source"],
        required=True,
        help="complementary view, chosen for the question asked — NOT a fallback chain",
    )
    ap.add_argument("--capture", default=None, help="capture id; defaults to pins.toml")
    args = ap.parse_args()

    cur = resolve(args.target, args.capture)
    cap = cur.path

    raw_outline = cur.artifact("ax_outline.txt").read_text(errors="replace")
    dom_index = json.loads(cur.artifact("dom_index.json").read_text())

    minimal = render_modality(
        args.modality,
        raw_outline=raw_outline,
        dom_index=dom_index,
        samples=args.samples,
        max_depth=args.max_depth,
        html=cur.artifact("rendered.html").read_text(errors="replace"),
        ax_nodes=json.loads(cur.artifact("ax.json").read_text()),
    )

    # Reported as a statistic only. It is NOT a decision input: modalities are
    # complementary views the caller picks for the question being asked, and letting a
    # heuristic silently swap them is how a contaminated AX read got mistaken for a
    # property of the page.
    _, stats = ax_is_thin(raw_outline, dom_index)
    print(
        f"ax stat      named {stats['ax_named']} vs texty DOM {stats['dom_texty']} "
        f"(ratio {stats['ratio']})  [statistic only, not a switch]"
    )
    print(f"modality     {args.modality}")
    (cap / f"minimal_{args.modality}.txt").write_text(minimal)

    rendered = cap / "rendered.html"
    html_tok = token_count(rendered.read_text(errors="replace")) if rendered.exists() else 0
    out_tok = token_count(raw_outline)
    min_tok = token_count(minimal)

    print(f"target       {args.target}")
    print(f"capture      {cap.name}")
    print(f"rendered     {html_tok:>9,} tok")
    print(f"ax_outline   {out_tok:>9,} tok")
    print(f"minimal      {min_tok:>9,} tok   ({len(minimal.splitlines()):,} lines)")
    if min_tok:
        print(f"vs html      {html_tok / min_tok:>9.1f}x")
    print(f"written      {cap / f'minimal_{args.modality}.txt'}\n")
    print("─" * 78)
    for line in minimal.splitlines()[: args.show]:
        print(line[:120])
    print("─" * 78)


if __name__ == "__main__":
    main()
