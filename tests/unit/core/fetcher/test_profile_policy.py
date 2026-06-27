from __future__ import annotations

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
