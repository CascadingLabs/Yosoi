"""Tests for Pipeline.process_urls with workers > 1 (scripted concurrent mode).

Validates that the Pipeline public API correctly delegates to the taskiq broker
when workers > 1, and falls back to sequential processing otherwise.
"""

import asyncio

import pytest

from yosoi.core.pipeline import Pipeline
from yosoi.core.tasks import EnqueueResult
from yosoi.models.defaults import NewsArticle


@pytest.fixture
def pipeline(mock_llm_config):
    """Create a Pipeline with mocked LLM config and quiet output."""
    return Pipeline(mock_llm_config, contract=NewsArticle, quiet=True)


class TestWorkersRouting:
    """Verify that the workers parameter routes to the correct code path."""

    async def test_workers_1_uses_sequential(self, mocker, pipeline):
        """workers=1 (default) should process URLs sequentially."""
        mock_concurrent = mocker.patch.object(pipeline, '_process_urls_concurrent', new_callable=mocker.AsyncMock)
        mocker.patch.object(pipeline, 'process_url', new_callable=mocker.AsyncMock)

        await pipeline.process_urls(['http://a.com', 'http://b.com'], workers=1)

        mock_concurrent.assert_not_awaited()
        assert pipeline.process_url.await_count == 2

    async def test_workers_gt1_uses_concurrent(self, mocker, pipeline):
        """workers > 1 with multiple URLs should use concurrent path."""
        mock_concurrent = mocker.patch.object(
            pipeline,
            '_process_urls_concurrent',
            new_callable=mocker.AsyncMock,
            return_value={'successful': ['http://a.com', 'http://b.com'], 'failed': [], 'skipped': []},
        )

        result = await pipeline.process_urls(['http://a.com', 'http://b.com'], workers=3)

        mock_concurrent.assert_awaited_once()
        assert len(result['successful']) == 2

    async def test_workers_gt1_single_url_stays_sequential(self, mocker, pipeline):
        """workers > 1 but only one URL should fall back to sequential."""
        mock_concurrent = mocker.patch.object(pipeline, '_process_urls_concurrent', new_callable=mocker.AsyncMock)
        mocker.patch.object(pipeline, 'process_url', new_callable=mocker.AsyncMock)

        await pipeline.process_urls(['http://a.com'], workers=5)

        mock_concurrent.assert_not_awaited()
        pipeline.process_url.assert_awaited_once()

    async def test_workers_capped_to_url_count(self, mocker, pipeline):
        """workers is capped to len(urls) via effective_workers."""
        mock_concurrent = mocker.patch.object(
            pipeline,
            '_process_urls_concurrent',
            new_callable=mocker.AsyncMock,
            return_value={'successful': ['http://a.com', 'http://b.com'], 'failed': [], 'skipped': []},
        )

        await pipeline.process_urls(['http://a.com', 'http://b.com'], workers=10)

        # effective_workers = min(10, 2) = 2
        call_kwargs = mock_concurrent.call_args[1]
        assert call_kwargs['max_workers'] == 2


class TestConcurrentProcessing:
    """Integration tests for the concurrent path through the real taskiq broker."""

    async def test_concurrent_processes_all_urls(self, mocker, pipeline, clean_broker):
        """All URLs should be processed when using concurrent mode."""
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = mocker.AsyncMock(return_value=None)

        urls = [f'http://site{i}.com' for i in range(4)]
        result = await pipeline._process_urls_concurrent(
            urls,
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=3,
        )

        assert len(result['successful']) == 4
        assert result['failed'] == []

    async def test_concurrent_collects_failures(self, mocker, pipeline, clean_broker):
        """Failed URLs are tracked in the 'failed' bucket."""

        async def _fail(url, **kwargs):
            if 'bad' in url:
                raise RuntimeError('boom')

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = _fail

        result = await pipeline._process_urls_concurrent(
            ['http://good.com', 'http://bad.com'],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=2,
        )

        assert 'http://good.com' in result['successful']
        assert 'http://bad.com' in result['failed']

    async def test_concurrent_processes_all_same_domain_urls(self, mocker, pipeline, clean_broker):
        """All same-domain URLs should be processed (no dedup skipping)."""
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = mocker.AsyncMock(return_value=None)

        result = await pipeline._process_urls_concurrent(
            ['http://example.com/page1', 'http://example.com/page2'],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=2,
        )

        assert len(result['successful']) == 2
        assert result['skipped'] == []

    async def test_concurrent_shuts_down_broker_on_error(self, mocker, pipeline, clean_broker):
        """Broker is shut down even if enqueue_urls raises."""
        mocker.patch('yosoi.core.tasks.configure_broker', new_callable=mocker.AsyncMock)
        mock_shutdown = mocker.patch('yosoi.core.tasks.shutdown_broker', new_callable=mocker.AsyncMock)
        mocker.patch(
            'yosoi.core.tasks.enqueue_urls',
            new_callable=mocker.AsyncMock,
            side_effect=RuntimeError('broker exploded'),
        )

        with pytest.raises(RuntimeError, match='broker exploded'):
            await pipeline._process_urls_concurrent(
                ['http://a.com'],
                force=False,
                skip_verification=False,
                fetcher_type='simple',
                max_fetch_retries=2,
                max_discovery_retries=3,
                output_format=['json'],
                max_workers=2,
            )

        mock_shutdown.assert_awaited_once()

    async def test_concurrent_passes_config_to_broker(self, mocker, pipeline, clean_broker):
        """configure_broker receives the pipeline's llm_config, contract, and settings."""
        mock_configure = mocker.patch('yosoi.core.tasks.configure_broker', new_callable=mocker.AsyncMock)
        mocker.patch('yosoi.core.tasks.shutdown_broker', new_callable=mocker.AsyncMock)
        mocker.patch(
            'yosoi.core.tasks.enqueue_urls',
            new_callable=mocker.AsyncMock,
            return_value=EnqueueResult(),
        )

        await pipeline._process_urls_concurrent(
            ['http://a.com'],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json', 'markdown'],
            max_workers=4,
        )

        mock_configure.assert_awaited_once()
        call_kwargs = mock_configure.call_args[1]
        assert call_kwargs['contract'] is NewsArticle
        assert call_kwargs['output_format'] == ['json', 'markdown']
        assert call_kwargs['max_workers'] == 4

    async def test_concurrent_skipped_always_empty(self, mocker, pipeline, clean_broker):
        """Result dict 'skipped' key is always empty (no domain dedup)."""
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = mocker.AsyncMock(return_value=None)

        result = await pipeline._process_urls_concurrent(
            ['http://a.com', 'http://a.com/page2', 'http://b.com'],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=3,
        )

        assert 'skipped' in result
        assert result['skipped'] == []
        assert len(result['successful']) == 3

    async def test_on_start_callback_passed_through(self, mocker, pipeline, clean_broker):
        """on_start callback is passed to enqueue_urls."""
        mocker.patch('yosoi.core.tasks.configure_broker', new_callable=mocker.AsyncMock)
        mocker.patch('yosoi.core.tasks.shutdown_broker', new_callable=mocker.AsyncMock)
        mock_enqueue = mocker.patch(
            'yosoi.core.tasks.enqueue_urls',
            new_callable=mocker.AsyncMock,
            return_value=EnqueueResult(),
        )

        async def _on_start(url: str) -> None:
            pass

        await pipeline._process_urls_concurrent(
            ['http://a.com'],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=2,
            on_start=_on_start,
        )

        call_kwargs = mock_enqueue.call_args[1]
        assert call_kwargs['on_start'] is _on_start


class TestConcurrentSemaphore:
    """Verify semaphore limiting works through the Pipeline API."""

    async def test_respects_max_workers(self, mocker, pipeline, clean_broker):
        """No more than max_workers tasks run simultaneously."""
        peak = 0
        current = 0
        lock = asyncio.Lock()

        async def _track(url, **kwargs):
            nonlocal peak, current
            async with lock:
                current += 1
                peak = max(peak, current)
            await asyncio.sleep(0.05)
            async with lock:
                current -= 1

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = _track

        await pipeline._process_urls_concurrent(
            [f'http://site{i}.com' for i in range(6)],
            force=False,
            skip_verification=False,
            fetcher_type='simple',
            max_fetch_retries=2,
            max_discovery_retries=3,
            output_format=['json'],
            max_workers=2,
        )

        assert peak <= 2


class TestEndToEndScripted:
    """Full process_urls(workers=N) call through the public API."""

    async def test_process_urls_concurrent_end_to_end(self, mocker, pipeline, clean_broker):
        """process_urls(workers=3) processes all URLs and returns results."""
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = mocker.AsyncMock(return_value=None)

        urls = ['http://a.com', 'http://b.com', 'http://c.com']
        result = await pipeline.process_urls(urls, workers=3)

        assert len(result['successful']) == 3
        assert result['failed'] == []
        assert result.get('skipped', []) == []

    async def test_process_urls_mixed_results(self, mocker, pipeline, clean_broker):
        """Mixed success/failure URLs are bucketed correctly."""

        async def _selective(url, **kwargs):
            if 'fail' in url:
                raise RuntimeError('nope')

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipe = mock_pipeline_cls.return_value
        mock_pipe.process_url = _selective

        urls = ['http://ok1.com', 'http://fail.com', 'http://ok2.com']
        result = await pipeline.process_urls(urls, workers=3)

        assert 'http://ok1.com' in result['successful']
        assert 'http://ok2.com' in result['successful']
        assert 'http://fail.com' in result['failed']

    async def test_on_start_threaded_through_process_urls(self, mocker, pipeline, clean_broker):
        """on_start callback flows from process_urls → _process_urls_concurrent."""
        mock_concurrent = mocker.patch.object(
            pipeline,
            '_process_urls_concurrent',
            new_callable=mocker.AsyncMock,
            return_value={'successful': ['http://a.com', 'http://b.com'], 'failed': [], 'skipped': []},
        )

        async def _on_start(url: str) -> None:
            pass

        await pipeline.process_urls(['http://a.com', 'http://b.com'], workers=2, on_start=_on_start)

        call_kwargs = mock_concurrent.call_args[1]
        assert call_kwargs['on_start'] is _on_start
