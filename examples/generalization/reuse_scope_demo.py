"""Reuse-scope generalization demo over real qscrape.dev captures.

A recipe was discovered on the qscrape.dev quote listing (``/``). For each *other*
page — a sibling sub-path, a different route on the same domain, a same-domain
detail page, and two different domains — should we REUSE that recipe or
re-discover?

Scenarios, all judged against the one seed:

* same sub-path        ``/tag/{slug}/page/{num}`` listings        -> expect ALLOW
* same domain, detail  ``/author/...`` and ``/login``            -> expect REFUSE
* cross domain         quotes.toscrape.com (same idea, diff DOM) -> expect ABSTAIN
                       books.toscrape.com  (different kind)       -> expect REFUSE

Observations are committed fixtures (captured live via voidcrawl) so the demo is
deterministic and offline. To run on freshly fetched HTML, build a
:class:`~yosoi.generalization.PageObservation` with
:func:`~yosoi.generalization.observe_html` and pass it to ``recommend``.

Run:
    uv run python examples/generalization/reuse_scope_demo.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from yosoi.generalization import PageObservation, build_decision, recommend

FIXTURE = Path(__file__).parent / 'fixtures' / 'qscrape_observations.json'

_SCENARIO_TITLES = {
    'same-subpath': 'SAME SUB-PATH (sibling tag/page listings)',
    'same-domain-other-route': 'SAME DOMAIN, different route (still a listing)',
    'same-domain-detail': 'SAME DOMAIN, detail page (must refuse)',
    'cross-domain-similar': 'CROSS DOMAIN, same idea / different DOM',
    'cross-domain-different': 'CROSS DOMAIN, different kind (must refuse)',
}


def _observation(record: dict) -> PageObservation:
    """Build a PageObservation from a fixture record (ignoring demo metadata).

    Args:
        record: One fixture entry with url/title/rows/body_class/tag_hist keys.

    Returns:
        The corresponding :class:`PageObservation`.
    """
    return PageObservation(
        url=record['url'],
        title=record['title'],
        rows=record['rows'],
        body_class=record['body_class'],
        tag_hist=record['tag_hist'],
    )


def main() -> None:
    """Run the recommender for every replay page against the seed and print it."""
    data = json.loads(FIXTURE.read_text())
    seed = _observation(data['seed'])

    print('=' * 78)
    print('REUSE-SCOPE GENERALIZATION — recipe discovered on:', seed.url)
    print('  row selector = ".quote"; qscrape.dev emits no body_class (no page-kind tell)')
    print('=' * 78)

    for replay_rec in data['replays']:
        replay = _observation(replay_rec)
        panel = recommend(seed, replay)
        decision = build_decision(panel, decided_at=datetime.now(timezone.utc), driver='demo')

        scenario = _SCENARIO_TITLES.get(replay_rec['scenario'], replay_rec['scenario'])
        print(f'\n[{scenario}]')
        print(f'  {replay.url}')
        print(
            f'  route: {panel.seed_route}  ->  {panel.replay_route}'
            f'  ({"same-domain" if panel.same_domain else "cross-domain"})'
        )
        for reading in panel.readings:
            thr = f' (thr {reading.threshold})' if reading.threshold else ''
            print(f'    - {reading.name:14s} {reading.verdict.value:7s} {reading.value}{thr}')
        print(f'  => {panel.recommendation.value.upper()}: {panel.rationale}')
        print(f'     trust={decision.trust.value}  (output usable only if consumer accepts quarantine)')


if __name__ == '__main__':
    main()
