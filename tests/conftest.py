import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from yosoi.core.discovery.config import LLMConfig
from yosoi.models import FieldSelectors
from yosoi.models.defaults import NewsArticle

# Single session-scoped exporter: register one TracerProvider for the whole
# test session, then clear() between tests. Avoids set_tracer_provider's
# "provider already set, ignoring" warning and is faster than per-test setup.
# Tests that need to inspect emitted spans take the `span_exporter` fixture.
_SPAN_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope='session', autouse=True)
def _install_test_tracer_provider():
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_SPAN_EXPORTER))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def span_exporter():
    """Return the in-memory OTel span exporter, cleared for this test."""
    _SPAN_EXPORTER.clear()
    yield _SPAN_EXPORTER
    from yosoi.utils import observability

    observability.reset_for_tests()


@pytest.fixture
def mock_llm_config():
    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test-key', temperature=0.0)


@pytest.fixture
def happy_path_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
    </head>
    <body>
        <h1 class="title">My Awesome Article</h1>
        <div class="meta">
            <span class="author">Jane Doe</span>
            <span class="date">2023-10-27</span>
        </div>
        <article>
            <p>This is the content of the article.</p>
        </article>
        <div class="related">
            <a href="/related1">Related 1</a>
        </div>
    </body>
    </html>
    """


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


@pytest.fixture
def html_fixture():
    """Return the load_html callable for qscrape.dev HTML fixtures.

    Usage::

        def test_something(html_fixture):
            html = html_fixture('mountainhome_home.html')
    """
    from tests.fixtures import load_html

    return load_html


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line('markers', 'integration: marks tests as integration tests')
    config.addinivalue_line('markers', 'unit: marks tests as unit tests')
    config.addinivalue_line('markers', 'eval: marks tests as evaluation tests')
    config.addinivalue_line('markers', 'smoke: marks opt-in live smoke tests')
    config.addinivalue_line(
        'markers',
        'browser_integration: requires YOSOI_INTEGRATION=1 and Chromium/Chrome',
    )


def pytest_collection_modifyitems(config, items):
    """Apply directory-based marks and conditional skips to collected items."""
    from pathlib import Path

    needs_browser = not os.getenv('YOSOI_INTEGRATION')
    skip_browser = pytest.mark.skip(reason='set YOSOI_INTEGRATION=1 to run browser integration tests')

    for item in items:
        if hasattr(item, 'fspath'):
            parts = Path(item.fspath).parts
            if 'integration' in parts:
                item.add_marker(pytest.mark.integration)
            elif 'unit' in parts:
                item.add_marker(pytest.mark.unit)
            elif 'evals' in parts:
                item.add_marker(pytest.mark.eval)
            elif 'smoke' in parts:
                item.add_marker(pytest.mark.smoke)

        if needs_browser and item.get_closest_marker('browser_integration'):
            item.add_marker(skip_browser)
