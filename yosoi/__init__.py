"""Yosoi: AI-powered CSS selector discovery and web scraping."""

from yosoi.config import DebugConfig, TelemetryConfig, YosoiConfig
from yosoi.core.discovery import LLMConfig, cerebras, gemini, groq, openai, openrouter
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.defaults import JobPosting, NewsArticle, Product, Video
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
    'TelemetryConfig',
    'Title',
    'Url',
    'Video',
    'YosoiConfig',
    'YosoiType',
    'cerebras',
    'gemini',
    'groq',
    'openai',
    'openrouter',
    'register_coercion',
]
