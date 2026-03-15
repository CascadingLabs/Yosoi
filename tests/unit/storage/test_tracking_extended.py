"""Extended tests for yosoi.storage.tracking — print_stats, reset, edge cases."""

import pytest

from yosoi.storage.tracking import LLMTracker


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with a temp tracking file."""
    return LLMTracker(tracking_file=str(tmp_path / 'stats.json'))


class TestLLMTrackerPrintStats:
    def test_print_stats_empty(self, tracker, capsys):
        """print_stats with no data prints 'No tracking data'."""
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'No tracking data' in output

    def test_print_stats_with_data(self, tracker, capsys):
        """print_stats with data shows domain breakdown."""
        tracker.record_url('https://example.com/page1', used_llm=True)
        tracker.record_url('https://example.com/page2', used_llm=False)
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'example.com' in output
        assert 'LLM Calls: 1' in output
        assert 'URLs Processed: 2' in output

    def test_print_stats_efficiency_zero_llm_calls(self, tracker, capsys):
        """print_stats handles zero LLM calls (efficiency = url_count)."""
        tracker.record_url('https://example.com', used_llm=False)
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'example.com' in output


class TestLLMTrackerReset:
    def test_reset_specific_domain(self, tracker, capsys):
        """Reset a specific domain removes only that domain."""
        tracker.record_url('https://a.com', used_llm=True)
        tracker.record_url('https://b.com', used_llm=True)
        tracker.reset('a.com')
        output = capsys.readouterr().out
        assert 'Reset tracking for a.com' in output
        assert tracker.get_llm_calls('a.com') == 0
        assert tracker.get_llm_calls('b.com') == 1

    def test_reset_nonexistent_domain(self, tracker, capsys):
        """Reset a domain that doesn't exist prints message."""
        tracker.reset('nonexistent.com')
        output = capsys.readouterr().out
        assert 'No tracking data for nonexistent.com' in output

    def test_reset_all(self, tracker, capsys):
        """Reset all clears everything."""
        tracker.record_url('https://a.com', used_llm=True)
        tracker.record_url('https://b.com', used_llm=True)
        tracker.reset()
        output = capsys.readouterr().out
        assert 'Reset all tracking data' in output
        assert tracker.get_all_stats() == {}


class TestLLMTrackerLevelDistribution:
    def test_record_with_level_distribution(self, tracker):
        """Level distribution is accumulated across calls."""
        tracker.record_url('https://a.com', used_llm=True, level_distribution={'css': 3, 'xpath': 1})
        tracker.record_url('https://a.com', used_llm=False, level_distribution={'css': 2})
        stats = tracker.get_stats('a.com')
        assert stats.level_distribution == {'css': 5, 'xpath': 1}


class TestLLMTrackerCorruptFile:
    def test_corrupt_tracking_file(self, tmp_path):
        """Corrupt tracking file returns empty dict."""
        tracking_file = tmp_path / 'stats.json'
        tracking_file.write_text('not valid json')
        tracker = LLMTracker(tracking_file=str(tracking_file))
        data = tracker._load_data()
        assert data == {}
