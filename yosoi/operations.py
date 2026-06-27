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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.models.contract import Contract
from yosoi.models.defaults import NewsArticle
from yosoi.models.selectors import SelectorLevel
from yosoi.models.spec import ContractSpec
from yosoi.policy import Policy, SearchPolicy
from yosoi.utils.contracts import resolve_contract

ContractInput = str | type[Contract] | ContractSpec | dict[str, Any]
SearchKind = Literal['text']
SearchProvider = Literal['ddgs']
SafeSearch = Literal['on', 'moderate', 'off']


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
    allow_llm: bool = True

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
            raw_contracts = [contracts]
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
    status: Literal['ok', 'failed'] = 'ok'
    selector_source: str = 'unknown'
    cache_decision: str = 'unknown'
    llm_used: bool = False
    llm_reason: str | None = None
    record_count: int = 0
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
            refs = [ContractRef.from_input(contracts)]
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


class SearchRequest(BaseModel):
    """Canonical request for ``ys.search`` / ``yosoi search``."""

    query: str
    kind: SearchKind = 'text'
    provider: SearchProvider = 'ddgs'
    backend: str = 'google,bing,brave'
    region: str = 'us-en'
    safesearch: SafeSearch = 'moderate'
    max_results: int = Field(default=10, ge=1)
    page: int = Field(default=1, ge=1)
    timelimit: str | None = None

    @field_validator('query', 'backend', 'region')
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must be non-empty')
        return value.strip()

    @field_validator('timelimit')
    @classmethod
    def _timelimit_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError('timelimit must be non-empty')
        return value.strip() if value is not None else None

    @field_validator('max_results', 'page', mode='before')
    @classmethod
    def _reject_bool_ints(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError('boolean values are not valid search numeric settings')
        return value

    @classmethod
    def from_policy(
        cls,
        query: str,
        policy: Policy | None = None,
        *,
        kind: SearchKind | None = None,
        provider: SearchProvider | None = None,
        backend: str | None = None,
        region: str | None = None,
        safesearch: SafeSearch | None = None,
        max_results: int | None = None,
        page: int | None = None,
        timelimit: str | None = None,
    ) -> SearchRequest:
        """Build a search request from effective policy plus explicit call-site overrides."""
        search_policy = policy.search if policy is not None and policy.search is not None else SearchPolicy()
        payload = search_policy.model_dump()
        overrides: dict[str, object | None] = {
            'kind': kind,
            'provider': provider,
            'backend': backend,
            'region': region,
            'safesearch': safesearch,
            'max_results': max_results,
            'page': page,
            'timelimit': timelimit,
        }
        payload.update({key: value for key, value in overrides.items() if value is not None})
        return cls(query=query, **payload)


class SearchHit(BaseModel):
    """Normalized web search hit."""

    rank: int = Field(ge=1)
    title: str
    url: str
    snippet: str
    source: SearchProvider = 'ddgs'
    backend: str


class SearchResult(BaseModel):
    """Machine-readable search result envelope."""

    status: Literal['ok'] = 'ok'
    request: SearchRequest
    hits: list[SearchHit] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


def _selector_level(value: str) -> SelectorLevel:
    if value.lower() == 'all':
        return max(SelectorLevel)
    try:
        return SelectorLevel[value.upper()]
    except KeyError as exc:
        raise ValueError(f'{value!r} is not a valid SelectorLevel') from exc


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
        allow_llm=request.allow_llm,
    )


def _unit_from_records(
    *,
    url: str,
    contract: type[Contract],
    records: Any,
    metadata: Mapping[str, Any] | None = None,
) -> ScrapeUnitResult:
    """Build a successful scrape unit from records and pipeline metadata."""
    meta = dict(metadata or {})
    record_list = [dict(item) for item in records]
    return ScrapeUnitResult(
        url=url,
        contract=contract.__name__,
        contract_fingerprint=contract.to_spec().fingerprint,
        selector_source=str(meta.get('selector_source') or 'unknown'),
        cache_decision=str(meta.get('cache_decision') or 'unknown'),
        llm_used=bool(meta.get('llm_used', False)),
        llm_reason=meta.get('llm_reason') if meta.get('llm_reason') is not None else None,
        record_count=len(record_list),
        records=record_list,
    )


def _envelope(units: list[ScrapeUnitResult]) -> ScrapeResult:
    if not units:
        return ScrapeResult(status='error', results=[])
    failed = sum(1 for unit in units if unit.status == 'failed')
    status: Literal['ok', 'partial', 'error'] = 'ok'
    if failed == len(units):
        status = 'error'
    elif failed:
        status = 'partial'
    return ScrapeResult(status=status, results=units)


def normalize_scrape_result(
    request: ScrapeRequest, raw: Any, metadata: Mapping[tuple[str, str], Mapping[str, Any]] | None = None
) -> ScrapeResult:
    """Normalize private scrape output into the canonical machine envelope."""
    contract_classes = request.contract_classes()
    units: list[ScrapeUnitResult] = []
    multi_url = request.url_axis_many
    multi_contract = request.contract_axis_many

    for url in request.urls:
        for contract_cls in contract_classes:
            name = contract_cls.__name__
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
                _unit_from_records(
                    url=url,
                    contract=contract_cls,
                    records=records,
                    metadata=(metadata or {}).get((url, name)),
                )
            )
    return _envelope(units)


async def _persist_scrape_unit(unit: ScrapeUnitResult) -> None:
    """Best-effort persistence for top-level scrape health."""
    try:
        from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

        parsed = urlparse(unit.url)
        domain = (parsed.hostname or '').removeprefix('www.')
        async with LibSQLCacheMetricsStore() as metrics_store:
            await metrics_store.record_scrape_run(
                url=unit.url,
                domain=domain,
                contract_fingerprint=unit.contract_fingerprint,
                status=unit.status,
                selector_source=unit.selector_source,
                cache_decision=unit.cache_decision,
                llm_used=unit.llm_used,
                llm_reason=unit.llm_reason,
                record_count=unit.record_count,
                failure_reason=unit.error,
            )
    except Exception:  # noqa: BLE001 - metrics persistence is best-effort
        pass


async def execute_scrape(request: ScrapeRequest) -> ScrapeResult:
    """Execute the canonical scrape request and return the canonical result."""
    from yosoi.api import _scrape_impl
    from yosoi.utils.exceptions import LLMBlockedError

    units: list[ScrapeUnitResult] = []
    contract_classes = request.contract_classes()
    for url in request.urls:
        for contract_cls in contract_classes:
            metadata: dict[tuple[str, str], dict[str, Any]] = {}
            try:
                raw = await _scrape_impl(
                    url,
                    contract_cls,
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
                    allow_llm=request.allow_llm,
                    metadata_collect=metadata,
                )
                unit = _unit_from_records(
                    url=url,
                    contract=contract_cls,
                    records=raw,
                    metadata=metadata.get((url, contract_cls.__name__)),
                )
            except LLMBlockedError as exc:
                unit = ScrapeUnitResult(
                    url=url,
                    contract=contract_cls.__name__,
                    contract_fingerprint=contract_cls.to_spec().fingerprint,
                    status='failed',
                    selector_source='none',
                    cache_decision='llm_blocked',
                    llm_used=False,
                    llm_reason=exc.reason,
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                meta = metadata.get((url, contract_cls.__name__), {})
                unit = ScrapeUnitResult(
                    url=url,
                    contract=contract_cls.__name__,
                    contract_fingerprint=contract_cls.to_spec().fingerprint,
                    status='failed',
                    selector_source=str(meta.get('selector_source') or 'unknown'),
                    cache_decision=str(meta.get('cache_decision') or 'unknown'),
                    llm_used=bool(meta.get('llm_used', False)),
                    llm_reason=meta.get('llm_reason') if meta.get('llm_reason') is not None else None,
                    error=str(exc),
                )
            units.append(unit)
            await _persist_scrape_unit(unit)
    return _envelope(units)


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


def _require_text(value: Any, *, field: str, row_index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Malformed ddgs row {row_index}: {field} must be a non-empty string')
    return value.strip()


def _require_url(value: Any, *, row_index: int) -> str:
    url = _require_text(value, field='url', row_index=row_index)
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError(f'Malformed ddgs row {row_index}: url must be an absolute HTTP(S) URL')
    return url


def normalize_search_result(request: SearchRequest, rows: Sequence[Mapping[str, Any]]) -> SearchResult:
    """Normalize DDGS provider rows into the stable public search envelope."""
    hits: list[SearchHit] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f'Malformed ddgs row {index}: row must be an object')
        title = _require_text(row.get('title'), field='title', row_index=index)
        url = _require_url(row.get('href', row.get('url')), row_index=index)
        snippet = _require_text(row.get('body', row.get('snippet')), field='snippet', row_index=index)
        hits.append(
            SearchHit(
                rank=index,
                title=title,
                url=url,
                snippet=snippet,
                backend=request.backend,
            )
        )
    return SearchResult(request=request, hits=hits, urls=[hit.url for hit in hits])


async def execute_search(request: SearchRequest) -> SearchResult:
    """Execute the canonical search request and return normalized web hits."""
    from yosoi.core.fetcher.search import fetch_ddgs_text

    return normalize_search_result(request, await fetch_ddgs_text(request))


async def run_crawl(request: CrawlRequest) -> CrawlResult:
    """Execute a crawl request and normalize summary for machine JSON."""
    from dataclasses import asdict

    summary = await execute_crawl(request)
    return CrawlResult(summary=asdict(summary))


async def run_scrape(request: ScrapeRequest) -> ScrapeResult:
    """Alias for executing a scrape request through the canonical surface."""
    return await execute_scrape(request)


async def run_search(request: SearchRequest) -> SearchResult:
    """Alias for executing a search request through the canonical surface."""
    return await execute_search(request)
