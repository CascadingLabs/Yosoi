from yosoi.pipeline import SelectorDiscoveryPipeline


def test_pipeline_happy_path(mocker, mock_llm_config, happy_path_html, mock_selectors, tmp_path):
    # Mock storage to use tmp_path
    storage_dir = tmp_path / 'selectors'
    storage_dir.mkdir(parents=True, exist_ok=True)  # Create the directory!

    # We patch init_yosoi to return our tmp_path instead of the default user dir
    mocker.patch('yosoi.storage.init_yosoi', return_value=storage_dir)

    # Setup Mocks using the mocker fixture (no unittest imports!)
    mock_agent = mocker.Mock()
    # The discovery class uses result.output
    mock_agent.run_sync.return_value = mocker.Mock(output=mock_selectors)

    # Patch the Agent class where it's imported in discovery
    # Note: SelectorDiscovery is imported in pipeline, but SelectorDiscovery imports Agent.
    # We need to patch where Agent is instantiated or used.
    # In SelectorDiscovery.__init__, it creates an Agent if not provided.
    # But SelectorDiscoveryPipeline initializes SelectorDiscovery with llm_config.
    # So SelectorDiscovery will call create_model and then Agent(...).
    # Easier: Mock SelectorDiscovery in pipeline? No, we want to test pipeline logic which calls discovery.
    # We should mock Agent in yosoi.discovery.
    mocker.patch('yosoi.discovery.Agent', return_value=mock_agent)

    # Mock Fetcher
    mock_fetcher = mocker.Mock()
    from yosoi.fetcher import ContentMetadata, FetchResult

    mock_fetcher.fetch.return_value = FetchResult(
        url='http://example.com',
        html=happy_path_html,
        status_code=200,
        metadata=ContentMetadata(content_length=len(happy_path_html)),
    )
    mocker.patch('yosoi.pipeline.create_fetcher', return_value=mock_fetcher)

    # We also need to mock create_model because SelectorDiscovery calls it
    mocker.patch('yosoi.discovery.create_model')

    pipeline = SelectorDiscoveryPipeline(mock_llm_config)

    # ACT
    success = pipeline.process_url('http://example.com', force=True)

    # ASSERT
    assert success is True

    # Verify it was saved
    saved = pipeline.storage.load_selectors('example.com')
    assert saved is not None
    assert saved['headline']['primary'] == 'h1.title'
