"""Scrape the qscrape.dev L1 ScoreTap scoreboard.

Run:
    uv run python examples/qscrape.dev/l1/scoretap/scores.py
"""

from __future__ import annotations

import asyncio
import json
import os

import yosoi as ys

URL = 'https://qscrape.dev/l1/scoretap/'


class MatchScore(ys.Contract):
    """One match or standing row on the static qscrape.dev L1 ScoreTap page."""

    team_a: str = ys.Field(description='First team or player name')
    team_b: str = ys.Field(description='Second team or player name')
    score: str = ys.Field(description='Displayed score or result')
    status: str | None = ys.Field(default=None, description='Match state, round, or time')


async def main() -> None:
    items = await ys.scrape(
        URL,
        MatchScore,
        model=os.getenv('YOSOI_MODEL') or None,
        fetcher_type='simple',
        force=os.getenv('YOSOI_FORCE', '').lower() in {'1', 'true', 'yes'},
        quiet=False,
    )
    print(json.dumps(items, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
