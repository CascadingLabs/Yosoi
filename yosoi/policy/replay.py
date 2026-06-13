"""Replay policy — declarative recipe replay for the public Policy tree (CAS-152 x CAS-214).

A :class:`ReplayPolicy` carries a *reference* to a minted recipe — a local
``.json`` path, an ``https://`` URL, or a ``gh:owner/repo/path@ref`` shorthand —
never the recipe payload itself. That keeps the policy artifact serializable,
``policy_hash``-stable, and secret-free: a private-repo token travels only as a
:class:`SecretRef`, and the raw value resolves into the execution-time spec
exactly once (see :mod:`yosoi.policy.replay_resolve`).

Guardrail placement (deliberate, because of cascade semantics):

* **Construction-time** checks are *intra-field format* checks only — plaintext
  ``http://`` refs and malformed ``recipe_id`` pins are rejected immediately.
* **Relational** checks (``on_miss='fail'`` without a recipe, ``force`` vs
  replay, credential without a recipe) live in
  :func:`yosoi.policy.replay_resolve.resolve_replay_values`, AFTER the cascade
  merge. A session layer that only sets ``on_miss='fail'`` must stay
  constructible on its own — the recipe ref may legitimately arrive from a
  different layer (env or call site), so rejecting the partial layer at
  construction would make that composition impossible.

Import-light by design: this module pulls pydantic + stdlib only. The recipe
loader (httpx) is imported lazily at hydration time so ``import yosoi`` stays
inside the cold-import budget (see ``tests/unit/test_policy_lazy.py``).

Intended location: ``yosoi/policy/replay.py``.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# WIRING: adjust to wherever SecretRef actually lives in the policy package
# (the CAS-214 branch exposes it as ys.SecretRef).
from yosoi.policy.secrets import SecretRef

#: Recipe identity pins are full content hashes, matching ``RecipeBundle.recipe_id``.
_RECIPE_ID_PREFIX = 'sha256:'

#: Env surface absorbed by :meth:`ReplayPolicy.layer_from_env` (wired into
#: ``Policy.from_env`` alongside YOSOI_MODEL / YOSOI_FORCE / ...).
ENV_RECIPE = 'YOSOI_RECIPE'
ENV_RECIPE_ON_MISS = 'YOSOI_RECIPE_ON_MISS'

OnMiss = Literal['discover', 'fail']


class ReplayPolicy(BaseModel):
    """Frozen, serializable configuration for recipe-based replay.

    Attributes:
        recipe: Recipe reference — local ``.json`` path, ``https://`` URL, or
            ``gh:owner/repo/path@ref``. ``None`` disables replay (the default).
        recipe_id: Optional pinned content hash (``sha256:...``). When set, a
            fetched bundle whose ``recipe_id`` differs fails closed — this is
            the lockfile-grade guarantee for refs that can move (``@main``).
        on_miss: What to do when a scraped URL's domain is not covered by the
            recipe. ``'discover'`` (default) falls through to normal LLM
            discovery; ``'fail'`` raises before any fetch or model spend — the
            zero-LLM replay guarantee. Note this governs *domain coverage*,
            never fetch/verification failures of an explicitly named recipe:
            those always fail loudly regardless of ``on_miss``.
        verify_fixtures: Replay the bundle's validation fixtures at hydration
            time before trusting its selectors. Forward-compat seam — resolved
            into the run spec but not yet consumed (same posture as
            ``DiscoveryPolicy.lesson_cache``).
        credential_ref: Secret *reference* (e.g. ``SecretRef.env('GITHUB_TOKEN')``)
            used to fetch recipes from private hosts. The raw token never
            appears in ``model_dump()``, ``repr()``, or ``policy_hash`` — it
            resolves only into the execution-time :class:`ResolvedReplay`.

    """

    model_config = ConfigDict(frozen=True)

    recipe: str | None = None
    recipe_id: str | None = None
    on_miss: OnMiss = 'discover'
    verify_fixtures: bool = False
    credential_ref: SecretRef | None = None

    @model_validator(mode='after')
    def _validate_formats(self) -> ReplayPolicy:
        """Reject malformed refs at construction (format checks only — see module docstring)."""
        if self.recipe is not None and self.recipe.startswith('http://'):
            raise ValueError(
                'ReplayPolicy.recipe must use https:// for remote recipes. '
                'Integrity hashing protects the artifact at rest, not a plaintext fetch '
                'an attacker can rewrite end-to-end (recipe_id travels inside the same file).'
            )
        if self.recipe_id is not None and not self.recipe_id.startswith(_RECIPE_ID_PREFIX):
            raise ValueError(
                f'ReplayPolicy.recipe_id must be a {_RECIPE_ID_PREFIX!r}-prefixed content hash '
                f'(got {self.recipe_id!r}); copy it from `yosoi recipe inspect` / manifest.'
            )
        return self

    @classmethod
    def layer_from_env(cls) -> ReplayPolicy | None:
        """Build the env-derived replay layer, or ``None`` when no replay env vars are set.

        Returns ``None`` rather than an empty model so ``Policy.from_env`` can skip
        the sub-policy entirely — with cascade's ``exclude_unset`` merge, an empty
        layer is harmless, but an absent one is cheaper and keeps ``policy_hash``
        identical to today's for users who never touch replay.

        Returns:
            A partial :class:`ReplayPolicy` carrying only the fields present in the
            environment (``YOSOI_RECIPE``, ``YOSOI_RECIPE_ON_MISS``), or ``None``.

        """
        kwargs: dict[str, str] = {}
        if recipe := os.getenv(ENV_RECIPE):
            kwargs['recipe'] = recipe
        if on_miss := os.getenv(ENV_RECIPE_ON_MISS):
            kwargs['on_miss'] = on_miss  # Literal validation rejects unknown values loudly
        return cls(**kwargs) if kwargs else None
