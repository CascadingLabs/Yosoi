"""Reaction resolution: the discovery<->extraction co-routine seam (W1).

A mid-scrape captcha and a drifted data selector are the SAME event: a pinned
target stopped resolving, so its *description* must be resolved concurrently and
the result hot-swapped back into the running tree. This module owns the OFF-the-
hot-path (PLANE B) side of that — the part where an LLM is allowed.

The hot-path walker (:func:`yosoi.core.replay.runtime.execute_tree`) NEVER imports
a model. When it hits an UNLEARNED reaction it calls a :class:`ReactionResolver`,
which fronts the existing :class:`~yosoi.core.discovery.bus.DiscoveryBus` leader/
waiter dedup so N concurrent tabs hitting the same novel description trigger ONE
resolution; the rest wait and get the learned leaf for free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from yosoi.core.discovery.bus import DiscoveryBus
    from yosoi.models.replay import ReplayCondition, TreeNode


class ReactionMiss(Exception):
    """Raised on a fired trigger with no learned recovery AND no resolver.

    This is the fail-fast signal that PLANE B must learn the recovery — it is
    NOT a garbage fallback. When a :class:`ReactionResolver` IS wired, the walker
    awaits it instead of raising; ``ReactionMiss`` only surfaces when nothing can
    learn the recovery (so the run honestly fails rather than scraping a wall).
    """

    def __init__(self, trigger: ReplayCondition, description: str | None, info: object) -> None:
        """Capture the unresolved trigger, its description, and probe info."""
        super().__init__(f'unlearned reaction fired: {description or trigger.kind}')
        self.trigger = trigger
        self.description = description
        self.info = info


class ReactionResolver(Protocol):
    """Resolves an UNLEARNED reaction's description into a recovery subtree.

    Implementations run OFF the hot path (PLANE B) and MAY use an LLM. The walker
    awaits :meth:`resolve` when a trigger fires on an UNLEARNED reaction; on a
    non-None return it hot-swaps the recovery in and resumes the parked branch.
    """

    async def resolve(self, domain: str, description: str, info: object) -> TreeNode | None:
        """Return a learned recovery subtree for *description*, or None on failure."""
        ...


class BusReactionResolver:
    """A :class:`ReactionResolver` fronted by the concurrent :class:`DiscoveryBus`.

    Captcha recovery and selector-drift repair collapse into ONE mechanism: a
    description resolved once per ``domain+description`` across concurrent tabs,
    then hot-swapped in. The bus's leader/waiter dedup guarantees a single
    resolution; waiters block on the same slot and receive the leader's result.

    The bus is typed to ``FieldSelectors``; reactions resolve to a ``TreeNode``.
    Rather than widen the bus's payload type, this resolver keeps a parallel
    in-memory ``_resolved`` map keyed identically and uses the bus purely as the
    leader/waiter *coordination* primitive (acquire/publish a sentinel, wait_for
    to block) so the dedup semantics are reused without duplicating them.
    """

    def __init__(
        self,
        bus: DiscoveryBus,
        learn: Callable[[str, str, object], Awaitable[TreeNode | None]],
    ) -> None:
        """Wire the resolver to *bus* with a *learn* coroutine doing the real work.

        Args:
            bus: The shared :class:`DiscoveryBus` providing leader/waiter dedup.
            learn: The PLANE-B coroutine ``(domain, description, info) -> TreeNode | None``
                that performs the actual (LLM-allowed) resolution. Called at most
                once per ``domain+description`` across concurrent callers.
        """
        self._bus = bus
        self._learn = learn
        self._resolved: dict[str, TreeNode | None] = {}

    async def resolve(self, domain: str, description: str, info: object) -> TreeNode | None:
        """Resolve *description* once per domain via the bus's leader/waiter dedup."""
        scoped = self._bus.scoped(domain)
        is_leader = await scoped.acquire(description)
        if is_leader:
            try:
                node = await self._learn(domain, description, info)
                self._resolved[f'{domain}:{description}'] = node
                return node
            finally:
                # Wake any waiters regardless of outcome (None => they re-learn or fail).
                await scoped.publish(description, None)
        await scoped.wait_for(description)
        return self._resolved.get(f'{domain}:{description}')
