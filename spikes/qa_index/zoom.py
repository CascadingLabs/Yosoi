"""The one hop: resolve a handle from the minimal outline to real DOM with attributes.

The minimal outline is deliberately lossy in the one dimension selector authoring needs
— it carries role and accessible name and NO attributes. So the index and the zoom
return different types on purpose:

    index : role + name        cheap, semantic, for CHOOSING which node
    zoom  : tag + attrs + text expensive, precise, for ADDRESSING it forever

Reads only frozen captures.

Usage:
    uv run python zoom.py --target books_toscrape --name "All products"
    uv run python zoom.py --target books_toscrape --idx 141 --budget 800
"""

from __future__ import annotations

import argparse
import json

from baselines import token_count
from cursor import resolve as resolve_cursor


def load_index(target: str, capture_id: str | None = None) -> tuple[list[dict], object]:
    cur = resolve_cursor(target, capture_id)
    return json.loads(cur.artifact("dom_index.json").read_text()), cur.path


def children_of(index: list[dict]) -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for e in index:
        kids.setdefault(e["parent"], []).append(e["idx"])
    return kids


def resolve(index: list[dict], name: str) -> list[int]:
    """Map an accessible-name-ish handle to candidate element indices.

    The outline gives a name; the DOM index has aria-label and own text. Exact matches
    rank above substring so a unique name resolves to one node.
    """
    needle = name.strip().lower()
    exact, partial = [], []
    for e in index:
        a = e["attrs"]
        cands = [
            e["text"],
            a.get("aria-label", ""),
            a.get("title", ""),
            a.get("alt", ""),
            a.get("placeholder", ""),
        ]
        for c in cands:
            c = (c or "").strip().lower()
            if not c:
                continue
            if c == needle:
                exact.append(e["idx"])
                break
            if needle and needle in c:
                partial.append(e["idx"])
                break
    return exact or partial


def record_unit(index: list[dict], by_idx: dict[int, dict], idx: int) -> tuple[int, int]:
    """Walk up from a matched leaf to the repeating record boundary.

    A handle resolves to whatever carried the accessible name — usually a leaf like an
    img or an a. That is almost never what you want to author a selector against. The
    useful unit is the enclosing element whose SIBLINGS repeat, because that is the
    record boundary a contract extracts one row from.

    Returns (idx, sibling_count). Falls back to the original idx when nothing repeats.
    """
    kids = children_of(index)
    best, best_n = idx, 1
    cur = idx
    while cur != -1 and cur in by_idx:
        e = by_idx[cur]
        sibs = [s for s in kids.get(e["parent"], []) if by_idx[s]["tag"] == e["tag"]]
        if len(sibs) > best_n:
            best, best_n = cur, len(sibs)
        cur = e["parent"]
    return best, best_n


def unique_attr_selector(index: list[dict], idx: int) -> str | None:
    """Pick a selector by MEASURING uniqueness, not by ranking attribute names.

    The previous version carried an ordered allowlist (data-testid, id, name, ...), which
    could only ever prefer attributes someone had thought of, and had no idea whether the
    one it picked actually identified the element.

    This tries every attribute the element genuinely has and keeps those whose
    (attribute, value) pair matches exactly one element in the document — which is the
    property a selector actually needs. Shortest wins as a tie-break, since short
    selectors tend to be the semantic ones. Returns None when nothing is unique, so the
    caller can say so instead of shipping a guess.
    """
    by_idx = {e["idx"]: e for e in index}
    target = by_idx.get(idx)
    if target is None:
        return None
    counts: dict[tuple[str, str], int] = {}
    for e in index:
        for k, v in e["attrs"].items():
            counts[(k, v)] = counts.get((k, v), 0) + 1
    unique = [
        (k, v) for k, v in target["attrs"].items() if counts.get((k, v)) == 1 and k != "class"
    ]
    if not unique:
        return None
    k, v = min(unique, key=lambda kv: len(kv[0]) + len(kv[1]))
    return f"#{v}" if k == "id" else f'[{k}="{v}"]'


def css_path(index: list[dict], by_idx: dict[int, dict], idx: int) -> str:
    """Structural fallback path — used when nothing selectorish is available."""
    parts: list[str] = []
    cur = idx
    while cur != -1 and cur in by_idx:
        e = by_idx[cur]
        seg = e["tag"]
        eid = e["attrs"].get("id")
        if eid:
            parts.append(f"#{eid}")
            break
        parts.append(f"{seg}:nth-child({e['nth']})")
        cur = e["parent"]
    return " > ".join(reversed(parts))


def render_subtree(
    index: list[dict], root_idx: int, *, budget: int, max_depth: int = 4
) -> tuple[str, int]:
    by_idx = {e["idx"]: e for e in index}
    kids = children_of(index)
    lines: list[str] = []
    elided = 0

    def fmt(e: dict, depth: int) -> str:
        a = e["attrs"]
        bits = [f"{e['idx']}", "  " * depth + e["tag"]]
        if a.get("id"):
            bits[-1] += f"#{a['id']}"
        if a.get("class"):
            bits[-1] += "." + ".".join(a["class"].split()[:3])
        for k in ("data-testid", "data-test", "data-cy", "role", "type", "name"):
            if a.get(k):
                bits[-1] += f"[{k}={a[k]}]"
        if a.get("href"):
            bits.append(f"href={a['href'][:60]}")
        if e["text"]:
            bits.append(f'"{e["text"][:80]}"')
        return "  ".join(bits)

    def walk(i: int, depth: int) -> None:
        nonlocal elided
        e = by_idx.get(i)
        if e is None:
            return
        if depth > max_depth or token_count("\n".join(lines)) > budget:
            elided += 1
            return
        lines.append(fmt(e, depth))
        for c in kids.get(i, []):
            walk(c, depth + 1)

    walk(root_idx, 0)
    if elided:
        lines.append(f"… {elided:,} nodes elided (raise --budget or --max-depth)")
    return "\n".join(lines), elided


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve an outline handle to DOM + attributes.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--capture", default=None, help="capture id; defaults to pins.toml")
    ap.add_argument("--name", help="accessible name from the minimal outline")
    ap.add_argument("--idx", type=int, help="data-qa-idx directly")
    ap.add_argument("--budget", type=int, default=1200, help="token budget for the fragment")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument(
        "--unit", action="store_true", help="zoom the repeating record, not the matched leaf"
    )
    args = ap.parse_args()

    index, cap = load_index(args.target, args.capture)
    by_idx = {e["idx"]: e for e in index}

    if args.idx is not None:
        hits = [args.idx]
    elif args.name:
        hits = resolve(index, args.name)
    else:
        raise SystemExit("pass --name or --idx")

    if not hits:
        raise SystemExit(f"no element matched {args.name!r} in {len(index):,} indexed elements")

    print(f"capture   {cap.name}   indexed {len(index):,} elements")
    print(f"handle    {args.name or args.idx!r} → {len(hits)} candidate(s): {hits[:8]}\n")

    root = hits[0]
    if args.unit:
        root, n_sib = record_unit(index, by_idx, root)
        print(f"unit      leaf {hits[0]} → record {root} ({n_sib} repeating siblings)\n")
    frag, elided = render_subtree(index, root, budget=args.budget, max_depth=args.max_depth)
    best = unique_attr_selector(index, root)

    print("─" * 78)
    print(frag)
    print("─" * 78)
    print(f"fragment  {token_count(frag):,} tok   elided {elided}")
    print(f"selector  {best or css_path(index, by_idx, root)}")
    print(f"stable    data-qa-idx={root}")


if __name__ == "__main__":
    main()
