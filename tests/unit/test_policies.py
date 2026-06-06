"""ys.policies — the resolved-once, immutable pipeline policy (P6 MVP slice / P5 phase 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.policies import Policy


def test_defaults_are_deny() -> None:
    p = Policy()
    assert p.atom_reads is False  # default-deny
    assert p.trust_tier == 'strict'
    # strict serves every tier EXCEPT the fingerprint-generalized (risky) one
    assert p.allowed_sources == frozenset({'verified', 'manual', 'llm'})
    assert 'fingerprint' not in (p.allowed_sources or frozenset())


def test_yellow_serves_all_tiers() -> None:
    assert Policy(trust_tier='yellow').allowed_sources is None


def test_frozen_is_immutable() -> None:
    p = Policy()
    with pytest.raises(ValidationError):
        p.atom_reads = True  # type: ignore[misc]


@pytest.mark.parametrize('raw', ['1', 'true', 'YES', 'On'])
def test_from_env_reads_truthy_variants(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv('YOSOI_ATOM_READS', raw)
    assert Policy.from_env().atom_reads is True


def test_from_env_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('YOSOI_ATOM_READS', raising=False)
    monkeypatch.delenv('YOSOI_ATOM_TRUST', raising=False)
    p = Policy.from_env()
    assert p.atom_reads is False
    assert p.trust_tier == 'strict'


@pytest.mark.parametrize(
    ('raw', 'tier'),
    [
        ('yellow', 'yellow'),
        ('ride', 'yellow'),
        ('all', 'yellow'),
        ('strict', 'strict'),
        ('green', 'strict'),
        ('garbage', 'strict'),
    ],
)
def test_from_env_trust_tier_aliases(monkeypatch: pytest.MonkeyPatch, raw: str, tier: str) -> None:
    monkeypatch.setenv('YOSOI_ATOM_TRUST', raw)
    assert Policy.from_env().trust_tier == tier


def test_from_env_accepts_injected_mapping() -> None:
    # pure: no global env needed — the env layer can be fed a mapping (testability)
    p = Policy.from_env({'YOSOI_ATOM_READS': 'on', 'YOSOI_ATOM_TRUST': 'yellow'})
    assert p.atom_reads is True
    assert p.trust_tier == 'yellow'


# ── the cascade: defaults < env < session < contract < call ──────────────────────────────────
def test_resolve_later_layer_wins() -> None:
    base = Policy(atom_reads=False, trust_tier='strict')
    override = Policy(trust_tier='yellow')  # partial: only trust_tier set
    eff = Policy.resolve(base, override)
    assert eff.trust_tier == 'yellow'  # overridden
    assert eff.atom_reads is False  # untouched field preserved from the lower layer


def test_resolve_partial_layer_only_changes_set_fields() -> None:
    env = Policy(atom_reads=True, trust_tier='strict')
    contract = Policy(atom_reads=False)  # only atom_reads explicitly set
    eff = Policy.resolve(env, contract)
    assert eff.atom_reads is False
    assert eff.trust_tier == 'strict'  # not clobbered back to a default


def test_resolve_skips_none_layers() -> None:
    eff = Policy.resolve(Policy.from_env({'YOSOI_ATOM_TRUST': 'yellow'}), None, None)
    assert eff.trust_tier == 'yellow'


def test_resolve_empty_is_defaults() -> None:
    assert Policy.resolve() == Policy()
