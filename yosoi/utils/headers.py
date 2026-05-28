"""Manages realistic user agents and headers for fetching."""

import random
from typing import ClassVar


class UserAgentRotator:
    """Manages a pool of realistic user agents.

    Provides methods to retrieve random or specific browser user agents
    to help avoid bot detection.

    Attributes:
        USER_AGENTS: A list of agents to fetch an HTML

    """

    # Pool for Yosoi's plain HTTP fetcher. Browser-side UA, platform,
    # and Client Hints are owned by VoidCrawl unless Yosoi explicitly
    # passes a UA override into the VoidCrawl-backed fetcher.
    USER_AGENTS: ClassVar[tuple[str, ...]] = (
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
        # Chrome on Linux
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
        # Firefox
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:142.0) Gecko/20100101 Firefox/142.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0',
    )

    @classmethod
    def get_random(cls) -> str:
        """Get a random user agent.

        Returns:
            A random user agent to be used to fetch an HTML

        """
        return random.choice(cls.USER_AGENTS)

    @classmethod
    def get_chrome(cls) -> str:
        """Get a Chrome UA for browser-backed fetching."""
        chrome = [ua for ua in cls.USER_AGENTS if 'Chrome' in ua and 'Edg' not in ua]
        return random.choice(chrome)

    @classmethod
    def get_chrome_windows(cls) -> str:
        """Get a Chrome on Windows user agent.

        Returns:
            A random Chrome on Windows user agent

        """
        chrome_windows = [ua for ua in cls.USER_AGENTS if 'Chrome' in ua and 'Windows' in ua and 'Edg' not in ua]
        return random.choice(chrome_windows)

    @classmethod
    def get_firefox(cls) -> str:
        """Get a Firefox user agent.

        Returns:
            A random Firefox user agent

        """
        firefox = [ua for ua in cls.USER_AGENTS if 'Firefox' in ua]
        return random.choice(firefox)


class HeaderGenerator:
    """Generates realistic browser headers with variation."""

    @staticmethod
    def generate_headers(
        user_agent: str | None = None,
        referer: str | None = None,
    ) -> dict[str, str]:
        """Generate realistic browser headers with randomization.

        Args:
            user_agent: The user agent to be attached to fetch an HTML
            referer: The referer to be attached to fetch an HTML

        Returns:
            The header to be used to fetch an HTML

        """
        if user_agent is None:
            user_agent = UserAgentRotator.get_random()

        # Base headers that all browsers send
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Add Sec-Fetch-* headers (Chrome/Edge specific).
        if 'Chrome' in user_agent or 'Edg' in user_agent:
            headers.update(
                {
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none' if referer is None else 'same-origin',
                    'Sec-Fetch-User': '?1',
                }
            )

        # Add referer if provided
        if referer:
            headers['Referer'] = referer

        # Randomly add some optional headers
        if random.random() > 0.5:
            headers['Cache-Control'] = random.choice(['no-cache', 'max-age=0'])

        return headers
