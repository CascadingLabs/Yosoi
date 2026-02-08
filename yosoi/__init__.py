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
from yosoi.models import (
    DEFAULT_BLUEPRINT,
    ArticleBluePrint,
    BluePrint,
    Field,
    FieldKind,
    Selectors,
    create_field_kind,
    create_scraping_config_model,
    field_kind,
)
from yosoi.storage import SelectorStorage
from yosoi.tracker import LLMTracker
from yosoi.utils import init_yosoi
from yosoi.validator import SelectorValidator

__all__ = [
    # Core components
    'SelectorDiscovery',
    'SelectorStorage',
    'SelectorValidator',
    'LLMTracker',
    # Fetchers
    'BotDetectionError',
    'FetchResult',
    'HTMLFetcher',
    'PlaywrightFetcher',
    'SimpleFetcher',
    'SmartFetcher',
    'create_fetcher',
    # LLM configuration
    'LLMConfig',
    'LLMBuilder',
    'MultiModelAgent',
    'create_model',
    'create_agent',
    'groq',
    'gemini',
    'openai',
    # Utilities
    'init_yosoi',
    # Models and BluePrints
    'BluePrint',
    'Field',
    'FieldKind',
    'Selectors',
    'create_field_kind',
    'field_kind',
    'create_scraping_config_model',
    # Defaults
    'ArticleBluePrint',
    'DEFAULT_BLUEPRINT',
]
