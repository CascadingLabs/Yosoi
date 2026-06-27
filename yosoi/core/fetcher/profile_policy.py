"""Resolve page profile policy into browser identity cascades."""

from __future__ import annotations

from typing import Any

from yosoi.core.fetcher.identity import BrowserIdentity, IdentityCascade
from yosoi.policy.page import BrowserProfilePolicy


def _profile_record(item: dict[str, Any]) -> dict[str, Any]:
    nested = item.get('profile')
    return nested if isinstance(nested, dict) else item


def cascade_from_profile_policy(
    policy: BrowserProfilePolicy | None,
    *,
    registry: Any | None = None,
) -> tuple[IdentityCascade | None, int]:
    """Build an ``IdentityCascade`` from a VoidCrawl-managed profile policy.

    The per-domain winner cache stays inside ``JSFetcher``; this helper only
    resolves the ordered candidate identities for the current run.
    """
    if policy is None or (not policy.profile and not policy.pool):
        return None, 3

    active_cap = int(policy.max_live)
    if registry is None:
        try:
            import voidcrawl
        except ImportError as exc:
            raise RuntimeError(
                'PagePolicy.profile requires a VoidCrawl build with ProfileRegistry support. '
                'Install the matching local VoidCrawl checkout or upgrade voidcrawl.'
            ) from exc

        ProfileRegistry = getattr(voidcrawl, 'ProfileRegistry', None)
        if ProfileRegistry is None:
            raise RuntimeError(
                'PagePolicy.profile requires a VoidCrawl build with ProfileRegistry support. '
                'Install the matching local VoidCrawl checkout or upgrade voidcrawl.'
            )
        registry = ProfileRegistry.default()

    if policy.profile:
        description = registry.describe_profile(policy.profile)
        profile = _profile_record(description)
        return (
            IdentityCascade(
                (
                    BrowserIdentity(
                        id=str(profile['id']),
                        profile_dir=str(profile['path']),
                        headful=policy.headful,
                    ),
                )
            ),
            active_cap,
        )

    assert policy.pool is not None
    resolved = registry.resolve_pool(policy.pool)
    pool = resolved['pool']
    identities = tuple(
        BrowserIdentity(
            id=str(_profile_record(item)['id']),
            profile_dir=str(_profile_record(item)['path']),
            headful=policy.headful,
        )
        for item in resolved['profiles']
    )
    if not identities:
        raise ValueError(f'profile pool {policy.pool!r} is empty')
    max_live = min(active_cap, int(pool.get('max_active') or active_cap), len(identities))
    return IdentityCascade(identities), max_live


__all__ = ['cascade_from_profile_policy']
