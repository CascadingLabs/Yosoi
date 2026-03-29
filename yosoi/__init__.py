"""Yosoi: AI-powered CSS selector discovery and web scraping."""

from importlib.metadata import PackageNotFoundError, version

from yosoi import yd
from yosoi.core.configs import DebugConfig, TelemetryConfig, YosoiConfig, auto_config

YosoiDriver = yd
from yosoi.core.discovery import (
    LLMConfig,
    alibaba,
    anthropic,
    azure,
    bedrock,
    cerebras,
    deepseek,
    fireworks,
    gemini,
    github,
    grok,
    groq,
    heroku,
    huggingface,
    litellm,
    mistral,
    moonshotai,
    nebius,
    ollama,
    openai,
    openrouter,
    ovhcloud,
    provider,
    sambanova,
    together,
    vercel,
    vertexai,
    xai,
)
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.defaults import JobPosting, NewsArticle, Product, Video
from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel, css, discover, jsonld, regex, xpath
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, SnapshotMap
from yosoi.types import (
    Author,
    BodyText,
    Datetime,
    Field,
    Price,
    Rating,
    Title,
    Url,
    YosoiType,
    register_coercion,
)
from yosoi.utils.contracts import resolve_contract
from yosoi.utils.urls import load_urls_from_file

try:
    __version__ = version('yosoi')
except PackageNotFoundError:
    __version__ = 'unknown'

__all__ = [
    'Author',
    'BodyText',
    'CacheVerdict',
    'Contract',
    'Datetime',
    'DebugConfig',
    'Field',
    'FieldSelectors',
    'JobPosting',
    'LLMConfig',
    'NewsArticle',
    'Pipeline',
    'Price',
    'Rating',
    'SelectorEntry',
    'SelectorLevel',
    'SelectorSnapshot',
    'SnapshotMap',
    'TelemetryConfig',
    'Title',
    'Url',
    'Video',
    'YosoiConfig',
    'YosoiDriver',
    'YosoiType',
    'alibaba',
    'anthropic',
    'auto_config',
    'azure',
    'bedrock',
    'cerebras',
    'css',
    'deepseek',
    'discover',
    'fireworks',
    'gemini',
    'github',
    'grok',
    'groq',
    'heroku',
    'huggingface',
    'jsonld',
    'litellm',
    'load_urls_from_file',
    'mistral',
    'moonshotai',
    'nebius',
    'ollama',
    'openai',
    'openrouter',
    'ovhcloud',
    'provider',
    'regex',
    'register_coercion',
    'resolve_contract',
    'sambanova',
    'together',
    'vercel',
    'vertexai',
    'xai',
    'xpath',
    'yd',
]
