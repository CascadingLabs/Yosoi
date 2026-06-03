"""Tests for the reuse-hint review CLI (yosoi-generalization)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from yosoi.cli.generalization import cli
from yosoi.generalization.advise import advise_reuse
from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.policy import ReuseProfile
from yosoi.generalization.store import DecisionStore
from yosoi.generalization.trust import Trust, build_decision

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)
_HIST = {'div': 10, 'a': 5, 'span': 8}
SEED = PageObservation(url='https://x.com/', rows=10, tag_hist=_HIST)
SIBLING = PageObservation(url='https://x.com/page/2', rows=10, tag_hist=_HIST)


@pytest.fixture
def store(tmp_path: Path, mocker: MockerFixture) -> DecisionStore:
    """A DecisionStore (and CLI) pointed at an isolated tmp ledger."""
    home = tmp_path / 'generalization'
    home.mkdir()
    mocker.patch('yosoi.generalization.store.init_yosoi', return_value=home)
    return DecisionStore()


def _seed_one(store: DecisionStore) -> str:
    # Force STRICT so the row lands quarantined + pending, independent of env.
    dec = build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test', profile=ReuseProfile.STRICT)
    store.append(dec)
    return dec.id


def test_review_list_json_shows_pending(store: DecisionStore) -> None:
    """`review list --json` surfaces the pending decision by id."""
    decision_id = _seed_one(store)
    result = CliRunner().invoke(cli, ['review', 'list', '--json'])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert [r['id'] for r in rows] == [decision_id]


def test_review_promote_verifies_and_clears_queue(store: DecisionStore) -> None:
    """Promote confirms the decision and removes it from the pending list."""
    decision_id = _seed_one(store)
    result = CliRunner().invoke(cli, ['review', 'promote', decision_id])
    assert result.exit_code == 0
    assert store.get(decision_id).trust is Trust.VERIFIED
    listed = CliRunner().invoke(cli, ['review', 'list', '--json'])
    assert json.loads(listed.output) == []


def test_review_reject_marks_rejected(store: DecisionStore) -> None:
    """Reject refutes the decision."""
    decision_id = _seed_one(store)
    result = CliRunner().invoke(cli, ['review', 'reject', decision_id])
    assert result.exit_code == 0
    assert store.get(decision_id).trust is Trust.REJECTED


def test_review_promote_unknown_id_fails(store: DecisionStore) -> None:
    """An unknown id is a clean CLI error, not a crash."""
    result = CliRunner().invoke(cli, ['review', 'promote', 'deadbeef'])
    assert result.exit_code != 0


def test_summary_json_totals(store: DecisionStore) -> None:
    """`summary --json` reports the folded ledger totals."""
    _seed_one(store)
    result = CliRunner().invoke(cli, ['summary', '--json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['total'] == 1
