"""Yosoi: AI-powered CSS selector discovery and web scraping."""

from yosoi.core.configs import DebugConfig, TelemetryConfig, YosoiConfig
from yosoi.core.discovery import LLMConfig, cerebras, gemini, groq, openai, openrouter, provider
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.defaults import JobPosting, NewsArticle, Product, Video
from yosoi.models.selectors import SelectorEntry, css, jsonld, regex, xpath
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

__version__ = '0.1.0'

__all__ = [
    'Author',
    'BodyText',
    'Contract',
    'Datetime',
    'DebugConfig',
    'Field',
    'JobPosting',
    'LLMConfig',
    'NewsArticle',
    'Pipeline',
    'Price',
    'Product',
    'Rating',
    'SelectorEntry',
    'TelemetryConfig',
    'Title',
    'Url',
    'Video',
    'YosoiConfig',
    'YosoiType',
    'cerebras',
    'css',
    'gemini',
    'groq',
    'jsonld',
    'openai',
    'openrouter',
    'provider',
    'regex',
    'register_coercion',
    'xpath',
]
