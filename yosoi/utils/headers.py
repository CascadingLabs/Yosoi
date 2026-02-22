"""Manages realistic user agents and headers for fetching."""

import random


class UserAgentRotator:
    """Manages a pool of realistic user agents.

    Provides methods to retrieve random or specific browser user agents
    to help avoid bot detection.

    Attributes:
        USER_AGENTS: A list of agents to fetch an HTML

    """

    # Pool of realistic, recent user agents
    USER_AGENTS = [
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        # Firefox on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        # Firefox on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
        # Safari on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        # Chrome on Linux
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    @classmethod
    def get_random(cls) -> str:
        """Get a random user agent.

        Returns:
            A random user agent to be used to fetch an HTML

        """
        return random.choice(cls.USER_AGENTS)

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
    def generate_headers(user_agent: str | None = None, referer: str | None = None) -> dict[str, str]:
        """Generate realistic browser headers with randomization.

        Args:
            user_agent: The user agent to be attached to fetch an HTML
            referer: The referer to be attached to fetch an HTML

        Returns:
            The header to be used to fetch an HTML

        """
        if user_agent is None:
            user_agent = UserAgentRotator.get_random()

        languages = [
            'en-US,en;q=0.9',
            'en-GB,en;q=0.9',
            'en-US,en;q=0.9,es;q=0.8',
            'en-US,en;q=0.9,fr;q=0.8',
            'en-US,en;q=0.5',
        ]

        # Base headers that all browsers send
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': random.choice(languages),
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Add Sec-Fetch-* headers (Chrome/Edge specific)
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
