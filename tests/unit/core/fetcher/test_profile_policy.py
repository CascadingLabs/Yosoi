from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from yosoi.core.fetcher.profile_policy import cascade_from_profile_policy
from yosoi.policy import BrowserProfilePolicy


class _Registry:
    def describe_profile(self, profile_id: str) -> dict[str, object]:
        return {'id': profile_id, 'path': f'/profiles/{profile_id}', 'status': 'available'}

    def resolve_pool(self, name: str) -> dict[str, object]:
        assert name == 'google-serp'
        return {
            'pool': {'name': name, 'profile_ids': ['google-001', 'google-002'], 'max_active': 1},
            'profiles': [
                {'id': 'google-001', 'path': '/profiles/google-001', 'status': 'available'},
                {'id': 'google-002', 'path': '/profiles/google-002', 'status': 'available'},
            ],
        }


def test_single_profile_policy_builds_one_identity() -> None:
    cascade, max_live = cascade_from_profile_policy(
        BrowserProfilePolicy(profile='google-001', headful=True, max_live=3),
        registry=_Registry(),
    )

    assert cascade is not None
    assert max_live == 3
    identities = cascade.ordered()
    assert len(identities) == 1
    assert identities[0].id == 'google-001'
    assert identities[0].profile_dir == '/profiles/google-001'
    assert identities[0].headful is True


def test_pool_policy_preserves_order_and_caps_live_count() -> None:
    cascade, max_live = cascade_from_profile_policy(
        BrowserProfilePolicy(pool='google-serp', max_live=3),
        registry=_Registry(),
    )

    assert cascade is not None
    assert [identity.id for identity in cascade.ordered()] == ['google-001', 'google-002']
    assert max_live == 1


def test_empty_profile_policy_returns_default() -> None:
    assert cascade_from_profile_policy(None) == (None, 3)
    assert cascade_from_profile_policy(BrowserProfilePolicy()) == (None, 3)


def test_registry_defaults_from_voidcrawl_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ProfileRegistry:
        @staticmethod
        def default() -> _Registry:
            return _Registry()

    monkeypatch.setitem(sys.modules, 'voidcrawl', SimpleNamespace(ProfileRegistry=_ProfileRegistry))

    cascade, max_live = cascade_from_profile_policy(BrowserProfilePolicy(profile='google-001', max_live=2))

    assert cascade is not None
    assert cascade.ordered()[0].id == 'google-001'
    assert max_live == 2


def test_missing_voidcrawl_profile_registry_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, 'voidcrawl', SimpleNamespace())

    with pytest.raises(RuntimeError, match='ProfileRegistry support'):
        cascade_from_profile_policy(BrowserProfilePolicy(profile='google-001'))


def test_missing_voidcrawl_module_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, 'voidcrawl', None)

    with pytest.raises(RuntimeError, match='ProfileRegistry support'):
        cascade_from_profile_policy(BrowserProfilePolicy(profile='google-001'))


def test_empty_profile_pool_raises() -> None:
    class EmptyRegistry:
        def resolve_pool(self, name: str) -> dict[str, object]:
            return {'pool': {'name': name}, 'profiles': []}

    with pytest.raises(ValueError, match='profile pool'):
        cascade_from_profile_policy(BrowserProfilePolicy(pool='empty'), registry=EmptyRegistry())
