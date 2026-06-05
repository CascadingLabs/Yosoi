"""Per-engine settle-time measurement scaffold for multi-engine SERP teleport.

OFF THE HOT PATH. This is discovery/instrumentation code: it measures how long a
SERP engine takes to *apply* a teleported location after navigation, so the
one-zone-lag (``prime_reload``) need can be encoded as a number per engine instead
of a blind ``asyncio.sleep`` (the ``serp_band.load_twice`` flat 1.0s sleep this
replaces lives in Nimbal; the Yosoi side records the measured distribution).

It is deliberately NOT used by :func:`yosoi.core.replay.runtime.execute_plan`'s leaf
dispatch — the deterministic replay wait is the node's ``expect`` ``ReplayCondition``
deadline (``AssertKind.TEXT`` for a city name in body, ``AssertKind.COUNT`` for
local-pack rows). This module is the *measurement* harness that produces the data
those conditions are tuned from.

No raw ``for``/``while`` + ``sleep`` polling loop: the wait is a tenacity
``AsyncRetrying`` (the blessed :func:`yosoi.utils.retry.get_async_retryer` wrapper)
that retries a "location-applied" predicate until it holds or the attempt budget is
exhausted, then fail-fasts. We measure ``perf_counter`` elapsed across the retry.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from yosoi.core.replay.runtime import ReplayExecutionError, _condition_holds
from yosoi.models.replay import ReplayCondition
from yosoi.utils.retry import get_async_retryer, log_retry


class SettleNotApplied(RuntimeError):
    """Raised inside the retry body when the location-applied predicate is False.

    A dedicated type so the tenacity retryer retries ONLY the not-yet-applied
    signal and lets unrelated errors (a broken tab call) surface immediately.
    """


@dataclass
class SettleMeasurement:
    """One measured settle observation for a single (engine, phase)."""

    engine: str
    applied: bool
    elapsed_s: float
    attempts: int


@dataclass
class SettleTable:
    """Accumulated per-engine settle observations.

    The point is a per-engine *distribution*, so each engine keeps a list of
    measurements; ``worst_elapsed`` / ``mean_elapsed`` summarize it for a budget.
    """

    by_engine: dict[str, list[SettleMeasurement]] = field(default_factory=dict)

    def record(self, m: SettleMeasurement) -> None:
        """Append a measurement under its engine key."""
        self.by_engine.setdefault(m.engine, []).append(m)

    def worst_elapsed(self, engine: str) -> float | None:
        """Slowest applied settle for ``engine`` (None if no applied sample)."""
        applied = [m.elapsed_s for m in self.by_engine.get(engine, []) if m.applied]
        return max(applied) if applied else None

    def mean_elapsed(self, engine: str) -> float | None:
        """Mean applied settle for ``engine`` (None if no applied sample)."""
        applied = [m.elapsed_s for m in self.by_engine.get(engine, []) if m.applied]
        return sum(applied) / len(applied) if applied else None


async def measure_settle(
    tab: object,
    engine: str,
    applied: ReplayCondition | Callable[[object], Awaitable[bool]],
    *,
    max_attempts: int = 8,
    wait_min: float = 0.25,
    wait_max: float = 2.0,
    table: SettleTable | None = None,
) -> SettleMeasurement:
    """Measure how long ``engine`` takes to apply a teleport, via tenacity retry.

    ``applied`` is the "location landed" predicate: either a :class:`ReplayCondition`
    (reusing the existing ``_condition_holds`` machinery — e.g. ``AssertKind.TEXT``
    with the city name, or ``AssertKind.COUNT`` of local-pack rows) or a raw async
    callable for ad-hoc probes. The predicate is polled by the blessed
    ``get_async_retryer`` wrapper (``async for attempt in ...``) — NO raw sleep loop.

    Fail-fast: if the predicate never holds within the attempt budget, the final
    ``SettleNotApplied`` is reraised as a :class:`ReplayExecutionError` so a
    never-localizing engine surfaces loudly instead of recording a bogus 0s settle.
    The successful ``perf_counter`` elapsed is returned (and recorded into ``table``).
    """

    async def _holds() -> bool:
        if isinstance(applied, ReplayCondition):
            return await _condition_holds(tab, applied)
        return await applied(tab)

    start = time.perf_counter()
    attempts = 0
    retryer = get_async_retryer(
        max_attempts=max_attempts,
        wait_min=wait_min,
        wait_max=wait_max,
        exceptions=(SettleNotApplied,),
        log_callback=log_retry,
        reraise=True,
    )
    try:
        async for attempt in retryer:
            with attempt:
                attempts += 1
                if not await _holds():
                    raise SettleNotApplied(f'{engine}: location not applied yet')
    except SettleNotApplied as exc:
        elapsed = time.perf_counter() - start
        measurement = SettleMeasurement(engine=engine, applied=False, elapsed_s=elapsed, attempts=attempts)
        if table is not None:
            table.record(measurement)
        raise ReplayExecutionError(f'settle never applied for {engine}: {exc}') from exc

    elapsed = time.perf_counter() - start
    measurement = SettleMeasurement(engine=engine, applied=True, elapsed_s=elapsed, attempts=attempts)
    if table is not None:
        table.record(measurement)
    return measurement
