"""Google Search replay example with parametrized navigation and captcha recovery.

The default run is deterministic and offline. It uses a tiny fake browser tab to
exercise the replay engine, the captcha reaction resolver, and the contract
signatures for organic vs sponsored results without touching Google.

Run:
    uv run python examples/google_search/google_search.py
    uv run python examples/google_search/google_search.py --queries 30 --captcha-on 12
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import yosoi as ys
from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.replay._captcha_js import CAPTURE_JS
from yosoi.core.replay.reactions import BusReactionResolver
from yosoi.core.replay.runtime import execute_plan
from yosoi.models.contract import Contract
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    NodeKind,
    ReactionState,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    TeleportSpec,
    TreeNode,
)


class SerpResult(Contract):
    """A Google Search result row with its link and visible title."""

    url: str = ys.Url()
    title: str = ys.Title()


OrganicResult = SerpResult.variant(
    'OrganicResult',
    'An organic unpaid Google Search result from the main results list, not an ad.',
)
AdResult = SerpResult.variant(
    'AdResult',
    'A sponsored Google Search ad marked as paid placement, not an organic result.',
)

EXTRACT_RESULTS_ACTION = 'extract_google_search_results'


def build_google_program(*, latitude: float, longitude: float) -> ReplayPlan:
    """Build a parametrized Google Search replay program."""
    navigate = TreeNode(
        kind=NodeKind.LEAF,
        id='google.navigate',
        leaf=ReplayNode(
            id='google.navigate',
            intent='open the Google Search results page for the query',
            act=ReplayAct(kind=ActKind.NAVIGATE, url='https://www.google.com/search?q={q}'),
        ),
    )
    extract = TreeNode(
        kind=NodeKind.LEAF,
        id='google.extract',
        leaf=ReplayNode(
            id='google.extract',
            intent='extract organic result hosts and titles',
            act=ReplayAct(kind=ActKind.EVAL, script=EXTRACT_RESULTS_ACTION, output_field='organic'),
        ),
    )
    guarded = TreeNode(kind=NodeKind.SEQUENCE, id='google.fetch', children=[navigate, extract])
    return ReplayPlan(
        tree=TreeNode(
            kind=NodeKind.REACTION,
            id='google.captcha_guard',
            child=guarded,
            trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
            state=ReactionState.UNLEARNED,
            description='solve the reCAPTCHA checkpoint blocking Google Search results',
        ),
        teleport=TeleportSpec(latitude=latitude, longitude=longitude, timezone='America/New_York'),
    )


def humanized_click_recovery() -> TreeNode:
    """Recovery subtree returned by the fake discovery resolver."""
    return TreeNode(
        kind=NodeKind.LEAF,
        id='google.captcha_recovery',
        leaf=ReplayNode(
            id='google.captcha_recovery',
            intent='humanized click on the reCAPTCHA checkbox',
            act=ReplayAct(kind=ActKind.HUMAN_CLICK, metadata={'offset_x': 0.12, 'offset_y': 0.5}),
        ),
    )


class FakeTab:
    """Minimal async browser-tab surface used by the replay runtime."""

    def __init__(self) -> None:
        self.url = 'about:blank'
        self.captcha_active = False
        self._arm_captcha_on_next_goto = False
        self.geo: tuple[float, float] | None = None
        self.timezone: str | None = None
        self.mouse_events: list[tuple[str, float, float]] = []
        self.captcha_episodes = 0

    def arm_captcha(self) -> None:
        """Make the next navigation render a fake captcha widget."""
        self._arm_captcha_on_next_goto = True

    async def goto(self, url: str | None) -> None:
        self.url = url or self.url
        if self._arm_captcha_on_next_goto:
            self.captcha_active = True
            self._arm_captcha_on_next_goto = False
            self.captcha_episodes += 1

    async def eval_js(self, script: str) -> Any:
        if script is CAPTURE_JS:
            if not self.captcha_active:
                return None
            return {
                'kind': 'recaptcha',
                'widget_rendered': True,
                'widget_rect': {'x': 380.0, 'y': 300.0, 'width': 300.0, 'height': 74.0},
            }
        if script == EXTRACT_RESULTS_ACTION:
            return [
                {'url': 'https://carebuildersathome.com/louisville/', 'title': 'CareBuilders at Home - Louisville'},
                {'url': 'https://example-competitor.com/', 'title': 'A Competitor'},
            ]
        return None

    async def set_geolocation(self, latitude: float, longitude: float) -> None:
        self.geo = (latitude, longitude)

    async def set_timezone(self, tz: str) -> None:
        self.timezone = tz

    async def set_locale(self, _locale: str) -> None:
        return None

    async def dispatch_mouse_event(self, kind: str, x: float, y: float) -> None:
        self.mouse_events.append((kind, x, y))
        if kind == 'mouseReleased':
            self.captcha_active = False


async def run_demo(*, queries: int, captcha_on: int) -> dict[str, Any]:
    """Run repeated Google Search replays and recover from one fake captcha."""
    tab = FakeTab()
    plan = build_google_program(latitude=38.2527, longitude=-85.7585)
    learn_calls: list[str] = []

    async def learn(domain: str, description: str, info: object) -> TreeNode:
        learn_calls.append(f'{domain}:{description}')
        return humanized_click_recovery()

    resolver = BusReactionResolver(DiscoveryBus(), learn)
    extracted: list[int] = []
    terms = ['home care louisville', 'senior care near me', 'in home caregivers ky']
    for i in range(1, queries + 1):
        if i == captcha_on:
            tab.arm_captcha()
        result = await execute_plan(
            tab,
            plan,
            params={'q': terms[i % len(terms)], 'domain': 'google.com'},
            resolver=resolver,
        )
        extracted.append(len(result.extracted_actions.get('organic') or []))

    return {
        'queries': queries,
        'rows_per_query': extracted,
        'captcha_episodes': tab.captcha_episodes,
        'learn_calls': learn_calls,
        'mouse_events': tab.mouse_events,
        'teleport_geo': tab.geo,
        'teleport_tz': tab.timezone,
        'reaction_state_after': plan.tree.state.value,
    }


def _print_contract_facts() -> None:
    from yosoi.utils.signatures import contract_signature

    organic = contract_signature(OrganicResult)
    ad = contract_signature(AdResult)
    print('OrganicResult signature:', organic)
    print('AdResult signature:     ', ad)
    print('distinct:', organic != ad)


async def _amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queries', type=int, default=8)
    parser.add_argument('--captcha-on', type=int, default=4)
    args = parser.parse_args()

    _print_contract_facts()
    report = await run_demo(queries=args.queries, captcha_on=args.captcha_on)
    print(f'teleport: geo={report["teleport_geo"]} tz={report["teleport_tz"]}')
    print(f'rows per query: {report["rows_per_query"]}')
    print(
        f'captcha episodes={report["captcha_episodes"]}; '
        f'learn calls={len(report["learn_calls"])}; '
        f'reaction state={report["reaction_state_after"]}'
    )


def main() -> None:
    asyncio.run(_amain())


if __name__ == '__main__':
    main()
