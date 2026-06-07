"""Scrape the qscrape.dev L2 JavaScript-rendered ScoreTap page.

Run:
    uv run python examples/qscrape.dev/l2/scoretap/scores.py
"""

from __future__ import annotations

import asyncio
import os

import yosoi as ys

URL = 'https://qscrape.dev/l2/scoretap/'


class MatchScore(ys.Contract):
    """One match or standings row in the JS-rendered qscrape.dev L2 scoreboard."""

    team_a: str = ys.Field(description='First team or player name')
    team_b: str = ys.Field(description='Second team or player name')
    score: str = ys.Field(description='Displayed score or result')
    status: str | None = ys.Field(description='Match state, round, or time')


async def main() -> None:
    items = await ys.scrape(
        URL,
        MatchScore,
        model=os.getenv('YOSOI_MODEL') or None,
        selector_level=ys.SelectorLevel.XPATH,
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    ys.show(items)


if __name__ == '__main__':
    asyncio.run(main())
