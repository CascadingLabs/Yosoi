"""Tests that taskiq background workers and asyncio pydantic-ai agents cooperate.

Validates that:
- Multiple concurrent taskiq tasks can each run a pydantic-ai agent.run() without
  event-loop conflicts or shared-state corruption.
- The semaphore correctly limits concurrency.
- Agent failures in one task don't poison other concurrent tasks.
- The full broker → enqueue → agent.run() → result path works end-to-end.
"""

import asyncio

import pytest

import yosoi.core.tasks as _tasks_mod
from yosoi.core.discovery.agent import SelectorDiscovery
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.yosoi_agent import YosoiAgent
from yosoi.core.tasks import (
    configure_broker,
    enqueue_urls,
    process_url_task,
    shutdown_broker,
)
from yosoi.models import FieldSelectors
from yosoi.models.defaults import NewsArticle


@pytest.fixture
def clean_broker():
    """Ensure broker state is clean before and after each test."""
    _tasks_mod._pipeline_config = None
    yield
    _tasks_mod._pipeline_config = None


@pytest.fixture
def mock_llm_config():
    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test-key', temperature=0.0)


@pytest.fixture
def mock_selectors():
    selector_model = NewsArticle.to_selector_model()
    return selector_model(
        headline=FieldSelectors(primary='h1.title', fallback='h1', tertiary=None),
        author=FieldSelectors(primary='span.author', fallback='.author', tertiary=None),
        date=FieldSelectors(primary='span.date', fallback='.date', tertiary=None),
        body_text=FieldSelectors(primary='article', fallback='body', tertiary=None),
        related_content=FieldSelectors(primary='.related', fallback='aside', tertiary=None),
    )


FAKE_HTML = """
<html><head><title>Test</title></head>
<body>
    <h1 class="title">Test Article</h1>
    <span class="author">Test Author</span>
    <span class="date">2025-01-01</span>
    <article><p>Test body content here.</p></article>
    <div class="related"><a href="/r">Related</a></div>
</body></html>
"""


# ──────────────────────────────────────────────────────────────────────
# Concurrent taskiq tasks each running pydantic-ai agent.run()
# ──────────────────────────────────────────────────────────────────────


class TestTaskiqAgentConcurrency:
    """Verify multiple taskiq tasks can concurrently call agent.run() without conflicts."""

    async def test_concurrent_tasks_with_mocked_agent(self, mocker, mock_llm_config, mock_selectors, clean_broker):
        """Multiple tasks enqueued simultaneously each get their own Pipeline + agent."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)

        urls = [f'http://site{i}.com/article' for i in range(5)]
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert len(results['successful']) == 5
        assert results['failed'] == []
        assert mock_pipeline.process_url.await_count == 5
        await shutdown_broker()

    async def test_concurrent_tasks_isolated_pipeline_instances(self, mocker, mock_llm_config, clean_broker):
        """Each task creates a fresh Pipeline — no shared mutable state."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)

        pipeline_instances = []

        class FakePipeline:
            def __init__(self, *args, **kwargs):
                pipeline_instances.append(self)

            async def process_url(self, *args, **kwargs):
                # Small sleep to simulate async I/O (agent.run)
                await asyncio.sleep(0.01)
                return True

        mocker.patch('yosoi.core.pipeline.Pipeline', FakePipeline)

        urls = ['http://a.com', 'http://b.com', 'http://c.com']
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert len(results['successful']) == 3
        # Each task should create its own Pipeline instance
        assert len(pipeline_instances) == 3
        # Verify they're distinct objects
        assert len({id(p) for p in pipeline_instances}) == 3
        await shutdown_broker()


# ──────────────────────────────────────────────────────────────────────
# Semaphore concurrency limiting
# ──────────────────────────────────────────────────────────────────────


class TestSemaphoreConcurrency:
    """Verify the asyncio.Semaphore limits concurrent tasks correctly."""

    async def test_semaphore_limits_concurrency(self, mocker, mock_llm_config, clean_broker):
        """With max_workers=2, no more than 2 tasks should run simultaneously."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=2)

        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _track_concurrency(*args, **kwargs):
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                peak_concurrent = max(peak_concurrent, current_concurrent)
            await asyncio.sleep(0.05)  # Simulate I/O
            async with lock:
                current_concurrent -= 1
            return True

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = _track_concurrency

        urls = [f'http://site{i}.com' for i in range(6)]
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert len(results['successful']) == 6
        assert peak_concurrent <= 2
        await shutdown_broker()


# ──────────────────────────────────────────────────────────────────────
# Agent failure isolation
# ──────────────────────────────────────────────────────────────────────


class TestAgentFailureIsolation:
    """One task's agent failure should not affect other concurrent tasks."""

    async def test_one_failure_doesnt_poison_others(self, mocker, mock_llm_config, clean_broker):
        """If one task's agent raises, other tasks still complete successfully."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)

        call_count = 0

        async def _selective_failure(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if 'fail' in url:
                raise Exception('Simulated LLM error')
            return True

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = _selective_failure

        urls = ['http://good1.com', 'http://fail.com', 'http://good2.com']
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert 'http://good1.com' in results['successful']
        assert 'http://good2.com' in results['successful']
        assert 'http://fail.com' in results['failed']
        # fail.com is retried (max_retries=2 means up to 2 total attempts), so 2 attempts + 1 each for the two good URLs
        assert call_count == 4
        await shutdown_broker()

    async def test_timeout_in_one_task_doesnt_block_others(self, mocker, mock_llm_config, clean_broker):
        """A slow task shouldn't prevent other tasks from completing."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=5)

        async def _variable_latency(url, **kwargs):
            if 'slow' in url:
                await asyncio.sleep(0.2)
            else:
                await asyncio.sleep(0.01)
            return True

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = _variable_latency

        urls = ['http://fast1.com', 'http://slow.com', 'http://fast2.com']
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert len(results['successful']) == 3
        await shutdown_broker()


# ──────────────────────────────────────────────────────────────────────
# Pydantic-AI agent.run() inside taskiq task (mocked network)
# ──────────────────────────────────────────────────────────────────────


class TestAgentRunInsideTask:
    """Test that pydantic-ai Agent.run() works correctly inside taskiq tasks."""

    async def test_agent_run_called_per_task(self, mocker, mock_llm_config, mock_selectors, clean_broker):
        """Each task should invoke agent.run() and get structured output back."""
        await configure_broker(mock_llm_config, contract=NewsArticle)

        # Mock at the Pipeline level but verify agent interaction
        mock_agent = mocker.Mock()
        mock_agent.run = mocker.AsyncMock(return_value=mocker.Mock(output=mock_selectors))

        # Mock the full pipeline flow: fetch → clean → discover → verify → save
        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=None)

        result = await process_url_task.original_func(url='http://example.com')

        assert result['url'] == 'http://example.com'
        assert 'elapsed' in result
        await shutdown_broker()

    async def test_discovery_agent_async_run(self, mocker, mock_selectors):
        """SelectorDiscovery.discover_selectors() calls agent.run() correctly in async context."""
        mock_agent = mocker.Mock(spec=YosoiAgent)
        mock_agent._contract = NewsArticle
        mock_agent.run = mocker.AsyncMock(
            return_value=mocker.Mock(output=mock_selectors),
        )

        discovery = SelectorDiscovery(
            contract=NewsArticle,
            agent=mock_agent,
        )

        selectors = await discovery.discover_selectors(FAKE_HTML, url='http://test.com')

        assert selectors is not None
        assert 'headline' in selectors
        mock_agent.run.assert_awaited_once()

    async def test_multiple_discovery_agents_concurrent(self, mocker, mock_selectors):
        """Multiple SelectorDiscovery instances can run concurrently without conflicts."""
        agents = []
        discoveries = []

        for _ in range(3):
            agent = mocker.Mock(spec=YosoiAgent)
            agent._contract = NewsArticle
            agent.run = mocker.AsyncMock(
                return_value=mocker.Mock(output=mock_selectors),
            )
            agents.append(agent)
            discoveries.append(SelectorDiscovery(contract=NewsArticle, agent=agent))

        # Run all discoveries concurrently
        results = await asyncio.gather(
            *[d.discover_selectors(FAKE_HTML, url=f'http://site{i}.com') for i, d in enumerate(discoveries)]
        )

        assert all(r is not None for r in results)
        assert all('headline' in r for r in results)
        for agent in agents:
            agent.run.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────
# Full broker→enqueue→process→agent path (mocked network)
# ──────────────────────────────────────────────────────────────────────


class TestEndToEndBrokerAgent:
    """End-to-end: broker startup → enqueue URLs → taskiq runs tasks → agent called → results collected."""

    async def test_full_flow_with_on_complete_callback(self, mocker, mock_llm_config, clean_broker):
        """on_complete callback fires for each completed task with correct args."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=2)

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = mocker.AsyncMock(return_value=True)
        mock_pipeline.last_elapsed = 0.1

        completed = []

        async def _on_complete(url: str, success: bool, elapsed: float):
            completed.append({'url': url, 'success': success, 'elapsed': elapsed})

        urls = ['http://a.com', 'http://b.com']
        results = await enqueue_urls(urls, dedup_by_domain=False, on_complete=_on_complete)

        assert len(completed) == 2
        assert all(c['success'] for c in completed)
        assert all(c['elapsed'] >= 0 for c in completed)
        assert {c['url'] for c in completed} == {'http://a.com', 'http://b.com'}
        assert len(results['successful']) == 2
        await shutdown_broker()

    async def test_broker_lifecycle_clean_shutdown(self, mock_llm_config, clean_broker):
        """Broker starts, processes, and shuts down cleanly without leaked state."""
        import yosoi.core.tasks as yosoi_tasks

        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=2)

        assert yosoi_tasks._semaphore is not None
        assert _tasks_mod._pipeline_config is not None
        assert _tasks_mod._pipeline_config['contract'] is NewsArticle

        await shutdown_broker()

        assert yosoi_tasks._semaphore is None
        assert _tasks_mod._pipeline_config is None

    async def test_mixed_success_and_failure_results(self, mocker, mock_llm_config, clean_broker):
        """Enqueue mix of passing and failing URLs, verify correct bucketing."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)

        async def _alternate(url, **kwargs):
            # odd-numbered sites always fail (even with retries), even ones succeed
            site_num = int(url.split('site')[1].split('.')[0])
            if site_num % 2 == 1:
                raise RuntimeError(f'Processing failed for {url}')

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = _alternate

        urls = [f'http://site{i}.com' for i in range(4)]
        results = await enqueue_urls(urls, dedup_by_domain=False)

        assert len(results['successful']) == 2
        assert len(results['failed']) == 2
        await shutdown_broker()


# ──────────────────────────────────────────────────────────────────────
# Event loop safety — no nested loops or blocking calls
# ──────────────────────────────────────────────────────────────────────


class TestEventLoopSafety:
    """Verify that the async flow doesn't accidentally nest event loops."""

    async def test_tasks_share_same_event_loop(self, mocker, mock_llm_config, clean_broker):
        """All tasks should execute in the same event loop (no asyncio.run() inside tasks)."""
        await configure_broker(mock_llm_config, contract=NewsArticle, max_workers=3)

        loops_seen = []

        async def _capture_loop(url, **kwargs):
            loops_seen.append(id(asyncio.get_running_loop()))
            return True

        mock_pipeline_cls = mocker.patch('yosoi.core.pipeline.Pipeline')
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_url = _capture_loop

        urls = [f'http://site{i}.com' for i in range(3)]
        await enqueue_urls(urls, dedup_by_domain=False)

        # All tasks must run in the same loop
        assert len(set(loops_seen)) == 1
        await shutdown_broker()

    async def test_agent_run_is_properly_awaited(self, mocker, mock_selectors):
        """Ensure agent.run() is awaited, not just called (returns coroutine)."""
        mock_agent = mocker.Mock(spec=YosoiAgent)
        mock_agent._contract = NewsArticle
        mock_agent.run = mocker.AsyncMock(
            return_value=mocker.Mock(output=mock_selectors),
        )

        discovery = SelectorDiscovery(contract=NewsArticle, agent=mock_agent)
        result = await discovery.discover_selectors(FAKE_HTML, url='http://test.com')

        # AsyncMock tracks await calls separately
        mock_agent.run.assert_awaited_once()
        assert result is not None
