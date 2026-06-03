"""Pipeline-facing glue for the experimental reuse-hint signal (CAS-85).

Gated by the ``YOSOI_REUSE_HINT`` env flag — **off by default**. When on:

* on fresh discovery, stash a seed :class:`PageObservation` for the domain
  (:func:`record_seed`);
* on a cached-recipe replay, emit an advisory :class:`ReuseHint` comparing the
  replay page to the seed, classify its reuse :class:`ReuseScope`, persist a
  :class:`DecisionRecord` (a flywheel/queue row), and return a :class:`ReplayAdvice`
  whose ``act`` flag — set by the active risk :class:`ReuseProfile` — tells the
  caller whether it may skip a doomed replay (:func:`hint_for_replay`).

The signal is **advisory**: the pipeline's per-field verify still owns
correctness. Whether the pipeline *acts* on a hint is governed by
``YOSOI_REUSE_PROFILE`` (strict = pure observer). Nothing here raises into the
scrape hot path — every failure degrades to "no advice", logged at debug level.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from yosoi.generalization.advise import ReuseHint, advise_reuse
from yosoi.generalization.capture import observe_html
from yosoi.generalization.policy import active_profile, disposition
from yosoi.generalization.scope import ReuseScope, classify_scope
from yosoi.generalization.seeds import load_seed, save_seed
from yosoi.generalization.store import DecisionStore
from yosoi.generalization.trust import DecisionRecord, build_decision

_FLAG = 'YOSOI_REUSE_HINT'

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayAdvice:
    """The reuse advice handed back to the pipeline for one replay page.

    Attributes:
        hint: The advisory reuse hint (TRY_REUSE / REDISCOVER / UNSURE).
        scope: The reuse scope this decision spans.
        act: Whether the active profile permits acting on the hint (e.g. skipping
            a doomed replay). False under the strict profile (pure observer).
        record: The persisted decision record (already written to the ledger).
    """

    hint: ReuseHint
    scope: ReuseScope
    act: bool
    record: DecisionRecord


def reuse_hint_enabled() -> bool:
    """Whether the experimental reuse-hint signal is switched on.

    Returns:
        True only when ``YOSOI_REUSE_HINT=1`` in the environment.
    """
    return os.getenv(_FLAG) == '1'


def record_seed(url: str, html: str, *, row_selector: str | None) -> None:
    """Stash a seed observation for ``url``'s domain (no-op unless enabled).

    Called on successful fresh discovery. Failures are swallowed (advisory only)
    so a seed-write error can never break discovery.

    Args:
        url: The page discovery succeeded on.
        html: The cleaned HTML of that page.
        row_selector: The recipe's repeating-row selector, if any.
    """
    if not reuse_hint_enabled():
        return
    try:
        save_seed(observe_html(url, html, row_selector=row_selector or ''))
    except Exception:  # noqa: BLE001 — advisory glue must never break the scrape hot path
        logger.debug('reuse-hint: failed to record seed for %s', url, exc_info=True)


def hint_for_replay(url: str, html: str, *, row_selector: str | None, driver: str = 'pipeline') -> ReplayAdvice | None:
    """Advisory reuse advice for replaying the domain recipe on ``url``.

    Compares the replay page against the domain's stored seed, classifies the
    reuse scope, applies the active risk profile, persists the decision to the
    ledger, and returns the advice. Returns None when the flag is off, no seed
    exists yet, or anything fails (fail-open).

    Args:
        url: The candidate replay page.
        html: The cleaned HTML of the replay page.
        row_selector: The cached recipe's repeating-row selector, if any.
        driver: Identifier recorded as the deciding agent.

    Returns:
        A :class:`ReplayAdvice`, or None.
    """
    if not reuse_hint_enabled():
        return None
    try:
        seed = load_seed(url)
        if seed is None:
            return None
        replay = observe_html(url, html, row_selector=row_selector or '')
        hint = advise_reuse(seed, replay)
        profile = active_profile()
        scope = classify_scope(hint.panel)
        act = disposition(hint.panel.recommendation, scope, profile).act
        record = build_decision(hint.panel, decided_at=datetime.now(timezone.utc), driver=driver, profile=profile)
        DecisionStore().append(record)
    except Exception:  # noqa: BLE001 — advisory glue must never break the scrape hot path
        logger.debug('reuse-hint: failed to advise for %s', url, exc_info=True)
        return None
    return ReplayAdvice(hint=hint, scope=scope, act=act, record=record)
