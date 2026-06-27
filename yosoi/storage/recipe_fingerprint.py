"""Recipe fingerprint validation — gate recipe replay on live-page shape drift.

Drop in as ``yosoi/storage/recipe_fingerprint.py``.

At replay, if a recipe carries a page fingerprint for the domain being scraped, compare it
to the live page's fingerprint and decide — per :class:`RecipeMatchMode` — whether to trust
the recipe's selectors. The comparison delegates to ``PageFingerprint.matches`` (the
conjunctive, fail-closed matcher); nothing here reimplements similarity.

``RecipeMatchMode`` is defined in ``yosoi.policy.fingerprint`` and re-exported here so callers
can import it from either layer; storage depends on policy, never the reverse.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from yosoi.policy.fingerprint import RecipeMatchMode  # re-exported; single source of truth

if TYPE_CHECKING:
    from yosoi.generalization.fingerprint import PageFingerprint, PageSimilarity

__all__ = ['RecipeFingerprintMismatch', 'RecipeMatchMode', 'evaluate_recipe_fingerprint']

logger = logging.getLogger(__name__)


class RecipeFingerprintMismatch(ValueError):
    """Raised (FAIL mode only) when a recipe's page no longer matches its minted fingerprint.

    Distinct from ``recipe_loader.StaleRecipeError`` (which means the SELECTORS failed per-field
    verification): this means the PAGE SHAPE drifted — a structural signal that can fire before
    any single selector visibly breaks. Surfacing them separately lets a consumer tell "the site
    reshaped" from "this specific selector broke".
    """

    def __init__(self, source: str, domain: str, similarity: PageSimilarity) -> None:
        """Build the message naming the recipe, domain, and weakest fingerprint layer."""
        self.source = source
        self.domain = domain
        self.similarity = similarity
        layers: dict[str, float] = {
            'skeleton': similarity.skeleton.weighted,
            'semantic': similarity.semantic.weighted,
        }
        for name in ('identity', 'ax', 'network', 'endpoint'):
            layer = getattr(similarity, name, None)
            if layer is not None:
                layers[name] = layer.weighted
        worst = min(layers, key=layers.get)
        super().__init__(
            f'Recipe {source!r} no longer matches the live page for {domain}: '
            f'page shape drifted (weakest layer {worst!r}={layers[worst]:.2f}, '
            f'aggregate={similarity.score:.2f}). The site was likely restructured '
            f'since the recipe was minted. Get a newer recipe, pass model=... to '
            f"re-discover, or set the recipe match mode to 'warn_use'/'warn_fallthrough'."
        )


def evaluate_recipe_fingerprint(
    *,
    recipe_fp: PageFingerprint | None,
    live_html: str,
    domain: str,
    source: str,
    mode: RecipeMatchMode,
    ax_snapshot: object = None,
    headers: object = None,
    endpoints: object = None,
) -> bool:
    """Decide whether a preloaded recipe should be used for this live page.

    Returns True to USE the recipe (proceed with preloaded selectors), False to SKIP it
    (fall through to discovery). Raises :class:`RecipeFingerprintMismatch` only in FAIL mode.

    Always returns True (graceful no-op) when: mode is OFF, the recipe carries no fingerprint
    for this domain (v1 recipe / not minted), or the live page fingerprints as degenerate
    (too thin to judge — a transient blank/JS-shell fetch must not veto a good recipe).
    """
    if mode is RecipeMatchMode.OFF or recipe_fp is None:
        return True

    from yosoi.generalization.fingerprint import PageFingerprint

    live_fp = PageFingerprint.of(live_html, ax_snapshot=ax_snapshot, headers=headers, endpoints=endpoints)

    if live_fp.degenerate:
        logger.info(
            'Recipe %r: live page for %s fingerprinted as degenerate (too thin to validate) '
            '— using recipe without fingerprint check.',
            source,
            domain,
        )
        return True

    sim = live_fp.similarity(recipe_fp)
    if sim.same_shape:
        logger.debug('Recipe %r fingerprint MATCH for %s (aggregate=%.2f).', source, domain, sim.score)
        return True

    if mode is RecipeMatchMode.FAIL:
        raise RecipeFingerprintMismatch(source, domain, sim)
    if mode is RecipeMatchMode.WARN_FALLTHROUGH:
        logger.warning(
            'Recipe %r fingerprint MISMATCH for %s (aggregate=%.2f) — NOT using the recipe; '
            'falling through to discovery. Pass model=... or get a newer recipe.',
            source,
            domain,
            sim.score,
        )
        return False
    logger.warning(
        'Recipe %r fingerprint MISMATCH for %s (aggregate=%.2f) — using the recipe anyway '
        '(match mode=warn_use). Selectors may be stale.',
        source,
        domain,
        sim.score,
    )
    return True
