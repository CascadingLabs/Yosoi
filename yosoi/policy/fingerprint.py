"""Fingerprint signal-lane sub-policy (CAS-168 item 4).

Governs the **signal lane**: gathering a page-fingerprint/health signal forks off the read
critical path. **Gathering** is default-on and invisible (off-path). Under backpressure the work
is **deferred as low-priority background work, not dropped** (``backpressure='defer'``); ``drop``
is the opt-in for bounded memory. **Acting** on the signal (reuse / quarantine / re-mint) is the
trust policy — default-deny — and is deliberately *not* part of this lane.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from yosoi.policy._base import StrictInt

Backpressure = Literal['defer', 'drop']


class FingerprintPolicy(BaseModel):
    """Knobs for the off-path fingerprint/health signal lane."""

    model_config = ConfigDict(frozen=True)

    signal_lane: bool = True  # gather the signal at all (default-on, invisible, off the hot path)
    backpressure: Backpressure = 'defer'  # full queue → defer (keep) vs drop (bounded memory)
    max_queue: StrictInt = Field(default=256, ge=1, le=1_000_000)
