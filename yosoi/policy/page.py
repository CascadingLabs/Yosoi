"""Generic page acquisition policy shared by crawl, scrape, and scripts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yosoi.policy._base import StrictFloat, StrictInt

FetcherPolicyName = Literal['auto', 'simple', 'headless', 'headful', 'waterfall']
CleanerProfileName = Literal['discovery', 'raw']


class PagePolicy(BaseModel):
    """Policy for acquiring a page before a runtime decides what to do with it."""

    model_config = ConfigDict(frozen=True)

    fetcher_type: FetcherPolicyName = 'auto'
    timeout_seconds: StrictFloat = Field(default=30.0, gt=0.0, le=300.0)
    max_fetch_retries: StrictInt = Field(default=1, ge=1, le=10)
    allow_redirects: bool = True
    clean_html: bool = True
    cleaner_profile: CleanerProfileName = 'discovery'
    chrome_ws_urls: tuple[str, ...] = ()

    @field_validator('chrome_ws_urls', mode='before')
    @classmethod
    def _coerce_chrome_ws_urls(cls, value: object) -> tuple[str, ...]:
        if value is None or value == '':
            return ()
        if isinstance(value, str):
            items: Sequence[object] = value.split(',')
        elif isinstance(value, Sequence):
            items = value
        else:
            raise TypeError('chrome_ws_urls must be a URL string or iterable of URL strings')
        cleaned = tuple(str(item).strip() for item in items if str(item).strip())
        return cleaned

    def to_runtime_config(self) -> PageRuntimeConfig:
        """Project public policy into the executor-facing acquisition config."""
        return PageRuntimeConfig(**self.model_dump())


class PageRuntimeConfig(BaseModel):
    """Executor-facing page acquisition config."""

    model_config = ConfigDict(frozen=True)

    fetcher_type: FetcherPolicyName
    timeout_seconds: float
    max_fetch_retries: int
    allow_redirects: bool
    clean_html: bool
    cleaner_profile: CleanerProfileName
    chrome_ws_urls: tuple[str, ...]


__all__ = ['CleanerProfileName', 'FetcherPolicyName', 'PagePolicy', 'PageRuntimeConfig']
