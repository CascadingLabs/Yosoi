"""Off-path page-fingerprint signal gathering for the read pipeline (CAS-168 item 4).

Builds the :class:`~yosoi.policy.signal_lane.SignalLane` for a scrape and defines its sink: the
page fingerprint is computed **in the drainer** (off the response path) and recorded. This is the
*gathering* half only — acting on the signal (drift → reuse/quarantine/re-mint) is the trust policy
(default-deny) and the similarity-vs-reference comparison is the P5 behavior layer, which needs a
reference-fingerprint store that does not exist yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from yosoi.policy.fingerprint import FingerprintPolicy
from yosoi.policy.signal_lane import SignalLane

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PageObservation:
    """A freshly-read page handed to the lane; the fingerprint is computed later, off-path."""

    url: str
    domain: str
    contract: str
    html: str
    ax_snapshot: Any | None = None


async def record_page_signal(obs: PageObservation) -> None:
    """Single-writer sink: compute the page fingerprint off the hot path and record it."""
    from yosoi.generalization.fingerprint import PageFingerprint

    fp = PageFingerprint.of(obs.html, ax_snapshot=obs.ax_snapshot)
    logger.debug(
        'page-signal domain=%s contract=%s skeleton=%d degenerate=%s',
        obs.domain,
        obs.contract,
        len(fp.skeleton),
        fp.degenerate,
    )


def build_fingerprint_lane(policy: FingerprintPolicy | None) -> SignalLane | None:
    """Build the lane when a contract/call opts in; ``None`` (the Policy default) means off.

    A present :class:`FingerprintPolicy` defaults ``signal_lane=True`` — so opting a scrape into
    gathering is just ``ys.Policy(fingerprint=ys.FingerprintPolicy())``. (Left opt-in rather than
    globally default-on while no drift consumer reads the signal; flipping the default is one line.)
    """
    if policy is None or not policy.signal_lane:
        return None
    return SignalLane(
        record_page_signal,
        enabled=True,
        backpressure=policy.backpressure,
        max_queue=policy.max_queue,
    )
