"""Yosoi - AI-Powered Selector Discovery.

Discover once, scrape forever with BeautifulSoup.
"""

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
