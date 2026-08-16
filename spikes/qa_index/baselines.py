"""L2 — baseline representations and their token cost.

Four baselines, cheapest-honest first. We must beat `pruned_ax` on MDS coverage at
<= its token budget; until then there is no gate and no result.

Reads only frozen captures. Never touches the network.

Usage:
    uv run python baselines.py
    uv run python baselines.py --budget 100000
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from cursor import list_captures, resolve

HERE = Path(__file__).parent
CAPTURES = HERE / "captures"
SCOREBOARD = HERE / "scoreboard.jsonl"

LINE_RE = re.compile(r'^(?P<indent>\s*)(?P<role>\S+)(?:\s+"(?P<name>.*)")?\s*$')


@dataclass
class Node:
    depth: int
    role: str
    name: str | None

    def render(self, count: int = 1) -> str:
        pad = "  " * self.depth
        label = f'{self.role} "{self.name}"' if self.name else self.role
        return f"{pad}{label}" + (f" ×{count}" if count > 1 else "")


def parse_outline(text: str) -> list[Node]:
    nodes: list[Node] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        nodes.append(Node(depth=indent // 2, role=m.group("role"), name=m.group("name")))
    return nodes


def focusable_roles(ax_nodes: list[dict]) -> set[str]:
    """Roles the browser itself reports as focusable in THIS document.

    This is the non-hardcoded source of "interactive". Chrome computes it; we read it.
    No role list of ours can go stale against it, and a page using an exotic role for a
    control is covered automatically.
    """
    out = set()
    for n in ax_nodes:
        role = (n.get("role") or {}).get("value")
        props = {
            p.get("name"): (p.get("value") or {}).get("value") for p in (n.get("properties") or [])
        }
        if role and props.get("focusable"):
            out.add(role)
    return out


def marker_roles(
    nodes: list[Node], *, protected: set[str] | None = None, min_count: int = 5, share: float = 0.9
) -> set[str]:
    """Find roles that behave like list markers IN THIS DOCUMENT.

    Replaces a hardcoded NOISE_ROLES set.

    The invariant is NOT length — that was tried and falsified. On Wikipedia 587 of 739
    ListMarker names are four characters ("100.", "101."), because reference numbering
    runs past 99, so a <=3-char rule detected nothing at all.

    The invariant that actually holds is that a marker carries no WORD: its name is
    ordinals, digits, glyphs and punctuation, with no run of two or more letters. That is
    true of "100.", "a.", "iv" aside, and "•" alike, and false of any real label. A role
    qualifies when it occurs often enough to be structural and ``share`` of its names
    look that way — derived per document, so a page that marks lists with some other
    role is handled without anyone having predicted it.

    ``protected`` excludes roles the browser reports focusable (see focusable_roles).
    Wordlessness alone is not sufficient and must not be used alone.
    """
    word = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
    protected = protected or set()
    by_role: dict[str, list[str | None]] = {}
    for n in nodes:
        by_role.setdefault(n.role, []).append(n.name)
    out = set()
    for role, names in by_role.items():
        # Never mark a focusable role. Conduit's favourite buttons are named "2"/"1"
        # with an icon glyph — wordless and frequent, therefore indistinguishable from a
        # bullet by name alone. Dropping them would delete real affordances.
        if role in protected:
            continue
        vals = [(x or "").strip() for x in names]
        if len(vals) < min_count or not all(vals):
            continue
        wordless = sum(1 for v in vals if not word.search(v))
        if wordless / len(vals) >= share:
            out.add(role)
    return out


def prune_ax(text: str, ax_nodes: list[dict] | None = None) -> str:
    """Drop structure that carries no information, then collapse repeated siblings.

    NO ROLE LISTS. The previous version kept a 34-role allowlist and a 26-role denylist,
    which meant any role nobody had thought of was invisible by construction — the same
    failure shape that produced the AX-blindness and malformed-meta misses.

    The rule is purely structural and works on any role vocabulary:
      * a node carrying an accessible NAME is information — keep it;
      * an unnamed node is scaffolding — keep it only where it is a BRANCH POINT
        (two or more child subtrees still contain information), because that is the only
        case where dropping it would flatten real hierarchy;
      * single-child unnamed chains collapse away entirely.

    The sibling collapse afterwards is where the size win lives: a page is mostly
    repeated structure, and 300 identical rows carry no more than one row plus a count.
    """
    nodes = parse_outline(text)
    # Marker detection needs the browser's focusability signal to be safe. Without
    # ax.json it is SKIPPED rather than guessed — an unsafe prune is worse than a
    # slightly larger index, and a silent guess is worse than both.
    markers = marker_roles(nodes, protected=focusable_roles(ax_nodes)) if ax_nodes else set()

    from reducers import build_tree

    root = build_tree(nodes)

    def informative(n) -> bool:
        return bool(n.name) and n.role not in markers

    def keep(n) -> bool:
        """Keep informative nodes, and unnamed nodes only at genuine branch points."""
        if informative(n):
            return True
        branching = sum(1 for c in n.children if subtree_has_info(c))
        return branching >= 2

    memo: dict[int, bool] = {}

    def subtree_has_info(n) -> bool:
        k = id(n)
        if k not in memo:
            memo[k] = informative(n) or any(subtree_has_info(c) for c in n.children)
        return memo[k]

    kept: list[Node] = []

    def walk(n, depth: int) -> None:
        show = n.role != "__root__" and keep(n)
        if show:
            kept.append(Node(depth=depth, role=n.role, name=n.name))
        for c in n.children:
            if subtree_has_info(c) or informative(c):
                walk(c, depth + 1 if show else depth)

    walk(root, 0)

    out: list[str] = []
    i = 0
    while i < len(kept):
        n = kept[i]
        run = 1
        while (
            i + run < len(kept)
            and kept[i + run].depth == n.depth
            and kept[i + run].role == n.role
            and kept[i + run].name == n.name
        ):
            run += 1
        out.append(n.render(run))
        i += run
    return "\n".join(out)


_encoder = None
_encoder_kind = "chars/4"


def token_count(text: str) -> int:
    """Token count. Any consistent tokenizer works — the metric is comparative."""
    global _encoder, _encoder_kind
    if _encoder is None:
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
            _encoder_kind = "tiktoken/cl100k_base"
        except Exception:
            _encoder = False
    if _encoder:
        return len(_encoder.encode(text, disallowed_special=()))
    return len(text) // 4


def representations(cap: Path) -> dict[str, str]:
    reps: dict[str, str] = {}

    rendered = cap / "rendered.html"
    if rendered.exists():
        reps["raw_html"] = rendered.read_text(errors="replace")

    ax_json = cap / "ax.json"
    if ax_json.exists():
        reps["ax_full"] = ax_json.read_text(errors="replace")

    outline = cap / "ax_outline.txt"
    if outline.exists():
        text = outline.read_text(errors="replace")
        reps["ax_outline"] = text
        reps["pruned_ax"] = prune_ax(text)

    return reps


def main() -> None:
    ap = argparse.ArgumentParser(description="L2 — baseline representations + token cost.")
    ap.add_argument("--budget", type=int, default=100_000, help="context budget in tokens")
    args = ap.parse_args()

    from capture import load_corpus

    rows = []
    for t in load_corpus():
        if not list_captures(t.id):
            continue
        cap = resolve(t.id).path  # pinned cursor; never 'latest'
        reps = representations(cap)
        if not reps:
            continue
        for name, text in reps.items():
            tok = token_count(text)
            rows.append(
                {
                    "target": t.id,
                    "axis": t.axis,
                    "lane": t.lane,
                    "representation": name,
                    "bytes": len(text),
                    "tokens": tok,
                    "fits_budget": tok <= args.budget,
                    "tokenizer": _encoder_kind,
                    "capture": cap.name,
                }
            )

    with SCOREBOARD.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    order = ["raw_html", "ax_full", "ax_outline", "pruned_ax"]
    targets = sorted({r["target"] for r in rows})
    print(f"tokenizer: {_encoder_kind}   budget: {args.budget:,}\n")
    header = f"{'TARGET':<28}" + "".join(f"{o:>14}" for o in order) + f"{'prune×':>9}"
    print(header)
    print("-" * len(header))
    for tgt in targets:
        by = {r["representation"]: r for r in rows if r["target"] == tgt}
        cells = ""
        for o in order:
            r = by.get(o)
            if r is None:
                cells += f"{'-':>14}"
            else:
                mark = " " if r["fits_budget"] else "!"
                cells += f"{r['tokens']:>13,}{mark}"
        ratio = ""
        if "raw_html" in by and "pruned_ax" in by and by["pruned_ax"]["tokens"]:
            ratio = f"{by['raw_html']['tokens'] / by['pruned_ax']['tokens']:.1f}x"
        print(f"{tgt:<28}{cells}{ratio:>9}")
    print(f"\n! = exceeds {args.budget:,} token budget")
    print(f"appended {len(rows)} rows to {SCOREBOARD.name}")


if __name__ == "__main__":
    main()
