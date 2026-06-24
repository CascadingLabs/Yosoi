"""Stateless pipeline helpers — pure utility methods with no LLM or fetch side-effects.

Contains: URL normalization, domain extraction, fetcher factory, root selector
helpers, download spec resolution, contract validation, save/track, and display
methods.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx2
from rich.console import Console
from rich.table import Table

from yosoi.core.fetcher import HTMLFetcher
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability

if TYPE_CHECKING:
    from yosoi.models.contract import Contract
    from yosoi.models.download import DownloadResult, DownloadSpec
    from yosoi.storage.tracking import DomainStats

# Type aliases — defined at module level so they exist at runtime (used in cast() calls)
ContentMap = dict[str, object]
ContentItems = list[dict[str, object]]

logger = logging.getLogger(__name__)


class PipelineUtilsMixin:
    """Stateless utility methods used throughout the Pipeline."""

    # These attributes are declared by Pipeline.__init__ and referenced here:
    _allow_downloads: bool
    _allowed_download_types: tuple[str, ...]
    _download_dir: str | None
    _max_download_bytes: int | None
    _keep_downloads: bool
    _download_log: list[tuple[str, DownloadResult]]
    _experimental_a3node: bool
    _url_start: float
    last_elapsed: float
    contract: type[Contract]
    console: Console
    storage: Any
    tracker: Any
    output_formats: list[str]
    selector_level: SelectorLevel
    js_storage: Any
    _contract_sig: str
    _client: httpx2.AsyncClient

    async def normalize_url(self, url: str) -> str:
        """Add protocol to URL, preferring https."""
        if not url.startswith(('http://', 'https://')):
            try:
                test_url = 'https://' + url
                await self._client.head(test_url, timeout=3, follow_redirects=True)
                return test_url
            except httpx2.HTTPError:
                return 'http://' + url
        return url

    def _extract_domain(self, url: str) -> str:
        """Extract the (sub)domain from URL."""
        return observability.normalize_user_id(url) or ''

    @staticmethod
    def _pop_root(selectors: dict[str, Any]) -> dict[str, Any] | None:
        """Remove and return the full ``root`` selector entry from a selector map."""
        root_entry = selectors.pop('root', None)
        if isinstance(root_entry, dict):
            primary = root_entry.get('primary')
            if isinstance(primary, str) and primary:
                return root_entry
            if isinstance(primary, dict):
                value = primary.get('value')
                return root_entry if isinstance(value, str) and value else None
        return None

    @staticmethod
    def _root_value(root_entry: dict[str, Any] | None) -> str | None:
        """Extract the selector value string from a full root entry."""
        if root_entry is None:
            return None
        primary = root_entry.get('primary')
        if isinstance(primary, str) and primary:
            return primary
        if isinstance(primary, dict):
            value = primary.get('value')
            return value if isinstance(value, str) and value else None
        return None

    def _resolve_root(self, selectors: dict[str, Any]) -> dict[str, Any] | None:
        """Determine the root selector from contract override or AI discovery."""
        contract_root = self.contract.get_root()
        if contract_root:
            self._pop_root(selectors)
            return {'primary': contract_root.model_dump()}
        return self._pop_root(selectors)

    def _file_download_specs(self) -> dict[str, DownloadSpec]:
        """Build resolved DownloadSpec objects for ys.File() fields."""
        from yosoi.models.download import DownloadSpec, output_view_for_annotation

        global_allowed = set(self._allowed_download_types)
        specs: dict[str, DownloadSpec] = {}
        for name, cfg in self.contract.file_fields().items():
            field_allowed = tuple(cfg.get('allowed_types') or ())
            if field_allowed and global_allowed:
                effective = tuple(t for t in field_allowed if t in global_allowed)
            elif field_allowed:
                effective = field_allowed
            else:
                effective = tuple(self._allowed_download_types)
            annotation = self.contract.model_fields[name].annotation
            specs[name] = DownloadSpec(
                field=name,
                mode=cfg.get('mode', 'retrigger'),
                trigger=cfg.get('trigger'),
                href=cfg.get('href'),
                url=cfg.get('url'),
                allowed_types=effective,
                output=output_view_for_annotation(annotation),
                max_bytes=cfg.get('max_bytes') or self._max_download_bytes,
            )
        return specs

    def _resolve_download_specs(self, fetcher: HTMLFetcher | None = None) -> dict[str, DownloadSpec] | None:
        """Build download specs, failing fast if file fields can't actually download."""
        specs = self._file_download_specs()
        if specs and not self._allow_downloads:
            raise RuntimeError(
                f'{self.contract.__name__} declares ys.File() field(s) {sorted(specs)} but downloads '
                'are disabled. Pass allow_downloads=True and use a browser fetcher tier '
                "(fetcher_type='auto'/'headless'/'headful')."
            )
        if specs and fetcher is not None and not getattr(fetcher, 'supports_browse', False):
            raise RuntimeError(
                f'{self.contract.__name__} declares ys.File() field(s) {sorted(specs)} but '
                "fetcher_type has no browser tab. Use fetcher_type='auto'/'headless'/'headful'."
            )
        return specs or None

    def _validate_items(self, extracted: ContentMap | ContentItems, url: str) -> ContentItems:
        """Normalise extraction result to list and validate each item."""
        items_list: ContentItems = extracted if isinstance(extracted, list) else [extracted]
        dropped_counts: dict[str, int] = {}
        validated = [self._validate_single_item(item, url, dropped_counts=dropped_counts) for item in items_list]
        validated = self._dedupe_validated_items(validated)
        if dropped_counts:
            parts = [
                f'{field} ({count} item{"s" if count != 1 else ""})' for field, count in sorted(dropped_counts.items())
            ]
            self.console.print(
                '[warning]⚠ Contract validation defaulted invalid field(s): '
                f'{", ".join(parts)}. Check the selector or field type if this was unexpected.[/warning]'
            )
        return validated

    def _dedupe_validated_items(self, items: ContentItems) -> ContentItems:
        """Collapse duplicated framework-island rows after contract coercion."""
        if len(items) < 2:
            return items

        seen: set[tuple[tuple[str, str], ...]] = set()
        out: ContentItems = []
        dropped = 0
        for item in items:
            key = self._identity_key(item)
            if key and key in seen:
                dropped += 1
                continue
            if key:
                seen.add(key)
            out.append(item)

        if dropped:
            self.console.print(f'[info]  ↻ Dropped {dropped} duplicate item(s) after validation[/info]')
        return out

    @staticmethod
    def _identity_key(item: ContentMap) -> tuple[tuple[str, str], ...] | None:
        """Return a conservative identity key for repeated content rows."""
        name_field = next((field for field in ('name', 'title', 'headline', 'service_name') if item.get(field)), None)
        if not name_field:
            return None

        partner_field = next(
            (field for field in ('price', 'url', 'service_url', 'date', 'published_at', 'score') if item.get(field)),
            None,
        )
        if partner_field is None:
            return None

        return (
            (name_field, PipelineUtilsMixin._normalize_identity_value(item[name_field])),
            (partner_field, PipelineUtilsMixin._normalize_identity_value(item[partner_field])),
        )

    @staticmethod
    def _normalize_identity_value(value: object) -> str:
        return ' '.join(str(value).casefold().split())

    def _validate_single_item(
        self,
        item: ContentMap,
        url: str,
        *,
        dropped_counts: dict[str, int] | None = None,
    ) -> ContentMap:
        """Validate a single content dict through the Contract."""
        from pydantic import ValidationError

        try:
            return self.contract.model_validate(item, context={'source_url': url}).model_dump()
        except ValidationError as e:
            offending = {str(err['loc'][0]) for err in e.errors() if err.get('loc')} & set(item)
            if not offending:
                logger.warning('Contract validation failed (unisolable), using raw data: %s', e)
                return item
            data: dict[str, Any] = dict(item)
            for field_name in offending:
                data[field_name] = self.contract.field_default(field_name)
                if dropped_counts is not None:
                    dropped_counts[field_name] = dropped_counts.get(field_name, 0) + 1
            try:
                return self.contract.model_validate(data, context={'source_url': url}).model_dump()
            except ValidationError as e2:
                logger.warning('Validation still failing after dropping fields, using raw: %s', e2)
                return item
        except (ValueError, TypeError) as e:
            logger.warning('Contract validation failed, using raw data: %s', e)
            self.console.print(f'[warning]⚠ Validation skipped: {e}[/warning]')
            return item

    @staticmethod
    def _selectors_with_root(verified: dict[str, Any], root_entry: dict[str, Any] | None) -> dict[str, Any]:
        """Re-attach root selector for persistence, preserving the original type."""
        selectors_to_save = dict(verified)
        if root_entry:
            selectors_to_save['root'] = root_entry
        return selectors_to_save

    async def _finish(
        self,
        url: str,
        domain: str,
        selectors_to_save: dict[str, Any],
        content: ContentMap | ContentItems | None,
        used_llm: bool,
        format_to_use: list[str],
    ) -> None:
        """Set elapsed time, save, track, and print timing."""
        elapsed = time.monotonic() - self._url_start
        self.last_elapsed = elapsed
        await self._save_and_track(url, domain, selectors_to_save, content, used_llm, format_to_use, elapsed)
        self.console.print(f'[dim]  ⏱ {self.last_elapsed:.1f}s elapsed[/dim]')

    async def _save_and_track(
        self,
        url: str,
        domain: str,
        verified: dict[str, Any],
        extracted: ContentMap | ContentItems | None,
        used_llm: bool,
        output_format: list[str],
        elapsed: float | None = None,
    ) -> None:
        """Save verified selectors, extracted content, and track LLM usage."""
        await self.storage.save_selectors(url, verified, verified=True, contract_sig=self._contract_sig)

        if extracted:
            for fmt in output_format:
                await self.storage.save_content(url, extracted, fmt, contract_sig=self._contract_sig)

        level_dist = getattr(self, '_last_level_distribution', None)
        stats = await self.tracker.record_url(
            url, used_llm=used_llm, level_distribution=level_dist or None, elapsed=elapsed
        )
        self._print_tracking_stats(domain, stats)

    def _print_tracking_stats(self, domain: str, stats: DomainStats) -> None:
        """Print LLM tracking statistics for domain."""
        self.console.print(f'\n[dim]  - Tracking Stats for {domain}:[/dim]')
        self.console.print(f'[dim]    -- LLM Calls: {stats.llm_calls}[/dim]')
        self.console.print(f'[dim]    -- URLs Processed: {stats.url_count}[/dim]')
        if stats.total_elapsed:
            self.console.print(f'[dim]    -- Total Elapsed: {stats.total_elapsed:.1f}s[/dim]')
        if stats.llm_calls > 0:
            efficiency = stats.url_count / stats.llm_calls
            self.console.print(f'[dim]     • Efficiency: {efficiency:.1f} URLs per LLM call[/dim]')
        self.console.print()

    def _print_summary(self, results: dict[str, list[str]], total_elapsed: float) -> None:
        """Print a standardised summary of processing results."""
        self.console.print(
            f'\n[bold]Results:[/bold] [green]{len(results["successful"])} succeeded[/green], '
            f'[red]{len(results["failed"])} failed[/red] '
            f'[dim]({total_elapsed:.1f}s total)[/dim]'
        )
        if results.get('skipped'):
            self.console.print(f'  [dim]{len(results["skipped"])} skipped[/dim]')
        if results['failed']:
            self.console.print('[bold red]Failed URLs:[/bold red]')
            for url in results['failed']:
                self.console.print(f'  [red]- {url}[/red]')

    async def show_summary(self) -> None:
        """Show summary of all saved selectors."""
        domains = await self.storage.list_domains()

        if not domains:
            self.console.print('[warning]No selectors found in storage[/warning]')
            return

        table = Table(title='Saved Selectors Summary')
        table.add_column('Domain', style='cyan')
        table.add_column('Fields', style='green')

        for domain in domains:
            selectors = await self.storage.load_selectors(domain)
            if selectors:
                table.add_row(domain, str(len(selectors)))

        self.console.print(table)
        self.console.print(f'\n[success]Total domains: {len(domains)}[/success]')

    async def show_llm_stats(self) -> None:
        """Show LLM usage statistics."""
        stats = await self.tracker.get_all_stats()

        total_llm_calls = sum(domain_stats.llm_calls for domain_stats in stats.values())
        total_urls = sum(domain_stats.url_count for domain_stats in stats.values())

        self.console.print('\n[bold cyan]═══ LLM Usage Statistics ═══[/bold cyan]')
        self.console.print(f'[info]Total URLs processed: {total_urls}[/info]')
        self.console.print(f'[info]LLM calls made: {total_llm_calls}[/info]')

        if total_llm_calls > 0:
            efficiency = total_urls / total_llm_calls
            self.console.print(f'[success]Efficiency: {efficiency:.1f} URLs per LLM call[/success]')

        self.console.print()

    def _validate_with_contract(self, extracted: ContentMap | ContentItems, url: str = '') -> ContentMap | ContentItems:
        """Instantiate Contract with extracted data to run validators and type coercion.

        Args:
            extracted: Raw extracted data (single dict or list of dicts).
            url: Source URL injected into validation context for relative URL resolution.

        Returns:
            Validated and transformed data, or the original if validation fails.

        """
        if isinstance(extracted, list):
            validated_items: ContentItems = [self._validate_single_item(item, url) for item in extracted]
            self.console.print(f'[success]✓ Contract validation applied to {len(validated_items)} items[/success]')
            return validated_items

        validated = self._validate_single_item(extracted, url)
        if validated is not extracted:
            self.console.print('[success]✓ Contract validation applied[/success]')
        return validated
