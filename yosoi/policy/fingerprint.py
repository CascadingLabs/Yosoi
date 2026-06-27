"""Fingerprint signal-lane sub-policy (CAS-168 item 4).

Governs the **signal lane**: gathering a page-fingerprint/health signal forks off the read
critical path. The lane is opt-in at ``Policy`` level: no fingerprint sub-policy means no
background work. Once a caller attaches ``FingerprintPolicy()``, gathering is on and invisible
(off-path). Under backpressure the work is **deferred as low-priority background work, not
dropped** (``backpressure='defer'``); ``drop`` is the opt-in for bounded memory. **Acting** on
the signal (reuse / quarantine / re-mint) is the trust policy — default-deny — and is deliberately
*not* part of this lane.

This module also owns :class:`RecipeMatchMode` — the one recipe-specific knob that DOES act on a
fingerprint: at replay, compare a recipe's minted page fingerprint to the live page and decide
whether to trust the recipe's selectors. It lives here (not in storage) so the policy layer has no
import dependency on storage; ``yosoi.storage.recipe_fingerprint`` re-exports it.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from yosoi.policy._base import StrictInt

Backpressure = Literal['defer', 'drop']


class RecipeMatchMode(str, Enum):
    """What to do when a recipe's minted fingerprint doesn't match the live page.

    OFF              — skip fingerprint validation entirely (no recipe shape-checking).
    WARN_USE         — log a warning, use the recipe anyway (fingerprint advisory only).
    WARN_FALLTHROUGH — log a warning, DON'T use the recipe; fall through to normal discovery
                       (needs a model configured, else the scrape fails like an uncovered domain).
    FAIL             — raise; refuse to replay a recipe whose page changed shape.
    """

    OFF = 'off'
    WARN_USE = 'warn_use'
    WARN_FALLTHROUGH = 'warn_fallthrough'
    FAIL = 'fail'


class FingerprintPolicy(BaseModel):
    """Knobs for the off-path fingerprint/health signal lane."""

    model_config = ConfigDict(frozen=True)

    signal_lane: bool = True  # when this sub-policy is attached, gather off the hot path
    backpressure: Backpressure = 'defer'  # full queue → defer (keep) vs drop (bounded memory)
    max_queue: StrictInt = Field(default=256, ge=1, le=1_000_000)
    # Recipe replay validation: compare a recipe's minted fingerprint to the live page.
    # Default OFF so attaching FingerprintPolicy for the signal lane does NOT silently
    # change recipe replay behavior — opt in explicitly.
    recipe_match: RecipeMatchMode = RecipeMatchMode.OFF
