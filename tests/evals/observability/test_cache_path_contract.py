"""Selector-cache observability view: ``yosoi.cache.path`` on the scrape root span.

Companion to the :mod:`pydantic_evals` dataset in ``test_observability_contract.py``
(LLM + A3Node views). The cache view is asserted with a real two-pass pipeline
run — pass 1 discovers fresh (``path='fresh'``), pass 2 reuses the persisted
selectors (``path='cached'``) — because seeding/replaying the selector cache is
expressed far more cleanly with pytest fixtures than a self-contained driver.

Transport is fully mocked (fetcher + discovery orchestrator + model), so the run
is deterministic with no live LLM, network, or browser.
"""

from __future__ import annotations

import pytest

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.pipeline import Pipeline
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import ContentMetadata, FetchResult
from yosoi.utils import observability as obs

pytestmark = pytest.mark.eval

CANNED_HTML = """
<!DOCTYPE html>
<html><body>
<h1 class="title">Cache contract test headline</h1>
<div class="meta"><span class="author">Test Author</span><span class="date">2026-01-01</span></div>
<article>Body text for the article goes here.</article>
<div class="related"><a href="/x">x</a></div>
</body></html>
"""

DISCOVERED_MAP = {
    'headline': {'primary': {'strategy': 'css', 'level': 1, 'value': 'h1.title'}},
    'author': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.author'}},
    'date': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.date'}},
    'body_text': {'primary': {'strategy': 'css', 'level': 1, 'value': 'article'}},
    'related_content': {'primary': {'strategy': 'css', 'level': 1, 'value': '.related'}},
}


@pytest.fixture(autouse=True)
def _clean_obs():
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


@pytest.fixture
def _active_obs(mocker):
    from opentelemetry import trace

    fake = mocker.MagicMock()
    fake.tracer = trace.get_tracer('yosoi-eval-cache')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


def _cache_path_of_scrape_span(span_exporter) -> str | None:
    scrape_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith('scrape ')]
    assert len(scrape_spans) == 1, f'expected one scrape span, got {[s.name for s in scrape_spans]}'
    return scrape_spans[0].attributes.get(obs.ATTR_CACHE_PATH)


@pytest.mark.usefixtures('_active_obs')
async def test_cache_path_fresh_then_cached(span_exporter, mocker, tmp_path):
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
    mocker.patch(
        'yosoi.core.discovery.orchestrator.DiscoveryOrchestrator.discover_selectors',
        new=mocker.AsyncMock(return_value=DISCOVERED_MAP),
    )

    fetch_result = FetchResult(
        url='https://news.example.com/a',
        html=CANNED_HTML,
        status_code=200,
        metadata=ContentMetadata(content_length=len(CANNED_HTML)),
    )
    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(return_value=fetch_result)
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)

    llm_config = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test-key', temperature=0.0)
    pipeline = Pipeline(llm_config, contract=NewsArticle)
    url = 'https://news.example.com/a'

    # Pass 1 — no cache yet → fresh discovery.
    span_exporter.clear()
    async for _ in pipeline.scrape(url, force=True):
        pass
    assert _cache_path_of_scrape_span(span_exporter) == obs.CACHE_FRESH

    # Pass 2 — selectors persisted by pass 1 → cached path, no re-discovery.
    span_exporter.clear()
    async for _ in pipeline.scrape(url, force=False):
        pass
    assert _cache_path_of_scrape_span(span_exporter) == obs.CACHE_CACHED
