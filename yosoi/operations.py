"""Canonical operation request/result models shared by Python and CLI.

These models are the stable, JSON-serializable edge for agent-driven use. Public
Python helpers and CLI commands should compile into these request values before
calling the runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlparse, urlunparse

import lxml.html
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from rich.console import Console

from yosoi.core.cleaning.cleaner import HTMLCleaner
from yosoi.core.fetcher.identity import BrowserIdentity
from yosoi.core.site_map import MapRequest as MapRequest
from yosoi.core.site_map import MapResult as MapResult
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
QualityStatus = Literal['ok', 'partial', 'failed', 'unknown']
ContentFormat = Literal['json', 'markdown', 'text']
FetchView = Literal[
    'text',
    'markdown',
    'html',
    'clean_html',
    'raw_html',
    'rendered_html',
    'ax',
    'links',
    'metadata',
    'bundle',
]
FetchInclude = Literal['headers', 'endpoints', 'fingerprint', 'links', 'ax', 'contract_probe']


def _normalize_fetch_url(value: str) -> str:
    """Normalize fetch/content URL input, accepting browser-style schemeless URLs."""
    raw = value.strip()
    if not raw:
        raise ValueError('url must be non-empty')
    if any(char.isspace() for char in raw):
        raise ValueError('url must not contain whitespace')
    if raw.startswith('//'):
        raw = f'https:{raw}'
    elif '://' not in raw:
        raw = f'https://{raw}'
    parsed = urlparse(raw)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('url must be an absolute HTTP(S) URL')
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, '', parsed.query, parsed.fragment))


def _normalize_fetch_urls(value: object) -> object:
    if isinstance(value, str):
        return [_normalize_fetch_url(value)]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
        if not items:
            raise ValueError('urls must contain at least one URL')
        return [_normalize_fetch_url(str(item)) for item in items]
    return value


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
    experimental_a3node: bool = False

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
    quality_status: QualityStatus = 'unknown'
    quality_issues: list[str] = Field(default_factory=list)
    expected_record_count: int | None = None
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
    run_id: str | None = None
    compact: bool = False
    include_html: bool = False
    include_fingerprints: bool = False
    store_crawl: bool = False
    stress: bool = False
    failure_threshold: int = Field(default=0, ge=0)
    deadline_seconds: float | None = Field(default=None, gt=0)

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

    status: Literal['ok', 'partial', 'error'] = 'ok'
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


class ContractProbeResult(BaseModel):
    """Advisory fit signal for a contract against an acquired page."""

    contract: str
    contract_fingerprint: str
    required_fields: list[str] = Field(default_factory=list)
    cached_fields: list[str] = Field(default_factory=list)
    verified_fields: list[str] = Field(default_factory=list)
    fit_score: float = 0.0
    fit: Literal['strong', 'partial', 'stale', 'candidate', 'uncached', 'unknown'] = 'unknown'
    page_shape: str | None = None
    fingerprint_degenerate: bool | None = None
    atom_matches: int = 0
    notes: list[str] = Field(default_factory=list)


class FetchRequest(BaseModel):
    """Canonical request for contractless page acquisition and safe content preview."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    urls: list[str]
    view: FetchView = 'text'
    policy: Policy | None = None
    fetcher_type: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=12_000, ge=1)
    include: list[FetchInclude] = Field(default_factory=list)
    contracts: list[ContractRef] = Field(default_factory=list)
    output_dir: str | None = None
    experimental_a3node: bool = False
    max_concurrency: int = Field(default=5, ge=1)

    @field_validator('urls', mode='before')
    @classmethod
    def _urls_non_empty(cls, value: object) -> object:
        return _normalize_fetch_urls(value)

    @field_validator('view', mode='before')
    @classmethod
    def _normalise_view(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower().replace('-', '_')
        return value

    @field_validator('include', mode='before')
    @classmethod
    def _normalise_include(cls, value: object) -> object:
        if value is None or value == '':
            return []
        if isinstance(value, str):
            value = value.split(',')
        if isinstance(value, Sequence):
            items = [str(item).strip().lower().replace('-', '_') for item in value if str(item).strip()]
            return ['endpoints' if item == 'network' else item for item in items]
        return value

    @classmethod
    def from_axes(
        cls,
        urls: str | Sequence[str],
        contracts: ContractInput | Sequence[ContractInput] | None = None,
        **kwargs: Any,
    ) -> FetchRequest:
        """Build a fetch request from scalar-or-list URLs and optional contracts."""
        url_list = [urls] if isinstance(urls, str) else list(urls)
        if contracts is None:
            refs: list[ContractRef] = []
        elif isinstance(contracts, (str, ContractSpec, dict)) or (
            isinstance(contracts, type) and issubclass(contracts, Contract)
        ):
            refs = [ContractRef.from_input(contracts)]
        else:
            refs = [ContractRef.from_input(contract) for contract in contracts]
        return cls(urls=url_list, contracts=refs, **kwargs)

    def contract_classes(self) -> list[type[Contract]]:
        """Resolve all advisory contract refs for execution."""
        return [ref.to_contract() for ref in self.contracts]


class FetchUnitResult(BaseModel):
    """Acquired page content for one URL, bounded for safe LLM use by default."""

    url: str
    final_url: str | None = None
    status: Literal['ok', 'failed', 'blocked'] = 'ok'
    status_code: int | None = None
    title: str | None = None
    view: FetchView = 'text'
    content: str | None = None
    content_chars: int = 0
    total_chars: int = 0
    page: int = 1
    page_size: int = 12_000
    truncated: bool = False
    next_page: int | None = None
    markdown: str | None = None
    text: str | None = None
    html: str | None = None
    raw_html_chars: int = 0
    cleaned_html_chars: int = 0
    text_chars: int = 0
    fetch_time: float = 0.0
    fetcher_type: str = 'unknown'
    headers: dict[str, str] | None = None
    endpoints: list[str] | None = None
    links: list[dict[str, Any]] | None = None
    fingerprint: dict[str, Any] | None = None
    ax_snapshot: dict[str, Any] | None = None
    contract_probes: list[ContractProbeResult] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    interrupt: dict[str, Any] | None = None

    def _metadata_doc(self) -> dict[str, Any]:
        return {
            'source_url': self.url,
            'final_url': self.final_url or self.url,
            'title': self.title,
            'status_code': self.status_code,
            'fetcher_type': self.fetcher_type,
            'fetch_time': self.fetch_time,
            'view': self.view,
            'raw_html_chars': self.raw_html_chars,
            'cleaned_html_chars': self.cleaned_html_chars,
            'text_chars': self.text_chars,
            'content_chars': self.content_chars,
            'total_chars': self.total_chars,
            'page': self.page,
            'page_size': self.page_size,
            'truncated': self.truncated,
            'next_page': self.next_page,
            'content_hash': _content_hash(self.content or self.markdown or self.text or ''),
        }

    @computed_field
    def metadata(self) -> dict[str, Any]:
        """Document metadata for Firecrawl-like API consumers."""
        return self._metadata_doc()

    def _data_doc(self) -> dict[str, Any] | None:
        if self.status != 'ok':
            return None
        markdown = self.markdown or (self.content if self.view == 'markdown' else None)
        text = self.text or (self.content if self.view == 'text' else None)
        html = self.html or (self.content if self.view in {'html', 'clean_html', 'raw_html', 'rendered_html'} else None)
        payload: dict[str, Any] = {
            'content': self.content,
            'metadata': self._metadata_doc(),
        }
        if markdown is not None:
            payload['markdown'] = markdown
        if text is not None:
            payload['text'] = text
        if html is not None:
            payload['html'] = html
        if self.links:
            payload['links'] = self.links
        if self.headers is not None:
            payload['headers'] = self.headers
        if self.endpoints is not None:
            payload['endpoints'] = self.endpoints
        if self.fingerprint is not None:
            payload['fingerprint'] = self.fingerprint
        if self.ax_snapshot is not None:
            payload['ax_snapshot'] = self.ax_snapshot
        if self.contract_probes:
            payload['contract_probes'] = [probe.model_dump(mode='json') for probe in self.contract_probes]
        if self.artifacts:
            payload['artifacts'] = self.artifacts
        return payload

    @computed_field
    def data(self) -> dict[str, Any] | None:
        """Single document payload shaped for local LLM/RAG handoff."""
        return self._data_doc()


class FetchResult(BaseModel):
    """Machine-readable contractless page acquisition envelope."""

    status: Literal['ok', 'partial', 'error', 'blocked'] = 'ok'
    results: list[FetchUnitResult] = Field(default_factory=list)

    @computed_field
    def success(self) -> bool:
        """Whether every requested URL produced usable document content."""
        return self.status == 'ok'

    @computed_field
    def data(self) -> dict[str, Any] | None:
        """Convenience payload for the common one-URL case."""
        if len(self.results) != 1:
            return None
        return self.results[0]._data_doc()

    @computed_field
    def documents(self) -> list[dict[str, Any]]:
        """Successful document payloads for multi-URL callers."""
        return [data for unit in self.results if (data := unit._data_doc()) is not None]

    @computed_field
    def errors(self) -> list[dict[str, str]]:
        """Failed URL diagnostics in a compact, machine-friendly shape."""
        return [{'url': unit.url, 'error': unit.error or 'failed'} for unit in self.results if unit.status == 'failed']

    @computed_field
    def interrupts(self) -> list[dict[str, Any]]:
        """Blocked URL interrupts with resumable handoff metadata."""
        return [unit.interrupt for unit in self.results if unit.status == 'blocked' and unit.interrupt is not None]


class ContentRequest(BaseModel):
    """Canonical request for URL-to-document content extraction."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    urls: list[str]
    policy: Policy | None = None
    fetcher_type: str | None = None
    include_html: bool = False
    max_text_chars: int | None = Field(default=None, gt=0)

    @field_validator('urls', mode='before')
    @classmethod
    def _urls_non_empty(cls, value: object) -> object:
        return _normalize_fetch_urls(value)

    @classmethod
    def from_axes(cls, urls: str | Sequence[str], **kwargs: Any) -> ContentRequest:
        """Build a content request from a scalar URL or URL sequence."""
        url_list = [urls] if isinstance(urls, str) else list(urls)
        return cls(urls=url_list, **kwargs)


class ContentUnitResult(BaseModel):
    """Clean document content for one URL."""

    url: str
    status: Literal['ok', 'failed'] = 'ok'
    status_code: int | None = None
    title: str | None = None
    markdown: str | None = None
    text: str | None = None
    html: str | None = None
    raw_html_chars: int = 0
    cleaned_html_chars: int = 0
    text_chars: int = 0
    fetch_time: float = 0.0
    fetcher_type: str = 'unknown'
    links: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None

    def _metadata_doc(self) -> dict[str, Any]:
        return {
            'source_url': self.url,
            'title': self.title,
            'status_code': self.status_code,
            'fetcher_type': self.fetcher_type,
            'fetch_time': self.fetch_time,
            'raw_html_chars': self.raw_html_chars,
            'cleaned_html_chars': self.cleaned_html_chars,
            'text_chars': self.text_chars,
            'content_hash': _content_hash(self.markdown or self.text or ''),
        }

    @computed_field
    def metadata(self) -> dict[str, Any]:
        """Firecrawl-like metadata block for document API consumers."""
        return self._metadata_doc()

    def _data_doc(self) -> dict[str, Any] | None:
        if self.status != 'ok':
            return None
        payload: dict[str, Any] = {
            'markdown': self.markdown,
            'text': self.text,
            'metadata': self._metadata_doc(),
        }
        if self.links:
            payload['links'] = self.links
        if self.html is not None:
            payload['html'] = self.html
        return payload

    @computed_field
    def data(self) -> dict[str, Any] | None:
        """Single-document payload shaped for LLM/RAG handoff."""
        return self._data_doc()


class ContentResult(BaseModel):
    """Machine-readable URL-to-document content envelope."""

    status: Literal['ok', 'partial', 'error'] = 'ok'
    results: list[ContentUnitResult] = Field(default_factory=list)

    @computed_field
    def success(self) -> bool:
        """Whether every requested URL produced usable document content."""
        return self.status == 'ok'

    @computed_field
    def data(self) -> dict[str, Any] | None:
        """Convenience payload for the common one-URL case."""
        if len(self.results) != 1:
            return None
        return self.results[0]._data_doc()

    @computed_field
    def documents(self) -> list[dict[str, Any]]:
        """Successful document payloads for multi-URL callers."""
        return [data for unit in self.results if (data := unit._data_doc()) is not None]

    @computed_field
    def errors(self) -> list[dict[str, str]]:
        """Failed URL diagnostics in a compact, machine-friendly shape."""
        return [{'url': unit.url, 'error': unit.error or 'failed'} for unit in self.results if unit.status == 'failed']


def _selector_level(value: str) -> SelectorLevel:
    if value.lower() == 'all':
        return max(SelectorLevel)
    try:
        return SelectorLevel[value.upper()]
    except KeyError as exc:
        raise ValueError(f'{value!r} is not a valid SelectorLevel') from exc


def _quality_status(value: object) -> QualityStatus:
    return cast('QualityStatus', value if value in {'ok', 'partial', 'failed', 'unknown'} else 'unknown')


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
        experimental_a3node=request.experimental_a3node,
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
        quality_status=_quality_status(meta.get('quality_status')),
        quality_issues=[str(issue) for issue in (meta.get('quality_issues') or [])],
        expected_record_count=(
            int(meta['expected_record_count']) if meta.get('expected_record_count') is not None else None
        ),
        record_count=len(record_list),
        records=record_list,
    )


def _envelope(units: list[ScrapeUnitResult]) -> ScrapeResult:
    if not units:
        return ScrapeResult(status='error', results=[])
    failed = sum(1 for unit in units if unit.status == 'failed')
    degraded = any(unit.quality_status in {'partial', 'failed'} for unit in units if unit.status == 'ok')
    status: Literal['ok', 'partial', 'error'] = 'ok'
    if failed == len(units):
        status = 'error'
    elif failed or degraded:
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
                    experimental_a3node=request.experimental_a3node,
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
                    quality_status='failed',
                    quality_issues=[str(exc)],
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
                    quality_status='failed',
                    quality_issues=[str(exc)],
                    error=str(exc),
                )
            units.append(unit)
            await _persist_scrape_unit(unit)
    return _envelope(units)


async def execute_crawl(request: CrawlRequest) -> Any:
    """Execute the canonical crawl request and return ``CrawlRunSummary``."""
    from yosoi.core.crawler.run import _crawl_impl

    contracts = request.contract_classes()
    crawl_coro = _crawl_impl(
        request.seeds if len(request.seeds) != 1 else request.seeds[0],
        contracts=contracts or None,
        limit=request.limit,
        policy=request.policy,
        fetcher_type=request.fetcher_type,
        persist=request.persist,
        progress=request.progress,
    )
    if request.deadline_seconds is not None:
        return await asyncio.wait_for(crawl_coro, timeout=request.deadline_seconds)
    return await crawl_coro


async def execute_map(request: MapRequest) -> MapResult:
    """Execute the canonical map request and return sitemap inventory."""
    from yosoi.core.site_map import discover_site_map

    return await discover_site_map(request)


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


def _text_from_html(html: str) -> str:
    if not html.strip():
        return ''
    try:
        tree = lxml.html.fromstring(html)
        text = ' '.join(part.strip() for part in tree.itertext() if part.strip())
    except Exception:  # noqa: BLE001 - malformed HTML still deserves a best-effort text body
        text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'\s+([,.;:!?])', r'\1', text)


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16] if value else ''


def _title_from_html(html: str) -> str | None:
    if not html.strip():
        return None
    try:
        tree = lxml.html.fromstring(html)
    except Exception:  # noqa: BLE001
        return None
    for selector in ('//title/text()', '//h1/text()'):
        values = [value.strip() for value in tree.xpath(selector) if isinstance(value, str) and value.strip()]
        if values:
            return re.sub(r'\s+', ' ', values[0]).strip()
    return None


def _links_from_html(html: str, base_url: str) -> list[dict[str, str]]:
    if not html.strip():
        return []
    try:
        tree = lxml.html.fromstring(html)
    except Exception:  # noqa: BLE001
        return []
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in tree.xpath('//a[@href]'):
        href = anchor.get('href')
        if not isinstance(href, str) or not href.strip():
            continue
        text = _normalise_text(anchor.text_content())
        absolute_url = urljoin(base_url, href.strip())
        key = (text, absolute_url)
        if key in seen:
            continue
        seen.add(key)
        links.append({'text': text, 'url': absolute_url})
    return links


def _normalise_text(value: str) -> str:
    value = re.sub(r'\s+', ' ', value).strip()
    return re.sub(r'\s+([,.;:!?])', r'\1', value)


def _inline_markdown_text(element: Any, base_url: str) -> str:
    chunks: list[str] = []
    if element.text:
        chunks.append(element.text)
    for child in element:
        child_text = _inline_markdown_text(child, base_url)
        if isinstance(child.tag, str) and child.tag.lower() == 'a':
            href = child.get('href')
            if href and child_text:
                chunks.append(f'[{child_text}]({urljoin(base_url, str(href))})')
            else:
                chunks.append(child_text)
        else:
            chunks.append(child_text)
        if child.tail:
            chunks.append(child.tail)
    return _normalise_text(''.join(chunks))


def _markdown_blocks_from_html(html: str, text: str, base_url: str) -> str:
    try:
        tree = lxml.html.fromstring(html)
    except Exception:  # noqa: BLE001
        return text
    blocks: list[str] = []
    for element in tree.iter():
        block = _markdown_block_for_element(element, base_url)
        if block:
            blocks.append(block)
    return _markdown_body_or_text(blocks, text)


def _markdown_block_for_element(element: Any, base_url: str) -> str | None:
    if not isinstance(element.tag, str):
        return None
    tag = element.tag.lower()
    if tag != 'table' and any(
        isinstance(parent.tag, str) and parent.tag.lower() == 'table' for parent in element.iterancestors()
    ):
        return None
    value = _inline_markdown_text(element, base_url)
    if not value:
        return None
    heading_prefix = {'h1': '##', 'h2': '##', 'h3': '###', 'h4': '####', 'h5': '#####', 'h6': '######'}
    if tag in heading_prefix:
        return f'{heading_prefix[tag]} {value}'
    if tag == 'li':
        return f'- {value}'
    if tag == 'blockquote':
        return '\n'.join(f'> {line}' for line in value.splitlines())
    if tag == 'pre':
        return f'```\n{value}\n```'
    if tag == 'table':
        return _markdown_table_for_element(element)
    if tag == 'p':
        return value
    if _is_standalone_inline_leaf(element, tag):
        return f'- {value}'
    return None


def _markdown_table_for_element(element: Any) -> str | None:
    rows: list[list[str]] = []
    for row in element.xpath('.//tr'):
        cells = [
            _normalise_text(cell.text_content())
            for cell in row.xpath('./th | ./td')
            if _normalise_text(cell.text_content())
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return None
    width = max(len(row) for row in rows)
    padded = [row + [''] * (width - len(row)) for row in rows]
    lines = ['| ' + ' | '.join(padded[0]) + ' |', '| ' + ' | '.join(['---'] * width) + ' |']
    lines.extend('| ' + ' | '.join(row) + ' |' for row in padded[1:])
    return '\n'.join(lines)


def _is_standalone_inline_leaf(element: Any, tag: str) -> bool:
    inline_tags = {'a', 'b', 'button', 'em', 'span', 'strong'}
    if tag not in inline_tags:
        return False
    if any(isinstance(parent.tag, str) and parent.tag.lower() in inline_tags for parent in element.iterancestors()):
        return False
    if any(isinstance(child.tag, str) and child.tag.lower() not in inline_tags for child in element):
        return False
    if len(_normalise_text(element.text_content())) > 120:
        return False
    block_ancestors = {'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'p', 'pre', 'td', 'th', 'tr'}
    return not any(
        isinstance(parent.tag, str) and parent.tag.lower() in block_ancestors for parent in element.iterancestors()
    )


def _markdown_body_or_text(blocks: list[str], text: str) -> str:
    deduped: list[str] = []
    for block in blocks:
        if block not in deduped[-3:]:
            deduped.append(block)
    body = '\n\n'.join(deduped).strip()
    body_text = re.sub(r'[#>`|*\-\s]+', ' ', body).strip()
    if not body or len(body_text) < len(text) * 0.6:
        return text
    text_tokens = set(re.findall(r'[$\w][\w$+.-]*', text.lower()))
    body_tokens = set(re.findall(r'[$\w][\w$+.-]*', body_text.lower()))
    coverage = len(text_tokens & body_tokens) / len(text_tokens) if text_tokens else 1.0
    currency_tokens = {token for token in text_tokens if '$' in token or '€' in token or '£' in token}
    if coverage < 0.8 or not currency_tokens.issubset(body_tokens):
        return f'{body}\n\n## Extracted Text\n\n{text}'
    return body


def _markdown_document(*, url: str, title: str | None, text: str, html: str) -> str:
    heading = title or url
    lines = [f'# {heading}', '', f'Source: {url}', '']
    if text:
        lines.append(_markdown_blocks_from_html(html, text, url))
    return '\n'.join(lines).rstrip() + '\n'


def _content_envelope(units: list[ContentUnitResult]) -> ContentResult:
    if not units:
        return ContentResult(status='error', results=[])
    failed = sum(1 for unit in units if unit.status == 'failed')
    status: Literal['ok', 'partial', 'error'] = 'ok'
    if failed == len(units):
        status = 'error'
    elif failed:
        status = 'partial'
    return ContentResult(status=status, results=units)


def _content_fetcher_kwargs(policy: Policy, fetcher_type: str, *, fast_fetch: bool = False) -> dict[str, Any]:
    from yosoi.core.fetcher.profile_policy import cascade_from_profile_policy

    page = policy.page_runtime()
    kwargs: dict[str, Any] = {
        'timeout': int(page.timeout_seconds),
        'allow_redirects': page.allow_redirects,
    }
    if page.chrome_ws_urls:
        kwargs['chrome_ws_urls'] = page.chrome_ws_urls
    if fetcher_type in {'auto', 'waterfall', 'headless', 'headful'}:
        kwargs['console'] = Console(stderr=True, quiet=True)
        identity_cascade, max_live = cascade_from_profile_policy(page.profile)
        if identity_cascade is not None:
            kwargs['identity_cascade'] = identity_cascade
            kwargs['max_live_identities'] = max_live
        if fast_fetch:
            if fetcher_type in {'auto', 'waterfall'}:
                kwargs['simple_first'] = True
                kwargs['crawl_frontier_only'] = True
            else:
                kwargs['lightweight_fetch'] = True
    return kwargs


def _effective_fetcher_type(request: FetchRequest, policy_fetcher_type: str) -> str:
    if request.fetcher_type is not None:
        return request.fetcher_type
    include = set(request.include)
    if request.view == 'raw_html':
        return 'simple'
    if request.view in {'rendered_html', 'ax', 'bundle'} or {'ax', 'endpoints'} & include:
        return 'headless'
    return policy_fetcher_type


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return str(value)


def _paginate_content(content: str, *, page: int, page_size: int) -> tuple[str, bool, int | None]:
    start = (page - 1) * page_size
    end = start + page_size
    page_content = content[start:end]
    next_page = page + 1 if end < len(content) else None
    return page_content, next_page is not None, next_page


def _interrupt_from_bot_detection(exc: Any) -> dict[str, Any]:
    captcha_kind = getattr(exc, 'captcha_kind', None)
    interrupt: dict[str, Any] = {
        'source': 'yosoi.fetch.bot_detection',
        'kind': 'captcha' if captcha_kind else 'bot_wall',
        'subkind': captcha_kind,
        'blocking': True,
        'url': str(getattr(exc, 'url', '') or ''),
        'evidence': {
            'status_code': getattr(exc, 'status_code', None),
            'indicators': list(getattr(exc, 'indicators', []) or []),
            'identity_id': getattr(exc, 'identity_id', None),
        },
        'resume_hint': {'strategy': 'rerun_after_resolution'},
    }
    attach = getattr(exc, 'attach', None)
    if isinstance(attach, Mapping):
        interrupt['attach'] = _jsonable(attach)
    return interrupt


def _interrupt_from_fetch_result(fetched: Any, url: str, reason: str) -> dict[str, Any] | None:
    interrupt = getattr(fetched, 'interrupt', None)
    if isinstance(interrupt, Mapping):
        return cast('dict[str, Any]', _jsonable(interrupt))
    if getattr(fetched, 'is_blocked', False):
        generated: dict[str, Any] = {
            'source': 'yosoi.fetch',
            'kind': 'bot_wall',
            'subkind': None,
            'blocking': True,
            'url': str(getattr(fetched, 'url', url) or url),
            'evidence': {'reason': reason, 'status_code': getattr(fetched, 'status_code', None)},
            'resume_hint': {'strategy': 'rerun_after_resolution'},
        }
        attach = getattr(fetched, 'attach', None)
        if isinstance(attach, Mapping):
            generated['attach'] = _jsonable(attach)
        return generated
    return None


def _fetch_envelope(units: list[FetchUnitResult]) -> FetchResult:
    if not units:
        return FetchResult(status='error', results=[])
    failed = sum(1 for unit in units if unit.status == 'failed')
    blocked = sum(1 for unit in units if unit.status == 'blocked')
    status: Literal['ok', 'partial', 'error', 'blocked'] = 'ok'
    if blocked == len(units):
        status = 'blocked'
    elif failed == len(units):
        status = 'error'
    elif failed or blocked:
        status = 'partial'
    return FetchResult(status=status, results=units)


def _fetch_metadata_doc(
    *,
    url: str,
    final_url: str,
    status_code: int | None,
    title: str | None,
    fetcher_type: str,
    fetch_time: float,
    raw_html: str,
    cleaned_html: str,
    text: str,
    include: set[str],
    headers: dict[str, str] | None,
    endpoints: list[str] | None,
    links: list[dict[str, Any]],
    fingerprint: dict[str, Any] | None,
    ax_snapshot: dict[str, Any] | None,
    contract_probes: list[ContractProbeResult],
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        'url': url,
        'final_url': final_url,
        'status_code': status_code,
        'title': title,
        'fetcher_type': fetcher_type,
        'fetch_time': fetch_time,
        'raw_html_chars': len(raw_html),
        'cleaned_html_chars': len(cleaned_html),
        'text_chars': len(text),
        'content_hash': _content_hash(cleaned_html or raw_html),
    }
    if 'headers' in include:
        doc['headers'] = headers or {}
    if 'endpoints' in include:
        doc['endpoints'] = endpoints or []
    if 'links' in include:
        doc['links'] = links
    if 'fingerprint' in include and fingerprint is not None:
        doc['fingerprint'] = fingerprint
    if 'ax' in include and ax_snapshot is not None:
        doc['ax_snapshot'] = ax_snapshot
    if contract_probes:
        doc['contract_probes'] = [probe.model_dump(mode='json') for probe in contract_probes]
    return doc


def _view_content(
    request: FetchRequest,
    *,
    raw_html: str,
    cleaned_html: str,
    text: str,
    markdown: str,
    links: list[dict[str, Any]],
    metadata: dict[str, Any],
    ax_snapshot: dict[str, Any] | None,
) -> str:
    view = request.view
    if view == 'text':
        return text
    if view == 'markdown':
        return markdown
    if view in {'html', 'clean_html'}:
        return cleaned_html
    if view in {'raw_html', 'rendered_html'}:
        return raw_html
    if view == 'links':
        return json.dumps(links, ensure_ascii=False, indent=2)
    if view == 'metadata':
        return json.dumps(metadata, ensure_ascii=False, indent=2)
    if view == 'ax':
        return json.dumps(ax_snapshot or {}, ensure_ascii=False, indent=2)
    if view == 'bundle':
        return json.dumps(metadata, ensure_ascii=False, indent=2)
    return text


async def _fetch_static_html(url: str, policy: Policy) -> str | None:
    from yosoi.core.fetcher import create_fetcher

    fetcher = create_fetcher('simple', **_content_fetcher_kwargs(policy, 'simple'))
    try:
        if hasattr(fetcher, '__aenter__') and hasattr(fetcher, '__aexit__'):
            async with fetcher:
                result = await fetcher.fetch(url)
        else:
            result = await fetcher.fetch(url)
    except Exception:  # noqa: BLE001 - bundle static capture is best-effort
        return None
    finally:
        if hasattr(fetcher, 'close') and not hasattr(fetcher, '__aexit__'):
            await fetcher.close()
    return result.html if result.success and result.html else None


def _fetch_artifact_dir(base_dir: str, url: str, *, multiple: bool) -> Path:
    path = Path(base_dir)
    if multiple:
        parsed = urlparse(url)
        stem = (parsed.hostname or 'page').removeprefix('www.') + (parsed.path or '/').replace('/', '-')
        stem = re.sub(r'[^A-Za-z0-9_.-]+', '-', stem).strip('-') or 'page'
        digest = hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]
        path = path / f'{stem}-{digest}'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_fetch_bundle(
    request: FetchRequest,
    *,
    url: str,
    raw_html: str,
    static_html: str | None,
    cleaned_html: str,
    text: str,
    markdown: str,
    links: list[dict[str, Any]],
    metadata: dict[str, Any],
    headers: dict[str, str] | None,
    endpoints: list[str] | None,
    fingerprint: dict[str, Any] | None,
    ax_snapshot: dict[str, Any] | None,
) -> dict[str, str]:
    if not request.output_dir:
        return {}
    artifact_dir = _fetch_artifact_dir(request.output_dir, url, multiple=len(request.urls) > 1)
    files: dict[str, str] = {}

    def write(name: str, content: str) -> None:
        path = artifact_dir / name
        path.write_text(content, encoding='utf-8')
        files[name] = str(path)

    write('raw.html', static_html or raw_html)
    write('static.html', static_html or raw_html)
    if static_html is not None and static_html != raw_html:
        write('rendered.html', raw_html)
    write('clean.html', cleaned_html)
    write('text.txt', text)
    write('markdown.md', markdown)
    write('links.json', json.dumps(links, ensure_ascii=False, indent=2))
    write('headers.json', json.dumps(headers or {}, ensure_ascii=False, indent=2))
    write('network.json', json.dumps({'endpoints': endpoints or []}, ensure_ascii=False, indent=2))
    write('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    if fingerprint is not None:
        write('fingerprint.json', json.dumps(fingerprint, ensure_ascii=False, indent=2))
    if ax_snapshot is not None:
        write('ax.json', json.dumps(ax_snapshot, ensure_ascii=False, indent=2))
    return files


async def _contract_probes(
    request: FetchRequest,
    *,
    url: str,
    final_url: str,
    cleaned_html: str,
    page_shape: str | None,
    fingerprint_degenerate: bool | None,
) -> list[ContractProbeResult]:
    if not request.contracts:
        return []
    from yosoi.core.verification.verifier import SelectorVerifier
    from yosoi.models.snapshot import snapshot_to_selector_dict
    from yosoi.storage.atoms import AtomStore, default_store_path
    from yosoi.storage.persistence import SelectorStorage
    from yosoi.utils.urls import extract_domain

    domain = extract_domain(final_url or url)
    verifier = SelectorVerifier(console=Console(quiet=True))
    storage = SelectorStorage()
    atom_store = AtomStore(default_store_path())
    atoms = atom_store.all()
    probes: list[ContractProbeResult] = []
    for contract_cls in request.contract_classes():
        spec = contract_cls.to_spec()
        required = sorted(contract_cls.discovery_field_names())
        snapshots = await storage.load_snapshots(domain, contract_sig=spec.fingerprint)
        selectors = {
            name: data for name, snap in (snapshots or {}).items() if (data := snapshot_to_selector_dict(snap))
        }
        cached_fields = sorted(selectors)
        verified_fields: list[str] = []
        notes: list[str] = []
        if selectors:
            verification = verifier.verify(cleaned_html, selectors)
            verified_fields = sorted(
                name for name, result in verification.results.items() if result.status == 'verified'
            )
        else:
            notes.append('no cached selectors for this domain/contract')

        required_set = set(required)
        verified_required = required_set & set(verified_fields)
        fit_score = (len(verified_required) / len(required_set)) if required_set else 0.0
        atom_matches = sum(
            1
            for atom in atoms
            if page_shape is not None and atom.page_shape == page_shape and contract_cls.__name__ in atom.contracts
        )
        if not snapshots and atom_matches:
            fit: Literal['strong', 'partial', 'stale', 'candidate', 'uncached', 'unknown'] = 'candidate'
            notes.append('same-shape field atoms exist; run discover/scrape to verify before reuse')
        elif not snapshots:
            fit = 'uncached'
        elif fit_score >= 1.0:
            fit = 'strong'
        elif fit_score > 0.0:
            fit = 'partial'
        else:
            fit = 'stale'
        probes.append(
            ContractProbeResult(
                contract=contract_cls.__name__,
                contract_fingerprint=spec.fingerprint,
                required_fields=required,
                cached_fields=cached_fields,
                verified_fields=verified_fields,
                fit_score=round(fit_score, 6),
                fit=fit,
                page_shape=page_shape,
                fingerprint_degenerate=fingerprint_degenerate,
                atom_matches=atom_matches,
                notes=notes,
            )
        )
    return probes


async def _fetch_unit(request: FetchRequest, url: str) -> FetchUnitResult:
    from yosoi.core.fetcher import create_fetcher
    from yosoi.generalization.capture import observe_html
    from yosoi.generalization.fingerprint import PageFingerprint, page_shape_fp

    policy = request.policy or Policy()
    page = policy.page_runtime()
    fetcher_type = _effective_fetcher_type(request, page.fetcher_type)
    include = set(request.include)
    fast_fetch = request.view not in {'ax', 'bundle'} and 'ax' not in include
    fetcher_kwargs = _content_fetcher_kwargs(policy, fetcher_type, fast_fetch=fast_fetch)
    if request.experimental_a3node and fetcher_type in {'auto', 'waterfall', 'headless', 'headful'}:
        fetcher_kwargs['experimental_a3node'] = True
    fetcher = create_fetcher(fetcher_type, **fetcher_kwargs)
    try:
        if hasattr(fetcher, '__aenter__') and hasattr(fetcher, '__aexit__'):
            async with fetcher:
                fetched = await fetcher.fetch(url)
        else:
            fetched = await fetcher.fetch(url)
    finally:
        if hasattr(fetcher, 'close') and not hasattr(fetcher, '__aexit__'):
            await fetcher.close()

    if not fetched.success or not fetched.html:
        reason = fetched.block_reason or 'fetch failed'
        interrupt = _interrupt_from_fetch_result(fetched, url, reason)
        return FetchUnitResult(
            url=url,
            final_url=str(getattr(fetched, 'url', url)),
            status='blocked' if interrupt is not None else 'failed',
            status_code=fetched.status_code,
            raw_html_chars=len(fetched.html or ''),
            fetch_time=fetched.fetch_time,
            fetcher_type=fetcher_type,
            view=request.view,
            page=request.page,
            page_size=request.page_size,
            error=reason,
            interrupt=interrupt,
        )

    raw_html = fetched.html
    final_url = str(getattr(fetched, 'url', url))
    title = _title_from_html(raw_html)
    cleaned_html = HTMLCleaner(console=Console(quiet=True)).clean_html(raw_html)
    text = _text_from_html(cleaned_html)
    markdown = _markdown_document(url=final_url, title=title, text=text, html=cleaned_html)
    links = cast('list[dict[str, Any]]', _links_from_html(cleaned_html, final_url))
    if request.view == 'bundle':
        include.update({'headers', 'endpoints', 'links', 'fingerprint', 'ax'})
    ax_snapshot = _jsonable(getattr(fetched, 'ax_snapshot', None)) if 'ax' in include or request.view == 'ax' else None
    fingerprint: dict[str, Any] | None = None
    page_shape: str | None = None
    fingerprint_degenerate: bool | None = None
    try:
        fp_obj = PageFingerprint.of(
            raw_html,
            ax_snapshot=getattr(fetched, 'ax_snapshot', None),
            headers=getattr(fetched, 'headers', None),
            endpoints=getattr(fetched, 'endpoints', None),
        )
        fingerprint = cast('dict[str, Any]', _jsonable(fp_obj))
        observation = observe_html(final_url, raw_html, row_selector='')
        page_shape = page_shape_fp(observation)
        fingerprint_degenerate = bool(getattr(fp_obj, 'degenerate', False))
    except Exception:  # noqa: BLE001 - fingerprinting is advisory for fetch
        pass
    contract_probes = await _contract_probes(
        request,
        url=url,
        final_url=final_url,
        cleaned_html=cleaned_html,
        page_shape=page_shape,
        fingerprint_degenerate=fingerprint_degenerate,
    )
    if contract_probes:
        include.add('contract_probe')
    metadata = _fetch_metadata_doc(
        url=url,
        final_url=final_url,
        status_code=fetched.status_code,
        title=title,
        fetcher_type=fetcher_type,
        fetch_time=fetched.fetch_time,
        raw_html=raw_html,
        cleaned_html=cleaned_html,
        text=text,
        include=cast('set[str]', include),
        headers=getattr(fetched, 'headers', None),
        endpoints=getattr(fetched, 'endpoints', None),
        links=links,
        fingerprint=fingerprint,
        ax_snapshot=cast('dict[str, Any] | None', ax_snapshot),
        contract_probes=contract_probes,
    )
    content_full = _view_content(
        request,
        raw_html=raw_html,
        cleaned_html=cleaned_html,
        text=text,
        markdown=markdown,
        links=links,
        metadata=metadata,
        ax_snapshot=cast('dict[str, Any] | None', ax_snapshot),
    )
    content_page, truncated, next_page = _paginate_content(content_full, page=request.page, page_size=request.page_size)
    static_html = (
        await _fetch_static_html(url, policy) if request.view == 'bundle' and fetcher_type != 'simple' else None
    )
    artifacts = _write_fetch_bundle(
        request,
        url=url,
        raw_html=raw_html,
        static_html=static_html,
        cleaned_html=cleaned_html,
        text=text,
        markdown=markdown,
        links=links,
        metadata=metadata,
        headers=getattr(fetched, 'headers', None),
        endpoints=getattr(fetched, 'endpoints', None),
        fingerprint=fingerprint if 'fingerprint' in include or request.view == 'bundle' else None,
        ax_snapshot=cast('dict[str, Any] | None', ax_snapshot) if request.view == 'bundle' else None,
    )
    if artifacts:
        metadata['artifacts'] = artifacts
        if request.view == 'bundle':
            content_full = json.dumps(metadata, ensure_ascii=False, indent=2)
            content_page, truncated, next_page = _paginate_content(
                content_full, page=request.page, page_size=request.page_size
            )

    return FetchUnitResult(
        url=url,
        final_url=final_url,
        status_code=fetched.status_code,
        title=title,
        view=request.view,
        content=content_page,
        content_chars=len(content_page),
        total_chars=len(content_full),
        page=request.page,
        page_size=request.page_size,
        truncated=truncated,
        next_page=next_page,
        markdown=content_page if request.view == 'markdown' else None,
        text=content_page if request.view == 'text' else None,
        html=content_page if request.view in {'html', 'clean_html', 'raw_html', 'rendered_html'} else None,
        raw_html_chars=len(raw_html),
        cleaned_html_chars=len(cleaned_html),
        text_chars=len(text),
        fetch_time=fetched.fetch_time,
        fetcher_type=fetcher_type,
        headers=getattr(fetched, 'headers', None) if 'headers' in include else None,
        endpoints=getattr(fetched, 'endpoints', None) if 'endpoints' in include else None,
        links=links if 'links' in include or request.view == 'links' else None,
        fingerprint=fingerprint if 'fingerprint' in include else None,
        ax_snapshot=cast('dict[str, Any] | None', ax_snapshot),
        contract_probes=contract_probes,
        artifacts=artifacts,
    )


async def _fetch_content_unit(request: ContentRequest, url: str) -> ContentUnitResult:
    from yosoi.core.fetcher import create_fetcher

    policy = request.policy or Policy()
    page = policy.page_runtime()
    fetcher_type = request.fetcher_type or page.fetcher_type
    fetcher = create_fetcher(fetcher_type, **_content_fetcher_kwargs(policy, fetcher_type, fast_fetch=True))
    try:
        if hasattr(fetcher, '__aenter__') and hasattr(fetcher, '__aexit__'):
            async with fetcher:
                fetched = await fetcher.fetch(url)
        else:
            fetched = await fetcher.fetch(url)
    finally:
        if hasattr(fetcher, 'close') and not hasattr(fetcher, '__aexit__'):
            await fetcher.close()

    if not fetched.success or not fetched.html:
        reason = fetched.block_reason or 'fetch failed'
        return ContentUnitResult(
            url=url,
            status='failed',
            status_code=fetched.status_code,
            raw_html_chars=len(fetched.html or ''),
            fetch_time=fetched.fetch_time,
            fetcher_type=fetcher_type,
            error=reason,
        )

    raw_html = fetched.html
    title = _title_from_html(raw_html)
    cleaned_html = HTMLCleaner(console=Console(quiet=True)).clean_html(raw_html)
    text = _text_from_html(cleaned_html)
    if request.max_text_chars is not None:
        text = text[: request.max_text_chars].rstrip()
    markdown = _markdown_document(url=url, title=title, text=text, html=cleaned_html)
    links = _links_from_html(cleaned_html, url)
    return ContentUnitResult(
        url=url,
        status_code=fetched.status_code,
        title=title,
        markdown=markdown,
        text=text,
        html=cleaned_html if request.include_html else None,
        raw_html_chars=len(raw_html),
        cleaned_html_chars=len(cleaned_html),
        text_chars=len(text),
        fetch_time=fetched.fetch_time,
        fetcher_type=fetcher_type,
        links=links,
    )


async def execute_fetch(request: FetchRequest) -> FetchResult:
    """Fetch URLs concurrently in bounded batches, preserving request order."""
    from yosoi.utils.exceptions import BotDetectionError

    async def _unit(url: str) -> FetchUnitResult:
        try:
            return await _fetch_unit(request, url)
        except BotDetectionError as exc:
            return FetchUnitResult(
                url=url,
                final_url=getattr(exc, 'url', url),
                status='blocked',
                status_code=getattr(exc, 'status_code', None),
                view=request.view,
                page=request.page,
                page_size=request.page_size,
                error=str(exc),
                interrupt=_interrupt_from_bot_detection(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return FetchUnitResult(
                url=url,
                status='failed',
                view=request.view,
                page=request.page,
                page_size=request.page_size,
                error=str(exc),
            )

    units: list[FetchUnitResult] = []
    for start in range(0, len(request.urls), request.max_concurrency):
        units.extend(
            await asyncio.gather(*(_unit(url) for url in request.urls[start : start + request.max_concurrency]))
        )
    return _fetch_envelope(units)


async def execute_content(request: ContentRequest) -> ContentResult:
    """Fetch URLs and return LLM/RAG-friendly document content."""
    units: list[ContentUnitResult] = []
    for url in request.urls:
        try:
            unit = await _fetch_content_unit(request, url)
        except Exception as exc:  # noqa: BLE001
            unit = ContentUnitResult(url=url, status='failed', error=str(exc))
        units.append(unit)
    return _content_envelope(units)


async def execute_search(request: SearchRequest) -> SearchResult:
    """Execute the canonical search request and return normalized web hits."""
    from yosoi.core.fetcher.search import fetch_ddgs_text

    return normalize_search_result(request, await fetch_ddgs_text(request))


async def run_crawl(request: CrawlRequest) -> CrawlResult:
    """Execute a crawl request and normalize summary for machine JSON."""
    from yosoi.storage.crawl_runs import CrawlRunsStore, compact_crawl_summary, crawl_run_status

    summary = await execute_crawl(request)
    run_id = request.run_id
    if request.store_crawl:
        if run_id is None:
            raise ValueError('run_id is required when store_crawl=True')
        async with CrawlRunsStore() as store:
            await store.save_summary(
                run_id=run_id,
                summary=summary,
                seeds=request.seeds,
                failure_threshold=request.failure_threshold,
                stress=request.stress,
            )
    status = cast(
        Literal['ok', 'partial', 'error'], crawl_run_status(summary, failure_threshold=request.failure_threshold)
    )
    if request.compact:
        return CrawlResult(
            status=status,
            summary=compact_crawl_summary(
                summary,
                run_id=run_id,
                failure_threshold=request.failure_threshold,
                include_html=request.include_html,
                include_fingerprints=request.include_fingerprints,
            ),
        )
    return CrawlResult(status=status, summary=asdict(summary))


async def run_scrape(request: ScrapeRequest) -> ScrapeResult:
    """Alias for executing a scrape request through the canonical surface."""
    return await execute_scrape(request)


async def run_search(request: SearchRequest) -> SearchResult:
    """Alias for executing a search request through the canonical surface."""
    return await execute_search(request)


async def run_fetch(request: FetchRequest) -> FetchResult:
    """Alias for executing a fetch request through the canonical surface."""
    return await execute_fetch(request)


async def run_content(request: ContentRequest) -> ContentResult:
    """Alias for executing a content request through the canonical surface."""
    return await execute_content(request)


async def run_map(request: MapRequest) -> MapResult:
    """Alias for executing a map request through the canonical surface."""
    return await execute_map(request)
