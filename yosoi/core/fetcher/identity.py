"""Profile-cascade primitive: per-identity browser fetchers + block rotation.

W2 — multi-profile cascade + per-IP vs per-profile block attribution
====================================================================

Yosoi's browser tier was single-identity: the whole pool shared ONE
``BrowserConfig`` with no profile / user-data-dir, no proxy rotation, and a
terminal headful tier that could not rotate on a block. This leaf module adds a
cascade that lives entirely in the FETCHER layer (replay runtime stays LLM-free,
CAS-87 intact):

* :class:`BrowserIdentity` — an ordered, frozen description of *one* browser
  identity (profile dir, proxy egress, locale/timezone/geo, headful flag).
* :class:`IdentityCascade` — an ordered list of identities Yosoi pins per run.
* :class:`IdentityFetcherPool` — owns a ``dict[identity_id, fetcher]`` of
  per-identity ``_VoidCrawlFetcher`` instances (each its OWN Chrome process,
  because VoidCrawl's pool is single-identity), lazy-started on demand and
  capped with an LRU close policy so a 30+ site run does not leak Chrome
  processes. Rotation is tenacity-driven (the blessed ``get_async_retryer``
  wrapper — no raw for/while + sleep) over the cascade, retrying on
  :class:`BotDetectionError`. Cascade exhausted -> raise (fail-fast, never a
  heuristic fallback).

Why per-identity = own process: VoidCrawl's ``PoolConfig`` holds a SINGLE shared
``BrowserConfig`` and the native pool ctor takes only a scalar ``extra_args``
list — N tabs in one pool are ONE identity. Multiple ``--user-data-dir`` cannot
be expressed per-tab today, so each identity gets its own fetcher (own pool /
process / user-data-dir). Memory cost is real (~750MB fixed base + ~80-120MB per
tab PER PROCESS), hence: headful identities run a single browser with a small
tab count, the cascade SERIALIZES headful escalation, and losing identities are
closed via the LRU cap.

Per-IP vs per-profile isolation EXPERIMENT (design)
---------------------------------------------------
A block can be attributed to the *profile* (fingerprint/cookies), the *IP*
(egress), or the PAIR. Rotating the scarce trusted profile on a per-IP block
just burns it. Two crossed trials decide the rotation key:

* **Trial A (hold IP, vary profile)** — fixed egress (no proxy, or one proxy),
  loop K distinct identities differing ONLY in ``profile_dir`` (one trusted +
  several fresh), fire the same N queries through each, and record the first
  block's query index plus ``indicators`` / ``captcha_kind`` per identity.
  Needs ZERO new infra and ships FIRST: it answers "is the trusted profile the
  real differentiator on Google?".
* **Trial B (hold profile, vary IP)** — fix ONE ``profile_dir``, rotate K
  identities differing only in ``proxy``, same query load, record block onset
  per IP. GATED on a proxy pool existing (open question: none threaded today),
  so it ships when proxies land.

Read-out: blocks track the profile regardless of IP -> per-profile (rotate
profiles, invest in a profile farm). Blocks track the IP regardless of profile
-> per-IP (rotate proxies, one good profile suffices). Both -> joint identity
(rotate the PAIR). Instrument via the per-(identity, query-index) block log this
module produces (``identity_id`` + ``captcha_kind`` on :class:`BotDetectionError`),
and SERIALIZE headful runs to respect the ~750MB/process budget.

Safety note: clone the trusted profile into a throwaway dir per identity rather
than leasing the live ``~/.config/chromium`` — that avoids burning the user's
real Google account AND sidesteps VoidCrawl's exclusive ``.voidcrawl.lock``
(a single live logged-in profile is a semaphore-of-1, not a pooled resource).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from yosoi.utils.exceptions import BotDetectionError
from yosoi.utils.retry import get_async_retryer, log_retry

if TYPE_CHECKING:
    from yosoi.core.fetcher.voiddriver import _VoidCrawlFetcher
    from yosoi.models.results import FetchResult

logger = logging.getLogger(__name__)

# Default ceiling on simultaneously-live identity fetchers (each = one Chrome
# process at ~750MB base). Keep the per-domain winner warm plus a couple of
# spares; evict the rest via LRU. Headful identities are the expensive ones, so
# this is deliberately small.
_DEFAULT_MAX_LIVE_FETCHERS = 3


@dataclass(frozen=True)
class BrowserIdentity:
    """One browser identity in a cascade.

    Frozen + ordered so identities are hashable cache keys and an
    :class:`IdentityCascade` can be a stable ordered list. The ``id`` is the
    attribution handle written onto :class:`BotDetectionError` and persisted in
    ``FetchStrategy.identity_id``.
    """

    id: str
    profile_dir: str | None = None  # raw --user-data-dir (trusted/logged-in, ideally a clone)
    profile_name: str | None = None  # VoidCrawl leased profile (with_profile) — secondary path
    proxy: str | None = None  # egress IP
    locale: str | None = None
    timezone_id: str | None = None
    geo: tuple[float, float] | None = None
    headful: bool = False

    def fetcher_kwargs(self) -> dict[str, Any]:
        """Return the identity-derived kwargs to thread into a ``_VoidCrawlFetcher``.

        Only non-``None`` knobs are emitted so the fetcher keeps its own
        defaults for everything this identity does not pin.
        """
        kwargs: dict[str, Any] = {'identity': self}
        return kwargs


@dataclass(frozen=True)
class IdentityCascade:
    """An ordered list of identities to try, cheapest/most-trusted first.

    ``ordered(prefer=...)`` returns the identities with the per-domain winner (if
    still present) moved to the front, so a cached winner is retried first on the
    next visit before paying to re-escalate.
    """

    identities: tuple[BrowserIdentity, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate the cascade is non-empty with unique identity ids."""
        if not self.identities:
            raise ValueError('IdentityCascade requires at least one identity')
        seen: set[str] = set()
        for ident in self.identities:
            if ident.id in seen:
                raise ValueError(f'duplicate identity id in cascade: {ident.id!r}')
            seen.add(ident.id)

    def __len__(self) -> int:
        """Number of identities in the cascade."""
        return len(self.identities)

    def ordered(self, prefer: str | None = None) -> list[BrowserIdentity]:
        """Return identities in try-order, with ``prefer`` (a winning id) first."""
        ids = list(self.identities)
        if prefer is None:
            return ids
        winner = next((i for i in ids if i.id == prefer), None)
        if winner is None:
            return ids
        return [winner, *[i for i in ids if i.id != prefer]]


# Factory: (identity, base_kwargs) -> an entered _VoidCrawlFetcher. Injected so the
# pool is unit-testable with mock fetchers (no real Chrome) and so voiddriver does
# not have to import identity at module load.
FetcherFactory = Callable[[BrowserIdentity, dict[str, Any]], Awaitable['_VoidCrawlFetcher']]


class IdentityFetcherPool:
    """Owns one lazily-started fetcher per identity, with an LRU close cap.

    The cascade body asks for a fetcher by identity; the first request starts and
    enters it, later requests reuse it. When the number of live fetchers would
    exceed ``max_live`` the least-recently-used one is closed (via the fetcher's
    own ``close()``), so a long multi-domain run does not accumulate Chrome
    processes. Closing is best-effort and never masks the in-flight result.
    """

    def __init__(
        self,
        factory: FetcherFactory,
        base_kwargs: dict[str, Any] | None = None,
        max_live: int = _DEFAULT_MAX_LIVE_FETCHERS,
    ) -> None:
        """Initialise with a fetcher *factory*, shared *base_kwargs*, and LRU cap."""
        if max_live < 1:
            raise ValueError('max_live must be >= 1')
        self._factory = factory
        self._base_kwargs = dict(base_kwargs or {})
        self._max_live = max_live
        # OrderedDict as an LRU: most-recently-used moved to the end.
        self._fetchers: OrderedDict[str, _VoidCrawlFetcher] = OrderedDict()

    @property
    def live_ids(self) -> list[str]:
        """Ids of currently-live (started) identity fetchers, LRU-first."""
        return list(self._fetchers.keys())

    async def get(self, identity: BrowserIdentity) -> _VoidCrawlFetcher:
        """Return the (lazily started) fetcher for *identity*, evicting LRU losers."""
        existing = self._fetchers.get(identity.id)
        if existing is not None:
            self._fetchers.move_to_end(identity.id)
            return existing

        # Evict before starting a new one so we never exceed the process budget.
        await self._evict_to(self._max_live - 1)
        fetcher = await self._factory(identity, dict(self._base_kwargs))
        self._fetchers[identity.id] = fetcher
        self._fetchers.move_to_end(identity.id)
        logger.info('Started identity fetcher %r (live=%d)', identity.id, len(self._fetchers))
        return fetcher

    async def _evict_to(self, target: int) -> None:
        """Close LRU fetchers until at most *target* remain live."""
        while len(self._fetchers) > max(target, 0):
            ident_id, fetcher = self._fetchers.popitem(last=False)
            logger.info('Evicting LRU identity fetcher %r', ident_id)
            try:
                await fetcher.close()
            except Exception as exc:  # noqa: BLE001 — best-effort teardown
                logger.warning('Error closing identity fetcher %r: %s', ident_id, exc)

    async def close(self) -> None:
        """Close every live identity fetcher."""
        await self._evict_to(0)


async def run_cascade(
    *,
    cascade: IdentityCascade,
    pool: IdentityFetcherPool,
    do_fetch: Callable[[_VoidCrawlFetcher, BrowserIdentity], Awaitable[FetchResult]],
    prefer: str | None = None,
) -> tuple[FetchResult, BrowserIdentity]:
    """Run *cascade*, rotating identities on :class:`BotDetectionError`.

    The winning identity is retried first when ``prefer`` names a cached winner.
    Rotation uses the blessed tenacity ``get_async_retryer`` (no raw for/while +
    sleep): ``max_attempts == len(order)``, retry only on ``BotDetectionError``,
    ``reraise=True`` so a fully-exhausted cascade RAISES the last block — fail
    fast, never a heuristic fallback.

    Returns the ``FetchResult`` and the ``BrowserIdentity`` that won, so the
    caller can persist the winner per-domain (``FetchStrategy.identity_id``).

    The verifier flagged ``order[attempt_number - 1]`` as fragile (couples retry
    count to list position). We instead drive an explicit cursor over the order
    list — a tenacity *internal* retry can never desync the index, and we bind
    the next identity by popping the cursor exactly once per attempt body.
    """
    order = cascade.ordered(prefer=prefer)
    cursor = iter(order)
    result_box: dict[str, Any] = {}

    async for attempt in get_async_retryer(
        max_attempts=len(order),
        wait_min=1.0,
        wait_max=8.0,
        exceptions=(BotDetectionError,),
        log_callback=log_retry,
    ):
        with attempt:
            # Bind the NEXT identity off the cursor — independent of tenacity's
            # internal attempt_number, so an internal retry cannot skip one.
            ident = next(cursor)
            fetcher = await pool.get(ident)
            res = await do_fetch(fetcher, ident)
            result_box['result'] = res
            result_box['identity'] = ident

    # reraise=True means an exhausted cascade already raised the last
    # BotDetectionError; we only reach here on success.
    return result_box['result'], result_box['identity']
