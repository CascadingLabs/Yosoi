from pydantic_ai import Agent

from yosoi.core.pipeline import Pipeline
from yosoi.models.defaults import NewsArticle
from yosoi.models.results import ContentMetadata, FetchResult


async def test_pipeline_happy_path(mocker, mock_llm_config, happy_path_html, mock_selectors, tmp_path):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))

    # 1. Mock Agent (async — use .run instead of .run_sync)
    mock_agent = mocker.Mock(spec=Agent)
    mock_agent.run = mocker.AsyncMock(return_value=mocker.Mock(output=mock_selectors))
    mocker.patch('yosoi.core.discovery.agent.Agent', return_value=mock_agent)
    mocker.patch('yosoi.core.discovery.agent.create_model')

    # 2. Mock Fetcher (async fetch)
    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url='http://example.com',
            html=happy_path_html,
            status_code=200,
            metadata=ContentMetadata(content_length=len(happy_path_html)),
        )
    )
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)

    # ACT
    success = await pipeline.process_url('http://example.com', force=True)

    # ASSERT
    assert success is True
    saved = pipeline.storage.load_selectors('example.com')
    assert saved is not None
    # primary is now a SelectorEntry dict: {'strategy': 'css', 'level': 1, 'value': '...'}
    primary = saved['headline']['primary']
    assert isinstance(primary, dict)
    assert primary['value'] == 'h1.title'


async def test_pipeline_fetch_failure(mocker, mock_llm_config, tmp_path):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))
    mocker.patch('yosoi.core.discovery.agent.create_model')
    mocker.patch('yosoi.core.discovery.agent.Agent')

    # Mock Fetcher (async fetch)
    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url='http://example.com', html=None, status_code=403, is_blocked=True, block_reason='Forbidden'
        )
    )
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)

    # ACT
    success = await pipeline.process_url('http://example.com', force=True)

    # ASSERT
    assert success is False


async def test_pipeline_ai_failure(mocker, mock_llm_config, happy_path_html, tmp_path):
    selector_dir = tmp_path / 'selectors'
    content_dir = tmp_path / 'content'
    selector_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch('yosoi.storage.persistence.init_yosoi', side_effect=[selector_dir, content_dir])
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 'tracking.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'test.log'))

    # 1. Mock Agent to fail (async)
    mock_agent = mocker.Mock(spec=Agent)
    mock_agent.run = mocker.AsyncMock(side_effect=Exception('AI Error'))
    mocker.patch('yosoi.core.discovery.agent.Agent', return_value=mock_agent)
    mocker.patch('yosoi.core.discovery.agent.create_model')

    # 2. Mock Fetcher (async fetch)
    mock_fetcher = mocker.AsyncMock()
    mock_fetcher.fetch = mocker.AsyncMock(
        return_value=FetchResult(
            url='http://ai-failure.com',
            html=happy_path_html,
            status_code=200,
            metadata=ContentMetadata(content_length=len(happy_path_html)),
        )
    )
    mocker.patch('yosoi.core.pipeline.create_fetcher', return_value=mock_fetcher)

    pipeline = Pipeline(mock_llm_config, contract=NewsArticle)

    # ACT — should fail if AI fails (Fail Fast)
    success = await pipeline.process_url('http://ai-failure.com', force=True, max_discovery_retries=1)

    # ASSERT
    assert success is False
    saved = pipeline.storage.load_selectors('ai-failure.com')
    assert saved is None
