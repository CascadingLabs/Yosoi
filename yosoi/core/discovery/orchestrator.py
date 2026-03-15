"""Fan-out discovery orchestrator: one LLM call per field, results merged at the end."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import logfire
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.field_agent import FieldDiscoveryAgent
from yosoi.core.discovery.field_task import FieldTaskResult, run_field_task
from yosoi.models.contract import Contract
from yosoi.models.selectors import SelectorLevel
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.storage.persistence import SelectorStorage

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
    ):
        """Initialise the orchestrator.

        Args:
            contract: Contract subclass defining fields to discover
            llm_config: LLM provider and model configuration
            storage: Selector storage (used for cache reads and the final write)
            console: Optional Rich console for output
            target_level: Maximum selector strategy level. Defaults to CSS.
            max_concurrent: Maximum concurrent LLM calls. Defaults to 5.

        """
        self._contract = contract
        self._storage = storage
        self._target_level = target_level
        self._max_concurrent = max_concurrent
        self._agent = FieldDiscoveryAgent(llm_config, console=console)
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

    @logfire.instrument('orchestrator_discover_selectors', extract_args=False)
    async def discover_selectors(self, html: str, url: str | None = None) -> SelectorMap | None:
        """Discover selectors for all contract fields in parallel.

        Args:
            html: Cleaned HTML to analyze
            url: Optional URL for cache domain lookup and saving

        Returns:
            SelectorMap with discovered selectors, or None if all fields failed.

        """
        url_context = url or 'the provided page'
        domain = self._extract_domain(url) if url else 'unknown'
        discovery_input = DiscoveryInput(url=url_context, html=html)

        field_descs = self._contract.field_descriptions()
        hints = self._collect_hints()
        overrides = self._contract.get_selector_overrides()

        # If every field has an override, skip AI entirely
        if not field_descs:
            logfire.info('Skipping AI discovery — all fields overridden', url=url_context)
            return {k: dict(v) for k, v in overrides.items()} if overrides else None

        semaphore = asyncio.Semaphore(self._max_concurrent)

        # Load the full domain selector map once — avoids N redundant file reads
        existing = self._storage.load_selectors(domain) or {}

        # Build task specs: contract fields + optional container
        task_specs: list[dict[str, object]] = [
            {
                'field_name': name,
                'field_description': desc,
                'field_hint': hints.get(name),
                'is_container': False,
            }
            for name, desc in field_descs.items()
        ]
        if not self._contract.get_root():
            task_specs.append(
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

        task_specs.extend(self._nested_discover_task_specs())

        # Fan-out: run all field tasks concurrently
        coroutines = [
            run_field_task(
                field_name=str(spec['field_name']),
                field_description=str(spec['field_description']),
                field_hint=spec['field_hint'] if spec['field_hint'] is None else str(spec['field_hint']),
                discovery_input=discovery_input,
                html=html,
                agent=self._agent,
                cached_entry=existing.get(str(spec['field_name'])),
                max_level=self._target_level,
                is_container=bool(spec['is_container']),
                semaphore=semaphore,
            )
            for spec in task_specs
        ]

        raw_results: list[FieldTaskResult | BaseException] = await asyncio.gather(*coroutines, return_exceptions=True)

        # Merge results — use task outputs only, never re-read cache
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

        # Merge manual overrides (overrides always take precedence)
        for field_name, override_dict in overrides.items():
            merged[field_name] = override_dict

        # Persist contract-pinned root so the cache is self-contained
        contract_root = self._contract.get_root()
        if contract_root:
            merged['root'] = {'primary': contract_root.model_dump(exclude_none=True)}

        # Check if all non-root fields failed
        non_container = {k: v for k, v in merged.items() if k != 'root'}
        if not non_container:
            logfire.warn('All field tasks returned None', url=url_context)
            return None

        logfire.info(
            'Orchestrator discovery complete',
            url=url_context,
            total=len(merged),
            cached=cached_count,
            escalated=escalated_count,
        )
        self.console.print(
            f'[success]Discovered selectors for {len(non_container)} fields (cached={cached_count})[/success]'
        )

        # Single write — avoids read-modify-write races across concurrent tasks
        if url:
            self._storage.save_selectors(url, merged)

        return merged

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

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract bare domain from URL."""
        return urlparse(url).netloc.replace('www.', '')
