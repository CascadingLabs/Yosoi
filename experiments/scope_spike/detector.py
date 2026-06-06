"""Distilled page-class reuse detector — typed PAIRWISE rules, zero LLM, zero deps.

Why rules, not a trained model (the lateral reviewer's decisive point): the
judgment is *pairwise* — "is the replay the same KIND of page as the seed?" — not
an absolute property of the replay. A rule like ``seed is a listing AND replay is
a detail -> refuse`` carries that pairwise structure naturally; a logistic
regression over replay-only features is wrong by construction whenever the seed's
class context flips the answer. Rules are also git-diffable, inspectable, and a
regression shows up as a NAMED rule's assertion failing — exactly the "typed,
fast-to-catch regression" the user asked for.

Distillation source: the LLM judge scored 1.00 on 52 samples (FINDINGS_LLM_JUDGE).
Its plain-text reasons literally name these features ("rows=0", "profile-page",
"article headline title", "p/br/font explosion", "ns-0 vs ns-14"). We transcribe
those reasons into typed rules and verify they reproduce the judge on the fixtures.

Economic role (the whole point): this runs FREE on the hot path. The expensive
LLM judge is reserved for the ABSTAIN band — cases no rule fires on — and its
verdict is cached per page-class signature. Deterministic content invariants
(``row.subreddit == requested``) are the final kill for the adversarial tail.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    """Three-way so the detector can ABSTAIN to the LLM instead of guessing."""

    ALLOW = 'allow'
    REFUSE = 'refuse'
    ABSTAIN = 'abstain'  # no confident rule -> escalate to cached LLM judge


@dataclass(frozen=True)
class Obs:
    """One page observation — the free features every fixture already carries."""

    url: str
    title: str
    rows: int
    body_class: str
    tag_hist: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """A detector verdict with the NAMED rule that fired (regression-friendly)."""

    verdict: Verdict
    rule: str
    reason: str


_FLAVOR = frozenset({'top-page', 'hot-page', 'new-page', 'rising-page', 'controversial-page'})
_DETAIL_TOKENS = frozenset({'comments-page', 'single-page', 'profile-page', 'question-page', 'user-page'})
# article-ish tags that explode on detail pages but stay sparse on listings
_PROSE_TAGS = ('p', 'cite', 'sup', 'br', 'font', 'pre', 'code', 'blockquote')


def _kind_tokens(body_class: str) -> frozenset[str]:
    return frozenset(body_class.split()) - _FLAVOR


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- #
# Rules. Each takes (seed, replay) and returns a Decision or None (no opinion).
# Ordered: REFUSE rules first (fail-closed bias), then ALLOW confirmations.
# Every rule is pairwise and names itself so a regression points at the culprit.
# --------------------------------------------------------------------------- #
Rule = Callable[[Obs, Obs], 'Decision | None']


def r_zero_rows(seed: Obs, r: Obs) -> Decision | None:
    """Listing seed but replay matched nothing => detail/empty page. (catches 18/26)."""
    if seed.rows > 3 and r.rows == 0:
        return Decision(Verdict.REFUSE, 'zero_rows', f'seed had {seed.rows} rows, replay 0')
    return None


def r_detail_bodyclass(seed: Obs, r: Obs) -> Decision | None:
    """Replay body-class carries an explicit detail/profile/comments token."""
    rt = _kind_tokens(r.body_class)
    hit = rt & _DETAIL_TOKENS
    if hit and not (_kind_tokens(seed.body_class) & _DETAIL_TOKENS):
        return Decision(Verdict.REFUSE, 'detail_bodyclass', f'replay body-class {sorted(hit)}')
    return None


def r_ns_mismatch(seed: Obs, r: Obs) -> Decision | None:
    """MediaWiki namespace tell: seed in ns-14 (category), replay in ns-0 (article)."""
    st, rt = _kind_tokens(seed.body_class), _kind_tokens(r.body_class)
    if 'ns-14' in st and 'ns-0' in rt:
        return Decision(Verdict.REFUSE, 'ns_mismatch', 'category seed -> article replay (ns-14->ns-0)')
    return None


def r_row_explosion(seed: Obs, r: Obs) -> Decision | None:
    """Replay has far MORE rows than seed AND prose-tag explosion => comments thread.

    Catches the HN 190-row trap a one-sided cardinality floor misses.
    """
    if seed.rows > 3 and r.rows > seed.rows * 3:
        prose = sum(r.tag_hist.get(t, 0) for t in _PROSE_TAGS)
        if prose > 5 * sum(seed.tag_hist.get(t, 0) for t in _PROSE_TAGS) + 50:
            return Decision(Verdict.REFUSE, 'row_explosion', f'rows {r.rows} >> seed {seed.rows} + prose blowup')
    return None


def r_profile_title(seed: Obs, r: Obs) -> Decision | None:
    """Title/URL says profile ('overview for X', /user/) — the costume case."""
    t = r.title.lower()
    if ('overview for' in t or '/user/' in r.url or '/~' in r.url) and 'overview for' not in seed.title.lower():
        return Decision(Verdict.REFUSE, 'profile_title', f'profile tell in {r.title!r}/{r.url}')
    return None


def r_structural_allow(seed: Obs, r: Obs) -> Decision | None:
    """Strong same-shape + sane row band => confident ALLOW (the cheap prefilter)."""
    cos = _cosine(seed.tag_hist, r.tag_hist)
    if cos >= 0.90 and r.rows > 0:
        hi, lo = max(seed.rows, r.rows), min(seed.rows, r.rows)
        if hi == 0 or lo / hi >= 0.15:
            return Decision(Verdict.ALLOW, 'structural_allow', f'cosine {cos:.3f}, rows in band')
    return None


# refuse-biased order; allow-confirm last
RULES: list[Rule] = [
    r_zero_rows,
    r_detail_bodyclass,
    r_ns_mismatch,
    r_row_explosion,
    r_profile_title,
    r_structural_allow,
]


def decide(seed: Obs, replay: Obs) -> Decision:
    """Run rules in order; first firing wins; no rule -> ABSTAIN (escalate to LLM)."""
    for rule in RULES:
        d = rule(seed, replay)
        if d is not None:
            return d
    return Decision(Verdict.ABSTAIN, 'none', 'no rule fired; escalate to cached LLM judge')
