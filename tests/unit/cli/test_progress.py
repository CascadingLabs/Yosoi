"""Tests for yosoi.cli.progress — _build_progress_table (compat stub)."""

import time

from yosoi.cli.progress import _build_progress_table


class TestBuildProgressTable:
    def test_empty_status(self):
        """Empty url_status produces a table with no rows."""
        table = _build_progress_table({})
        assert table.title == 'Concurrent Processing'
        assert table.row_count == 0

    def test_queued_status(self):
        """Queued URL shows in the table."""
        url_status = {'https://example.com': ('Queued', 0.0)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1

    def test_running_status_with_elapsed(self):
        """Running URL shows elapsed time."""
        now = time.monotonic()
        url_status = {'https://example.com': ('Running', now)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1

    def test_done_status(self):
        """Done URL shows elapsed time."""
        url_status = {'https://example.com': ('Done', 5.2)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1

    def test_failed_status(self):
        """Failed URL shows in the table."""
        url_status = {'https://example.com': ('Failed', 3.0)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1

    def test_skipped_status(self):
        """Skipped URL shows in the table."""
        url_status = {'https://example.com': ('Skipped', 0.0)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1

    def test_multiple_urls(self):
        """Multiple URLs all appear in the table."""
        url_status = {
            'https://a.com': ('Queued', 0.0),
            'https://b.com': ('Done', 2.0),
            'https://c.com': ('Failed', 1.0),
        }
        table = _build_progress_table(url_status)
        assert table.row_count == 3

    def test_unknown_status_uses_default_style(self):
        """Unknown status uses default bold red style."""
        url_status = {'https://example.com': ('UnknownStatus', 1.0)}
        table = _build_progress_table(url_status)
        assert table.row_count == 1
