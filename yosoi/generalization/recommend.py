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

from yosoi.generalization.canonicalize import route_template, same_registrable_domain
from yosoi.generalization.fingerprint import PageObservation, StructuralSignals, structural_signals
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


def _combine(readings: list[SignalReading], same_domain: bool) -> tuple[Verdict, str]:
    """Cost-asymmetric cascade over the readings -> (recommendation, rationale)."""
    refusals = [r for r in readings if r.verdict is Verdict.REFUSE]
    if refusals:
        return Verdict.REFUSE, f'refused by {refusals[0].name}: {refusals[0].rationale}'
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
    optional = (_zero_rows_reading(sig), _row_explosion_reading(seed, replay, sig))
    readings.extend(r for r in optional if r is not None)

    same_domain = same_registrable_domain(seed.url, replay.url)
    recommendation, rationale = _combine(readings, same_domain)
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
