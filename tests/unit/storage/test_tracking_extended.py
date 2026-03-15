"""Extended tests for yosoi.storage.tracking — print_stats, reset, edge cases."""

import pytest

from yosoi.storage.tracking import LLMTracker


@pytest.fixture
def tracker(tmp_path):
    """Create a tracker with a temp tracking file."""
    return LLMTracker(tracking_file=str(tmp_path / 'stats.json'))


class TestLLMTrackerPrintStats:
    async def test_print_stats_empty(self, tracker, capsys):
        """print_stats with no data prints 'No tracking data'."""
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'No tracking data' in output

    async def test_print_stats_with_data(self, tracker, capsys):
        """print_stats with data shows domain breakdown."""
        await tracker.record_url('https://example.com/page1', used_llm=True)
        await tracker.record_url('https://example.com/page2', used_llm=False)
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'example.com' in output
        assert 'LLM Calls: 1' in output
        assert 'URLs Processed: 2' in output

    async def test_print_stats_efficiency_zero_llm_calls(self, tracker, capsys):
        """print_stats handles zero LLM calls (efficiency = url_count)."""
        await tracker.record_url('https://example.com', used_llm=False)
        tracker.print_stats()
        output = capsys.readouterr().out
        assert 'example.com' in output


class TestLLMTrackerReset:
    async def test_reset_specific_domain(self, tracker, capsys):
        """Reset a specific domain removes only that domain."""
        await tracker.record_url('https://a.com', used_llm=True)
        await tracker.record_url('https://b.com', used_llm=True)
        tracker.reset('a.com')
        output = capsys.readouterr().out
        assert 'Reset tracking for a.com' in output
        assert tracker.get_llm_calls('a.com') == 0
        assert tracker.get_llm_calls('b.com') == 1

    async def test_reset_nonexistent_domain(self, tracker, capsys):
        """Reset a domain that doesn't exist prints message."""
        tracker.reset('nonexistent.com')
        output = capsys.readouterr().out
        assert 'No tracking data for nonexistent.com' in output

    async def test_reset_all(self, tracker, capsys):
        """Reset all clears everything."""
        await tracker.record_url('https://a.com', used_llm=True)
        await tracker.record_url('https://b.com', used_llm=True)
        tracker.reset()
        output = capsys.readouterr().out
        assert 'Reset all tracking data' in output
        assert tracker.get_all_stats() == {}


class TestLLMTrackerLevelDistribution:
    async def test_record_with_level_distribution(self, tracker):
        """Level distribution is accumulated across calls."""
        await tracker.record_url('https://a.com', used_llm=True, level_distribution={'css': 3, 'xpath': 1})
        await tracker.record_url('https://a.com', used_llm=False, level_distribution={'css': 2})
        stats = tracker.get_stats('a.com')
        assert stats.level_distribution == {'css': 5, 'xpath': 1}


class TestLLMTrackerCorruptFile:
    async def test_corrupt_tracking_file(self, tmp_path):
        """Corrupt tracking file returns empty dict."""
        tracking_file = tmp_path / 'stats.json'
        tracking_file.write_text('not valid json')
        tracker = LLMTracker(tracking_file=str(tracking_file))
        data = tracker._load_data()
        assert data == {}


class TestLLMTrackerElapsedAndPartial:
    async def test_elapsed_accumulates(self, tracker):
        """elapsed seconds are summed across record_url calls."""
        await tracker.record_url('https://a.com', elapsed=1.5)
        await tracker.record_url('https://a.com', elapsed=2.5)
        stats = tracker.get_stats('a.com')
        assert abs(stats.total_elapsed - 4.0) < 0.01

    async def test_partial_rediscovery_count_increments(self, tracker):
        """partial_discovery=True increments partial_rediscovery_count."""
        await tracker.record_url('https://a.com', partial_discovery=True)
        await tracker.record_url('https://a.com', partial_discovery=True)
        await tracker.record_url('https://a.com', partial_discovery=False)
        stats = tracker.get_stats('a.com')
        assert stats.partial_rediscovery_count == 2

    async def test_partial_rediscovery_count_default_zero(self, tracker):
        """partial_discovery defaults to False — count stays 0."""
        await tracker.record_url('https://a.com')
        stats = tracker.get_stats('a.com')
        assert stats.partial_rediscovery_count == 0


class TestLLMTrackerUrlBasedLookup:
    async def test_get_llm_calls_with_full_url(self, tracker):
        """get_llm_calls accepts a full URL and extracts domain."""
        await tracker.record_url('https://example.com/page', used_llm=True)
        # Full URL lookup should work
        assert tracker.get_llm_calls('https://example.com/page') == 1

    async def test_get_url_count_with_full_url(self, tracker):
        """get_url_count accepts a full URL and extracts domain."""
        await tracker.record_url('https://example.com/page')
        await tracker.record_url('https://example.com/other')
        assert tracker.get_url_count('https://example.com/page') == 2

    async def test_get_all_stats_returns_all_domains(self, tracker):
        """get_all_stats returns DomainStats for every tracked domain."""
        await tracker.record_url('https://a.com', used_llm=True)
        await tracker.record_url('https://b.com', used_llm=False)
        all_stats = tracker.get_all_stats()
        assert 'a.com' in all_stats
        assert 'b.com' in all_stats
        assert all_stats['a.com'].llm_calls == 1
        assert all_stats['b.com'].url_count == 1

    async def test_extract_domain_removes_www(self, tracker):
        """extract_domain strips www. prefix."""
        assert tracker.extract_domain('https://www.example.com/path') == 'example.com'

    async def test_normalize_stats_from_dict(self, tracker):
        """_normalize_stats converts raw dict to DomainStats."""
        from yosoi.storage.tracking import DomainStats

        raw = {
            'llm_calls': 5,
            'url_count': 10,
            'level_distribution': {},
            'total_elapsed': 3.0,
            'partial_rediscovery_count': 1,
        }
        stats = LLMTracker._normalize_stats(raw)
        assert isinstance(stats, DomainStats)
        assert stats.llm_calls == 5
        assert stats.partial_rediscovery_count == 1
