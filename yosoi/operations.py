"""Canonical operation request/result models shared by Python and CLI.

These models are the stable, JSON-serializable edge for agent-driven use. Public
Python helpers and CLI commands should compile into these request values before
calling the runtime.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel
from yosoi.models.spec import ContractSpec
from yosoi.policy import Policy
from yosoi.utils.contracts import resolve_contract

ContractInput = str | type[Contract] | ContractSpec | dict[str, Any]


class ContractRef(BaseModel):
    """A JSON-safe reference to a contract.

    ``ref`` accepts the same durable doors the CLI accepts: registered name
    (usually ``@Name``), JSON file path, inline JSON object/string, or
    ``path:Class``. ``spec`` is preferred for request JSON because it is fully
    self-contained.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref: str | None = None
    spec: ContractSpec | None = None

    @field_validator('ref')
    @classmethod
    def _non_empty_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError('contract ref must be non-empty')
        return value

    def to_contract(self) -> type[Contract]:
        """Resolve this reference to an executable Contract subclass."""
        if self.spec is not None:
            return resolve_contract(self.spec)
        if self.ref is None:
            return NewsArticle
        raw = self.ref.strip()
        if raw.startswith('@'):
            raw = raw[1:]
        if raw.startswith('{'):
            return resolve_contract(json.loads(raw))
        path = Path(raw)
        if path.suffix.lower() == '.json' and path.exists():
            return resolve_contract(json.loads(path.read_text(encoding='utf-8')))
        return resolve_contract(raw)

    @classmethod
    def from_input(cls, value: ContractInput) -> ContractRef:
        """Build a JSON-safe reference from a public contract input."""
        if isinstance(value, ContractSpec):
            return cls(spec=value)
        if isinstance(value, dict):
            return cls(spec=ContractSpec.model_validate(value))
        if isinstance(value, str):
            return cls(ref=value)
        if isinstance(value, type) and issubclass(value, Contract):
            return cls(spec=value.to_spec())
        raise TypeError(f'Unsupported contract input: {value!r}')


class ScrapeRequest(BaseModel):
    """Canonical request for ``ys.scrape`` / ``yosoi scrape``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    urls: list[str]
    contracts: list[ContractRef] = Field(default_factory=lambda: [ContractRef.from_input(NewsArticle)])
    url_axis_many: bool = False
    contract_axis_many: bool = False
    model: str | None = None
    policy: Policy | None = None
    force: bool = False
    skip_verification: bool = False
    fetcher_type: str | Mapping[str, str] | Callable[[str], str] = 'auto'
    selector_level: str = 'all'
    save_formats: list[str] = Field(default_factory=list)
    quiet: bool = True
    identities: Mapping[str, BrowserIdentity] | Callable[[str], BrowserIdentity | None] | None = Field(
        default=None, exclude=True
    )
    allow_downloads: bool = False
    allowed_download_types: list[str] = Field(default_factory=list)
    download_dir: str | None = None
    max_download_bytes: int | None = None
    keep_downloads: bool = True
    max_concurrency: int | None = None

    @field_validator('urls')
    @classmethod
    def _urls_non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError('urls must contain at least one URL')
        return value

    @classmethod
    def from_axes(
        cls,
        urls: str | Sequence[str],
        contracts: ContractInput | Sequence[ContractInput] | None = None,
        **kwargs: Any,
    ) -> ScrapeRequest:
        """Build a request from the public scalar-or-list scrape axes."""
        url_axis_many = not isinstance(urls, str)
        url_list = [urls] if isinstance(urls, str) else list(urls)
        raw_contracts: Sequence[ContractInput]
        if contracts is None:
            contract_axis_many = False
            raw_contracts = [NewsArticle]
        elif isinstance(contracts, (str, ContractSpec, dict)) or (
            isinstance(contracts, type) and issubclass(contracts, Contract)
        ):
            contract_axis_many = False
            raw_contracts = [contracts]  # type: ignore[list-item]
        else:
            contract_axis_many = True
            raw_contracts = list(contracts)
        return cls(
            urls=url_list,
            contracts=[ContractRef.from_input(c) for c in raw_contracts],
            url_axis_many=url_axis_many,
            contract_axis_many=contract_axis_many,
            **kwargs,
        )

    def contract_classes(self) -> list[type[Contract]]:
        """Resolve all contract refs for execution."""
        return [ref.to_contract() for ref in self.contracts]


class ScrapeUnitResult(BaseModel):
    """Machine-readable result for one URL x contract unit."""

    url: str
    contract: str
    contract_fingerprint: str
    status: Literal['ok', 'error'] = 'ok'
    records: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class ScrapeResult(BaseModel):
    """Machine-readable scrape result envelope."""

    status: Literal['ok', 'partial', 'error'] = 'ok'
    results: list[ScrapeUnitResult] = Field(default_factory=list)


class CrawlRequest(BaseModel):
    """Canonical request for ``ys.crawl`` / ``yosoi crawl``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    seeds: list[str]
    contracts: list[ContractRef] = Field(default_factory=list)
    limit: int | None = None
    policy: Policy | None = None
    fetcher_type: str | None = None
    persist: bool = False
    progress: bool | None = None

    @field_validator('seeds')
    @classmethod
    def _seeds_non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError('seeds must contain at least one URL')
        return value

    @classmethod
    def from_axes(
        cls,
        seeds: str | Sequence[str],
        contracts: ContractInput | Sequence[ContractInput] | None = None,
        **kwargs: Any,
    ) -> CrawlRequest:
        """Build a request from the public scalar-or-list crawl seed axis."""
        seed_list = [seeds] if isinstance(seeds, str) else list(seeds)
        if contracts is None:
            refs: list[ContractRef] = []
        elif isinstance(contracts, (str, ContractSpec, dict)) or (
            isinstance(contracts, type) and issubclass(contracts, Contract)
        ):
            refs = [ContractRef.from_input(contracts)]  # type: ignore[arg-type]
        else:
            refs = [ContractRef.from_input(c) for c in contracts]
        return cls(seeds=seed_list, contracts=refs, **kwargs)

    def contract_classes(self) -> list[type[Contract]]:
        """Resolve all crawl target contract refs for execution."""
        return [ref.to_contract() for ref in self.contracts]


class CrawlResult(BaseModel):
    """Machine-readable crawl result envelope."""

    status: Literal['ok', 'error'] = 'ok'
    summary: dict[str, Any]


def _selector_level(value: str) -> SelectorLevel:
    if value.lower() == 'all':
        return max(SelectorLevel)
    try:
        return SelectorLevel[value.upper()]
    except KeyError:
        return SelectorLevel(value)


async def _execute_scrape_shape(request: ScrapeRequest) -> Any:
    """Execute the private scrape engine and return its axis-shaped intermediate."""
    from yosoi.api import _scrape_impl

    contract_classes = request.contract_classes()
    return await _scrape_impl(
        request.urls if request.url_axis_many else request.urls[0],
        contract_classes if request.contract_axis_many else contract_classes[0],
        model=request.model,
        force=request.force,
        skip_verification=request.skip_verification,
        fetcher_type=request.fetcher_type,
        selector_level=_selector_level(request.selector_level),
        save_formats=request.save_formats,
        quiet=request.quiet,
        allow_downloads=request.allow_downloads,
        allowed_download_types=request.allowed_download_types,
        download_dir=request.download_dir,
        max_download_bytes=request.max_download_bytes,
        keep_downloads=request.keep_downloads,
        identities=request.identities,
        max_concurrency=request.max_concurrency,
        policy=request.policy,
    )


def normalize_scrape_result(request: ScrapeRequest, raw: Any) -> ScrapeResult:
    """Normalize private scrape output into the canonical machine envelope."""
    contract_classes = request.contract_classes()
    units: list[ScrapeUnitResult] = []
    multi_url = request.url_axis_many
    multi_contract = request.contract_axis_many

    for url in request.urls:
        for contract_cls in contract_classes:
            name = contract_cls.__name__
            fp = contract_cls.to_spec().fingerprint
            records: Any
            if multi_url and multi_contract:
                records = raw[url][name]
            elif multi_url:
                records = raw[url]
            elif multi_contract:
                records = raw[name]
            else:
                records = raw
            units.append(
                ScrapeUnitResult(
                    url=url,
                    contract=name,
                    contract_fingerprint=fp,
                    records=[dict(item) for item in records],
                )
            )
    return ScrapeResult(results=units)


async def execute_scrape(request: ScrapeRequest) -> ScrapeResult:
    """Execute the canonical scrape request and return the canonical result."""
    return normalize_scrape_result(request, await _execute_scrape_shape(request))


async def execute_crawl(request: CrawlRequest) -> Any:
    """Execute the canonical crawl request and return ``CrawlRunSummary``."""
    from yosoi.core.crawler.run import _crawl_impl

    contracts = request.contract_classes()
    return await _crawl_impl(
        request.seeds if len(request.seeds) != 1 else request.seeds[0],
        contracts=contracts or None,
        limit=request.limit,
        policy=request.policy,
        fetcher_type=request.fetcher_type,
        persist=request.persist,
        progress=request.progress,
    )


async def run_crawl(request: CrawlRequest) -> CrawlResult:
    """Execute a crawl request and normalize summary for machine JSON."""
    from dataclasses import asdict

    summary = await execute_crawl(request)
    return CrawlResult(summary=asdict(summary))


async def run_scrape(request: ScrapeRequest) -> ScrapeResult:
    """Alias for executing a scrape request through the canonical surface."""
    return await execute_scrape(request)
