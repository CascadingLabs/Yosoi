import pytest

from yosoi.core.discovery.config import LLMConfig
from yosoi.models import FieldSelectors
from yosoi.models.defaults import NewsArticle


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


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line('markers', 'integration: marks tests as integration tests')
    config.addinivalue_line('markers', 'unit: marks tests as unit tests')
    config.addinivalue_line('markers', 'eval: marks tests as evaluation tests')


def pytest_collection_modifyitems(config, items):
    """Apply directory-based marks to collected test items."""
    from pathlib import Path

    for item in items:
        if hasattr(item, 'fspath'):
            parts = Path(item.fspath).parts
            if 'integration' in parts:
                item.add_marker(pytest.mark.integration)
            elif 'unit' in parts:
                item.add_marker(pytest.mark.unit)
            elif 'evals' in parts:
                item.add_marker(pytest.mark.eval)
