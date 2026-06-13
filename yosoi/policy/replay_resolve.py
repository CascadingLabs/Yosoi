"""Edge resolution + hydration for :class:`~yosoi.policy.replay.ReplayPolicy`.

Split into the same two phases ``resolve_run_spec`` already enforces for the
rest of the policy tree (the CAS-119/168 purity loop):

1. :func:`resolve_replay_values` — SYNC, called from inside
   ``Policy.resolve_run_spec`` after the cascade merge. Reads env/secrets
   (``SecretRef`` resolution), runs the *relational* guardrails the frozen model
   deliberately defers (force-vs-replay, ``on_miss='fail'`` without a recipe),
   and rewrites ``gh:`` refs into raw URLs. Pure values in, pure values out —
   the result is a :class:`ResolvedReplay` carried on the run spec.
2. :func:`hydrate_recipe` — ASYNC network/disk IO, called at the ``ys.scrape``
   edge just before ``Pipeline`` construction. Fetches + verifies the bundle
   (lazy-importing the httpx-backed loader), enforces the pinned ``recipe_id``,
   and hands back the value the pure core consumes:
   ``Pipeline(..., preloaded_snapshots=bundle.selectors)``.

:func:`assert_recipe_covers` is the ``on_miss='fail'`` preflight: it checks
every target URL's domain against the bundle BEFORE any fetch or model spend,
mirroring ``SelectorStorage._preloaded_for_domain``'s one-label subdomain
fallback exactly, so the edge guarantee and the storage lookup can never
disagree about coverage.

Intended location: ``yosoi/policy/replay_resolve.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from yosoi.policy.replay import OnMiss, ReplayPolicy

if TYPE_CHECKING:
    from yosoi.models.recipe import RecipeBundle
    from yosoi.models.snapshot import SnapshotMap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedReplay:
    """Execution-time replay values — refs rewritten, secrets resolved, no IO yet.

    Attributes:
        url: Fully resolved recipe location (``gh:`` already rewritten to a
            ``raw.githubusercontent.com`` URL; local paths pass through).
        expected_recipe_id: Pinned content hash to enforce at hydration, or None.
        on_miss: Domain-coverage behavior ('discover' falls through, 'fail' preflights).
        verify_fixtures: Whether hydration should replay validation fixtures.
        token: Raw fetch credential resolved from the policy's ``credential_ref``.
            ``repr=False`` keeps it out of logs/tracebacks, matching the run
            spec's secret-hygiene posture (the live value stays reachable for use).

    """

    url: str
    expected_recipe_id: str | None
    on_miss: OnMiss
    verify_fixtures: bool
    token: str | None = field(default=None, repr=False)

    @property
    def model_optional(self) -> bool:
        """Return True when this replay run needs no LLM at all.

        ``on_miss='fail'`` guarantees zero discovery, so ``resolve_run_spec``
        should consult this BEFORE fail-fasting on a missing provider key —
        a pure replay run must not demand a credential it will never use.
        """
        return self.on_miss == 'fail'


def resolve_replay_values(replay: ReplayPolicy | None, *, force: bool = False) -> ResolvedReplay | None:
    """Resolve the cascaded replay layer into execution-time values (sync, env-only).

    This is the single place the relational guardrails run — after the cascade,
    so a recipe ref contributed by one layer composes with an ``on_miss`` set by
    another (see the placement note in :mod:`yosoi.policy.replay`).

    Args:
        replay: The post-cascade :class:`ReplayPolicy`, or ``None`` when no layer set one.
        force: The resolved force flag from the rest of the spec. Forcing
            rediscovery while supplying pre-discovered selectors is a
            contradiction; it raises here rather than silently picking a winner.

    Returns:
        A :class:`ResolvedReplay`, or ``None`` when replay is not configured.

    Raises:
        ValueError: On force-vs-replay conflict, ``on_miss='fail'`` with no
            recipe, or a credential_ref with no recipe to spend it on.

    """
    if replay is None or (replay.recipe is None and replay.on_miss == 'discover' and replay.credential_ref is None):
        if replay is not None and replay.on_miss == 'fail':
            raise ValueError(
                "ReplayPolicy(on_miss='fail') requires a recipe: the zero-LLM guarantee "
                'is meaningless without selectors to replay. Set ReplayPolicy.recipe '
                '(or YOSOI_RECIPE) in some layer of the cascade.'
            )
        return None

    if replay.recipe is None:
        # credential_ref (and/or recipe_id) without a recipe anywhere in the cascade.
        raise ValueError(
            'ReplayPolicy carries credential_ref/recipe_id but no recipe ref survived the '
            'cascade — nothing to fetch. Set ReplayPolicy.recipe in some layer.'
        )

    if force:
        raise ValueError(
            'force=True contradicts ReplayPolicy.recipe: forcing rediscovery while '
            'supplying pre-discovered selectors is ambiguous. Drop one of the two '
            '(use force to re-mint, or the recipe to replay — not both).'
        )

    token: str | None = None
    if replay.credential_ref is not None:
        # WIRING: SecretRef resolution — reuse the same accessor resolve_run_spec
        # uses for ModelPolicy.credential_ref so masking/repr semantics stay uniform.
        token = replay.credential_ref.resolve()

    # Lazy import: the resolver is pure string work, but it lives in the storage
    # layer (single source of truth — the legacy ``contract='gh:...'`` overload
    # routes through it too), and policy modules must not eagerly pull storage.
    from yosoi.storage.recipe_loader import resolve_recipe_ref

    return ResolvedReplay(
        url=resolve_recipe_ref(replay.recipe),
        expected_recipe_id=replay.recipe_id,
        on_miss=replay.on_miss,
        verify_fixtures=replay.verify_fixtures,
        token=token,
    )


async def hydrate_recipe(resolved: ResolvedReplay) -> RecipeBundle:
    """Fetch, parse, and verify the resolved recipe — the IO half of the edge.

    Lazy-imports the httpx-backed loader so policy modules never pay its import
    cost. All loader failure modes (schema mismatch, integrity failure, empty
    selectors, pinned-id mismatch) raise regardless of ``on_miss`` — a named
    recipe that cannot be verified is a broken artifact, not a coverage miss.

    Args:
        resolved: Execution-time replay values from :func:`resolve_replay_values`.

    Returns:
        The verified :class:`RecipeBundle`. Pass ``bundle.selectors`` to
        ``Pipeline(preloaded_snapshots=...)`` (or onto the run spec).

    """
    from yosoi.storage.recipe_loader import load_recipe

    bundle = await load_recipe(
        resolved.url,
        expected_recipe_id=resolved.expected_recipe_id,
        token=resolved.token,
    )
    logger.info(
        'Recipe hydrated: id=%s domains=%s on_miss=%s',
        bundle.recipe_id,
        list(bundle.selectors.keys()),
        resolved.on_miss,
    )
    return bundle


def recipe_covers_domain(snapshots: dict[str, SnapshotMap], domain: str) -> bool:
    """Return True when the bundle covers *domain*, with the storage layer's exact fallback.

    Mirrors ``SelectorStorage._preloaded_for_domain``: an exact key match, else
    strip ONE leading label (``www.example.com`` → ``example.com``). Kept
    byte-for-byte equivalent on purpose — if the preflight and the storage
    lookup ever disagree about coverage, ``on_miss='fail'`` would lie.

    Args:
        snapshots: The bundle's ``{domain: SnapshotMap}`` map.
        domain: Bare (sub)domain extracted from a target URL.

    Returns:
        Whether replay can serve this domain from the bundle.

    """
    if domain in snapshots:
        return True
    parts = domain.split('.', 1)
    return len(parts) == 2 and parts[1] in snapshots


def assert_recipe_covers(bundle: RecipeBundle, urls: list[str], on_miss: OnMiss) -> None:
    """Preflight the ``on_miss='fail'`` guarantee before any fetch or model spend.

    Args:
        bundle: The hydrated recipe.
        urls: Every target URL of the run.
        on_miss: No-op under ``'discover'``; under ``'fail'`` every URL's domain
            must be covered (with subdomain fallback).

    Raises:
        ValueError: Listing every uncovered domain, when ``on_miss='fail'``.

    """
    if on_miss != 'fail':
        return
    from yosoi.utils.urls import extract_domain

    uncovered = sorted({d for url in urls if not recipe_covers_domain(bundle.selectors, d := extract_domain(url))})
    if uncovered:
        raise ValueError(
            f'Recipe does not cover domain(s) {", ".join(uncovered)} and '
            f"ReplayPolicy.on_miss='fail' forbids falling back to discovery. "
            f'Covered: {", ".join(sorted(bundle.selectors))}. '
            "Re-mint the recipe for these domains or set on_miss='discover'."
        )
