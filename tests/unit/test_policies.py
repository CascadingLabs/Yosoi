"""ys.policies — the resolved-once, immutable pipeline policy (P6 MVP slice / P5 phase 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.policies import QUARANTINED_SOURCES, TRUSTED_SOURCES, Policy


def test_defaults_are_deny() -> None:
    p = Policy()
    assert p.atom_reads is False  # default-deny
    assert p.trust_tier == 'strict'
    # strict serves only the positive trusted allow-list
    assert p.allowed_sources == TRUSTED_SOURCES
    assert 'fingerprint' not in (p.allowed_sources or frozenset())


def test_strict_allowlist_is_positive_and_partitions_all_sources() -> None:
    # Guards the fail-OPEN seam: strict must be an explicit allow-list, and every known provenance
    # tier must be classified as trusted XOR quarantined. A new tier added to SOURCE_TRUST without
    # a deliberate classification fails THIS test (fail closed), never silently serves under strict.
    from yosoi.storage.atoms import SOURCE_TRUST

    assert TRUSTED_SOURCES.isdisjoint(QUARANTINED_SOURCES)
    assert set(SOURCE_TRUST) == TRUSTED_SOURCES | QUARANTINED_SOURCES


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
        ('YELLOW', 'yellow'),  # normalized (strip/lower) in the one classifier
        ('strict', 'strict'),
        ('all', 'strict'),  # NOT an alias — only yellow/ride mean "let it ride"
        ('green', 'strict'),  # NOT an alias — anything unrecognized is strict (fail closed)
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


def test_from_env_only_sets_present_vars() -> None:
    # an absent env var must NOT be materialized as an explicitly-set field (or it would clobber a
    # lower cascade layer). Empty env → nothing set → contributes nothing to a cascade.
    assert Policy.from_env({}).model_dump(exclude_unset=True) == {}
    assert set(Policy.from_env({'YOSOI_ATOM_TRUST': 'yellow'}).model_fields_set) == {'trust_tier'}


# ── the cascade: defaults < env < session < contract < call ──────────────────────────────────
def test_cascade_later_layer_wins() -> None:
    base = Policy(atom_reads=False, trust_tier='strict')
    override = Policy(trust_tier='yellow')  # partial: only trust_tier set
    eff = Policy.cascade(base, override)
    assert eff.trust_tier == 'yellow'  # overridden
    assert eff.atom_reads is False  # untouched field preserved from the lower layer


def test_cascade_partial_layer_only_changes_set_fields() -> None:
    env = Policy(atom_reads=True, trust_tier='strict')
    contract = Policy(atom_reads=False)  # only atom_reads explicitly set
    eff = Policy.cascade(env, contract)
    assert eff.atom_reads is False
    assert eff.trust_tier == 'strict'  # not clobbered back to a default


def test_cascade_env_layer_does_not_clobber_lower_hardening() -> None:
    # the dictator's reset-the-hardening case: a lower layer pins yellow, then an env layer whose
    # YOSOI_ATOM_TRUST is UNSET runs on top. The unset env var must not reset the tier.
    session = Policy(trust_tier='yellow')
    eff = Policy.cascade(session, Policy.from_env({}))
    assert eff.trust_tier == 'yellow'


def test_cascade_skips_none_layers() -> None:
    eff = Policy.cascade(Policy.from_env({'YOSOI_ATOM_TRUST': 'yellow'}), None, None)
    assert eff.trust_tier == 'yellow'


def test_cascade_empty_is_defaults() -> None:
    assert Policy.cascade() == Policy()
