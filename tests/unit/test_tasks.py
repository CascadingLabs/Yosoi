"""Tests for yosoi.tasks — broker, task registration, dedup, and enqueue."""

import pytest

from yosoi.tasks import (
    DomainDedup,
    _pipeline_config,
    configure_broker,
    enqueue_urls,
    get_pipeline_config,
    process_url_task,
    shutdown_broker,
)


@pytest.fixture
def clean_broker():
    """Ensure broker state is clean before and after each test."""
    _pipeline_config.clear()
    yield
    _pipeline_config.clear()


# ──────────────────────────────────────────────────────────────────────
# DomainDedup
# ──────────────────────────────────────────────────────────────────────


class TestDomainDedup:
    def test_first_domain_allowed(self):
        dedup = DomainDedup()
        assert dedup.should_process('example.com') is True

    def test_duplicate_domain_blocked(self):
        dedup = DomainDedup()
        dedup.should_process('example.com')
        assert dedup.should_process('example.com') is False

    def test_different_domains_allowed(self):
        dedup = DomainDedup()
        assert dedup.should_process('a.com') is True
        assert dedup.should_process('b.com') is True

    def test_reset_clears_state(self):
        dedup = DomainDedup()
        dedup.should_process('example.com')
        dedup.reset()
        assert dedup.should_process('example.com') is True


# ──────────────────────────────────────────────────────────────────────
# Broker configuration
# ──────────────────────────────────────────────────────────────────────


class TestBrokerConfig:
    async def test_configure_and_shutdown(self, mock_llm_config, clean_broker):
        import yosoi.tasks
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)
        config = get_pipeline_config()
        assert config['contract'] is NewsArticle
        assert config['output_format'] == 'json'
        assert config['max_workers'] == 3
        # Semaphore should be created with the right limit
        assert yosoi.tasks._semaphore is not None
        await shutdown_broker()
        assert _pipeline_config == {}
        assert yosoi.tasks._semaphore is None

    def test_get_config_before_configure_raises(self, clean_broker):
        with pytest.raises(RuntimeError, match='Broker not configured'):
            get_pipeline_config()


# ──────────────────────────────────────────────────────────────────────
# process_url_task
# ──────────────────────────────────────────────────────────────────────


class TestProcessUrlTask:
    async def test_task_returns_success(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)

        # Call the task function directly (not via kiq) for unit testing
        result = await process_url_task.original_func(url='http://example.com', force=True)

        assert result['url'] == 'http://example.com'
        assert result['success'] is True
        assert 'elapsed' in result
        mock_pipeline.process_url.assert_awaited_once()
        await shutdown_broker()

    async def test_task_returns_failure(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=False)

        result = await process_url_task.original_func(url='http://fail.com')

        assert result['url'] == 'http://fail.com'
        assert result['success'] is False
        assert 'elapsed' in result
        await shutdown_broker()

    async def test_task_catches_exception(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(side_effect=Exception('boom'))

        result = await process_url_task.original_func(url='http://error.com')

        assert result['url'] == 'http://error.com'
        assert result['success'] is False
        assert 'boom' in result['error']
        assert 'elapsed' in result
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
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)

        results = await enqueue_urls(
            ['http://a.com/page1', 'http://b.com/page1'],
            dedup_by_domain=False,
        )

        assert 'http://a.com/page1' in results['successful']
        assert 'http://b.com/page1' in results['successful']
        assert results['failed'] == []
        await shutdown_broker()

    async def test_dedup_skips_duplicate_domain(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)

        results = await enqueue_urls(
            ['http://example.com/page1', 'http://example.com/page2'],
            dedup_by_domain=True,
        )

        assert 'http://example.com/page1' in results['successful']
        assert 'http://example.com/page2' in results['skipped']
        assert len(results['skipped']) == 1
        await shutdown_broker()

    async def test_failed_tasks_tracked(self, mocker, mock_llm_config, clean_broker):
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=False)

        results = await enqueue_urls(['http://fail.com'], dedup_by_domain=False)

        assert 'http://fail.com' in results['failed']
        assert results['successful'] == []
        await shutdown_broker()

    async def test_dedup_handles_bare_urls(self, mocker, mock_llm_config, clean_broker):
        """Bare URLs (no scheme) should still be deduped correctly by domain."""
        from yosoi.models.defaults import NewsArticle

        await configure_broker(mock_llm_config, contract=NewsArticle)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)

        results = await enqueue_urls(
            ['example.com/page1', 'example.com/page2'],
            dedup_by_domain=True,
        )

        # Second bare URL should be deduped, not both processed
        assert len(results['skipped']) == 1
        await shutdown_broker()

    async def test_broker_task_is_registered(self):
        # Verify the task decorator registered it properly
        assert process_url_task is not None
        assert hasattr(process_url_task, 'kiq')
        assert hasattr(process_url_task, 'original_func')
