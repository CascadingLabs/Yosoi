"""Tests for the flag-gated pipeline reuse-hint glue (seeds + integration)."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from yosoi.generalization import integration as reuse_hint
from yosoi.generalization.advise import SuggestedAction
from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.seeds import domain_key, load_seed, save_seed

pytestmark = pytest.mark.unit

# A listing seed and a same-shape sibling (TRY_REUSE) on the same domain.
_SEED_HTML = '<html><body class="listing-page"><div class="q">a</div><div class="q">b</div>'
_SEED_HTML += '<div class="q">c</div><div class="q">d</div><p>x</p></body></html>'
_SIBLING_HTML = _SEED_HTML.replace('listing-page', 'listing-page top-page')
# A detail page on the same domain (REDISCOVER): zero rows, prose-heavy.
_DETAIL_HTML = '<html><body class="profile-page"><p>bio</p><p>more</p></body></html>'

_SEED_URL = 'https://finance.example.com/quote/AAPL'
_SIBLING_URL = 'https://finance.example.com/quote/MSFT'
_DETAIL_URL = 'https://finance.example.com/user/jane'


@pytest.fixture
def isolated_home(tmp_path: Path, mocker: MockerFixture) -> Path:
    """Point both the seed store and the ledger at an isolated tmp dir."""
    home = tmp_path / 'generalization'
    home.mkdir()
    mocker.patch('yosoi.generalization.seeds.init_yosoi', return_value=home)
    mocker.patch('yosoi.generalization.store.init_yosoi', return_value=home)
    return home


def test_domain_key_strips_www_and_port() -> None:
    """The domain key mirrors the cache's host-not-URL keying."""
    assert domain_key('https://www.finance.example.com:443/quote/AAPL') == 'finance_example_com'


def test_seed_roundtrips_by_domain(isolated_home: Path) -> None:
    """A saved seed reloads for any URL on the same domain."""
    save_seed(PageObservation(url=_SEED_URL, rows=4, body_class='listing-page'))
    loaded = load_seed(_SIBLING_URL)  # different path, same domain
    assert loaded is not None
    assert loaded.rows == 4


def test_disabled_flag_is_a_no_op(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag off nothing is written and no hint is produced."""
    monkeypatch.delenv('YOSOI_REUSE_HINT', raising=False)
    reuse_hint.record_seed(_SEED_URL, _SEED_HTML, row_selector='div.q')
    assert load_seed(_SEED_URL) is None
    assert reuse_hint.hint_for_replay(_SIBLING_URL, _SIBLING_HTML, row_selector='div.q') is None


def test_enabled_sibling_yields_try_reuse_and_logs_row(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag on: a same-shape sibling gets TRY_REUSE and a ledger row is written."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    reuse_hint.record_seed(_SEED_URL, _SEED_HTML, row_selector='div.q')
    advice = reuse_hint.hint_for_replay(_SIBLING_URL, _SIBLING_HTML, row_selector='div.q')
    assert advice is not None
    assert advice.hint.suggested_action is SuggestedAction.TRY_REUSE
    assert sorted(isolated_home.glob('*.jsonl'))  # a decision row was persisted


def test_enabled_detail_page_yields_rediscover(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag on: a same-domain detail page is refused (the REFUSE→re-discover win)."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    reuse_hint.record_seed(_SEED_URL, _SEED_HTML, row_selector='div.q')
    advice = reuse_hint.hint_for_replay(_DETAIL_URL, _DETAIL_HTML, row_selector='div.q')
    assert advice is not None
    assert advice.hint.suggested_action is SuggestedAction.REDISCOVER


def test_enabled_without_seed_returns_none(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag on but no seed yet (first visit): no hint, no crash."""
    monkeypatch.setenv('YOSOI_REUSE_HINT', '1')
    assert reuse_hint.hint_for_replay(_SIBLING_URL, _SIBLING_HTML, row_selector='div.q') is None
