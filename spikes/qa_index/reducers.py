"""Reducers beyond the AX outline, and label-free retention estimates.

The outline already does most of the work (see scoreboard). The remaining win is
structural: a page repeats whole SUBTREES, not just adjacent identical lines. Twenty
product cards with four children each are twenty copies of one skeleton carrying twenty
different names. Collapsing them to `exemplar ×20 + the names` is the role-typed
skeleton idea — skeleton says "these are the same shape", AX says what the shape is.

Coverage is measured directly by defects.py (inject a known defect, check whether the
reduced view still differs). The earlier estimate-based proxies were removed once real
coverage existed — an estimator that nothing calls is just a hardcoded role list
pretending to be a metric.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class TreeNode:
    role: str
    name: str | None
    depth: int
    children: list[TreeNode] = field(default_factory=list)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def build_tree(nodes) -> TreeNode:
    """Rebuild hierarchy from the outline's indentation."""
    root = TreeNode(role="__root__", name=None, depth=-1)
    stack = [root]
    for n in nodes:
        while len(stack) > 1 and stack[-1].depth >= n.depth:
            stack.pop()
        node = TreeNode(role=n.role, name=n.name, depth=n.depth)
        stack[-1].children.append(node)
        stack.append(node)
    return root


def skeleton_sig(node: TreeNode) -> str:
    """Structural signature ignoring names — the skeleton, not the content.

    Two subtrees share a signature iff they have the same role shape. This is the
    primitive that lets 20 cards collapse to 1 exemplar without assuming anything about
    what the cards contain.
    """
    parts = [node.role] + [skeleton_sig(c) for c in node.children]
    return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


def _names_in(node: TreeNode) -> list[str]:
    return [n.name for n in node.walk() if n.name]


def dedup_subtrees(root: TreeNode, *, min_run: int = 2, samples: int = 3) -> list[str]:
    """Collapse runs of same-skeleton siblings into exemplar + count + sampled names.

    ``samples`` is the token/retention dial: 0 keeps shape only (cheapest, worst name
    retention), higher keeps more of what actually distinguishes the repeated items.
    """
    out: list[str] = []

    def emit(node: TreeNode, depth: int, count: int, extra_names: list[str]) -> None:
        pad = "  " * depth
        label = f'{node.role} "{node.name}"' if node.name else node.role
        suffix = f" ×{count}" if count > 1 else ""
        if extra_names:
            shown = ", ".join(extra_names[:samples]) if samples else ""
            more = len(extra_names) - min(samples, len(extra_names))
            tail = f" [{shown}{f' +{more}' if more > 0 else ''}]" if shown else ""
            suffix += tail
        out.append(f"{pad}{label}{suffix}")

    def recurse(node: TreeNode, depth: int) -> None:
        i = 0
        kids = node.children
        while i < len(kids):
            sig = skeleton_sig(kids[i])
            run = 1
            while i + run < len(kids) and skeleton_sig(kids[i + run]) == sig:
                run += 1
            head = kids[i]
            if run >= min_run:
                # Names that vary across the collapsed group carry the content the
                # skeleton throws away — sample them rather than lose them silently.
                varying: list[str] = []
                for sib in kids[i : i + run]:
                    varying.extend(_names_in(sib))
                distinct = list(dict.fromkeys(varying))
                emit(head, depth, run, distinct)
                # Descend into the exemplar only — that is the whole point.
                recurse(head, depth + 1)
            else:
                emit(head, depth, 1, [])
                recurse(head, depth + 1)
            i += run

    recurse(root, 0)
    return out


def skeleton_dedup(outline_text: str, parse_outline, *, samples: int = 3) -> str:
    root = build_tree(parse_outline(outline_text))
    return "\n".join(dedup_subtrees(root, samples=samples))


NON_CONTENT_TAGS = {"script", "style", "noscript", "template", "link", "meta"}


def dom_outline(dom_index: list[dict], *, max_depth: int = 8) -> str:
    """Build an outline from the DOM side instead of the AX tree.

    Needed because the AX outline goes BLIND on div-soup / framework-island pages: on
    qscrape /l2/eshop the AX tree reported `main` as empty while the DOM held 19
    <article> elements of product data. A 139-token index there was not efficiency, it
    was blindness — and the only way to tell the two apart is to check.

    Costs more than the AX outline (~12x reduction vs ~200x) because tag+class is less
    semantically dense than role+name. Use it when the AX tree is thin, not by default.
    """
    by = {e["idx"]: e for e in dom_index}
    depth_cache: dict[int, int] = {}

    def depth(e: dict) -> int:
        if e["idx"] in depth_cache:
            return depth_cache[e["idx"]]
        d, cur = 0, e["parent"]
        while cur != -1 and cur in by:
            d += 1
            cur = by[cur]["parent"]
        depth_cache[e["idx"]] = d
        return d

    lines: list[str] = []
    for e in dom_index:
        if e["tag"] in NON_CONTENT_TAGS:
            continue
        text = (e["text"] or "").strip()
        label = e["attrs"].get("aria-label") or e["attrs"].get("title") or ""
        if not text and not label:
            continue
        cls = (e["attrs"].get("class") or "").split()
        sig = e["tag"] + (f".{cls[0]}" if cls else "")
        lines.append("  " * min(depth(e), max_depth) + f'{sig} "{(text or label)[:70]}"')
    return "\n".join(lines)


def ax_is_thin(ax_outline_text: str, dom_index: list[dict]) -> tuple[bool, dict]:
    """Decide whether the AX index can be trusted for this page.

    A plain named-vs-texty RATIO is NOT sufficient — measured, not assumed. Google Maps
    scores 0.266 yet its AX index worked perfectly (351 tok → a complete 11-field spec),
    so a 0.5 ratio threshold wrongly forces the 12x-more-expensive DOM source there.

    The signal that actually distinguished the blind case (qscrape /l2/eshop) was
    STRUCTURAL: the `main` landmark had no named descendants at all, while the DOM held
    19 <article> elements. So test emptiness of the content landmark first, and keep the
    ratio only as a coarse backstop.
    """
    lines = ax_outline_text.splitlines()
    ax_named = sum(1 for line in lines if '"' in line)
    dom_texty = sum(
        1
        for e in dom_index
        if e["tag"] not in NON_CONTENT_TAGS
        and ((e["text"] or "").strip() or e["attrs"].get("aria-label"))
    )
    ratio = (ax_named / dom_texty) if dom_texty else 1.0

    # Named descendants under the main/feed content landmark.
    main_named, in_main, main_indent = 0, False, 0
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(stripped)
        role = stripped.split(" ", 1)[0] if stripped else ""
        if in_main and indent <= main_indent:
            in_main = False
        if role in {"main", "feed"} and not in_main:
            in_main, main_indent = True, indent
            continue
        if in_main and '"' in stripped:
            main_named += 1

    has_main = any(ln.strip().split(" ", 1)[0] in {"main", "feed"} for ln in lines)
    blind_main = has_main and main_named == 0 and dom_texty > 20
    thin = blind_main or ratio < 0.1
    return thin, {
        "ax_named": ax_named,
        "dom_texty": dom_texty,
        "ratio": round(ratio, 3),
        "main_named": main_named,
        "reason": "empty main landmark" if blind_main else ("low ratio" if thin else "ok"),
    }


def source_outline(html_text: str, *, top_attrs: int | None = None, clip: int = 110) -> str:
    """Index the HTML SOURCE — the surface ax/dom/zoom all drop.

    `dom` is already an index of the rendered DOM, but a lossy one: dom_index.json keeps
    a hardcoded attribute allowlist and own-text only. Two things fall through:

      * <head> ENTIRELY. No other modality carries <title>, meta description, canonical,
        or og:* — the whole SEO/social QA category has zero coverage.
      * The ATTRIBUTE VOCABULARY. Which attributes a page actually uses is a QA signal,
        and an allowlist can only ever report what it was told to look for.

    NOTHING HERE IS ENUMERATED. Every meta, every link rel, every attribute is reported
    as found. This is not stylistic: on a real portfolio it surfaced
    `<meta name="Andrew Berg">` — a malformed tag that almost certainly meant
    `name="author"`, and which any sensible allowlist (description/og:/twitter:) would
    have silently hidden. An allowlist cannot find the thing you did not predict.

    The single deliberate exception, with its reason: event handlers are detected by the
    `on*` prefix, which is the HTML specification's own definition of event handler
    content attributes — a closed rule from the spec, not a guess about this page.

    `top_attrs=None` reports the full vocabulary. Any cap is display-only and is stated
    in the output, never silent.
    """
    from collections import Counter

    from lxml import html as LH

    root = LH.fromstring(html_text)
    out: list[str] = []

    out.append("HEAD")
    title = root.findtext(".//title")
    out.append(f'  title "{(title or "").strip()[:clip]}"' if title else "  title MISSING")
    lang = root.get("lang")
    out.append(f"  html[lang] {lang}" if lang else "  html[lang] MISSING")
    for m in root.findall(".//meta"):
        key = m.get("name") or m.get("property") or m.get("http-equiv") or m.get("charset")
        if not key:
            continue
        val = (m.get("content") or m.get("charset") or "").strip()
        out.append(f'  meta[{key}] "{val[:clip]}"')
    # Every rel, discovered — no allowlist. A page that declares an unexpected rel is
    # exactly the case worth seeing.
    for link in root.findall(".//link"):
        rel = link.get("rel")
        if rel:
            out.append(f'  link[{rel}] "{(link.get("href") or "")[:clip]}"')

    scripts = root.findall(".//script")
    ext = [x for x in scripts if x.get("src")]
    sheets = [x for x in root.findall(".//link") if (x.get("rel") or "") == "stylesheet"]
    out.append("\nRESOURCES")
    out.append(f"  script  {len(ext)} external, {len(scripts) - len(ext)} inline")
    out.append(f"  stylesheet  {len(sheets)}")

    attrs: Counter = Counter()
    handlers: Counter = Counter()
    tags: Counter = Counter()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tags[el.tag] += 1
        for a in el.attrib:
            attrs[a] += 1
            if a.startswith("on"):  # HTML spec: event handler content attributes
                handlers[a] += 1

    shown = attrs.most_common(top_attrs) if top_attrs else attrs.most_common()
    out.append(f"\nATTRIBUTE VOCABULARY  (observed, not enumerated — {len(attrs)} distinct)")
    if top_attrs and len(attrs) > top_attrs:
        out.append(f"  [showing top {top_attrs} of {len(attrs)}; pass top_attrs=None for all]")
    for a, n in shown:
        out.append(f"  {a:<24} {n}")
    if handlers:
        out.append(f"\n  INLINE HANDLERS: {dict(handlers)}")
    out.append(
        f"\nTAGS  ({len(tags)} distinct): " + ", ".join(f"{t}:{n}" for t, n in tags.most_common(20))
    )
    return "\n".join(out)
