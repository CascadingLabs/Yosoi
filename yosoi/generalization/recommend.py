"""The deterministic reuse-scope recommender.

Given a seed page observation (where a recipe was discovered) and a replay page
observation (a candidate reuse target), produce a :class:`ReuseSignalPanel` with
a fail-closed ALLOW / REFUSE / ABSTAIN recommendation.

The combination rule is a **cost-asymmetric cascade**, not a vote — because the
costs are asymmetric: a leak (reusing on a wrong-class page → silently wrong
data) is catastrophic, a false alarm (refusing a safe reuse) just costs a
re-discovery, and an abstain costs one escalation. So:

1. any high-precision REFUSE signal fires → REFUSE (fail-closed bias);
2. otherwise, ALLOW only when structure *and* cardinality agree strongly;
3. otherwise ABSTAIN — never ALLOW on a bare match.

The route template participates as a *signal*, never as the gate: the scope-canon
spike showed URL templates over-split and over-merge at scale, so a route match
can support ALLOW but a route mismatch only ABSTAINs (it does not, by itself,
REFUSE).
"""

from __future__ import annotations

from difflib import SequenceMatcher

from yosoi.generalization.canonicalize import route_template, same_registrable_domain
from yosoi.generalization.fingerprint import (
    MIN_TAGS,
    ElementObservation,
    PageObservation,
    StructuralSignals,
    structural_signals,
)
from yosoi.generalization.signals import ReuseSignalPanel, SignalReading, Verdict

# Body-class tokens that positively identify a non-listing page kind.
_DETAIL_TOKENS: frozenset[str] = frozenset(
    {'comments-page', 'single-page', 'profile-page', 'question-page', 'user-page', 'ns-0'}
)
# Body-class tokens that positively identify a listing/index page kind.
_LISTING_TOKENS: frozenset[str] = frozenset({'listing-page', 'list-page', 'search-page', 'index-page', 'ns-14'})

COSINE_ALLOW = 0.90  # structural-similarity floor for a confident ALLOW
ROWS_BAND = 0.20  # replay rows must be >= this fraction of seed rows
ROWS_EXPLOSION = 3.0  # replay rows > this * seed rows is suspicious (e.g. comments)
PROSE_EXPLOSION = 5.0  # replay prose-share > this * seed prose-share is detail-like


def _route_reading(seed: PageObservation, replay: PageObservation) -> SignalReading:
    """Route-template signal: supports ALLOW on match, ABSTAINs on mismatch."""
    st, rt = route_template(seed.url), route_template(replay.url)
    if st == rt:
        return SignalReading(
            name='route_template',
            value=f'{st}',
            threshold='equal',
            verdict=Verdict.ALLOW,
            rationale='same route template',
        )
    return SignalReading(
        name='route_template',
        value=f'{st} -> {rt}',
        threshold='equal',
        verdict=Verdict.ABSTAIN,
        rationale='route template differs (key only, not a gate)',
    )


def _bodyclass_reading(seed: PageObservation, replay: PageObservation) -> SignalReading:
    """Body-class kind signal: REFUSE when replay is an explicit non-listing kind."""
    seed_kinds, replay_kinds = seed.kind_tokens(), replay.kind_tokens()
    replay_detail = replay_kinds & _DETAIL_TOKENS
    seed_detail = seed_kinds & _DETAIL_TOKENS
    if replay_detail and not seed_detail:
        return SignalReading(
            name='bodyclass_kind',
            value=','.join(sorted(replay_detail)),
            threshold='no detail token',
            verdict=Verdict.REFUSE,
            rationale='replay body-class is a detail/profile/comments kind',
        )
    if seed_kinds and replay_kinds and seed_kinds == replay_kinds:
        return SignalReading(
            name='bodyclass_kind',
            value=','.join(sorted(replay_kinds)),
            threshold='equal',
            verdict=Verdict.ALLOW,
            rationale='body-class kind tokens match',
        )
    return SignalReading(
        name='bodyclass_kind',
        value=','.join(sorted(replay_kinds)) or '(none)',
        threshold='equal',
        verdict=Verdict.ABSTAIN,
        rationale='body-class kind inconclusive',
    )


def _zero_rows_reading(sig: StructuralSignals) -> SignalReading | None:
    """REFUSE when a listing seed's recipe matches nothing on replay."""
    if sig.rows_seed > 3 and sig.rows_replay == 0:
        return SignalReading(
            name='zero_rows',
            value='0',
            threshold=f'>0 (seed {sig.rows_seed})',
            verdict=Verdict.REFUSE,
            rationale='recipe matched no rows on replay',
        )
    return None


def _row_explosion_reading(
    seed: PageObservation, replay: PageObservation, sig: StructuralSignals
) -> SignalReading | None:
    """REFUSE on a row + prose explosion (e.g. a comments thread vs a listing)."""
    if sig.rows_seed > 3 and sig.rows_replay > sig.rows_seed * ROWS_EXPLOSION:
        seed_prose = seed.prose_share()
        if replay.prose_share() > PROSE_EXPLOSION * seed_prose + 0.05:
            return SignalReading(
                name='row_explosion',
                value=f'{sig.rows_replay} rows',
                threshold=f'<= {ROWS_EXPLOSION}x seed',
                verdict=Verdict.REFUSE,
                rationale='row + prose explosion suggests a detail/thread page',
            )
    return None


def _cardinality_reading(sig: StructuralSignals) -> SignalReading:
    """Two-sided cardinality band: ALLOW within band, REFUSE far below."""
    if sig.rows_seed > 0 and sig.rows_ratio < ROWS_BAND and sig.rows_replay < sig.rows_seed:
        return SignalReading(
            name='cardinality',
            value=f'{sig.rows_replay}/{sig.rows_seed}',
            threshold=f'ratio >= {ROWS_BAND}',
            verdict=Verdict.REFUSE,
            rationale='replay row count far below discovery',
        )
    return SignalReading(
        name='cardinality',
        value=f'{sig.rows_replay}/{sig.rows_seed}',
        threshold=f'ratio >= {ROWS_BAND}',
        verdict=Verdict.ALLOW,
        rationale='row count within band of discovery',
    )


def _cosine_reading(sig: StructuralSignals) -> SignalReading:
    """Structural-similarity signal: ALLOW above the floor, else ABSTAIN."""
    verdict = Verdict.ALLOW if sig.tag_cosine >= COSINE_ALLOW else Verdict.ABSTAIN
    return SignalReading(
        name='tag_cosine',
        value=f'{sig.tag_cosine:.3f}',
        threshold=f'>= {COSINE_ALLOW}',
        verdict=verdict,
        rationale='structural tag-histogram similarity',
    )


def _degenerate_reading(seed: PageObservation, replay: PageObservation) -> SignalReading | None:
    """ABSTAIN when either page is too thin to compare (blank/unrendered/error).

    Guards against the vacuous tag-cosine of 1.0 between two empty histograms,
    which would otherwise read as a confident ALLOW on a blank or JS-shell page.
    """
    thin = [name for name, obs in (('seed', seed), ('replay', replay)) if obs.is_degenerate()]
    if not thin:
        return None
    return SignalReading(
        name='degenerate',
        value=','.join(thin),
        threshold=f'>= {MIN_TAGS} tags',
        verdict=Verdict.ABSTAIN,
        rationale='page too thin to compare (blank/unrendered/error)',
    )


def _combine(readings: list[SignalReading], same_domain: bool, *, degenerate: bool) -> tuple[Verdict, str]:
    """Cost-asymmetric cascade over the readings -> (recommendation, rationale)."""
    refusals = [r for r in readings if r.verdict is Verdict.REFUSE]
    if refusals:
        return Verdict.REFUSE, f'refused by {refusals[0].name}: {refusals[0].rationale}'
    # A too-thin page yields a vacuous structural match — never ALLOW on it.
    if degenerate:
        return Verdict.ABSTAIN, 'degenerate page; cannot confidently allow'
    # Confident ALLOW needs structure AND cardinality to both say ALLOW.
    gates = {'tag_cosine', 'cardinality'}
    gate_readings = [r for r in readings if r.name in gates]
    if gate_readings and all(r.verdict is Verdict.ALLOW for r in gate_readings):
        scope = 'same-domain' if same_domain else 'cross-domain'
        return Verdict.ALLOW, f'structure + cardinality agree ({scope} reuse)'
    return Verdict.ABSTAIN, 'no confident allow and no refusal; escalate'


def recommend(seed: PageObservation, replay: PageObservation) -> ReuseSignalPanel:
    """Produce a fail-closed reuse recommendation for a (seed, replay) pair.

    Args:
        seed: Observation of the page the recipe was discovered on.
        replay: Observation of the candidate reuse page.

    Returns:
        A :class:`ReuseSignalPanel` with per-signal readings and a combined
        ALLOW / REFUSE / ABSTAIN recommendation. ABSTAIN and REFUSE are terminal
        for safety; ALLOW means structure and cardinality both agree.
    """
    sig = structural_signals(seed, replay)
    readings: list[SignalReading] = [
        _route_reading(seed, replay),
        _bodyclass_reading(seed, replay),
        _cosine_reading(sig),
        _cardinality_reading(sig),
    ]
    optional = (_zero_rows_reading(sig), _row_explosion_reading(seed, replay, sig), _degenerate_reading(seed, replay))
    readings.extend(r for r in optional if r is not None)

    same_domain = same_registrable_domain(seed.url, replay.url)
    degenerate = seed.is_degenerate() or replay.is_degenerate()
    recommendation, rationale = _combine(readings, same_domain, degenerate=degenerate)
    return ReuseSignalPanel(
        seed_url=seed.url,
        replay_url=replay.url,
        seed_route=route_template(seed.url),
        replay_route=route_template(replay.url),
        same_domain=same_domain,
        readings=readings,
        recommendation=recommendation,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Per-element drift detection (CAS-141)
# ---------------------------------------------------------------------------

# Weighted scores mirror recommend.py's cost-asymmetric posture: identity attrs
# are 4x more load-bearing than text, which itself outweighs positional signals.
_ELEMENT_WEIGHTS: dict[str, float] = {
    'identity': 4.0,
    'tag': 2.0,
    'class': 1.5,
    'text': 1.0,
    'ancestry': 0.5,
    'siblings': 0.5,
}
_TOTAL_WEIGHT: float = sum(_ELEMENT_WEIGHTS.values())  # 9.5

# Score thresholds for the three-way outcome.
ELEMENT_MATCH_FLOOR = 0.80  # >= this → MATCH  → Verdict.ALLOW
ELEMENT_DRIFT_FLOOR = 0.50  # >= this → DRIFTED → Verdict.REFUSE; below → AMBIGUOUS → Verdict.ABSTAIN


def _identity_score(a: dict[str, str], b: dict[str, str]) -> float:
    """Similarity of identity-attribute dicts; 0.75 (mildly positive) when both empty.

    Both nodes lacking stable identity is a consistent signal — they agree on being
    un-anchored. Neutral 0.5 would unfairly penalise elements that never had
    id/data-testid; 0.75 lets the other signals decide when both are empty.
    """
    ka, kb = set(a), set(b)
    if not ka and not kb:
        return 0.75
    all_keys = ka | kb
    shared = ka & kb
    if not shared:
        return 0.0 if (ka and kb) else 0.25
    matches = sum(a.get(k) == b.get(k) for k in all_keys)
    return matches / len(all_keys)


def _class_score(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of filtered class tokens; 0.5 (neutral) when both empty."""
    if not a and not b:
        return 0.5
    union = len(a | b)
    return len(a & b) / union if union else 0.5


def _text_score(a: str | None, b: str | None) -> float:
    """SequenceMatcher ratio on text content; 0.5 (neutral) when both absent."""
    if a is None and b is None:
        return 0.5
    if a is None or b is None:
        return 0.0
    return SequenceMatcher(None, a[:500], b[:500]).ratio()


def _seq_score(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """SequenceMatcher ratio on tag-name sequences; 0.5 (neutral) when both empty."""
    if not a and not b:
        return 0.5
    return SequenceMatcher(None, a, b).ratio()


def _element_score(stored: ElementObservation, current: ElementObservation) -> float:
    """Weighted asymmetric similarity of two element fingerprints, in [0, 1]."""
    components: dict[str, float] = {
        'identity': _identity_score(stored.identity_attrs, current.identity_attrs),
        'tag': 1.0 if stored.tag == current.tag else 0.0,
        'class': _class_score(stored.class_tokens, current.class_tokens),
        'text': _text_score(stored.text, current.text),
        'ancestry': _seq_score(stored.ancestry, current.ancestry),
        'siblings': _seq_score(stored.siblings, current.siblings),
    }
    return sum(_ELEMENT_WEIGHTS[k] * v for k, v in components.items()) / _TOTAL_WEIGHT


def element_drift(stored: ElementObservation, current: ElementObservation) -> SignalReading:
    """Compare a stored element fingerprint against a live node fingerprint.

    Three outcomes (mirroring the page-level cascade's cost-asymmetric posture):

    * **MATCH** (score >= :data:`ELEMENT_MATCH_FLOOR`) → :attr:`Verdict.ALLOW`:
      the same node survived; reuse is safe.
    * **DRIFTED** (:data:`ELEMENT_DRIFT_FLOOR` <= score < floor) → :attr:`Verdict.REFUSE`:
      the node changed; trigger offline re-discovery, never relocate live.
    * **AMBIGUOUS** (score < :data:`ELEMENT_DRIFT_FLOOR`) → :attr:`Verdict.ABSTAIN`:
      element unrecognizable or two candidates within ε; fail closed.

    Identity attributes dominate (4x weight) so a stable ``id``/``data-testid``
    survives a class or position change without triggering a false DRIFTED. Text
    and positional signals are tie-breakers and drift detectors, not gates.

    Args:
        stored: :class:`ElementObservation` captured at discovery time.
        current: :class:`ElementObservation` of the element the selector matched
            on replay.

    Returns:
        A :class:`SignalReading` with ``name='element_drift'``, the weighted score
        as ``value``, and ALLOW / REFUSE / ABSTAIN as ``verdict``.
    """
    score = _element_score(stored, current)
    if score >= ELEMENT_MATCH_FLOOR:
        verdict, label = Verdict.ALLOW, 'match'
    elif score >= ELEMENT_DRIFT_FLOOR:
        verdict, label = Verdict.REFUSE, 'drifted'
    else:
        verdict, label = Verdict.ABSTAIN, 'ambiguous'
    return SignalReading(
        name='element_drift',
        value=f'{score:.3f}',
        threshold=f'>={ELEMENT_MATCH_FLOOR} match, >={ELEMENT_DRIFT_FLOOR} drifted',
        verdict=verdict,
        rationale=f'element fingerprint {label} (score {score:.3f})',
    )
