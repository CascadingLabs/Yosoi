"""
yosoi - AI-Powered CSS Selector Discovery
==========================================

Yosoi is a Python library that uses AI to discover CSS selectors from web pages.
Discover once, scrape forever with BeautifulSoup.

Main Components:
    - SelectorDiscovery: AI-powered selector discovery from HTML
    - SelectorStorage: Save and load discovered selectors
    - SelectorValidator: Validate selectors against web pages
    - LLMTracker: Track LLM usage and efficiency
    - Fetchers: HTML fetching with bot detection avoidance

Example:
    >>> from yosoi import SelectorDiscovery, groq
    >>> config = groq('llama-3.3-70b-versatile', 'your-api-key')
    >>> discovery = SelectorDiscovery(llm_config=config)
    >>> selectors = discovery.discover_from_html(url, html)
"""

__version__ = '0.1.0'

from yosoi.discovery import SelectorDiscovery
from yosoi.fetcher import (
    BotDetectionError,
    FetchResult,
    HTMLFetcher,
    PlaywrightFetcher,
    SimpleFetcher,
    SmartFetcher,
    create_fetcher,
)
from yosoi.llm_config import (
    LLMBuilder,
    LLMConfig,
    MultiModelAgent,
    create_agent,
    create_model,
    gemini,
    groq,
    openai,
)
from yosoi.storage import SelectorStorage
from yosoi.tracker import LLMTracker
from yosoi.validator import SelectorValidator

__all__ = [
    'SelectorDiscovery',
    'SelectorStorage',
    'SelectorValidator',
    'LLMTracker',
    'BotDetectionError',
    'FetchResult',
    'HTMLFetcher',
    'PlaywrightFetcher',
    'SimpleFetcher',
    'SmartFetcher',
    'create_fetcher',
    'LLMConfig',
    'LLMBuilder',
    'MultiModelAgent',
    'create_model',
    'create_agent',
    'groq',
    'gemini',
    'openai',
]
