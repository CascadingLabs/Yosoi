"""Cache mixin — cached selector replay and per-field staleness handling.

Contains: _try_cached, _evaluate_cached_verdicts, _extract_all_fresh,
_partial_rediscovery, _merge_and_save_snapshots, _verify_per_field,
_yield_cached_items, _track_cached_success.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from rich.console import Console

from yosoi.models.needs_discovery import NeedsDiscovery
from yosoi.models.selectors import SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, snapshot_to_selector_dict
from yosoi.utils import observability
from yosoi.utils.exceptions import BotDetectionError, LLMBlockedError

if TYPE_CHECKING:
    from typing import Protocol

    from yosoi.core.fetcher import HTMLFetcher
    from yosoi.models.contract import Contract

# Type aliases — defined at module level so they exist at runtime (used in cast() calls)
ContentMap = dict[str, object]
ContentItems = list[dict[str, object]]


if TYPE_CHECKING:

    class _PipelineCacheHost(Protocol):
        """Sibling-mixin surface used by the cache mixin."""

        cleaner: Any
        debug: Any
        discovery: Any

        def _mark_scrape_decision(
            self,
            *,
            selector_source: str,
            cache_decision: str,
            llm_used: bool,
            llm_reason: str | None = None,
        ) -> None: ...

        async def _fetch(self, url: str, fetcher: HTMLFetcher, max_retries: int = 2, **kwargs: Any) -> Any: ...

        async def _extract_with_cached(
            self,
            url: str,
            fetcher: HTMLFetcher,
            existing_selectors: dict[str, Any],
            skip_verification: bool,
        ) -> tuple[ContentItems | None, bool]: ...

        def _resolve_root(self, selectors: dict[str, Any]) -> dict[str, Any] | None: ...

        def _root_value(self, root_entry: dict[str, Any] | None) -> str | None: ...

        def _extract(
            self,
            url: str,
            html: str,
            verified_selectors: dict[str, Any],
            container_selector: str | None = None,
        ) -> ContentMap | ContentItems | None: ...

        async def _semantic_refine(
            self, *args: Any, **kwargs: Any
        ) -> tuple[ContentMap | ContentItems | None, dict[str, Any]]: ...

        def _validate_items(self, extracted: ContentMap | ContentItems, url: str) -> ContentItems: ...

        async def _record_fetch_strategy_selector_level(self, fetcher: HTMLFetcher, domain: str) -> None: ...

        def _print_tracking_stats(self, *args: Any, **kwargs: Any) -> None: ...


logger = logging.getLogger(__name__)


class PipelineCacheMixin:
    """Methods for replaying cached selectors and managing per-field staleness."""

    # Pipeline attributes referenced here
    console: Console
    contract: type[Contract]
    storage: Any
    verifier: Any
    selector_level: SelectorLevel
    tracker: Any
    _url_start: float
    last_elapsed: float
    _contract_sig: str
    _last_level_distribution: dict[str, int]
    _allow_llm: bool

    async def _try_cached(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        skip_verification: bool,
        format_to_use: list[str],
        *,
        max_discovery_retries: int = 3,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Attempt cached-selector path with per-field granularity."""
        host = cast('_PipelineCacheHost', self)
        snapshots = await self.storage.load_snapshots(domain, contract_sig=self._contract_sig)
        if not snapshots:
            host._mark_scrape_decision(
                selector_source='none',
                cache_decision='miss',
                llm_used=False,
                llm_reason='cache_miss',
            )
            return None

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        host._mark_scrape_decision(
            selector_source='cache',
            cache_decision='hit',
            llm_used=False,
            llm_reason=None,
        )
        if getattr(getattr(self, '_policy', None), 'atom_reads', False):
            self.console.print(
                '[dim]  ↳ Field atoms armed, but the verified selector cache hit wins; atoms try on cache miss.[/dim]'
            )
        logger.info('Using cached selectors domain=%s url=%s', domain, url)

        if skip_verification or self.contract.file_fields():
            existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
            items, cache_valid = await host._extract_with_cached(url, fetcher, existing, skip_verification)
            if not cache_valid:
                return None
            await self._record_cache_hit_metric(url, domain, set(existing))
            return self._yield_cached_items(
                items,
                url,
                domain,
                format_to_use,
                root_span=root_span,
                selectors_payload=existing,
                quality_snapshots=snapshots,
            )

        fetch_result = await self._fetch_and_clean_for_cache(url, fetcher)
        if fetch_result is None:
            existing_for_payload = {
                name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))
            }
            await self._record_cache_hit_metric(url, domain, set(existing_for_payload))
            return self._yield_cached_items(
                None,
                url,
                domain,
                format_to_use,
                root_span=root_span,
                selectors_payload=existing_for_payload,
                quality_snapshots=snapshots,
            )

        raw_html, cleaned_html = fetch_result
        return await self._evaluate_cached_verdicts(
            url,
            domain,
            fetcher,
            raw_html,
            cleaned_html,
            snapshots,
            format_to_use,
            max_discovery_retries,
            root_span=root_span,
        )

    async def _fetch_and_clean_for_cache(self, url: str, fetcher: HTMLFetcher) -> tuple[str, str] | None:
        """Fetch HTML for cache verification. Returns (raw_html, cleaned_html) or None."""
        host = cast('_PipelineCacheHost', self)
        with observability.span('fetch', url=url, mode='cache_verify'):
            try:
                result = await host._fetch(url, fetcher)
                if result is None or result.html is None:
                    self.console.print('[warning]⚠ Could not fetch HTML, skipping extraction[/warning]')
                    return None
            except BotDetectionError:
                raise
            except Exception as e:
                logger.exception('Fetch failed during cache verification for %s', url)
                self.console.print(f'[warning]⚠ Error: {e}, skipping extraction[/warning]')
                return None

        self.console.print('[step]Cleaning HTML...[/step]')
        with observability.span('clean', url=url, raw_chars=len(result.html), mode='cache_verify'):
            cleaned_html: str = host.cleaner.clean_html(result.html)

        if len(cleaned_html) < 1000:
            self.console.print(
                '[warning]⚠ Fetched HTML too short for verification — using cached selectors as-is[/warning]'
            )
            return None

        await host.debug.save_debug_html(url, cleaned_html)
        return result.html, cleaned_html

    async def _evaluate_cached_verdicts(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        raw_html: str,
        cleaned_html: str,
        snapshots: dict[str, SelectorSnapshot],
        format_to_use: list[str],
        max_discovery_retries: int = 3,
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Verify cached fields, branch on fresh/stale/partial."""
        host = cast('_PipelineCacheHost', self)
        with observability.span('verify', url=url, mode='per_field_cache', fields=len(snapshots)):
            verdicts = self._verify_per_field(cleaned_html, snapshots)

        for field_name, verdict in verdicts.items():
            await self.storage.record_verdict(domain, field_name, verdict, contract_sig=self._contract_sig)

        stale_fields = {f for f, v in verdicts.items() if v != CacheVerdict.FRESH}
        fresh_fields = {f for f, v in verdicts.items() if v == CacheVerdict.FRESH}

        # Frozen cached fields replay unchanged even when drift verification marks
        # them stale. They are caller-owned anchors, not discovery candidates.
        frozen_cached = self.contract.frozen_fields() & set(snapshots)
        stale_but_frozen = stale_fields & frozen_cached
        if stale_but_frozen:
            self.console.print(
                '[info]  ↳ Frozen fields with drift — replaying cached selectors: '
                f'{", ".join(sorted(stale_but_frozen))}[/info]'
            )
            stale_fields -= stale_but_frozen
            fresh_fields |= stale_but_frozen

        overridden = set(self.contract.get_selector_overrides())
        missing = (self.contract.discovery_field_names() - overridden) - set(snapshots)
        if missing:
            self.console.print(
                '[warning]⚠ Selector cache missing current contract field(s): '
                f'{", ".join(sorted(missing))} — discovering only those field(s)[/warning]'
            )
            stale_fields |= missing

        if not stale_fields:
            observability.annotate_cache(root_span, path=observability.CACHE_CACHED, fresh_fields=len(fresh_fields))
            return await self._extract_all_fresh(
                url, domain, fetcher, raw_html, snapshots, fresh_fields, format_to_use, root_span=root_span
            )

        if not fresh_fields:
            self.console.print(
                f'[warning]⚠ All {len(stale_fields)} cached selectors stale — forcing re-discovery[/warning]'
            )
            host._mark_scrape_decision(
                selector_source='none',
                cache_decision='stale',
                llm_used=False,
                llm_reason='stale_selector',
            )
            if not getattr(self, '_allow_llm', True):
                host._mark_scrape_decision(
                    selector_source='none',
                    cache_decision='llm_blocked',
                    llm_used=False,
                    llm_reason='stale_selector',
                )
                raise LLMBlockedError('stale_selector')
            return None

        observability.annotate_cache(
            root_span,
            path=observability.CACHE_PARTIAL,
            fresh_fields=len(fresh_fields),
            stale_fields=len(stale_fields),
        )
        llm_reason = 'missing_contract_fields' if missing & stale_fields else 'stale_selector'
        if not getattr(self, '_allow_llm', True):
            host._mark_scrape_decision(
                selector_source='cache',
                cache_decision='llm_blocked',
                llm_used=False,
                llm_reason=llm_reason,
            )
            raise LLMBlockedError(llm_reason)
        return await self._partial_rediscovery(
            url,
            domain,
            raw_html,
            cleaned_html,
            fetcher,
            snapshots,
            fresh_fields,
            stale_fields,
            format_to_use,
            max_discovery_retries,
            llm_reason=llm_reason,
            root_span=root_span,
        )

    async def _extract_all_fresh(
        self,
        url: str,
        domain: str,
        fetcher: HTMLFetcher,
        raw_html: str,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        format_to_use: list[str],
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap]:
        """All cached selectors verified — extract content via the pure replay artifact."""
        host = cast('_PipelineCacheHost', self)
        self.console.print(f'[success]✓ All {len(fresh_fields)} cached selectors verified[/success]')
        host._mark_scrape_decision(
            selector_source='cache',
            cache_decision='hit',
            llm_used=False,
            llm_reason=None,
        )
        existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
        await self._record_cache_hit_metric(url, domain, fresh_fields)
        root_entry = host._resolve_root(dict(existing))
        container_selector = host._root_value(root_entry)
        with observability.span('extract', url=url, mode='cache', container=container_selector or 'single'):
            items_list = self._resolve_cached_records(url, domain, raw_html, existing)
        if items_list:
            return self._yield_cached_items(
                items_list,
                url,
                domain,
                format_to_use,
                fetcher=fetcher,
                root_span=root_span,
                selectors_payload=existing,
                quality_snapshots=snapshots,
            )
        self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
        return self._yield_cached_items(
            None,
            url,
            domain,
            format_to_use,
            fetcher=fetcher,
            root_span=root_span,
            selectors_payload=existing,
            quality_snapshots=snapshots,
        )

    def _resolve_cached_records(
        self, url: str, domain: str, html: str, selectors: dict[str, Any]
    ) -> ContentItems | None:
        """Replay a loaded selector map through ``resolve()`` (CAS-119 SSoT)."""
        from yosoi.core.resolve import build_cache_from_selectors, resolve
        from yosoi.policy import Policy

        spec = self.contract.to_spec()
        result = resolve(
            spec,
            html,
            build_cache_from_selectors(domain, spec.fingerprint, selectors),
            domain,
            max_level=self.selector_level,
            url=url,
            policy=getattr(self, '_policy', Policy()),
        )
        if isinstance(result, NeedsDiscovery):
            return None
        return result

    async def _record_cache_hit_metric(self, url: str, domain: str, field_names: set[str]) -> None:
        """Record successful cached replay/use without affecting selector write counts."""
        try:
            from yosoi.storage.cache_metrics_libsql import LibSQLCacheMetricsStore

            async with LibSQLCacheMetricsStore() as metrics_store:
                await metrics_store.record_cache_hit(
                    url=url,
                    domain=domain,
                    contract_fingerprint=self._contract_sig,
                    field_names=field_names,
                )
        except Exception:  # noqa: BLE001
            logger.warning('Failed to record cache hit metric for %s', url, exc_info=True)

    async def _partial_rediscovery(
        self,
        url: str,
        domain: str,
        raw_html: str,
        cleaned_html: str,
        fetcher: HTMLFetcher,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        stale_fields: set[str],
        format_to_use: list[str],
        max_discovery_retries: int = 3,
        llm_reason: str = 'stale_selector',
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Rediscover only stale fields, merge with fresh cache, extract and yield."""
        host = cast('_PipelineCacheHost', self)
        host._mark_scrape_decision(
            selector_source='partial_repair',
            cache_decision='partial_repair',
            llm_used=True,
            llm_reason=llm_reason,
        )
        self.console.print(
            f'[info]  ↳ {len(fresh_fields)} fresh, {len(stale_fields)} stale '
            f'— partial rediscovery for: {", ".join(sorted(stale_fields))}[/info]'
        )

        new_selectors = await host.discovery.discover_selectors(cleaned_html, url, stale_fields=stale_fields)
        merged = await self._merge_and_save_snapshots(url, snapshots, fresh_fields, new_selectors, cleaned_html)

        root_entry = host._resolve_root(merged)
        container_selector = host._root_value(root_entry)
        extracted = host._extract(url, raw_html, merged, container_selector)

        if not extracted:
            self.console.print('[warning]⚠ Extraction failed after partial rediscovery[/warning]')
            return None

        with observability.span('semantic_refine', url=url, mode='cache_partial'):
            extracted, merged = await host._semantic_refine(
                url,
                cleaned_html,
                raw_html,
                merged,
                container_selector,
                extracted,
                max_discovery_retries,
            )

        if not extracted:
            self.console.print('[warning]⚠ Extraction failed after semantic refinement[/warning]')
            return None

        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        validated = host._validate_items(items_list, url)

        async def _yield_partial() -> AsyncIterator[ContentMap]:
            for v in validated:
                yield v
            save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
            self._set_quality(status='ok', issues=[], expected_record_count=len(validated))
            for fmt in format_to_use:
                await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            await host._record_fetch_strategy_selector_level(fetcher, domain)
            elapsed = time.monotonic() - self._url_start
            self.last_elapsed = elapsed
            stats = await self.tracker.record_url(
                url, used_llm=True, level_distribution=None, elapsed=elapsed, partial_discovery=True
            )
            host._print_tracking_stats(url, domain, stats, used_llm=True, elapsed=elapsed, partial_discovery=True)
            self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')
            observability.set_trace_output(
                root_span,
                {
                    'path': 'cache-partial',
                    'selectors': merged,
                    'extracted_count': len(validated),
                    'extracted_sample': validated[0] if validated else None,
                },
            )

        return _yield_partial()

    def _resolve_atom_records(self, url: str, domain: str, html: str) -> ContentItems | None:
        """Try policy-gated atom replay through ``resolve()`` on legacy-cache miss."""
        policy = getattr(self, '_policy', None)
        if policy is None or not policy.atom_reads or self.contract.file_fields():
            return None

        from yosoi.core.resolve import resolve

        result = resolve(
            self.contract.to_spec(),
            html,
            {},
            domain,
            max_level=self.selector_level,
            url=url,
            policy=policy,
        )
        if isinstance(result, NeedsDiscovery):
            return None
        return result

    def _yield_atom_cached_items(
        self,
        url: str,
        domain: str,
        html: str,
        format_to_use: list[str],
        *,
        fetcher: HTMLFetcher,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Return an atom-cache replay generator, or None when atoms cannot serve."""
        items = self._resolve_atom_records(url, domain, html)
        if items is None:
            return None

        self.console.print('[success]✓ Resolved from field-atom cache (no LLM)[/success]')
        host = cast('_PipelineCacheHost', self)

        async def _gen() -> AsyncIterator[ContentMap]:
            replay = self._yield_cached_items(
                items,
                url,
                domain,
                format_to_use,
                fetcher=fetcher,
                root_span=root_span,
                selectors_payload={},
            )
            async for item in replay:
                yield item
            host._mark_scrape_decision(
                selector_source='atom_cache',
                cache_decision='atom_hit',
                llm_used=False,
                llm_reason=None,
            )
            observability.set_trace_output(
                root_span,
                {
                    'path': 'atom-cache',
                    'selectors': {},
                    'extracted_count': len(items),
                    'extracted_sample': items[0] if items else None,
                },
            )

        return _gen()

    def _verify_per_field(self, html: str, snapshots: dict[str, SelectorSnapshot]) -> dict[str, CacheVerdict]:
        """Verify each cached field independently and apply root cascade."""
        from parsel import Selector as _PS

        sel = _PS(text=html)
        verdicts: dict[str, CacheVerdict] = {}
        field_levels: dict[str, str] = {}

        for field_name, snap in snapshots.items():
            if not snap.is_active:
                verdicts[field_name] = CacheVerdict.FRESH
                continue
            sel_dict = snapshot_to_selector_dict(snap)
            field_result = self.verifier._verify_field(sel, field_name, sel_dict, self.selector_level)
            verdicts[field_name] = CacheVerdict.FRESH if field_result.status == 'verified' else CacheVerdict.STALE
            if field_result.status == 'verified' and field_result.selector_level:
                field_levels[field_name] = field_result.selector_level

        if verdicts.get('root') == CacheVerdict.STALE:
            for name in verdicts:
                if name != 'root':
                    verdicts[name] = CacheVerdict.STALE

        level_distribution: dict[str, int] = {}
        for field_name, level in field_levels.items():
            if verdicts[field_name] == CacheVerdict.FRESH:
                level_distribution[level] = level_distribution.get(level, 0) + 1

        self._last_level_distribution = level_distribution
        return verdicts

    def _yield_cached_items(
        self,
        items: ContentItems | None,
        url: str,
        domain: str,
        format_to_use: list[str],
        *,
        fetcher: HTMLFetcher | None = None,
        root_span: Any | None = None,
        selectors_payload: dict[str, Any] | None = None,
        quality_snapshots: dict[str, SelectorSnapshot] | None = None,
    ) -> AsyncIterator[ContentMap]:
        """Wrap cached items into an async generator that tracks and saves."""
        host = cast('_PipelineCacheHost', self)

        async def _gen() -> AsyncIterator[ContentMap]:
            validated_for_output: ContentItems | None = None
            if items:
                validated = host._validate_items(items, url)
                validated_for_output = validated
                self._evaluate_replay_quality(validated, quality_snapshots)
                for v in validated:
                    yield v
                save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
                for fmt in format_to_use:
                    await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            else:
                self._evaluate_replay_quality(None, quality_snapshots)
            if fetcher is not None:
                await host._record_fetch_strategy_selector_level(fetcher, domain)
            await self._track_cached_success(url, domain)
            self.last_elapsed = time.monotonic() - self._url_start
            self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')
            observability.annotate_cache(root_span, path=observability.CACHE_CACHED)
            observability.set_trace_output(
                root_span,
                {
                    'path': 'cache-fresh',
                    'selectors': selectors_payload or {},
                    'extracted_count': len(validated_for_output) if validated_for_output else 0,
                    'extracted_sample': validated_for_output[0] if validated_for_output else None,
                },
            )

        return _gen()

    async def _merge_and_save_snapshots(
        self,
        url: str,
        snapshots: dict[str, SelectorSnapshot],
        fresh_fields: set[str],
        new_selectors: dict[str, Any] | None,
        cleaned_html: str,
    ) -> dict[str, Any]:
        """Merge fresh cached selectors with newly discovered, verify new ones, and save."""
        from yosoi.models.snapshot import selector_dict_to_snapshot as _to_snap

        merged: dict[str, Any] = {
            name: data
            for name, snap in snapshots.items()
            if name in fresh_fields and (data := snapshot_to_selector_dict(snap))
        }
        if new_selectors:
            merged.update(new_selectors)
            verification = self.verifier.verify(cleaned_html, new_selectors, max_level=self.selector_level)
            level_distribution = getattr(self, '_last_level_distribution', {}).copy()
            for level, count in verification.level_distribution.items():
                level_distribution[level] = level_distribution.get(level, 0) + count
            self._last_level_distribution = level_distribution
            for name, field_result in verification.results.items():
                if field_result.status != 'verified':
                    self.console.print(f'[warning]⚠ Rediscovered selector for {name} failed verification[/warning]')
                    merged.pop(name, None)

        now = datetime.now(timezone.utc)
        merged_snapshots: dict[str, SelectorSnapshot] = {}
        for name, sel_dict in merged.items():
            if name in fresh_fields and name in snapshots:
                merged_snapshots[name] = snapshots[name]
            else:
                merged_snapshots[name] = _to_snap(sel_dict, discovered_at=now, last_verified_at=now)
        await self.storage.save_snapshots(
            url, merged_snapshots, contract_sig=self._contract_sig, contract=self.contract
        )
        return merged

    async def _track_cached_success(self, url: str, domain: str) -> None:
        """Track successful use of cached selectors."""
        host = cast('_PipelineCacheHost', self)
        elapsed = time.monotonic() - self._url_start
        stats = await self.tracker.record_url(url, used_llm=False, level_distribution=None, elapsed=elapsed)
        host._print_tracking_stats(url, domain, stats, used_llm=False, elapsed=elapsed)
