"""Per-field discovery sub-task: cache check -> LLM -> inline verify -> escalate."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from parsel import Selector
from tenacity import RetryError

from yosoi.core.verification.verifier import SelectorVerifier
from yosoi.models.selectors import FieldSelectors, SelectorLevel
from yosoi.models.snapshot import SnapshotStatus
from yosoi.prompts.discovery import DiscoveryInput, FieldFeedback
from yosoi.utils import observability as obs
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
        absent: True only when the model intentionally returned NA for this field.

    """

    field_name: str
    selectors: FieldSelectors | None
    from_cache: bool
    escalated_to: SelectorLevel | None
    absent: bool = False


async def _invoke_agent(
    agent: FieldDiscoveryAgent,
    field_name: str,
    field_description: str,
    discovery_input: DiscoveryInput,
    level: SelectorLevel,
    is_container: bool,
    semaphore: asyncio.Semaphore | None,
    feedback: FieldFeedback | None = None,
) -> FieldSelectors | None:
    """Invoke the field discovery agent, optionally throttled by a semaphore."""
    if semaphore is not None:
        async with semaphore:
            return await agent.discover_field(
                field_name, field_description, discovery_input, level, is_container, feedback
            )
    return await agent.discover_field(field_name, field_description, discovery_input, level, is_container, feedback)


def _selector_strategy_order(max_level: SelectorLevel, discovery_input: DiscoveryInput) -> list[SelectorLevel]:
    """Rank selector ceilings for discovery attempts.

    Static HTML keeps the historical simple-to-complex order. Browser-rendered
    L2+ captures include an AX hint, where role/name anchors are usually more
    stable than class soup, so try the all-strategy/AX ceiling first.
    """
    levels = [level for level in SelectorLevel if level <= max_level]
    if not discovery_input.ax_hint:
        return levels

    ranked = [
        SelectorLevel.ROLE,
        SelectorLevel.CSS,
        SelectorLevel.ATTR,
        SelectorLevel.GLOBAL_ID,
        SelectorLevel.XPATH,
        SelectorLevel.JSONLD,
        SelectorLevel.REGEX,
        SelectorLevel.VISUAL,
    ]
    return [level for level in ranked if level in levels]


def _retry_error_detail(exc: RetryError) -> str:
    """Return the underlying final exception message from a tenacity RetryError."""
    last = exc.last_attempt.exception()
    return str(last or exc)


async def _discover_at_level(
    *,
    field_name: str,
    field_description: str,
    discovery_input: DiscoveryInput,
    agent: FieldDiscoveryAgent,
    level: SelectorLevel,
    max_retries: int,
    is_container: bool,
    semaphore: asyncio.Semaphore | None,
    feedback: FieldFeedback | None,
) -> tuple[FieldSelectors | None, bool]:
    """Run bounded LLM discovery for one selector level; return (selectors, saw_na)."""
    discovered: FieldSelectors | None = None
    saw_absent = False
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
                    discovery_input,
                    level,
                    is_container,
                    semaphore,
                    feedback,
                )
                if llm_result is None:
                    saw_absent = True
                    break
                discovered = llm_result
    except RetryError as exc:
        logger.debug('All retries exhausted for %s at level %s', field_name, level.name)
        raise LLMGenerationError(
            f'LLM discovery failed for `{field_name}` after {max_retries} attempt(s): {_retry_error_detail(exc)}'
        ) from exc
    except LLMGenerationError:
        logger.debug('LLM discovery failed for %s at level %s', field_name, level.name)
        raise
    return discovered, saw_absent


async def _discover_field(
    field_name: str,
    field_description: str,
    discovery_input: DiscoveryInput,
    html: str,
    agent: FieldDiscoveryAgent,
    cached_entry: dict[str, Any] | None,
    max_level: SelectorLevel,
    max_retries: int,
    is_container: bool,
    semaphore: asyncio.Semaphore | None,
    feedback: FieldFeedback | None = None,
) -> FieldTaskResult:
    """Cache-check + per-level escalation loop. No bus coordination."""
    verifier = SelectorVerifier()
    parsel_sel = Selector(text=html)
    failure = FieldTaskResult(field_name=field_name, selectors=None, from_cache=False, escalated_to=None)

    # --- 1. Cache check ---
    if cached_entry is not None:
        status = cached_entry.get('status')
        if (
            status
            in {
                SnapshotStatus.ABSENT,
                SnapshotStatus.ABSENT.value,
                SnapshotStatus.DISCOVERY_FAILED,
                SnapshotStatus.DISCOVERY_FAILED.value,
                SnapshotStatus.VERIFICATION_FAILED,
                SnapshotStatus.VERIFICATION_FAILED.value,
            }
            or cached_entry.get('primary') == 'NA'
        ):
            logger.info('Field cache is inactive: %s status=%s', field_name, status)
            return failure

        try:
            cached_selectors = FieldSelectors.model_validate(cached_entry)
            verify_result = verifier._verify_field(parsel_sel, field_name, cached_selectors, max_level)
            if verify_result.status == 'verified':
                logger.info('Cache hit for field %s', field_name)
                with obs.span(f'cache_hit[{field_name}]', field=field_name, source='cache'):
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
    saw_absent = False
    for level in _selector_strategy_order(max_level, discovery_input):
        discovered, absent_at_level = await _discover_at_level(
            field_name=field_name,
            field_description=field_description,
            discovery_input=discovery_input,
            agent=agent,
            level=level,
            max_retries=max_retries,
            is_container=is_container,
            semaphore=semaphore,
            feedback=feedback,
        )
        saw_absent = saw_absent or absent_at_level
        if discovered is None:
            continue

        # --- Inline verify ---
        verify_result = verifier._verify_field(parsel_sel, field_name, discovered, max_level)
        if verify_result.status == 'verified':
            winning_level = discovered.max_level
            escalated = winning_level if winning_level > SelectorLevel.CSS else None
            logger.info(
                'Field discovered field=%s level=%s selector_level=%s escalated=%s',
                field_name,
                level.name,
                winning_level.name,
                escalated is not None,
            )
            return FieldTaskResult(
                field_name=field_name,
                selectors=discovered,
                from_cache=False,
                escalated_to=escalated,
            )

        logger.debug('Selector for %s at level %s failed verification', field_name, level.name)

    obs.warning('Field discovery failed all levels', field=field_name, max_level=max_level.name)
    if saw_absent:
        return FieldTaskResult(field_name=field_name, selectors=None, from_cache=False, escalated_to=None, absent=True)
    return failure


async def run_field_task(
    field_name: str,
    field_description: str,
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
    feedback: FieldFeedback | None = None,
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
        feedback: Optional semantic-validation feedback prepended to the LLM
            prompt on a corrective retry. When set, the discovery bus is
            bypassed so a sibling's (wrong) cached result cannot short-circuit
            the correction.

    Returns:
        FieldTaskResult with selectors=None if all attempts failed.

    """
    # A corrective retry must not be satisfied by another pipeline's shared
    # (and likely identical, hence wrong) result — bypass the bus entirely.
    if feedback:
        scoped_bus = None

    # --- Bus coordination ---
    is_bus_leader = False
    sig: str = ''
    if scoped_bus is not None:
        sig = field_signature(field_name, field_description, yosoi_type)
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
            discovery_input=discovery_input,
            html=html,
            agent=agent,
            cached_entry=cached_entry,
            max_level=max_level,
            max_retries=max_retries,
            is_container=is_container,
            semaphore=semaphore,
            feedback=feedback,
        )
        return result
    finally:
        if is_bus_leader:
            await scoped_bus.publish(sig, result.selectors)  # type: ignore[union-attr]
