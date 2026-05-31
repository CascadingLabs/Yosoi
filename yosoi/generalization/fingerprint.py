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

import math

from pydantic import BaseModel, Field

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
