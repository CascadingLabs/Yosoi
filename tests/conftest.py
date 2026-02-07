import pytest

from yosoi.llm_config import LLMConfig
from yosoi.models import FieldSelectors, ScrapingConfig


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
    return ScrapingConfig(
        headline=FieldSelectors(primary='h1.title', fallback='h1', tertiary='NA'),
        author=FieldSelectors(primary='span.author', fallback='.author', tertiary='NA'),
        date=FieldSelectors(primary='span.date', fallback='.date', tertiary='NA'),
        body_text=FieldSelectors(primary='article', fallback='body', tertiary='NA'),
        related_content=FieldSelectors(primary='.related', fallback='aside', tertiary='NA'),
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line('markers', 'integration: marks tests as integration tests')
    config.addinivalue_line('markers', 'unit: marks tests as unit tests')
    config.addinivalue_line('markers', 'eval: marks tests as evaluation tests')


def pytest_collection_modifyitems(config, items):
    """Apply directory-based marks to collected test items."""

    for item in items:
        # Get the test file path
        if hasattr(item, 'fspath'):
            file_path = str(item.fspath)

            # Add marks based on directory
            if '/tests/integration/' in file_path:
                item.add_marker(pytest.mark.integration)
            elif '/tests/unit/' in file_path:
                item.add_marker(pytest.mark.unit)
            elif '/tests/evals/' in file_path:
                item.add_marker(pytest.mark.eval)
