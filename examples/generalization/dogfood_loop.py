"""Dogfood loop: run reuse advice over a URL list and log the decisions.

This is the *safe* way to exercise generalization before it is wired into the
scrape Pipeline. For each candidate page it emits an **advisory** reuse hint
(``TRY_REUSE`` / ``REDISCOVER`` / ``UNSURE``) against a single seed, records the
decision to ``.yosoi/generalization/<date>.jsonl``, and prints a live panel.

Nothing here gates correctness: a discovery agent that acted on these hints would
still run semantic verification, which catches a wrong reuse and re-discovers.
The persisted :class:`~yosoi.generalization.DecisionRecord`s are the flywheel
ledger — once their outcomes are back-filled (by an invariant or the agent's own
verification) they become labelled training rows for a future learned recommender.

Observations are committed fixtures (captured live via voidcrawl) so the loop is
deterministic and offline; swap in :func:`~yosoi.generalization.observe_html` on
freshly fetched HTML to run it for real.

Run:
    uv run python examples/generalization/dogfood_loop.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from yosoi.generalization import (
    DecisionStore,
    PageObservation,
    advise_reuse,
    build_decision,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'qscrape_observations.json'


def _observation(record: dict) -> PageObservation:
    """Build a PageObservation from a fixture record (ignoring demo metadata)."""
    return PageObservation(
        url=record['url'],
        title=record['title'],
        rows=record['rows'],
        body_class=record['body_class'],
        tag_hist=record['tag_hist'],
    )


def main() -> None:
    """Advise reuse for every fixture page against the seed; log every decision."""
    data = json.loads(FIXTURE.read_text())
    seed = _observation(data['seed'])
    store = DecisionStore()

    print('=' * 78)
    print('DOGFOOD LOOP — advisory reuse hints (verification remains the gate)')
    print('  seed recipe discovered on:', seed.url)
    print('=' * 78)

    for replay_rec in data['replays']:
        replay = _observation(replay_rec)
        hint = advise_reuse(seed, replay)
        decision = build_decision(hint.panel, decided_at=datetime.now(timezone.utc), driver='dogfood')
        store.append(decision)
        print(f'\n  {replay.url}')
        print(f'    {hint.as_prompt_line()}')
        print(f'    logged: trust={decision.trust.value} outcome={decision.outcome.value} (pending back-fill)')

    print('\n' + '-' * 78)
    print('ledger summary:', store.summary())
    print('Back-fill outcomes via DecisionRecord.promote(confirmed=...) once the')
    print('discovery agent semantically verifies each acted-on reuse.')


if __name__ == '__main__':
    main()
