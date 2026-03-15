"""Tests for yosoi.tasks — broker, task registration, domain locks, and enqueue."""

import asyncio

import pytest

import yosoi.core.tasks as _tasks_mod
from yosoi.core.tasks import (
    _domain_locks,
    configure_broker,
    enqueue_urls,
    get_pipeline_config,
    process_url_task,
    shutdown_broker,
)

# ──────────────────────────────────────────────────────────────────────
# Broker configuration
# ──────────────────────────────────────────────────────────────────────


class TestBrokerConfig:
    async def test_configure_and_shutdown(self, mock_llm_config, clean_broker):
        import yosoi.core.tasks as yosoi_tasks
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)
        config = get_pipeline_config()
        assert config.contract is NewsArticle
        assert config.output_format == 'json'
        assert config.max_workers == 3
        # Semaphore should be created with the right limit
        assert yosoi_tasks._semaphore is not None
        await shutdown_broker()
        assert _tasks_mod._pipeline_config is None
        assert yosoi_tasks._semaphore is None

    def test_get_config_before_configure_raises(self, clean_broker):
        with pytest.raises(RuntimeError, match='Broker not configured'):
            get_pipeline_config()

    async def test_shutdown_clears_domain_locks(self, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)
        _domain_locks['example.com'] = asyncio.Lock()
        await shutdown_broker()
        assert len(_domain_locks) == 0


# ──────────────────────────────────────────────────────────────────────
# process_url_task
# ──────────────────────────────────────────────────────────────────────


class TestProcessUrlTask:
    async def test_task_returns_success(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        # Call the task function directly (not via kiq) for unit testing
        result = await process_url_task.original_func(url='http://example.com', force=True)

        assert result.url == 'http://example.com'
        assert result.elapsed is not None
        mock_pipeline.process_url.assert_awaited_once()
        await shutdown_broker()

    async def test_task_reraises_exception(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(side_effect=Exception('boom'))

        with pytest.raises(Exception, match='boom'):
            await process_url_task.original_func(url='http://error.com')
        await shutdown_broker()

    async def test_task_acquires_domain_lock(self, mocker, mock_llm_config, clean_broker):
        """Per-domain lock should be created and used."""
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        await process_url_task.original_func(url='http://example.com/page1')
        assert 'example.com' in _domain_locks
        await shutdown_broker()


# ──────────────────────────────────────────────────────────────────────
# enqueue_urls (via InMemoryBroker)
# ──────────────────────────────────────────────────────────────────────


class TestEnqueueUrls:
    async def test_enqueue_and_collect_results(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        results = await enqueue_urls(
            ['http://a.com/page1', 'http://b.com/page1'],
        )

        assert 'http://a.com/page1' in results.successful
        assert 'http://b.com/page1' in results.successful
        assert results.failed == []
        await shutdown_broker()

    async def test_same_domain_urls_all_processed(self, mocker, mock_llm_config, clean_broker):
        """Same-domain URLs should all be processed (no dedup skipping)."""
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        results = await enqueue_urls(
            ['http://example.com/page1', 'http://example.com/page2'],
        )

        assert 'http://example.com/page1' in results.successful
        assert 'http://example.com/page2' in results.successful
        assert results.skipped == []
        await shutdown_broker()

    async def test_failed_tasks_tracked(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(side_effect=Exception('fail'))

        results = await enqueue_urls(['http://fail.com'])

        assert 'http://fail.com' in results.failed
        assert results.successful == []
        await shutdown_broker()

    async def test_on_start_callback_fired(self, mocker, mock_llm_config, clean_broker):
        """on_start callback should be called for each URL before task starts."""
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        started: list[str] = []

        async def _on_start(url: str) -> None:
            started.append(url)

        await enqueue_urls(['http://a.com', 'http://b.com'], on_start=_on_start)

        assert started == ['http://a.com', 'http://b.com']
        await shutdown_broker()

    async def test_broker_task_is_registered(self):
        # Verify the task decorator registered it properly
        assert process_url_task is not None
        assert hasattr(process_url_task, 'kiq')
        assert hasattr(process_url_task, 'original_func')
