"""Scrape the qscrape.dev L3 island-rendered ScoreTap page.

Run:
    uv run python examples/qscrape.dev/l3/scoretap/scores.py
"""

from __future__ import annotations

import asyncio

import yosoi as ys

URL = 'https://qscrape.dev/l3/scoretap/'


class MatchScore(ys.Contract):
    """One match or standings row assembled across qscrape.dev L3 islands."""

    team_a: str = ys.Field(description='First team or player name')
    team_b: str = ys.Field(description='Second team or player name')
    score: str = ys.Field(description='Displayed score or result')
    status: str | None = ys.Field(description='Match state, round, or time')


async def main() -> None:
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(selector_level=ys.SelectorLevel.XPATH),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    items = await ys.scrape(
        URL,
        MatchScore,
        policy=policy,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
