"""CAS-83 regression test — different Contracts on the same domain must NOT collide.

Before the fix, ``SelectorStorage`` keyed selectors by domain alone, so a
RedditPost contract running on reddit.com would overwrite a RedditComment
contract's selectors (root selector in particular). The fix threads a
``contract_sig`` argument through every storage method and uses it as a
filename suffix.

This test pins the no-collision invariant: save selectors for two distinct
contract signatures against the same domain, then load each back — neither
should see the other's data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yosoi.storage.persistence import SelectorStorage


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SelectorStorage:
    """Storage rooted at a sandboxed tmp_path — avoids leaking across tests
    or polluting the real ``.yosoi/`` directory."""
    selectors_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    monkeypatch.setattr('yosoi.utils.files.init_yosoi', lambda sub: str(tmp_path / sub))
    selectors_dir.mkdir()
    content_dir.mkdir()
    storage = SelectorStorage()
    # Re-pin storage_dir / content_dir to the sandbox in case init_yosoi cached.
    storage.storage_dir = str(selectors_dir)
    storage.content_dir = str(content_dir)
    return storage


_SIG_POST = '20b8599db1af4284'
_SIG_COMMENT = 'a3c8d712ef091200'


def test_two_contracts_same_domain_have_separate_files(isolated_storage: SelectorStorage) -> None:
    """The exact CAS-83 scenario: post + comment selectors for reddit.com.
    Each contract gets its own file. Loading one must not see the other."""
    post_url = 'https://www.reddit.com/r/ted/top'
    comment_url = 'https://www.reddit.com/r/ted/comments/abc/some-post/'

    isolated_storage.save_selectors(
        post_url,
        {'title': {'primary': 'a.titleline'}, 'root': {'primary': 'shreddit-post'}},
        contract_sig=_SIG_POST,
    )
    isolated_storage.save_selectors(
        comment_url,
        {'body': {'primary': 'shreddit-comment div'}, 'root': {'primary': 'shreddit-comment'}},
        contract_sig=_SIG_COMMENT,
    )

    post_loaded = isolated_storage.load_selectors('reddit.com', contract_sig=_SIG_POST)
    comment_loaded = isolated_storage.load_selectors('reddit.com', contract_sig=_SIG_COMMENT)

    assert post_loaded is not None
    assert comment_loaded is not None
    # Each contract sees only its own root — the regression we're fixing.
    assert post_loaded['root']['primary'] == 'shreddit-post'
    assert comment_loaded['root']['primary'] == 'shreddit-comment'
    # And only its own per-field selectors.
    assert 'title' in post_loaded
    assert 'body' not in post_loaded
    assert 'body' in comment_loaded
    assert 'title' not in comment_loaded


def test_load_with_wrong_sig_returns_none(isolated_storage: SelectorStorage) -> None:
    """Asking for a contract sig that was never saved returns None — no
    silent fallback to another contract's data."""
    isolated_storage.save_selectors(
        'https://www.reddit.com/',
        {'title': {'primary': 'h1'}},
        contract_sig=_SIG_POST,
    )
    # Different contract — should miss.
    assert isolated_storage.load_selectors('reddit.com', contract_sig=_SIG_COMMENT) is None


def test_load_without_sig_does_not_pick_up_per_contract_files(isolated_storage: SelectorStorage) -> None:
    """Legacy callers that don't pass a sig look at the un-suffixed filename;
    the per-contract files are invisible to them. Prevents leaking a contract's
    cache via the legacy path."""
    isolated_storage.save_selectors(
        'https://www.reddit.com/',
        {'title': {'primary': 'h1'}},
        contract_sig=_SIG_POST,
    )
    # No sig -> legacy filename, which doesn't exist here.
    assert isolated_storage.load_selectors('reddit.com') is None


def test_selector_exists_respects_contract_sig(isolated_storage: SelectorStorage) -> None:
    isolated_storage.save_selectors(
        'https://x.example/',
        {'title': {'primary': 'h1'}},
        contract_sig=_SIG_POST,
    )
    assert isolated_storage.selector_exists('x.example', contract_sig=_SIG_POST)
    assert not isolated_storage.selector_exists('x.example', contract_sig=_SIG_COMMENT)
    assert not isolated_storage.selector_exists('x.example')  # no sig = legacy path


def test_legacy_unsigned_save_and_load_still_work(isolated_storage: SelectorStorage) -> None:
    """Back-compat: calls without contract_sig use the legacy un-suffixed
    filename and round-trip cleanly."""
    isolated_storage.save_selectors('https://x.example/', {'title': {'primary': 'h1'}})
    loaded = isolated_storage.load_selectors('x.example')
    assert loaded is not None
    assert loaded['title']['primary'] == 'h1'


def test_record_verdict_threads_contract_sig(isolated_storage: SelectorStorage) -> None:
    """The audit-trail update must also key by contract — otherwise verdicts
    from contract A would clobber contract B's snapshot file."""
    from yosoi.models.snapshot import CacheVerdict

    isolated_storage.save_selectors(
        'https://x.example/',
        {'title': {'primary': 'h1'}},
        contract_sig=_SIG_POST,
    )
    # Record a verdict against the right contract — must succeed silently.
    isolated_storage.record_verdict('x.example', 'title', CacheVerdict.FRESH, contract_sig=_SIG_POST)
    # Recording against a non-existent (contract_sig, domain) is a no-op,
    # NOT an exception.
    isolated_storage.record_verdict('x.example', 'title', CacheVerdict.FRESH, contract_sig=_SIG_COMMENT)
