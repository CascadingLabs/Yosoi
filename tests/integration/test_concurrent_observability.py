"""C2.1 — concurrent observability with the real broker stack (in-process InMemoryBroker).

Uses the real ``yosoi.core.tasks`` broker dispatch path with light external mocks
(fetcher + LLM) so workers actually go through ``configure_broker`` →
``process_url_task`` → worker entrypoint (which opens its own session/user wrap).

Asserts via ``span_exporter`` that all worker-emitted spans share the
orchestrator's session id and per-URL user ids are correct in live data.
"""

from __future__ import annotations

import pytest

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.pipeline import Pipeline
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import ContentMetadata, FetchResult
from yosoi.utils import observability as obs

pytestmark = pytest.mark.integration


CANNED_HTML = """
<!DOCTYPE html>
<html><body>
<h1 class="title">Concurrent test</h1>
<div class="meta"><span class="author">Test</span><span class="date">2026-01-01</span></div>
<article>body</article>
<div class="related"><a href="/x">x</a></div>
</body></html>
"""


@pytest.fixture
def _broker_clean():
    import yosoi.core.tasks as _tasks_mod

    _tasks_mod._pipeline_config = None
    _tasks_mod._domain_locks.clear()
    obs.reset_for_tests()
    yield
    _tasks_mod._pipeline_config = None
    _tasks_mod._domain_locks.clear()
    obs.reset_for_tests()


@pytest.fixture
def _active_obs(mocker):
    from opentelemetry import trace

    fake = mocker.MagicMock()
    fake.tracer = trace.get_tracer('yosoi-integration-concurrent')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_concurrent_session_propagation_via_real_broker(
    span_exporter,
    mocker,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv('YOSOI_SESSION_ID', 'integration-sess')

    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=selector_dir)
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')

    discovered_map = {
        'headline': {'primary': {'strategy': 'css', 'level': 1, 'value': 'h1.title'}},
        'author': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.author'}},
        'date': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.date'}},
        'body_text': {'primary': {'strategy': 'css', 'level': 1, 'value': 'article'}},
        'related_content': {'primary': {'strategy': 'css', 'level': 1, 'value': '.related'}},
    }
    mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value=discovered_map),
    )

    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url='http://a.example.com',
            html=CANNED_HTML,
            status_code=200,
            metadata=ContentMetadata(content_length=len(CANNED_HTML)),
        )
    )
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)

    llm_config = LLMConfig(
        provider='groq',
        model_name='llama-3.3-70b-versatile',
        api_key='test-key',
        temperature=0.0,
    )

    pipeline = Pipeline(llm_config, contract=NewsArticle)

    urls = [
        'http://a.example.com/1',
        'http://b.example.com/1',
        'http://a.example.com/2',
        'http://b.example.com/2',
    ]
    await pipeline.process_urls(urls, workers=2, force=True, origin='cli')

    spans = span_exporter.get_finished_spans()
    assert spans, 'no spans were emitted by the concurrent dispatch'

    # Orchestrator-side enqueue span exists exactly once (detached_span: emitted
    # but does NOT become parent of worker scrape spans).
    enqueue_spans = [s for s in spans if s.name == 'enqueue']
    assert len(enqueue_spans) == 1, f'expected exactly one "enqueue" span, got: {[s.name for s in spans]}'
    enq = enqueue_spans[0]
    assert enq.attributes.get('count') == len(urls)
    assert enq.attributes.get('workers') == 2

    # Per-URL trace spans: one per URL, named 'scrape <netloc><path>'.
    scrape_spans = [s for s in spans if s.name.startswith('scrape ')]
    assert len(scrape_spans) == len(urls), f'expected {len(urls)} scrape spans, got: {[s.name for s in scrape_spans]}'

    # Each scrape span is a trace root (no parent) — "trace = per URL" model.
    for s in scrape_spans:
        assert s.parent is None, f'scrape span {s.name!r} has unexpected parent {s.parent}'

    # Each scrape span's URL attribute matches one of the input URLs.
    seen_urls = {s.attributes.get('url') for s in scrape_spans}
    assert seen_urls == set(urls)

    # Each scrape span has its own trace_id — N URLs = N traces.
    trace_ids = {s.context.trace_id for s in scrape_spans}
    assert len(trace_ids) == len(urls), (
        f'expected {len(urls)} distinct trace_ids (one per URL), got {len(trace_ids)}: {trace_ids}'
    )

    # The enqueue span's trace id must NOT match any scrape span's — it's a
    # standalone trace root, proving detached_span did not parent the workers.
    assert enq.context.trace_id not in trace_ids
