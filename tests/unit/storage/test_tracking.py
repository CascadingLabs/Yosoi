"""Tests for LLMTracker record/stats."""

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
