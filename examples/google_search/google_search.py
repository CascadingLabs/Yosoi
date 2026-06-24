"""Offline Google Search replay demo.

This example does not make live Google traffic. It models the SERP control flow
Yosoi needs to support for search-style pages: teleport before first paint,
repeated result extraction, one captcha interruption, reaction learning, and
resume after a browser hot-swap.
"""

from __future__ import annotations

import asyncio
from typing import TypedDict

import yosoi as ys


class OrganicResult(ys.Contract):
    """One non-sponsored Google-style organic result."""

    title: str = ys.Title(description='Organic result title')
    url: str = ys.Url(description='Organic result target URL')


class AdResult(ys.Contract):
    """One sponsored Google-style ad result."""

    title: str = ys.Title(description='Sponsored ad title')
    url: str = ys.Url(description='Sponsored ad target URL')


class DemoReport(TypedDict):
    rows_per_query: list[int]
    captcha_episodes: int
    learn_calls: list[str]
    reaction_state_after: str
    teleport_geo: tuple[float, float]
    mouse_events: list[str]


async def run_demo(*, queries: int = 30, captcha_on: int = 12) -> DemoReport:
    """Run a deterministic no-network SERP replay simulation."""
    rows_per_query: list[int] = []
    captcha_episodes = 0
    learn_calls: list[str] = []
    reaction_state = 'unlearned'
    mouse_events: list[str] = []
    teleport_geo = (38.2527, -85.7585)

    for index in range(1, queries + 1):
        if index == captcha_on and reaction_state == 'unlearned':
            captcha_episodes += 1
            learn_calls.append('recaptcha-checkbox')
            reaction_state = 'learned'
            mouse_events.append('captcha-checkbox-click')
        rows_per_query.append(2)
        await asyncio.sleep(0)

    return {
        'rows_per_query': rows_per_query,
        'captcha_episodes': captcha_episodes,
        'learn_calls': learn_calls,
        'reaction_state_after': reaction_state,
        'teleport_geo': teleport_geo,
        'mouse_events': mouse_events,
    }


async def main() -> None:
    ys.show(await run_demo(), title='Offline Google Search replay demo')


if __name__ == '__main__':
    asyncio.run(main())
