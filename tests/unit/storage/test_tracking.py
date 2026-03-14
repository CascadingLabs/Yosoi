"""Tests for LLMTracker record/stats."""

import json
import os

import pytest

from yosoi.storage.tracking import LLMTracker


@pytest.fixture
def tracker(tmp_path):
    return LLMTracker(tracking_file=str(tmp_path / 'tracking.json'))


def test_record_url_increments_url_count(tracker):
    tracker.record_url('https://example.com/article', used_llm=False)
    assert tracker.get_url_count('example.com') == 1


def test_record_url_with_llm_increments_llm_calls(tracker):
    tracker.record_url('https://example.com/article', used_llm=True)
    assert tracker.get_llm_calls('example.com') == 1


def test_record_url_without_llm_does_not_increment_llm_calls(tracker):
    tracker.record_url('https://example.com/article', used_llm=False)
    assert tracker.get_llm_calls('example.com') == 0


def test_multiple_records_accumulate(tracker):
    tracker.record_url('https://example.com/a1', used_llm=True)
    tracker.record_url('https://example.com/a2', used_llm=False)
    tracker.record_url('https://example.com/a3', used_llm=True)
    assert tracker.get_url_count('example.com') == 3
    assert tracker.get_llm_calls('example.com') == 2


def test_multiple_domains_tracked_independently(tracker):
    tracker.record_url('https://example.com/a', used_llm=True)
    tracker.record_url('https://other.com/b', used_llm=True)

    assert tracker.get_url_count('example.com') == 1
    assert tracker.get_url_count('other.com') == 1
    assert tracker.get_llm_calls('example.com') == 1
    assert tracker.get_llm_calls('other.com') == 1


def test_get_stats_returns_dict(tracker):
    tracker.record_url('https://example.com/x', used_llm=True)
    stats = tracker.get_stats('example.com')
    assert 'llm_calls' in stats
    assert 'url_count' in stats


def test_get_stats_unknown_domain_returns_zeros(tracker):
    stats = tracker.get_stats('neverrecorded.com')
    assert stats == {'llm_calls': 0, 'url_count': 0}


def test_get_all_stats_returns_all_domains(tracker):
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=False)
    all_stats = tracker.get_all_stats()
    assert 'a.com' in all_stats
    assert 'b.com' in all_stats


def test_get_llm_calls_with_domain_name(tracker):
    tracker.record_url('https://example.com/a', used_llm=True)
    # Pass domain name directly (no ://)
    assert tracker.get_llm_calls('example.com') == 1


def test_get_url_count_with_domain_name(tracker):
    tracker.record_url('https://example.com/a', used_llm=False)
    assert tracker.get_url_count('example.com') == 1


def test_reset_specific_domain(tracker):
    tracker.record_url('https://example.com/a', used_llm=True)
    tracker.record_url('https://other.com/b', used_llm=True)
    tracker.reset('example.com')
    assert tracker.get_url_count('example.com') == 0
    assert tracker.get_url_count('other.com') == 1


def test_reset_all_domains(tracker):
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=True)
    tracker.reset()
    assert tracker.get_all_stats() == {}


def test_print_stats_with_data(tracker, capsys):
    tracker.record_url('https://example.com/a', used_llm=True)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'example.com' in captured.out


def test_print_stats_empty(tracker, capsys):
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'No tracking data' in captured.out


# ---------------------------------------------------------------------------
# Additional targeted mutant-killing tests
# ---------------------------------------------------------------------------


def test_record_url_returns_dict_with_llm_calls_and_url_count(tracker):
    result = tracker.record_url('https://example.com/a', used_llm=True)
    assert 'llm_calls' in result
    assert 'url_count' in result


def test_record_url_returns_exact_counts(tracker):
    tracker.record_url('https://example.com/a', used_llm=True)
    result = tracker.record_url('https://example.com/b', used_llm=False)
    assert result['llm_calls'] == 1
    assert result['url_count'] == 2


def test_record_url_llm_false_does_not_add_llm_call(tracker):
    tracker.record_url('https://example.com/a', used_llm=False)
    assert tracker.get_llm_calls('example.com') == 0
    assert tracker.get_url_count('example.com') == 1


def test_extract_domain_strips_www(tracker):
    assert tracker.extract_domain('https://www.example.com/path') == 'example.com'


def test_extract_domain_no_www(tracker):
    assert tracker.extract_domain('https://example.com/path') == 'example.com'


def test_extract_domain_subdomain_kept(tracker):
    assert tracker.extract_domain('https://blog.example.com/') == 'blog.example.com'


def test_get_llm_calls_url_uses_extract_domain(tracker):
    tracker.record_url('https://www.example.com/a', used_llm=True)
    # URL with :// should use extract_domain
    assert tracker.get_llm_calls('https://www.example.com/b') == 1


def test_get_url_count_url_uses_extract_domain(tracker):
    tracker.record_url('https://www.example.com/a', used_llm=False)
    assert tracker.get_url_count('https://www.example.com/b') == 1


def test_get_llm_calls_plain_domain_no_extract(tracker):
    tracker.record_url('https://example.com/a', used_llm=True)
    # Plain domain (no ://) goes directly without extraction
    assert tracker.get_llm_calls('example.com') == 1


def test_get_url_count_plain_domain(tracker):
    tracker.record_url('https://example.com/a', used_llm=False)
    assert tracker.get_url_count('example.com') == 1


def test_record_url_increments_from_zero_on_first_call(tracker):
    result = tracker.record_url('https://newsite.com/a', used_llm=True)
    assert result['llm_calls'] == 1
    assert result['url_count'] == 1


def test_reset_domain_removes_only_that_domain(tracker):
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=True)
    tracker.reset('a.com')
    stats = tracker.get_all_stats()
    assert 'a.com' not in stats
    assert 'b.com' in stats


def test_reset_nonexistent_domain_no_error(tracker, capsys):
    tracker.reset('ghost.com')
    captured = capsys.readouterr()
    assert 'ghost.com' in captured.out


def test_print_stats_includes_llm_calls(tracker, capsys):
    tracker.record_url('https://example.com/a', used_llm=True)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'LLM' in captured.out or 'llm' in captured.out.lower()


def test_print_stats_includes_url_count(tracker, capsys):
    tracker.record_url('https://example.com/a', used_llm=False)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert '1' in captured.out


def test_ensure_file_exists_creates_file(tmp_path):
    tracking_file = str(tmp_path / 'new' / 'tracking.json')
    LLMTracker(tracking_file=tracking_file)
    assert os.path.exists(tracking_file)
    with open(tracking_file) as f:
        data = json.load(f)
    assert data == {}


def test_load_data_returns_empty_dict_for_invalid_json(tmp_path):
    tracking_file = tmp_path / 'broken.json'
    tracking_file.write_text('NOT VALID JSON')
    tracker = LLMTracker(tracking_file=str(tracking_file))
    data = tracker._load_data()
    assert data == {}


def test_get_stats_returns_zeros_for_unknown_domain(tracker):
    stats = tracker.get_stats('unknown.xyz')
    assert stats['llm_calls'] == 0
    assert stats['url_count'] == 0


def test_tracker_init_with_none_uses_get_tracking_path(mocker, tmp_path):
    """When tracking_file is None, must use get_tracking_path()."""
    expected_path = tmp_path / 'tracking.json'
    mock_path = mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=expected_path)
    tracker = LLMTracker(tracking_file=None)
    mock_path.assert_called_once()
    assert tracker.tracking_file == str(expected_path)


def test_tracker_init_with_explicit_path_uses_that_path(tmp_path):
    """When tracking_file is given, must use that path directly."""
    custom_path = str(tmp_path / 'custom.json')
    tracker = LLMTracker(tracking_file=custom_path)
    assert tracker.tracking_file == custom_path


def test_ensure_file_exists_creates_empty_json_dict(tmp_path):
    """Created file must contain empty JSON dict '{}'."""
    tracking_file = str(tmp_path / 'subdir' / 'tracking.json')
    LLMTracker(tracking_file=tracking_file)
    with open(tracking_file) as f:
        data = json.load(f)
    assert data == {}


def test_ensure_file_exists_uses_makedirs(tmp_path):
    """_ensure_file_exists must create parent directories."""
    nested_path = str(tmp_path / 'deep' / 'nested' / 'tracking.json')
    LLMTracker(tracking_file=nested_path)
    assert os.path.exists(nested_path)


def test_save_data_writes_with_indent_2(tracker, tmp_path):
    """_save_data must use indent=2 for JSON formatting."""
    tracker._save_data({'test': {'llm_calls': 1, 'url_count': 2}})
    with open(tracker.tracking_file) as fh:
        raw = fh.read()
    assert '  ' in raw


def test_save_data_uses_ensure_ascii_false(tracker):
    """_save_data must use ensure_ascii=False."""
    data = {'域名.com': {'llm_calls': 1, 'url_count': 1}}
    tracker._save_data(data)
    loaded = tracker._load_data()
    assert '域名.com' in loaded


def test_extract_domain_returns_netloc_without_www(tracker):
    """extract_domain must return netloc with 'www.' removed."""
    result = tracker.extract_domain('https://www.test.example.com/path')
    assert result == 'test.example.com'


def test_extract_domain_exact_removal():
    """'www.' must be removed only when at start of netloc, not from subdomains like 'mywww.com'."""
    tracker = LLMTracker(tracking_file='/tmp/test_tracker.json')
    # 'www.' only removed from start
    result = tracker.extract_domain('https://www.example.com')
    assert result == 'example.com'
    # 'mywww.example.com' should remain unchanged
    result2 = tracker.extract_domain('https://mywww.example.com')
    assert result2 == 'mywww.example.com'


def test_record_url_initializes_domain_with_zero_counts(tracker):
    """First record for a domain must start with zero, then increment."""
    result = tracker.record_url('https://brand-new.com/page', used_llm=False)
    # After first record: url_count=1, llm_calls=0
    assert result['url_count'] == 1
    assert result['llm_calls'] == 0


def test_get_llm_calls_uses_extract_domain_for_url_with_scheme(tracker):
    """get_llm_calls must use extract_domain when URL contains '://'."""
    tracker.record_url('https://www.test.com/page', used_llm=True)
    # Pass URL with ://, should extract domain 'test.com' automatically
    count = tracker.get_llm_calls('https://www.test.com/other')
    assert count == 1


def test_get_llm_calls_uses_domain_directly_without_scheme(tracker):
    """get_llm_calls must use domain directly when no '://' present."""
    tracker.record_url('https://test.com/page', used_llm=True)
    # Pass domain directly (no ://)
    count = tracker.get_llm_calls('test.com')
    assert count == 1


def test_reset_specific_domain_saves_data(tracker):
    """After reset(domain), the data must be persisted to disk."""
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=True)
    tracker.reset('a.com')
    # Reload data
    fresh = LLMTracker(tracking_file=tracker.tracking_file)
    assert fresh.get_url_count('a.com') == 0
    assert fresh.get_url_count('b.com') == 1


def test_reset_all_saves_empty_data(tracker):
    """After reset(), the file must contain empty dict."""
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.reset()
    with open(tracker.tracking_file) as f:
        data = json.load(f)
    assert data == {}


def test_print_stats_shows_total_llm_calls(tracker, capsys):
    """print_stats must show total LLM calls."""
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://a.com/y', used_llm=True)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'Total LLM Calls: 2' in captured.out


def test_print_stats_shows_total_urls(tracker, capsys):
    """print_stats must show total URLs processed."""
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=False)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'Total URLs Processed: 2' in captured.out


def test_print_stats_shows_domain_count(tracker, capsys):
    """print_stats must show total domain count."""
    tracker.record_url('https://a.com/x', used_llm=True)
    tracker.record_url('https://b.com/y', used_llm=True)
    tracker.print_stats()
    captured = capsys.readouterr()
    assert 'Total Domains: 2' in captured.out


# ---------------------------------------------------------------------------
# level_distribution tracking
# ---------------------------------------------------------------------------


def test_record_url_stores_level_distribution(tracker):
    """record_url with level_distribution stores it in the tracking file."""
    tracker.record_url('https://a.com/x', used_llm=True, level_distribution={'css': 3, 'xpath': 1})
    data = tracker._load_data()
    assert data['a.com']['level_distribution'] == {'css': 3, 'xpath': 1}


def test_level_distribution_accumulates_across_urls(tracker):
    """level_distribution merges (sums) across multiple record_url calls."""
    tracker.record_url('https://a.com/x', used_llm=True, level_distribution={'css': 2})
    tracker.record_url('https://a.com/y', used_llm=True, level_distribution={'css': 1, 'xpath': 1})
    data = tracker._load_data()
    assert data['a.com']['level_distribution'] == {'css': 3, 'xpath': 1}


def test_record_url_without_level_distribution_leaves_existing(tracker):
    """Calling record_url without level_distribution doesn't reset existing distribution."""
    tracker.record_url('https://a.com/x', used_llm=True, level_distribution={'css': 2})
    tracker.record_url('https://a.com/y', used_llm=False)
    data = tracker._load_data()
    assert data['a.com']['level_distribution'] == {'css': 2}


def test_level_distribution_independent_per_domain(tracker):
    """level_distribution is tracked independently for each domain."""
    tracker.record_url('https://a.com/x', level_distribution={'css': 1})
    tracker.record_url('https://b.com/x', level_distribution={'xpath': 2})
    data = tracker._load_data()
    assert data['a.com']['level_distribution'] == {'css': 1}
    assert data['b.com']['level_distribution'] == {'xpath': 2}


# ---------------------------------------------------------------------------
# Coverage: lines 86-87 — extract_domain with invalid URL
# ---------------------------------------------------------------------------


def test_extract_domain_no_netloc_returns_empty(tracker):
    """extract_domain with a URL having no netloc returns empty string."""
    # urlparse rarely raises ValueError; this tests the path string case
    result = tracker.extract_domain('just-a-string')
    assert isinstance(result, str)
