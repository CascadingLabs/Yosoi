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
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import TYPE_CHECKING

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
