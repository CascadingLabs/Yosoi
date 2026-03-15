"""Per-field discovery sub-task: cache check -> LLM -> inline verify -> escalate."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import logfire
from parsel import Selector
from tenacity import RetryError

from yosoi.core.verification.verifier import SelectorVerifier
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.prompts.discovery import DiscoveryInput
from yosoi.utils.exceptions import LLMGenerationError
from yosoi.utils.retry import get_async_retryer
from yosoi.utils.signatures import field_signature

if TYPE_CHECKING:
    from yosoi.core.discovery.bus import ScopedBus
    from yosoi.core.discovery.field_agent import FieldDiscoveryAgent

logger = logging.getLogger(__name__)


@dataclass
class FieldTaskResult:
    """Result from a single-field discovery task.

    Attributes:
        field_name: Name of the contract field
        selectors: Discovered and inline-verified selectors, or None if failed
        from_cache: True if selectors came from the domain cache
        escalated_to: The SelectorLevel that succeeded (None if CSS or cache hit)

    """

    field_name: str
    selectors: FieldSelectors | None
    from_cache: bool
    escalated_to: SelectorLevel | None


async def _invoke_agent(
    agent: FieldDiscoveryAgent,
    field_name: str,
    field_description: str,
    field_hint: str | None,
    discovery_input: DiscoveryInput,
    level: SelectorLevel,
    is_container: bool,
    semaphore: asyncio.Semaphore | None,
) -> FieldSelectors | None:
    """Invoke the field discovery agent, optionally throttled by a semaphore."""
    if semaphore is not None:
        async with semaphore:
            return await agent.discover_field(
                field_name, field_description, field_hint, discovery_input, level, is_container
            )
    return await agent.discover_field(field_name, field_description, field_hint, discovery_input, level, is_container)


async def _discover_field(
    field_name: str,
    field_description: str,
    field_hint: str | None,
    discovery_input: DiscoveryInput,
    html: str,
    agent: FieldDiscoveryAgent,
    cached_entry: dict[str, Any] | None,
    max_level: SelectorLevel,
    max_retries: int,
    is_container: bool,
    semaphore: asyncio.Semaphore | None,
) -> FieldTaskResult:
    """Cache-check + per-level escalation loop. No bus coordination."""
    verifier = SelectorVerifier()
    parsel_sel = Selector(text=html)
    failure = FieldTaskResult(field_name=field_name, selectors=None, from_cache=False, escalated_to=None)

    # --- 1. Cache check ---
    if cached_entry is not None:
        try:
            cached_selectors = FieldSelectors.model_validate(cached_entry)
            verify_result = verifier._verify_field(parsel_sel, field_name, cached_selectors, max_level)
            if verify_result.status == 'verified':
                logfire.info('Cache hit for field', field=field_name)
                return FieldTaskResult(
                    field_name=field_name,
                    selectors=cached_selectors,
                    from_cache=True,
                    escalated_to=None,
                )
            logger.debug('Cached selector for %s failed verification, re-discovering', field_name)
        except (ValueError, TypeError):
            logger.debug('Cached selector for %s is invalid, re-discovering', field_name)

    # --- 2. Per-level escalation loop ---
    for level in SelectorLevel:
        if level > max_level:
            break

        discovered: FieldSelectors | None = None

        try:
            retryer = get_async_retryer(
                max_attempts=max_retries,
                wait_min=1,
                wait_max=10,
                exceptions=(LLMGenerationError,),
                reraise=True,
            )
            async for attempt in retryer:
                with attempt:
                    llm_result = await _invoke_agent(
                        agent,
                        field_name,
                        field_description,
                        field_hint,
                        discovery_input,
                        level,
                        is_container,
                        semaphore,
                    )
                    if llm_result is None:
                        # LLM returned NA — not retryable, skip to next level
                        break
                    discovered = llm_result

        except (LLMGenerationError, RetryError):
            logger.debug('All retries exhausted for %s at level %s', field_name, level.name)
            continue  # try next level

        if discovered is None:
            continue

        # --- Inline verify ---
        verify_result = verifier._verify_field(parsel_sel, field_name, discovered, max_level)
        if verify_result.status == 'verified':
            escalated = level if level > SelectorLevel.CSS else None
            logfire.info(
                'Field discovered',
                field=field_name,
                level=level.name,
                escalated=escalated is not None,
            )
            return FieldTaskResult(
                field_name=field_name,
                selectors=discovered,
                from_cache=False,
                escalated_to=escalated,
            )

        logger.debug('Selector for %s at level %s failed verification', field_name, level.name)

    logfire.warn('Field discovery failed all levels', field=field_name, max_level=max_level.name)
    return failure


async def run_field_task(
    field_name: str,
    field_description: str,
    field_hint: str | None,
    discovery_input: DiscoveryInput,
    html: str,
    agent: FieldDiscoveryAgent,
    cached_entry: dict[str, Any] | None,
    max_level: SelectorLevel,
    max_retries: int = 3,
    is_container: bool = False,
    semaphore: asyncio.Semaphore | None = None,
    scoped_bus: ScopedBus | None = None,
    yosoi_type: str | None = None,
) -> FieldTaskResult:
    """Discover selectors for a single field with cache check, escalation, and inline verification.

    Execution order:

    1. Check cached_entry for existing selector
    2. If cached and passes inline verification: return immediately
    3. Otherwise iterate SelectorLevel from CSS up to max_level:
       a. Retry LLM call up to max_retries times (per level)
       b. Inline verify the result
       c. If verified: return with escalation info
    4. If all levels fail: return FieldTaskResult(selectors=None)

    Retries are applied **per level** -- CSS is retried 3x before escalating to XPath.

    Args:
        field_name: Name of the field to discover
        field_description: Human-readable description from the contract
        field_hint: Optional AI hint from the contract field definition
        discovery_input: URL and HTML passed to the agent
        html: Raw HTML for inline verification (same as discovery_input.html)
        agent: Shared FieldDiscoveryAgent instance
        cached_entry: Pre-loaded selector dict for this field, or None if not cached.
            Caller is responsible for loading this -- avoids N redundant file reads.
        max_level: Maximum SelectorLevel to try
        max_retries: Retry attempts per level. Defaults to 3.
        is_container: True when discovering the yosoi_container field
        semaphore: Optional asyncio.Semaphore to cap concurrent LLM calls
        scoped_bus: Optional domain-scoped discovery bus for cross-pipeline sharing.
        yosoi_type: Semantic type string used in the field signature (e.g. ``'price'``).

    Returns:
        FieldTaskResult with selectors=None if all attempts failed.

    """
    # --- Bus coordination ---
    is_bus_leader = False
    sig: str = ''
    if scoped_bus is not None:
        sig = field_signature(field_name, field_description, field_hint, yosoi_type)
        is_bus_leader = await scoped_bus.acquire(sig)
        if not is_bus_leader:
            cached = await scoped_bus.wait_for(sig)
            if cached is not None:
                return FieldTaskResult(field_name=field_name, selectors=cached, from_cache=True, escalated_to=None)
            # Leader failed → fall through to independent discovery (slot consumed)

    result: FieldTaskResult = FieldTaskResult(
        field_name=field_name, selectors=None, from_cache=False, escalated_to=None
    )
    try:
        result = await _discover_field(
            field_name=field_name,
            field_description=field_description,
            field_hint=field_hint,
            discovery_input=discovery_input,
            html=html,
            agent=agent,
            cached_entry=cached_entry,
            max_level=max_level,
            max_retries=max_retries,
            is_container=is_container,
            semaphore=semaphore,
        )
        return result
    finally:
        if is_bus_leader:
            await scoped_bus.publish(sig, result.selectors)  # type: ignore[union-attr]
