"""Yosoi: AI-powered CSS selector discovery and web scraping.

The public API is resolved **lazily** (PEP 562). ``import yosoi`` no longer
eagerly pulls the heavy dependency graph (pydantic-ai and its provider SDKs, the
Claude/OpenCode transports, parsel, dateparser, …); each name is imported from
its submodule on first access instead. This cuts ``import yosoi`` — and every
short-lived subprocess that only needs a slice of the package, e.g. the
``yosoi-validator-mcp`` server — from ~1.6s to well under a second.

Static typing is unaffected: ``yosoi/__init__.pyi`` declares every name
statically, so type-checkers and IDEs see the full API. Keep that stub and the
``_LAZY`` map below in lockstep with each other.
"""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('yosoi')
except PackageNotFoundError:
    __version__ = 'unknown'

# Public name -> submodule that defines it. Resolved on first attribute access.
_LAZY: dict[str, str] = {
    # api
    'scrape': 'yosoi.api',
    'scrape_many': 'yosoi.api',
    'scrape_sync': 'yosoi.api',
    # config
    'DebugConfig': 'yosoi.core.configs',
    'DiscoveryConfig': 'yosoi.core.configs',
    'TelemetryConfig': 'yosoi.core.configs',
    'YosoiConfig': 'yosoi.core.configs',
    'auto_config': 'yosoi.core.configs',
    # discovery: LLM config + provider helpers
    'LLMConfig': 'yosoi.core.discovery',
    'alibaba': 'yosoi.core.discovery',
    'anthropic': 'yosoi.core.discovery',
    'azure': 'yosoi.core.discovery',
    'bedrock': 'yosoi.core.discovery',
    'cerebras': 'yosoi.core.discovery',
    'claude_sdk': 'yosoi.core.discovery',
    'deepseek': 'yosoi.core.discovery',
    'fireworks': 'yosoi.core.discovery',
    'gemini': 'yosoi.core.discovery',
    'github': 'yosoi.core.discovery',
    'grok': 'yosoi.core.discovery',
    'groq': 'yosoi.core.discovery',
    'heroku': 'yosoi.core.discovery',
    'huggingface': 'yosoi.core.discovery',
    'litellm': 'yosoi.core.discovery',
    'mistral': 'yosoi.core.discovery',
    'moonshotai': 'yosoi.core.discovery',
    'nebius': 'yosoi.core.discovery',
    'ollama': 'yosoi.core.discovery',
    'openai': 'yosoi.core.discovery',
    'opencode': 'yosoi.core.discovery',
    'openrouter': 'yosoi.core.discovery',
    'ovhcloud': 'yosoi.core.discovery',
    'provider': 'yosoi.core.discovery',
    'sambanova': 'yosoi.core.discovery',
    'together': 'yosoi.core.discovery',
    'vercel': 'yosoi.core.discovery',
    'vertexai': 'yosoi.core.discovery',
    'xai': 'yosoi.core.discovery',
    # pipeline
    'Pipeline': 'yosoi.core.pipeline',
    # integration transports
    'ClaudeSDKModel': 'yosoi.integrations',
    'OpenCodeModel': 'yosoi.integrations',
    # models
    'Contract': 'yosoi.models.contract',
    'JobPosting': 'yosoi.models.defaults',
    'NewsArticle': 'yosoi.models.defaults',
    'Product': 'yosoi.models.defaults',
    'Video': 'yosoi.models.defaults',
    'FieldSelectors': 'yosoi.models.selectors',
    'SelectorEntry': 'yosoi.models.selectors',
    'SelectorLevel': 'yosoi.models.selectors',
    'attr': 'yosoi.models.selectors',
    'css': 'yosoi.models.selectors',
    'discover': 'yosoi.models.selectors',
    'global_id': 'yosoi.models.selectors',
    'jsonld': 'yosoi.models.selectors',
    'regex': 'yosoi.models.selectors',
    'role': 'yosoi.models.selectors',
    'visual': 'yosoi.models.selectors',
    'xpath': 'yosoi.models.selectors',
    'CacheVerdict': 'yosoi.models.snapshot',
    'SelectorSnapshot': 'yosoi.models.snapshot',
    'SnapshotMap': 'yosoi.models.snapshot',
    'SnapshotStatus': 'yosoi.models.snapshot',
    # semantic types (importing these registers their coercions)
    'Author': 'yosoi.types',
    'BodyText': 'yosoi.types',
    'Datetime': 'yosoi.types',
    'Field': 'yosoi.types',
    'Price': 'yosoi.types',
    'Rating': 'yosoi.types',
    'Title': 'yosoi.types',
    'Url': 'yosoi.types',
    'js': 'yosoi.types',
    'register_coercion': 'yosoi.types',
    # utils
    'resolve_contract': 'yosoi.utils.contracts',
    'load_urls_from_file': 'yosoi.utils.urls',
}

__all__ = [
    'Author',
    'BodyText',
    'CacheVerdict',
    'ClaudeSDKModel',
    'Contract',
    'Datetime',
    'DebugConfig',
    'DiscoveryConfig',
    'Field',
    'FieldSelectors',
    'JobPosting',
    'LLMConfig',
    'NewsArticle',
    'OpenCodeModel',
    'Pipeline',
    'Price',
    'Rating',
    'SelectorEntry',
    'SelectorLevel',
    'SelectorSnapshot',
    'SnapshotMap',
    'SnapshotStatus',
    'TelemetryConfig',
    'Title',
    'Url',
    'Video',
    'YosoiConfig',
    'alibaba',
    'anthropic',
    'attr',
    'auto_config',
    'azure',
    'bedrock',
    'cerebras',
    'claude_sdk',
    'css',
    'deepseek',
    'discover',
    'fireworks',
    'gemini',
    'github',
    'global_id',
    'grok',
    'groq',
    'heroku',
    'huggingface',
    'js',
    'jsonld',
    'litellm',
    'load_urls_from_file',
    'mistral',
    'moonshotai',
    'nebius',
    'ollama',
    'openai',
    'opencode',
    'openrouter',
    'ovhcloud',
    'provider',
    'regex',
    'register_coercion',
    'resolve_contract',
    'role',
    'sambanova',
    'scrape',
    'scrape_many',
    'scrape_sync',
    'together',
    'vercel',
    'vertexai',
    'visual',
    'xai',
    'xpath',
]


def __getattr__(name: str) -> object:
    """Lazily import a public name from its defining submodule (PEP 562)."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
