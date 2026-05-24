"""Fan-out discovery orchestrator: one LLM call per field, results merged at the end."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.field_agent import FieldDiscoveryAgent
from yosoi.core.discovery.field_task import FieldTaskResult, run_field_task
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.storage.persistence import SelectorStorage
from yosoi.utils import observability as obs
from yosoi.utils.signatures import _get_yosoi_type

# Selector dict: field name → {primary, fallback, tertiary} selectors
SelectorMap = dict[str, dict[str, Any]]

logger = logging.getLogger(__name__)


class DiscoveryOrchestrator:
    """Orchestrates per-field fan-out selector discovery.

    For each contract field, runs an independent :func:`run_field_task` that
    checks the cache, calls the LLM (with retries), and inline-verifies the
    result.  All field tasks run concurrently via ``asyncio.gather``.  A single
    ``save_selectors`` write is performed at the end to avoid read-modify-write
    races.

    The public API — ``discover_selectors(html, url) -> SelectorMap | None`` —
    is intentionally identical to :class:`~yosoi.core.discovery.agent.SelectorDiscovery`
    so that ``Pipeline`` can swap the two transparently.

    Attributes:
        model_name: LLM model name
        provider: LLM provider name
        console: Rich console for output

    """

    def __init__(
        self,
        contract: type[Contract],
        llm_config: LLMConfig,
        storage: SelectorStorage,
        console: Console | None = None,
        target_level: SelectorLevel = SelectorLevel.CSS,
        max_concurrent: int = 5,
        bus: DiscoveryBus | None = None,
        write_lock: asyncio.Lock | None = None,
    ):
        """Initialise the orchestrator.

        Args:
            contract: Contract subclass defining fields to discover
            llm_config: LLM provider and model configuration
            storage: Selector storage (used for cache reads and the final write)
            console: Optional Rich console for output
            target_level: Maximum selector strategy level. Defaults to CSS.
            max_concurrent: Maximum concurrent LLM calls. Defaults to 5.
            bus: Optional shared discovery bus for cross-pipeline field sharing.
            write_lock: Optional asyncio.Lock to serialize selector writes for the domain.

        """
        self._contract = contract
        self._storage = storage
        self._target_level = target_level
        self._max_concurrent = max_concurrent
        self._agent = FieldDiscoveryAgent(llm_config, console=console)
        self._bus = bus
        self._write_lock = write_lock
        self.console = console or Console()
        self.model_name = llm_config.model_name
        self.provider = llm_config.provider

    @property
    def target_level(self) -> SelectorLevel:
        """Maximum selector strategy level used for discovery."""
        return self._target_level

    @target_level.setter
    def target_level(self, value: SelectorLevel) -> None:
        self._target_level = value

    @property
    def max_concurrent(self) -> int:
        """Cap on per-field LLM calls fanned out concurrently inside one URL.

        Backed by ``asyncio.Semaphore(max_concurrent)`` around the per-field
        ``asyncio.gather``. Default 5; configurable via
        :class:`yosoi.core.configs.DiscoveryConfig`.
        """
        return self._max_concurrent

    async def discover_selectors(
        self,
        html: str,
        url: str | None = None,
        *,
        stale_fields: set[str] | None = None,
        force: bool = False,
    ) -> SelectorMap | None:
        """Discover selectors for all contract fields in parallel.

        Args:
            html: Cleaned HTML to analyze
            url: Optional URL for cache domain lookup and saving
            stale_fields: When not None, only discover these fields (partial
                rediscovery). The caller is responsible for merging fresh cached
                selectors with the newly discovered ones and saving.
            force: Force re-discovery even if selectors exist. Defaults to False.

        Returns:
            SelectorMap with discovered selectors, or None if all fields failed.

        """
        url_context = url or 'the provided page'
        # Use the same normalisation the Pipeline / enqueue path uses so the
        # cache lookup, tracing user_id, and per-domain locking all share one
        # bucket (no port/userinfo/casing splits).
        domain = (obs.normalize_user_id(url) if url else None) or 'unknown'
        discovery_input = DiscoveryInput(url=url_context, html=html)

        field_descs = self._contract.field_descriptions()
        hints = self._collect_hints()
        overrides = self._contract.get_selector_overrides()

        # Build specs first so the bypass check sees root/nested container
        # tasks: a contract that overrides every content field can still depend
        # on a discovered root or container selector.
        task_specs = self._build_task_specs(field_descs, hints, stale_fields)
        field_count = len(task_specs)

        # Only skip AI when there is genuinely nothing left to discover
        # (every content field overridden AND no root/nested container task).
        if not task_specs:
            logger.info('Skipping AI discovery — nothing left to discover (url=%s)', url_context)
            with obs.span(
                'orchestrator_discover_selectors',
                url=url_context,
                field_count=0,
                max_concurrent=0,
                bypass='all_overrides',
            ):
                pass
            return {k: dict(v) for k, v in overrides.items()} if overrides else None

        with obs.span(
            'orchestrator_discover_selectors',
            url=url_context,
            field_count=field_count,
            max_concurrent=self._max_concurrent,
        ):
            return await self._discover_selectors_impl(
                html=html,
                url=url,
                url_context=url_context,
                domain=domain,
                discovery_input=discovery_input,
                hints=hints,
                overrides=overrides,
                stale_fields=stale_fields,
                force=force,
            )

    async def _discover_selectors_impl(
        self,
        *,
        html: str,
        url: str | None,
        url_context: str,
        domain: str,
        discovery_input: DiscoveryInput,
        hints: dict[str, str | None],
        overrides: dict[str, dict[str, Any]],
        stale_fields: set[str] | None,
        force: bool = False,
    ) -> SelectorMap | None:
        field_descs = self._contract.field_descriptions()

        semaphore = asyncio.Semaphore(self._max_concurrent)

        # Load the full domain selector map once — avoids N redundant file reads
        existing = self._storage.load_selectors(domain) or {}

        task_specs = self._build_task_specs(field_descs, hints, stale_fields)

        # Obtain a domain-scoped bus view shared by all field tasks in this batch
        scoped_bus = self._bus.scoped(domain) if self._bus is not None else None

        # Fan-out: run all field tasks concurrently
        coroutines = [
            run_field_task(
                field_name=str(spec['field_name']),
                field_description=str(spec['field_description']),
                field_hint=spec['field_hint'] if spec['field_hint'] is None else str(spec['field_hint']),
                discovery_input=discovery_input,
                html=html,
                agent=self._agent,
                cached_entry=None if force else existing.get(str(spec['field_name'])),
                max_level=self._target_level,
                is_container=bool(spec['is_container']),
                semaphore=semaphore,
                scoped_bus=scoped_bus,
                yosoi_type=_get_yosoi_type(self._contract, str(spec['field_name'])),
            )
            for spec in task_specs
        ]

        raw_results: list[FieldTaskResult | BaseException] = await asyncio.gather(*coroutines, return_exceptions=True)

        merged, cached_count, escalated_count = self._merge_results(raw_results, overrides, task_specs)

        # Persist contract-pinned root so the cache is self-contained
        contract_root = self._contract.get_root()
        if contract_root:
            merged['root'] = {'primary': contract_root.model_dump(exclude_none=True)}

        # Check if all non-root fields failed
        non_container = {k: v for k, v in merged.items() if k != 'root'}
        if not non_container:
            obs.warning('All field tasks returned None', url=url_context)
            return None

        logger.info(
            'Orchestrator discovery complete url=%s total=%d cached=%d escalated=%d',
            url_context,
            len(merged),
            cached_count,
            escalated_count,
        )
        self.console.print(
            f'[success]Discovered selectors for {len(non_container)} fields (cached={cached_count})[/success]'
        )

        # Single write — avoids read-modify-write races across concurrent tasks
        # Skip save for partial rediscovery (pipeline handles merge + save)
        if url and stale_fields is None:
            if self._write_lock is not None:
                async with self._write_lock:
                    self._storage.save_selectors(url, merged)
            else:
                self._storage.save_selectors(url, merged)

        return merged

    def _merge_results(
        self,
        raw_results: list[FieldTaskResult | BaseException],
        overrides: dict[str, dict[str, Any]],
        task_specs: list[dict[str, object]],
    ) -> tuple[SelectorMap, int, int]:
        """Merge field task results into a selector map.

        Combines successful field discoveries, logs unexpected exceptions,
        applies manual overrides, and writes NA sentinels for fields that
        failed so they are not re-attempted on future runs.

        Args:
            raw_results: Raw asyncio.gather output — mix of FieldTaskResult and exceptions.
            overrides: Manual selector overrides from the contract (always take precedence).
            task_specs: The task specs used to build the coroutines, used to determine
                which fields were attempted so NA sentinels can be written for failures.

        Returns:
            Tuple of (merged selector map, cached field count, escalated field count).

        """
        merged: SelectorMap = {}
        cached_count = 0
        escalated_count = 0

        for raw in raw_results:
            if isinstance(raw, BaseException):
                logger.warning('Field task raised unexpectedly: %s', raw)
                continue
            result: FieldTaskResult = raw
            if result.selectors is not None:
                merged[result.field_name] = result.selectors.model_dump(exclude_none=True)
                if result.from_cache:
                    cached_count += 1
                if result.escalated_to is not None:
                    escalated_count += 1

        # Overrides always take precedence
        for field_name, override_dict in overrides.items():
            merged[field_name] = override_dict

        # Write NA sentinels to storage for fields that were attempted but failed entirely.
        # This prevents repeated LLM calls for fields that don't exist on this domain.
        # Note: sentinels are NOT included in the returned merged map — callers see only
        # fields that were actually discovered.
        all_attempted = {str(spec['field_name']) for spec in task_specs}
        self._na_sentinels = {field_name for field_name in all_attempted if field_name not in merged}

        return merged, cached_count, escalated_count

    def _build_task_specs(
        self,
        field_descs: dict[str, str],
        hints: dict[str, str | None],
        stale_fields: set[str] | None,
    ) -> list[dict[str, object]]:
        """Build the list of field task specs, optionally filtered to stale fields only."""
        specs: list[dict[str, object]] = [
            {
                'field_name': name,
                'field_description': desc,
                'field_hint': hints.get(name),
                'is_container': False,
            }
            for name, desc in field_descs.items()
        ]
        if not self._contract.get_root():
            specs.append(
                {
                    'field_name': 'root',
                    'field_description': (
                        'Selector for the repeating wrapper element that contains one complete item '
                        '(e.g., .product-card, article.listing). '
                        'Set to null for single-item pages.'
                    ),
                    'field_hint': None,
                    'is_container': True,
                }
            )
        specs.extend(self._nested_discover_task_specs())
        if stale_fields is not None:
            specs = [s for s in specs if str(s['field_name']) in stale_fields]
        return specs

    def _nested_discover_task_specs(self) -> list[dict[str, object]]:
        """Return task specs for nested child contracts that use ``root = ys.discover()``."""
        from yosoi.models.selectors import is_discover_sentinel

        specs: list[dict[str, object]] = []
        for parent_name, child_contract in self._contract.nested_contracts().items():
            if is_discover_sentinel(child_contract.root):
                specs.append(
                    {
                        'field_name': f'{parent_name}_root',
                        'field_description': f'Scoped container element that wraps all {parent_name} fields',
                        'field_hint': None,
                        'is_container': True,
                    }
                )
        return specs

    def _collect_hints(self) -> dict[str, str | None]:
        """Extract yosoi_hint from each contract field, expanding nested contracts."""
        return self._contract.field_hints()
