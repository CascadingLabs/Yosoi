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
from typing import TYPE_CHECKING, Any

from rich.console import Console

from yosoi.models.selectors import SelectorLevel
from yosoi.models.snapshot import CacheVerdict, SelectorSnapshot, snapshot_to_selector_dict
from yosoi.utils import observability
from yosoi.utils.exceptions import BotDetectionError

if TYPE_CHECKING:
    from yosoi.core.fetcher import HTMLFetcher
    from yosoi.models.contract import Contract

# Type aliases — defined at module level so they exist at runtime (used in cast() calls)
ContentMap = dict[str, object]
ContentItems = list[dict[str, object]]

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
        snapshots = await self.storage.load_snapshots(domain, contract_sig=self._contract_sig)
        if not snapshots:
            return None

        self.console.print(f'[success]✓ Found cached selectors for {domain}[/success]')
        logger.info('Using cached selectors domain=%s url=%s', domain, url)

        if skip_verification or self.contract.file_fields():
            existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
            items, cache_valid = await self._extract_with_cached(url, fetcher, existing, skip_verification)  # type: ignore[attr-defined]
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
        with observability.span('fetch', url=url, mode='cache_verify'):
            try:
                result = await self._fetch(url, fetcher)  # type: ignore[attr-defined]
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
            cleaned_html: str = self.cleaner.clean_html(result.html)  # type: ignore[attr-defined]

        if len(cleaned_html) < 1000:
            self.console.print(
                '[warning]⚠ Fetched HTML too short for verification — using cached selectors as-is[/warning]'
            )
            return None

        await self.debug.save_debug_html(url, cleaned_html)  # type: ignore[attr-defined]
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
            return None

        observability.annotate_cache(
            root_span,
            path=observability.CACHE_PARTIAL,
            fresh_fields=len(fresh_fields),
            stale_fields=len(stale_fields),
        )
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
        """All cached selectors verified — extract content."""
        self.console.print(f'[success]✓ All {len(fresh_fields)} cached selectors verified[/success]')
        existing = {name: data for name, snap in snapshots.items() if (data := snapshot_to_selector_dict(snap))}
        await self._record_cache_hit_metric(url, domain, fresh_fields)
        root_entry = self._resolve_root(existing)  # type: ignore[attr-defined]
        container_selector = self._root_value(root_entry)  # type: ignore[attr-defined]
        with observability.span('extract', url=url, mode='cache', container=container_selector or 'single'):
            extracted = self._extract(url, raw_html, existing, container_selector)  # type: ignore[attr-defined]
        if extracted:
            items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
            return self._yield_cached_items(
                items_list,
                url,
                domain,
                format_to_use,
                fetcher=fetcher,
                root_span=root_span,
                selectors_payload=existing,
            )
        self.console.print('[warning]⚠ Extraction failed with cached selectors[/warning]')
        return self._yield_cached_items(
            None, url, domain, format_to_use, fetcher=fetcher, root_span=root_span, selectors_payload=existing
        )

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
        *,
        root_span: Any | None = None,
    ) -> AsyncIterator[ContentMap] | None:
        """Rediscover only stale fields, merge with fresh cache, extract and yield."""
        self.console.print(
            f'[info]  ↳ {len(fresh_fields)} fresh, {len(stale_fields)} stale '
            f'— partial rediscovery for: {", ".join(sorted(stale_fields))}[/info]'
        )

        new_selectors = await self.discovery.discover_selectors(cleaned_html, url, stale_fields=stale_fields)  # type: ignore[attr-defined]
        merged = await self._merge_and_save_snapshots(url, snapshots, fresh_fields, new_selectors, cleaned_html)

        root_entry = self._resolve_root(merged)  # type: ignore[attr-defined]
        container_selector = self._root_value(root_entry)  # type: ignore[attr-defined]
        extracted = self._extract(url, raw_html, merged, container_selector)  # type: ignore[attr-defined]

        if not extracted:
            self.console.print('[warning]⚠ Extraction failed after partial rediscovery[/warning]')
            return None

        with observability.span('semantic_refine', url=url, mode='cache_partial'):
            extracted, merged = await self._semantic_refine(  # type: ignore[attr-defined]
                url,
                cleaned_html,
                raw_html,
                merged,
                container_selector,
                extracted,
                max_discovery_retries,
            )

        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        validated = self._validate_items(items_list, url)  # type: ignore[attr-defined]

        async def _yield_partial() -> AsyncIterator[ContentMap]:
            for v in validated:
                yield v
            save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
            for fmt in format_to_use:
                await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            await self._record_fetch_strategy_selector_level(fetcher, domain)  # type: ignore[attr-defined]
            elapsed = time.monotonic() - self._url_start
            self.last_elapsed = elapsed
            stats = await self.tracker.record_url(
                url, used_llm=True, level_distribution=None, elapsed=elapsed, partial_discovery=True
            )
            self._print_tracking_stats(  # type: ignore[attr-defined]
                url, domain, stats, used_llm=True, elapsed=elapsed, partial_discovery=True
            )
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
    ) -> AsyncIterator[ContentMap]:
        """Wrap cached items into an async generator that tracks and saves."""

        async def _gen() -> AsyncIterator[ContentMap]:
            validated_for_output: ContentItems | None = None
            if items:
                validated = self._validate_items(items, url)  # type: ignore[attr-defined]
                validated_for_output = validated
                for v in validated:
                    yield v
                save_content: ContentMap | ContentItems = validated if len(validated) > 1 else validated[0]
                for fmt in format_to_use:
                    await self.storage.save_content(url, save_content, fmt, contract_sig=self._contract_sig)
            if fetcher is not None:
                await self._record_fetch_strategy_selector_level(fetcher, domain)  # type: ignore[attr-defined]
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
        elapsed = time.monotonic() - self._url_start
        stats = await self.tracker.record_url(url, used_llm=False, level_distribution=None, elapsed=elapsed)
        self._print_tracking_stats(url, domain, stats, used_llm=False, elapsed=elapsed)  # type: ignore[attr-defined]
