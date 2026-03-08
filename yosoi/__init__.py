"""Yosoi: AI-powered CSS selector discovery and web scraping."""

from yosoi.core.discovery import LLMConfig, gemini, groq, openai
from yosoi.core.fetcher import SmartFetcher
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract, NewsArticle

__version__ = '0.1.0'

__all__ = [
    'Contract',
    'LLMConfig',
    'NewsArticle',
    'Pipeline',
    'SmartFetcher',
    'gemini',
    'groq',
    'openai',
]
