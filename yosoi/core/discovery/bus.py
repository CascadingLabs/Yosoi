"""Concurrent discovery bus: share in-flight field discoveries across pipeline instances.

When multiple pipeline instances process pages from the same domain concurrently,
the DiscoveryBus ensures that only one instance performs the LLM call for each
field. All other instances wait for the result and receive it directly, making
zero extra LLM calls.

Slot state machine
------------------
States:   PENDING  → leader is currently discovering
          DONE     → result published (result may be None if leader failed)

Transitions:
  [absent]  --acquire()→  PENDING   returns True  (caller is the leader)
  PENDING   --acquire()→  PENDING   returns False (caller is a waiter)
  DONE      --acquire()→  DONE      returns False (late arrival, slot consumed)

  PENDING   --publish(r)→ DONE      stores result, sets event

wait_for():
  PENDING   → blocks on event.wait(), returns result after wake-up
  DONE      → returns result immediately (event already set)

Failure handling
----------------
When the leader publishes None, all waiters unblock and receive None. They then
proceed with independent LLM discovery, bypassing the bus (the slot is DONE/None
and stays that way — no re-registration).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from yosoi.models.selectors import FieldSelectors

logger = logging.getLogger(__name__)

_MAX_SLOTS = 10_000


@dataclass
class _Slot:
    """Internal state for a single field discovery slot."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: FieldSelectors | None = None
    done: bool = False


class ScopedBus:
    """Domain-scoped view of a :class:`DiscoveryBus`.

    Returned by :meth:`DiscoveryBus.scoped`. All per-field operations go
    through this class so that callers never need to pass the domain string
    explicitly.
    """

    def __init__(self, bus: DiscoveryBus, domain: str) -> None:
        """Initialise a scoped bus view for *domain*."""
        self._bus = bus
        self._domain = domain

    def _key(self, field_sig: str) -> str:
        return f'{self._domain}:{field_sig}'

    async def acquire(self, field_sig: str) -> bool:
        """Atomically claim leadership for *field_sig*.

        Returns:
            ``True`` if the caller is the leader and **must** call
            :meth:`publish` in a ``try/finally`` block.
            ``False`` if a slot already exists; the caller must call
            :meth:`wait_for` instead.

        """
        return await self._bus._acquire(self._key(field_sig))

    async def publish(self, field_sig: str, result: FieldSelectors | None) -> None:
        """Publish *result* for *field_sig* and wake all waiters.

        Must be called exactly once by the leader, always inside a
        ``try/finally`` block so that waiters are never left blocked
        permanently on a failure path.

        Args:
            field_sig: The field signature returned by :func:`field_signature`.
            result: Discovered selectors, or ``None`` if discovery failed.

        """
        await self._bus._publish(self._key(field_sig), result)

    async def wait_for(self, field_sig: str) -> FieldSelectors | None:
        """Wait for the leader to publish a result for *field_sig*.

        Must only be called after :meth:`acquire` returned ``False``.
        Returns immediately when the slot is already DONE.

        Args:
            field_sig: The field signature to wait on.

        Returns:
            The leader's result, or ``None`` if the leader failed.
            When ``None`` is returned, the caller should run discovery
            independently (the bus slot is consumed; do not re-register).

        """
        return await self._bus._wait_for(self._key(field_sig))


class DiscoveryBus:
    """In-memory bus for sharing field discoveries across concurrent pipelines.

    Use :meth:`scoped` to obtain a :class:`ScopedBus` tied to a specific domain,
    then call :meth:`ScopedBus.acquire` / :meth:`ScopedBus.publish` /
    :meth:`ScopedBus.wait_for` from field tasks.

    The ``_slots`` dict grows for the process lifetime. Call :meth:`clear` at
    shutdown to release memory.
    """

    def __init__(self) -> None:
        """Initialise an empty bus with no active slots."""
        self._slots: dict[str, _Slot] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def scoped(self, domain: str) -> ScopedBus:
        """Return a domain-scoped bus view.

        Args:
            domain: Bare domain string (e.g. ``'example.com'``).

        Returns:
            A :class:`ScopedBus` for *domain*.

        """
        return ScopedBus(self, domain)

    def clear(self) -> None:
        """Reset all slots. Call at broker shutdown."""
        self._slots.clear()

    def prune_done(self) -> int:
        """Remove completed slots to reclaim memory.

        Returns:
            Number of slots pruned.

        """
        done_keys = [k for k, s in self._slots.items() if s.done]
        for k in done_keys:
            del self._slots[k]
        return len(done_keys)

    async def _acquire(self, key: str) -> bool:
        """Atomically check-and-set under the internal lock."""
        async with self._lock:
            if key not in self._slots:
                if len(self._slots) >= _MAX_SLOTS:
                    logger.warning(
                        'DiscoveryBus slot count reached %d — possible memory leak; pruning done slots',
                        _MAX_SLOTS,
                    )
                    self.prune_done()
                self._slots[key] = _Slot()
                return True
            return False

    async def _publish(self, key: str, result: FieldSelectors | None) -> None:
        """Store result and unblock all waiters for *key*."""
        async with self._lock:
            slot = self._slots[key]
            slot.result = result
            slot.done = True
            slot.event.set()

    async def _wait_for(self, key: str) -> FieldSelectors | None:
        """Block until the slot for *key* is DONE, then return its result."""
        async with self._lock:
            slot = self._slots.get(key)

        if slot is None:
            # Should not happen if acquire() was called first, but be safe
            return None

        if slot.done:
            return slot.result

        await slot.event.wait()
        return slot.result
