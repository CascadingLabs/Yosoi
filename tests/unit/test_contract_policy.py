"""Per-contract Policy override folded into the api-edge cascade (CAS-168 item 3)."""

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.api import _edge_policy


class _EdgePlain(ys.Contract):
    title: str


class _EdgeYellow(ys.Contract):
    title: str
    policy = ys.Policy(trust_tier='yellow')


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('YOSOI_ATOM_READS', raising=False)
    monkeypatch.delenv('YOSOI_ATOM_TRUST', raising=False)


def test_contract_without_policy_uses_defaults() -> None:
    effective = _edge_policy(_EdgePlain, None)
    assert effective.trust_tier == 'strict'
    assert effective.atom_reads is False


def test_contract_policy_is_applied() -> None:
    assert _edge_policy(_EdgeYellow, None).trust_tier == 'yellow'


def test_call_site_overrides_contract() -> None:
    # contract pins yellow; the per-call override wins (call-site is highest precedence).
    assert _edge_policy(_EdgeYellow, ys.Policy(trust_tier='strict')).trust_tier == 'strict'


def test_contract_and_call_site_compose_on_different_fields() -> None:
    effective = _edge_policy(_EdgeYellow, ys.Policy(atom_reads=True))
    assert effective.trust_tier == 'yellow'  # from the contract layer
    assert effective.atom_reads is True  # from the call-site layer
