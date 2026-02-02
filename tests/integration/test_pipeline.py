import unittest.mock

import pytest
from pydantic_ai import Agent

from yosoi.llm_config import LLMConfig
from yosoi.models import FieldSelectors, ScrapingConfig
from yosoi.pipeline import SelectorDiscoveryPipeline


@pytest.fixture
def mock_llm_config():
    return LLMConfig(provider='groq', model_name='test-model', api_key='test-key')


@pytest.fixture
def happy_path_html():
    return """
    <html>
    <body>
        <h1 class="title">Test Headline</h1>
        <span class="author">John Doe</span>
        <time>2025-01-01</time>
        <article>
            <p>Main content paragraph.</p>
        </article>
        <aside>
            <a href="/related">Related link</a>
        </aside>
    </body>
    </html>
    """


def test_pipeline_happy_path(mock_llm_config, happy_path_html):
    # 1. Setup expected output
    expected_output = ScrapingConfig(
        headline=FieldSelectors(primary='h1.title', fallback='h1', tertiary='NA'),
        author=FieldSelectors(primary='span.author', fallback='.author', tertiary='NA'),
        date=FieldSelectors(primary='time', fallback='.date', tertiary='NA'),
        body_text=FieldSelectors(primary='article p', fallback='p', tertiary='NA'),
        related_content=FieldSelectors(primary='aside a', fallback='.related a', tertiary='NA'),
    )

    # 2. Mock Agent with TestModel
    # We patch the agent creation in SelectorDiscovery or pass a pre-configured one.
    # The pipeline creates SelectorDiscovery which creates the agent.
    # We can patch SelectorDiscovery.__init__ or the factory it uses.

    with unittest.mock.patch('yosoi.discovery.Agent') as mock_agent_class:
        mock_agent = unittest.mock.MagicMock(spec=Agent)
        mock_result = unittest.mock.MagicMock()
        mock_result.output = expected_output
        mock_agent.run_sync.return_value = mock_result
        mock_agent_class.return_value = mock_agent

        pipeline = SelectorDiscoveryPipeline(mock_llm_config)

        # Mock Fetcher to return our HTML
        with unittest.mock.patch('yosoi.pipeline.create_fetcher') as mock_create_fetcher:
            mock_fetcher = unittest.mock.MagicMock()
            from yosoi.fetcher import ContentMetadata, FetchResult

            mock_fetcher.fetch.return_value = FetchResult(
                url='http://example.com',
                html=happy_path_html,
                status_code=200,
                metadata=ContentMetadata(content_length=len(happy_path_html)),
            )
            mock_create_fetcher.return_value = mock_fetcher

            # ACT
            success = pipeline.process_url('http://example.com', force=True)

            # ASSERT
            assert success is True

            # Check if selectors were saved
            saved = pipeline.storage.load_selectors('example.com')
            assert saved is not None
            assert saved['headline']['primary'] == 'h1.title'


def test_pipeline_fetch_failure(mock_llm_config):
    pipeline = SelectorDiscoveryPipeline(mock_llm_config)

    with unittest.mock.patch('yosoi.pipeline.create_fetcher') as mock_create_fetcher:
        mock_fetcher = unittest.mock.MagicMock()
        from yosoi.fetcher import FetchResult

        mock_fetcher.fetch.return_value = FetchResult(
            url='http://example.com', html=None, status_code=403, is_blocked=True, block_reason='Forbidden'
        )
        mock_create_fetcher.return_value = mock_fetcher

        # ACT
        success = pipeline.process_url('http://example.com', force=True)

        # ASSERT
        assert success is False


def test_pipeline_ai_failure(mock_llm_config, happy_path_html):
    with unittest.mock.patch('yosoi.discovery.Agent') as mock_agent_class:
        mock_agent = unittest.mock.MagicMock(spec=Agent)
        mock_agent.run_sync.side_effect = Exception('AI Error')
        mock_agent_class.return_value = mock_agent

        pipeline = SelectorDiscoveryPipeline(mock_llm_config)

        with unittest.mock.patch('yosoi.pipeline.create_fetcher') as mock_create_fetcher:
            mock_fetcher = unittest.mock.MagicMock()
            from yosoi.fetcher import ContentMetadata, FetchResult

            mock_fetcher.fetch.return_value = FetchResult(
                url='http://example.com',
                html=happy_path_html,
                status_code=200,
                metadata=ContentMetadata(content_length=len(happy_path_html)),
            )
            mock_create_fetcher.return_value = mock_fetcher

            # ACT
            # Should fallback to heuristics if AI fails 3 times
            success = pipeline.process_url('http://example.com', force=True, max_discovery_retries=1)

            # ASSERT
            assert success is True  # Success because of fallback heuristics
            saved = pipeline.storage.load_selectors('example.com')
            assert saved['headline']['primary'] == 'h1'  # Default heuristic
