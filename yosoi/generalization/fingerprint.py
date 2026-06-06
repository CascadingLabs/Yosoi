"""Page observations and structural fingerprints for reuse-scope decisions.

A :class:`PageObservation` is the cheap, capture-time view of a page — exactly
the fields a fetch already produces (title, matched-row count, body-class tokens,
an HTML tag-frequency histogram). It deliberately holds **no raw HTML**: every
signal here is O(number of distinct tags), so a reuse decision never re-parses a
document.

From a pair of observations we derive the structural signals the scope-canon
spike found load-bearing: tag-histogram cosine (template similarity), a two-sided
row-count ratio (cardinality band), body-class page-kind agreement, and
interpretable scalars (link density, prose share). These are the inputs the
deterministic recommender (:mod:`yosoi.generalization.recommend`) combines.

The fingerprint is **redundant by construction** — no single component is
load-bearing, so a corrupted or missing component degrades gracefully rather than
breaking the decision (validated by ablation in the spike).

This file holds THREE structural views of a page, cheapest first:
  * **shape** (:func:`page_shape_fp`) — a tag-frequency bucket hash. Coarse; fragments on
    content drift. Used as the exact bucket key for the field-atom cache.
  * **skeleton** (:func:`page_skeleton`) — the set of depth-D tree paths (the template).
    Robust to repeated content; compared by Jaccard, not exact hash.
  * **fingerprint** (:class:`PageFingerprint`) — skeleton (L1) + semantics (L2) together,
    compared with a conjunctive, fail-closed matcher.

Most callers want **`PageFingerprint.of(html)` then `a.matches(b)`**, or the
`same_shape(a_html, b_html)` one-liner. The `*_fp` exact hashes exist for the cache key;
the similarity path (`PageFingerprint`) is the trustworthy "are these the same page?" answer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parsel import Selector

# Below this many tags a page is too thin to compare — a blank page, an
# unrendered JS shell, or an error stub. Reuse must ABSTAIN rather than ride a
# vacuous tag-cosine of 1.0 (two empty histograms are "identical").
MIN_TAGS = 5

# Versioned scheme for ``page_shape_fp`` so a change to what feeds the bucket hash
# is observable (a shape-keyed cache miss is distinguishable from a genuine new
# shape), mirroring ``SIGNATURE_SCHEME_VERSION`` on the contract side.
SHAPE_SCHEME_VERSION = 's1'
# Tags contributing less than this share of the document are structural noise and
# are excluded from the shape bucket, so the bucket is robust to row-count drift
# (10 vs 30 results on the same SERP template land in one bucket).
_SHAPE_TAG_FLOOR = 0.005
# Tags whose abundance signals long-form/detail pages rather than listings.
_PROSE_TAGS: tuple[str, ...] = ('p', 'cite', 'sup', 'br', 'font', 'pre', 'code', 'blockquote', 'dd', 'dl')
# Body-class tokens that flag a sort/filter *flavor* of the same page kind, not a
# different kind — stripped before comparing page-kind tokens.
_FLAVOR_TOKENS: frozenset[str] = frozenset({'top-page', 'hot-page', 'new-page', 'rising-page', 'controversial-page'})


class PageObservation(BaseModel):
    """A compact, capture-time snapshot of one page (no raw HTML).

    Attributes:
        url: The page URL (used for route-template canonicalization).
        title: Document title text, used as a coarse semantic tell.
        rows: Count of elements the recipe's row/item selector matched.
        body_class: Space-separated ``<body>`` class tokens (may be empty).
        tag_hist: Mapping of lowercase HTML tag name to its occurrence count.
    """

    url: str
    title: str = ''
    rows: int = 0
    body_class: str = ''
    tag_hist: dict[str, int] = Field(default_factory=dict)

    def kind_tokens(self) -> frozenset[str]:
        """Return body-class tokens with sort/filter flavor tokens removed.

        Returns:
            The set of page-kind tokens (e.g. ``listing-page``, ``profile-page``)
            with flavor tokens like ``top-page`` stripped, so two sorts of the
            same listing compare equal.
        """
        return frozenset(self.body_class.split()) - _FLAVOR_TOKENS

    def link_density(self) -> float:
        """Share of all tags that are anchors — listings are link-dense.

        Returns:
            ``<a>`` count divided by total tag count, in ``[0, 1]``.
        """
        return _share(self.tag_hist, ('a',))

    def prose_share(self) -> float:
        """Share of all tags that are prose/markup — detail pages are prose-heavy.

        Returns:
            Combined prose-tag count divided by total tag count, in ``[0, 1]``.
        """
        return _share(self.tag_hist, _PROSE_TAGS)

    def is_degenerate(self) -> bool:
        """Whether the page is too thin to compare structurally.

        Returns:
            True when the tag histogram holds fewer than :data:`MIN_TAGS` tags —
            a blank page, an unrendered JS shell, or an error stub, where the
            tag-cosine is vacuous and reuse must not be allowed on it.
        """
        return sum(self.tag_hist.values()) < MIN_TAGS


class StructuralSignals(BaseModel):
    """Pairwise structural signals between a seed page and a replay page.

    Each field is a similarity/closeness in ``[0, 1]`` (higher = more alike),
    except ``rows_seed``/``rows_replay`` which are the raw counts retained for the
    cardinality checks the recommender applies.

    Attributes:
        tag_cosine: Cosine similarity of the two tag-frequency histograms.
        rows_ratio: ``min/max`` of the two row counts (two-sided cardinality).
        rows_seed: Seed page matched-row count.
        rows_replay: Replay page matched-row count.
        bodyclass_jaccard: Jaccard overlap of the page-kind body-class tokens.
        link_close: ``1 - |Δ link-density|`` between the pages.
        prose_close: ``1 - |Δ prose-share|`` between the pages.
    """

    tag_cosine: float
    rows_ratio: float
    rows_seed: int
    rows_replay: int
    bodyclass_jaccard: float
    link_close: float
    prose_close: float


def _share(hist: dict[str, int], tags: tuple[str, ...]) -> float:
    """Fraction of total tag count contributed by ``tags``."""
    total = sum(hist.values())
    if total == 0:
        return 0.0
    return sum(hist.get(t, 0) for t in tags) / total


def tag_cosine(seed: dict[str, int], replay: dict[str, int]) -> float:
    """Cosine similarity between two tag-frequency histograms.

    Args:
        seed: Seed page tag histogram.
        replay: Replay page tag histogram.

    Returns:
        Cosine similarity in ``[0, 1]``; ``1.0`` when both are empty (vacuously
        identical) and ``0.0`` when exactly one is empty.
    """
    keys = set(seed) | set(replay)
    if not keys:
        return 1.0
    dot = sum(seed.get(k, 0) * replay.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in seed.values()))
    nb = math.sqrt(sum(v * v for v in replay.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def structural_signals(seed: PageObservation, replay: PageObservation) -> StructuralSignals:
    """Compute all pairwise structural signals for a (seed, replay) pair.

    Args:
        seed: Observation of the page the recipe was discovered on.
        replay: Observation of the candidate reuse page.

    Returns:
        A :class:`StructuralSignals` with every cheap similarity the recommender
        needs.
    """
    hi = max(seed.rows, replay.rows)
    lo = min(seed.rows, replay.rows)
    rows_ratio = 1.0 if hi == 0 else lo / hi

    seed_kinds = seed.kind_tokens()
    replay_kinds = replay.kind_tokens()
    union = seed_kinds | replay_kinds
    bodyclass_jaccard = 1.0 if not union else len(seed_kinds & replay_kinds) / len(union)

    return StructuralSignals(
        tag_cosine=tag_cosine(seed.tag_hist, replay.tag_hist),
        rows_ratio=rows_ratio,
        rows_seed=seed.rows,
        rows_replay=replay.rows,
        bodyclass_jaccard=bodyclass_jaccard,
        link_close=1.0 - abs(seed.link_density() - replay.link_density()),
        prose_close=1.0 - abs(seed.prose_share() - replay.prose_share()),
    )


def page_shape_fp(obs: PageObservation) -> str:
    """Return a stable, coarse *bucket* hash of a page's structural shape.

    Identity is the page's *template skeleton*, not its URL/domain: the set of
    structurally significant tags (those above :data:`_SHAPE_TAG_FLOOR`, so exact
    counts — and thus row-count drift — don't split the bucket) plus the page-kind
    body-class tokens. Mirrors and locales rendering the same template
    (google.com / google.co.uk / an unseen white-label SERP) therefore hash to one
    bucket, which is what lets a lesson learned on one host serve another.

    A degenerate page (too thin to compare — blank, unrendered JS shell, error
    stub) returns a distinct sentinel rather than a real bucket: such pages must
    never share selectors via a vacuous structural match. The fail-closed reuse
    recommender is the actual gate; this hash is only the coarse bucket key.

    Args:
        obs: A capture-time :class:`PageObservation` (no raw HTML needed).

    Returns:
        ``"<scheme>:<16-hex digest>"`` for a real shape, or ``"<scheme>:degenerate"``.
    """
    if obs.is_degenerate():
        return f'{SHAPE_SCHEME_VERSION}:degenerate'
    total = sum(obs.tag_hist.values()) or 1
    significant = sorted(tag for tag, n in obs.tag_hist.items() if n / total >= _SHAPE_TAG_FLOOR)
    payload = json.dumps(
        {'tags': significant, 'kind': sorted(obs.kind_tokens())},
        sort_keys=True,
        separators=(',', ':'),
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f'{SHAPE_SCHEME_VERSION}:{digest}'


def is_degenerate_shape(shape: str) -> bool:
    """True when a ``page_shape``/``page_skeleton`` fingerprint is the degenerate sentinel.

    Thin/blank/unrendered pages all collapse to ``"<scheme>:degenerate"``. Atoms must never be
    minted or served under it — otherwise two unrelated thin pages share one bucket and one
    serves the other's selectors (silent cross-page corruption). Callers (the atom read/write
    paths) gate on this.
    """
    return shape.endswith(':degenerate')


# ---------------------------------------------------------------------------
# Template-skeleton fingerprint (P5 / WF1) — content-volume-invariant structural identity
# ---------------------------------------------------------------------------

SKELETON_SCHEME_VERSION = 't1'
# depth-2 + class tokens gave the cleanest separation on real Yahoo (quote family incl.
# cross-locale ~0.63-0.68 Jaccard vs a different template ~0.28); see skeleton_jaccard.
_SKELETON_DEPTH = 2  # root-to-node path length (tree q-gram)
_SKELETON_CLASS_K = 2  # top-K structural class tokens folded into a node symbol
_MIN_SKELETON_SHINGLES = 8  # below this a page is too thin to identify → degenerate
# Same-shape if each layer's Jaccard ≥ its threshold. 0.40/0.50 is the empirical operating
# point from a 12-page cross-domain sweep (experiments/fingerprint_generalization.py): recall
# 4/4 template families incl. cross-locale, precision 61/62 (the one false merge is quarantined
# anyway). A match only PROPOSES a fingerprint-sourced reuse; the strict trust policy is the
# real safety, not this threshold.
SKELETON_SIMILARITY_THRESHOLD = 0.40
# Presence (not value) of any of these marks a structurally significant / templated node.
_IDENTITY_PRESENCE_ATTRS: tuple[str, ...] = ('id', 'data-testid', 'name', 'role', 'aria-label')


def _node_symbol(el: Any) -> str:
    """A content-free structural symbol for one element: tag + identity-presence + top-K classes."""
    tag = el.tag if isinstance(el.tag, str) else '_'
    ident = '#' if any(el.get(a) for a in _IDENTITY_PRESENCE_ATTRS) else ''
    classes = sorted(filter_class_tokens(el.get('class') or ''))[:_SKELETON_CLASS_K]
    return tag + ident + ''.join(f'.{c}' for c in classes)


def page_skeleton_fp(html: str) -> str:
    """Return a content-volume-invariant TEMPLATE fingerprint of a page (P5 / WF1).

    A page is an instance of a template; two pages share a shape iff they share the template.
    We approximate the template by the SET of depth-D root-to-node paths of *content-free*
    node symbols (tree q-grams). Using a SET (not a multiset) makes repeated siblings — 12 vs
    30 ad / recommended rows — collapse for free, so content volume does not fragment the
    bucket the way the tag-histogram :func:`page_shape_fp` does. Class names have their
    CSS-in-JS hashes stripped (:func:`filter_class_tokens`), so randomized classes don't churn it.

    Returns ``"t1:<16hex>"`` for a real skeleton, or ``"t1:degenerate"`` for a too-thin page.

    NOTE (measured on real Yahoo): the EXACT hash over-discriminates — two quote pages whose
    templates are ~95% identical still differ in a few per-ticker modules, so their hashes
    differ. Identity should therefore be a SIMILARITY over :func:`page_skeleton` (see
    :func:`skeleton_jaccard`), with this exact hash only as the same-template fast path.
    """
    shingles = page_skeleton(html)
    if len(shingles) < _MIN_SKELETON_SHINGLES:
        return f'{SKELETON_SCHEME_VERSION}:degenerate'
    payload = json.dumps(sorted(shingles), separators=(',', ':'))
    return f'{SKELETON_SCHEME_VERSION}:{hashlib.sha256(payload.encode()).hexdigest()[:16]}'


def page_skeleton(html: str) -> frozenset[str]:
    """Return the SET of depth-D content-free node-symbol paths (the template feature set).

    This is the feature set behind the skeleton fingerprint. As a *set* it is content-volume
    invariant (repeated siblings dedup); compared by Jaccard it measures template similarity
    robustly, which exact-hashing it (:func:`page_skeleton_fp`) throws away.
    """
    from parsel import Selector

    root = Selector(text=html).root
    if not hasattr(root, 'iter'):
        return frozenset()
    shingles: set[str] = set()
    for el in root.iter():
        if not isinstance(getattr(el, 'tag', None), str):
            continue  # comment / processing-instruction node
        chain: list[str] = []
        cur: Any = el
        for _ in range(_SKELETON_DEPTH):
            if cur is None or not isinstance(getattr(cur, 'tag', None), str):
                break
            chain.append(_node_symbol(cur))
            cur = cur.getparent()
        shingles.add('/'.join(reversed(chain)))
    return frozenset(shingles)


def skeleton_jaccard(a_html: str, b_html: str) -> float:
    """Jaccard similarity of two pages' template skeletons, in ``[0, 1]`` (1 = identical set).

    High between same-template pages (a quote for AAPL vs MSFT) even when their exact
    skeleton hashes differ; low between genuinely different templates (a quote vs a news
    feed). This is the similarity the exact hash cannot express.
    """
    a, b = page_skeleton(a_html), page_skeleton(b_html)
    union = a | b
    return len(a & b) / len(union) if union else 1.0


# ---------------------------------------------------------------------------
# L2 semantic layer (P5) — landmark spine + heading outline + schema.org types (static)
# ---------------------------------------------------------------------------

_LANDMARK_TAGS: tuple[str, ...] = ('header', 'nav', 'main', 'aside', 'footer', 'section', 'article', 'form')
SEMANTIC_SIMILARITY_THRESHOLD = 0.5


def _count_band(n: int) -> str:
    """Coarse count band so heading counts don't churn the feature on small drift."""
    return 'lo' if n <= 2 else ('mid' if n <= 6 else 'hi')


def _parse_ld_types(blob: str) -> set[str]:
    """Parse one JSON-LD blob into its schema.org ``@type`` set; ``{}`` on bad JSON."""
    try:
        return _ld_types(json.loads(blob))
    except (ValueError, TypeError):
        return set()


def _ld_types(data: Any) -> set[str]:
    """Recursively collect schema.org ``@type`` strings from parsed JSON-LD."""
    out: set[str] = set()
    if isinstance(data, dict):
        t = data.get('@type')
        if isinstance(t, str):
            out.add(t)
        elif isinstance(t, list):
            out.update(x for x in t if isinstance(x, str))
        for v in data.values():
            out |= _ld_types(v)
    elif isinstance(data, list):
        for item in data:
            out |= _ld_types(item)
    return out


def page_semantics(html: str) -> frozenset[str]:
    """L2 semantic feature set (static-derivable): landmarks + roles + heading shape + schema types.

    These are properties of the authored template's *meaning* — a screen-reader skeleton plus
    structured-data contract — which personalization is contractually forbidden from breaking,
    so they survive the per-ticker module churn that drags the deep skeleton down. Compared by
    Jaccard alongside the structural skeleton in the conjunctive matcher.
    """
    from parsel import Selector

    sel = Selector(text=html)
    feats: set[str] = set()
    for tag in _LANDMARK_TAGS:
        if sel.css(tag):
            feats.add(f'lm:{tag}')
    for role in sel.css('[role]::attr(role)').getall():
        r = role.strip().lower()
        if r:
            feats.add(f'role:{r}')
    for lvl in range(1, 7):
        n = len(sel.css(f'h{lvl}'))
        if n:
            feats.add(f'h{lvl}:{_count_band(n)}')
    for blob in sel.css('script[type="application/ld+json"]::text').getall():
        feats.update(f'schema:{t}' for t in _parse_ld_types(blob))
    for it in sel.css('[itemtype]::attr(itemtype)').getall():
        seg = it.rstrip('/').rsplit('/', 1)[-1].strip()
        if seg:
            feats.add(f'schema:{seg}')
    return frozenset(feats)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def semantics_jaccard(a_html: str, b_html: str) -> float:
    """Jaccard similarity of two pages' L2 semantic feature sets, in ``[0, 1]``."""
    return _jaccard(page_semantics(a_html), page_semantics(b_html))


class PageSimilarity(BaseModel):
    """Per-layer similarity and the conjunctive same-shape verdict between two fingerprints."""

    skeleton: float  # L1 structural skeleton Jaccard
    semantic: float  # L2 landmark / heading / schema Jaccard
    same_shape: bool  # conjunctive verdict — every layer agrees


class PageFingerprint(BaseModel):
    """A page's structural identity — compute ONCE from HTML, then compare cheaply.

    The clean surface for the whole fingerprint: ``PageFingerprint.of(html)`` extracts the
    layer feature sets once; ``a.matches(b)`` / ``a.similarity(b)`` compare them. Adding a
    layer (L3 network) is a new field + one term in :meth:`similarity` — generalizable by
    construction.

    Matching is CONJUNCTIVE and fail-closed: two pages are the same shape only if EVERY layer
    clears its threshold, so a coarse layer can never *force* a merge (on real Yahoo, L2 rates
    a different template ~0.9, but the skeleton ~0.4 vetoes it). A match only PROPOSES a
    ``fingerprint``-sourced reuse, which the strict trust policy quarantines by default — the
    fingerprint proposes, the trust policy decides what is served.
    """

    skeleton: frozenset[str]  # L1 structural template (depth-D node-symbol paths)
    semantic: frozenset[str]  # L2 landmark / heading / schema feature set

    @classmethod
    def of(cls, html: str) -> PageFingerprint:
        """Compute a page's fingerprint from its HTML (do this once per page)."""
        return cls(skeleton=page_skeleton(html), semantic=page_semantics(html))

    @property
    def degenerate(self) -> bool:
        """True when the page is too thin to identify (fewer than the minimum structural paths).

        A degenerate fingerprint NEVER matches another: two near-empty pages share a vacuously
        high Jaccard (tiny sets, both semantic sets empty → 1.0), so abstaining is the only
        fail-closed answer. This guard lives here, not just in the exact-hash helpers, so the
        similarity path can't be tricked into a vacuous merge.
        """
        return len(self.skeleton) < _MIN_SKELETON_SHINGLES

    def similarity(
        self,
        other: PageFingerprint,
        *,
        skeleton_threshold: float = SKELETON_SIMILARITY_THRESHOLD,
        semantic_threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
    ) -> PageSimilarity:
        """Per-layer Jaccard plus the conjunctive same-shape verdict against ``other``.

        Thresholds default to the tuned operating point but are overridable — bring your own.
        A degenerate fingerprint on either side forces ``same_shape=False`` (fail closed).
        """
        sk = _jaccard(self.skeleton, other.skeleton)
        se = _jaccard(self.semantic, other.semantic)
        same = not self.degenerate and not other.degenerate and sk >= skeleton_threshold and se >= semantic_threshold
        return PageSimilarity(skeleton=sk, semantic=se, same_shape=same)

    def matches(
        self,
        other: PageFingerprint,
        *,
        skeleton_threshold: float = SKELETON_SIMILARITY_THRESHOLD,
        semantic_threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
    ) -> bool:
        """Whether two pages are the same shape (conjunctive, fail-closed)."""
        return self.similarity(
            other, skeleton_threshold=skeleton_threshold, semantic_threshold=semantic_threshold
        ).same_shape


def same_shape(a_html: str, b_html: str) -> bool:
    """Convenience: are two pages the same shape? Builds both fingerprints and matches.

    A True only PROPOSES a ``fingerprint``-sourced reuse, which the strict trust policy
    quarantines by default. The fingerprint proposes; the trust policy decides.
    """
    return PageFingerprint.of(a_html).matches(PageFingerprint.of(b_html))


# ---------------------------------------------------------------------------
# Per-element fingerprint (CAS-141) — capture-time selector-drift detector
# ---------------------------------------------------------------------------

# Stable identity attributes that anchor a node across layout changes.
_IDENTITY_ATTRS: tuple[str, ...] = ('id', 'data-testid', 'name', 'aria-label', 'href', 'src')
# CSS-in-JS hash pattern: 5+ consecutive hex-compatible chars containing a digit.
_HASH_PATTERN = re.compile(r'[0-9a-f]{5,}', re.IGNORECASE)


class ElementObservation(BaseModel):
    """Capture-time identity of one matched node, for selector-drift detection.

    Holds no raw HTML; every field is O(node degree). Identity signals gate the
    match; positional signals only flag drift.

    Attributes:
        tag: Lowercase element tag name.
        identity_attrs: Stable identity attributes (id, data-testid, name,
            aria-label, href, src) — the primary match anchors.
        class_tokens: Whitespace-split class tokens with hash-shaped atomics
            (CSS-in-JS) stripped so only semantic tokens remain.
        text: Normalized text content of the node (None when absent).
        ancestry: Root-to-node tag chain (Scrapling's ``path`` field).
        siblings: Up to 3 immediately-preceding + 3 following sibling tags.
        parent_tag: Immediate parent tag (last entry of ``ancestry``).
    """

    tag: str
    identity_attrs: dict[str, str]
    class_tokens: frozenset[str]
    text: str | None = None
    ancestry: tuple[str, ...] = ()
    siblings: tuple[str, ...] = ()
    parent_tag: str | None = None


def _is_hash_token(token: str) -> bool:
    """True when a class token looks like a CSS-in-JS generated hash.

    Matches tokens that contain 5+ consecutive hex-compatible characters AND at
    least one digit — e.g. ``css-1a2b3c``, ``sc-abc12``, ``MuiBox-a1b2c3``.
    Pure word tokens like ``listing-page`` are left intact.
    """
    m = _HASH_PATTERN.search(token)
    return m is not None and any(c.isdigit() for c in m.group())


def filter_class_tokens(raw: str) -> frozenset[str]:
    """Split a class-attribute string and drop hash-shaped atomics.

    Args:
        raw: The raw ``class`` attribute value (may be empty).

    Returns:
        Frozenset of stable semantic class tokens.
    """
    return frozenset(t for t in raw.split() if not _is_hash_token(t))


def observe_element(node: Selector) -> ElementObservation:
    """Build an :class:`ElementObservation` from a parsel Selector node.

    Extracts tag, identity attributes, filtered class tokens, normalized text,
    root-to-node ancestry, up to 3+3 adjacent siblings, and the immediate
    parent tag. Uses lxml-direct access for tag/attrs and parsel XPath for
    ancestry/siblings.

    Args:
        node: A parsel Selector for a single matched element (e.g. the result
            of ``sel.css('selector')[0]``).

    Returns:
        An :class:`ElementObservation` with no raw HTML.
    """
    root = node.root
    tag = (root.tag if isinstance(root.tag, str) else '').lower()

    identity_attrs: dict[str, str] = {}
    for attr in _IDENTITY_ATTRS:
        val = (root.get(attr) or '').strip()
        if val:
            identity_attrs[attr] = val

    class_tokens = filter_class_tokens(root.get('class') or '')
    raw_text = (node.xpath('normalize-space(.)').get() or '').strip()
    text = raw_text or None

    # parsel normalises ancestor::* to document order (root first).
    anc_tags = node.xpath('ancestor::*').xpath('name()').getall()
    ancestry = tuple(t.lower() for t in anc_tags)

    # preceding-sibling::* is nearest-first — reverse to document order, keep last 3.
    prev_raw = node.xpath('preceding-sibling::*').xpath('name()').getall()
    prev_tags = [t.lower() for t in reversed(prev_raw)][-3:]
    next_tags = [t.lower() for t in node.xpath('following-sibling::*').xpath('name()').getall()[:3]]
    siblings = tuple(prev_tags) + tuple(next_tags)

    return ElementObservation(
        tag=tag,
        identity_attrs=identity_attrs,
        class_tokens=class_tokens,
        text=text,
        ancestry=ancestry,
        siblings=siblings,
        parent_tag=ancestry[-1] if ancestry else None,
    )
