"""Tests for yosoi.cli.progress — _build_progress_table and run_concurrent URL dedup."""

import time

import pytest

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


# ---------------------------------------------------------------------------
# Coverage: run_concurrent delegates to Pipeline.process_urls(workers=N)
# ---------------------------------------------------------------------------


class TestRunConcurrentUrlDedup:
    @pytest.mark.asyncio
    async def test_duplicate_domains_are_skipped(self, mocker):
        """URLs with the same domain should be marked as Skipped in the Live display."""
        from yosoi.cli.progress import run_concurrent
        from yosoi.models.contract import Contract

        class TestContract(Contract):
            title: str

        mock_config = mocker.MagicMock()

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_urls = mocker.AsyncMock(
            return_value={
                'successful': ['https://example.com/page1'],
                'failed': [],
                'skipped': ['https://example.com/page2'],
            },
        )
        mocker.patch('yosoi.cli.progress.Live')

        urls = [
            'https://example.com/page1',
            'https://example.com/page2',  # same domain, should be skipped
        ]
        await run_concurrent(mock_config, TestContract, urls)

        mock_pipeline.process_urls.assert_awaited_once()
        call_kwargs = mock_pipeline.process_urls.call_args[1]
        assert call_kwargs['workers'] == 5  # default max_workers

    @pytest.mark.asyncio
    async def test_different_domains_not_skipped(self, mocker):
        """URLs with different domains should all be Running, not Skipped."""
        from yosoi.cli.progress import run_concurrent
        from yosoi.models.contract import Contract

        class TestContract2(Contract):
            title: str

        mock_config = mocker.MagicMock()
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_urls = mocker.AsyncMock(
            return_value={'successful': [], 'failed': [], 'skipped': []},
        )
        mocker.patch('yosoi.cli.progress.Live')

        urls = ['https://example.com/page1', 'https://other.com/page2']
        await run_concurrent(mock_config, TestContract2, urls)

    @pytest.mark.asyncio
    async def test_url_without_scheme_gets_https_prefix(self, mocker):
        """URLs without http/https prefix get https:// added for domain extraction."""
        from yosoi.cli.progress import run_concurrent
        from yosoi.models.contract import Contract

        class TestContract3(Contract):
            title: str

        mock_config = mocker.MagicMock()
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_urls = mocker.AsyncMock(
            return_value={'successful': [], 'failed': [], 'skipped': []},
        )
        mocker.patch('yosoi.cli.progress.Live')

        urls = ['example.com/page1']
        await run_concurrent(mock_config, TestContract3, urls)

    @pytest.mark.asyncio
    async def test_on_complete_callback_passed_to_pipeline(self, mocker):
        """run_concurrent passes an on_complete callback to pipeline.process_urls."""
        from yosoi.cli.progress import run_concurrent
        from yosoi.models.contract import Contract

        class TestContract4(Contract):
            title: str

        mock_config = mocker.MagicMock()
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_urls = mocker.AsyncMock(
            return_value={'successful': [], 'failed': [], 'skipped': []},
        )
        mocker.patch('yosoi.cli.progress.Live')

        await run_concurrent(mock_config, TestContract4, ['https://a.com'])

        call_kwargs = mock_pipeline.process_urls.call_args[1]
        assert call_kwargs['on_complete'] is not None
