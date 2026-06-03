"""Tests for the advisory reuse hint and the decision-record store."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from yosoi.generalization.advise import ReuseHint, SuggestedAction, advise_reuse
from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.store import DecisionStore
from yosoi.generalization.trust import Outcome, Trust, build_decision

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)

SEED = PageObservation(
    url='https://qscrape.dev/',
    rows=10,
    tag_hist={'span': 69, 'div': 54, 'a': 43, 'blockquote': 10, 'i': 43, 'p': 16},
)
SIBLING = PageObservation(
    url='https://qscrape.dev/page/2/',
    rows=10,
    tag_hist={'span': 69, 'div': 54, 'a': 42, 'blockquote': 10, 'i': 43, 'p': 16},
)
DETAIL = PageObservation(url='https://qscrape.dev/author/x', rows=0, tag_hist={'div': 5, 'p': 2})


@pytest.fixture
def store(tmp_path: Path, mocker: MockerFixture) -> DecisionStore:
    """A DecisionStore writing to an isolated tmp directory.

    Mirrors the repo storage-test convention: patch ``init_yosoi`` rather than
    relying on cwd/env, so the ledger never touches the real ``.yosoi``.
    """
    ledger_dir = tmp_path / 'generalization'
    ledger_dir.mkdir()
    mocker.patch('yosoi.generalization.store.init_yosoi', return_value=ledger_dir)
    return DecisionStore()


def test_advise_reuse_suggests_try_reuse_for_sibling() -> None:
    """A same-shape sibling listing yields a TRY_REUSE advisory hint."""
    hint = advise_reuse(SEED, SIBLING)
    assert isinstance(hint, ReuseHint)
    assert hint.suggested_action is SuggestedAction.TRY_REUSE
    assert hint.advisory is True
    assert 0.0 <= hint.confidence <= 1.0


def test_advise_reuse_suggests_rediscover_for_detail() -> None:
    """A zero-row detail page yields a REDISCOVER advisory hint."""
    hint = advise_reuse(SEED, DETAIL)
    assert hint.suggested_action is SuggestedAction.REDISCOVER


def test_hint_prompt_line_marks_itself_advisory() -> None:
    """The prompt line is prefixed so an agent knows it can be ignored."""
    line = advise_reuse(SEED, SIBLING).as_prompt_line()
    assert line.startswith('[reuse-hint · advisory]')
    assert 'TRY_REUSE' in line


def test_hint_carries_full_panel() -> None:
    """The compact hint still exposes the full underlying signal panel."""
    hint = advise_reuse(SEED, DETAIL)
    assert hint.panel.reading('tag_cosine') is not None
    assert hint.panel.replay_route == '/author/x'


def test_store_append_and_reload_roundtrip(store: DecisionStore) -> None:
    """A persisted decision reloads identically from the JSONL ledger."""
    decision = build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test')
    store.append(decision)

    reloaded = store.load_all()
    assert len(reloaded) == 1
    assert reloaded[0].panel.replay_url == SIBLING.url
    assert reloaded[0].driver == 'test'


def test_store_summary_tallies_verdicts_and_outcomes(store: DecisionStore) -> None:
    """The summary counts totals, per-verdict, per-outcome, and overrides."""
    store.append(build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test'))
    store.append(build_decision(advise_reuse(SEED, DETAIL).panel, decided_at=_NOW, driver='test'))

    summary = store.summary()
    assert summary['total'] == 2
    assert summary['outcome:pending'] == 2
    assert summary['overrides'] == 0


def test_store_back_filled_outcome_is_persisted(store: DecisionStore) -> None:
    """A promoted (outcome back-filled) decision persists its resolved state."""
    decision = build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test')
    store.append(decision.promote(confirmed=True))

    reloaded = store.load_all()[0]
    assert reloaded.outcome is Outcome.CONFIRMED
    assert reloaded.trust is Trust.VERIFIED


def test_decide_folds_to_current_without_duplicating(store: DecisionStore) -> None:
    """A promotion appends a correction row; current() folds to the latest state."""
    decision = build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test')
    store.append(decision)
    resolved = store.decide(decision.id, confirmed=True)

    assert resolved is not None
    assert resolved.trust is Trust.VERIFIED
    assert len(store.load_all()) == 2  # original + correction, append-only
    current = store.current()
    assert len(current) == 1  # folded to one
    assert current[0].trust is Trust.VERIFIED


def test_decide_unknown_id_is_none(store: DecisionStore) -> None:
    """Deciding an unknown id is a no-op returning None."""
    assert store.decide('nope', confirmed=True) is None


def test_load_all_skips_corrupt_line(store: DecisionStore) -> None:
    """A torn/garbage line is skipped, not fatal."""
    store.append(build_decision(advise_reuse(SEED, SIBLING).panel, decided_at=_NOW, driver='test'))
    (store.storage_dir / '2026-01-02.jsonl').open('a', encoding='utf-8').write('{not json\n')
    assert len(store.load_all()) == 1
