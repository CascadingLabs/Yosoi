"""robots.txt compliance gate — a generic policy mechanism (``CrawlSafety.respect_robots``).

Stack-agnostic on purpose: any pipeline that fetches URLs (crawl today, scrape later) can gate
on it. Fetches each host's ``robots.txt`` once (via any duck-typed ``fetcher`` with an async
``fetch(url)`` returning an object exposing ``.html``), then caches the parsed rules. A missing,
empty, or unreachable ``robots.txt`` is treated as allow-all — the standard posture. Callers
build the gate only when the policy opts to respect robots; ``respect_robots=False`` opts out.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


class RobotsGate:
    """Per-host robots.txt allow-check, matched against ``user_agent`` (default ``*``)."""

    def __init__(self, fetcher: Any, *, user_agent: str = '*') -> None:
        """Gate over ``fetcher`` (async ``fetch(url)->.html``), matching ``user_agent`` rules."""
        self._fetcher = fetcher
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = asyncio.Lock()

    async def allowed(self, url: str) -> bool:
        """Whether ``url`` may be fetched under its host's robots.txt."""
        parts = urlsplit(url)
        if not parts.netloc:
            return True
        parser = await self._parser_for(parts.scheme or 'https', parts.netloc)
        return parser is None or parser.can_fetch(self._user_agent, url)

    async def _parser_for(self, scheme: str, netloc: str) -> RobotFileParser | None:
        if netloc in self._parsers:
            return self._parsers[netloc]
        async with self._lock:
            if netloc not in self._parsers:  # double-checked: one robots fetch per host
                self._parsers[netloc] = await self._load(f'{scheme}://{netloc}/robots.txt')
            return self._parsers[netloc]

    async def _load(self, robots_url: str) -> RobotFileParser | None:
        try:
            response = await self._fetcher.fetch(robots_url)
        except Exception:  # noqa: BLE001 - an unreachable robots.txt is allow-all, never fatal
            return None
        body = getattr(response, 'html', None)
        if not body:
            return None
        parser = RobotFileParser()
        parser.parse(str(body).splitlines())
        return parser
