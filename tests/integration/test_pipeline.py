from pydantic_ai import Agent

from yosoi.fetcher import ContentMetadata, FetchResult
from yosoi.pipeline import SelectorDiscoveryPipeline


def test_pipeline_happy_path(mocker, mock_llm_config, happy_path_html, mock_selectors):
    # 1. Mock Agent
    mock_agent = mocker.Mock(spec=Agent)
    mock_agent.run_sync.return_value = mocker.Mock(output=mock_selectors)
    mocker.patch('yosoi.discovery.Agent', return_value=mock_agent)

    # 2. Mock Fetcher
    mock_fetcher = mocker.Mock()
    mock_fetcher.fetch.return_value = FetchResult(
        url='http://example.com',
        html=happy_path_html,
        status_code=200,
        metadata=ContentMetadata(content_length=len(happy_path_html)),
    )
    mocker.patch('yosoi.pipeline.create_fetcher', return_value=mock_fetcher)

    pipeline = SelectorDiscoveryPipeline(mock_llm_config)

    # ACT
    success = pipeline.process_url('http://example.com', force=True)

    # ASSERT
    assert success is True
    saved = pipeline.storage.load_selectors('example.com')
    assert saved is not None
    assert saved['headline']['primary'] == 'h1.title'


def test_pipeline_fetch_failure(mocker, mock_llm_config):
    # Mock Fetcher
    mock_fetcher = mocker.Mock()
    mock_fetcher.fetch.return_value = FetchResult(
        url='http://example.com', html=None, status_code=403, is_blocked=True, block_reason='Forbidden'
    )
    mocker.patch('yosoi.pipeline.create_fetcher', return_value=mock_fetcher)

    pipeline = SelectorDiscoveryPipeline(mock_llm_config)

    # ACT
    success = pipeline.process_url('http://example.com', force=True)

    # ASSERT
    assert success is False


def test_pipeline_ai_failure(mocker, mock_llm_config, happy_path_html):
    # 1. Mock Agent to fail
    mock_agent = mocker.Mock(spec=Agent)
    mock_agent.run_sync.side_effect = Exception('AI Error')
    mocker.patch('yosoi.discovery.Agent', return_value=mock_agent)

    # 2. Mock Fetcher
    mock_fetcher = mocker.Mock()
    mock_fetcher.fetch.return_value = FetchResult(
        url='http://example.com',
        html=happy_path_html,
        status_code=200,
        metadata=ContentMetadata(content_length=len(happy_path_html)),
    )
    mocker.patch('yosoi.pipeline.create_fetcher', return_value=mock_fetcher)

    # 3. Use heuristics as fallback
    pipeline = SelectorDiscoveryPipeline(mock_llm_config)

    # ACT
    # Should fallback to heuristics if AI fails
    success = pipeline.process_url('http://example.com', force=True, max_discovery_retries=1)

    # ASSERT
    assert success is True  # Success because of fallback heuristics
    saved = pipeline.storage.load_selectors('example.com')
    assert saved is not None
    assert saved['headline']['primary'] == 'h1'  # Default heuristic
