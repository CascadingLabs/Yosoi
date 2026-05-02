"""Span-tree integration test for the Pipeline observability wiring.

Asserts the *actual* OTel span tree emitted by ``Pipeline.scrape()`` and that
``propagate_attributes`` is invoked with the expected ``user_id`` /
``session_id`` for the per-URL trace.

The canned HTML below is intentionally minimal so the expected span set is
deterministic. Heavy collaborators (fetcher, cleaner, discovery, verifier,
extractor, storage) are stubbed; we only exercise the observability side.
"""

from contextlib import contextmanager

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FetchResult
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs
from yosoi.utils.signatures import contract_signature

CANNED_URL = 'https://shop.example.com/x'
CANNED_HTML = '<html><body><h1>book</h1><span class="price">$10</span></body></html>'
CLEANED_HTML = '<body><h1>book</h1><span class="price">$10</span></body>'
DISCOVERED_SELECTORS = {'title': {'primary': 'h1'}, 'price': {'primary': 'span.price'}}
EXTRACTED = {'title': 'book', 'price': '$10'}

# Expected span set for the fresh-discovery path of the canned input above.
# Pinned explicitly per plan B3: a vague subset is rejected.
EXPECTED_CHILD_SPANS = {'fetch', 'clean', 'discover', 'verify', 'extract', 'validate', 'save'}
EXPECTED_ROOT_SPAN = 'scrape shop.example.com/x'


class _SimpleContract(Contract):
    title: str = ys.Title()
    price: float = ys.Price()


def _capturing_propagate(captured: list[dict]):
    @contextmanager
    def _fake(**kwargs):
        captured.append(kwargs)
        yield

    return _fake


@pytest.fixture
def pipeline_stub(mocker):
    """Pipeline instance with all heavy collaborators mocked."""
    stub = Pipeline.__new__(Pipeline)
    stub.contract = _SimpleContract
    stub.console = mocker.MagicMock()
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.cleaner.clean_html.return_value = CLEANED_HTML
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=DISCOVERED_SELECTORS)
    stub.verifier = mocker.MagicMock()
    stub.extractor = mocker.MagicMock()
    stub.storage = mocker.MagicMock()
    stub.storage.load_snapshots.return_value = None
    stub.storage.load_selectors.return_value = None
    stub.tracker = mocker.MagicMock()
    stub.tracker.record_url = mocker.AsyncMock()
    stub._client = mocker.AsyncMock()
    stub.debug = mocker.MagicMock()
    stub.debug_mode = False
    stub.output_formats = ['json']
    stub.force = False
    stub.selector_level = SelectorLevel.CSS
    stub._contract_sig = contract_signature(stub.contract)
    stub.session_id = 'test-session-xyz'
    stub._url_start = 0.0
    return stub


@pytest.fixture
def _active_observability(mocker):
    """Install a fake Langfuse client whose tracer is the test TracerProvider's."""
    from opentelemetry import trace

    obs.reset_for_tests()
    fake = mocker.MagicMock()
    fake.tracer = trace.get_tracer('yosoi-test')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


async def _drain(gen):
    return [item async for item in gen]


@pytest.mark.usefixtures('_active_observability')
async def test_scrape_emits_pinned_span_tree(pipeline_stub, span_exporter, mocker):
    """The fresh-discovery path emits exactly one root span and the pinned set of stage children."""
    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))
    mocker.patch.object(Pipeline, 'normalize_url', return_value=CANNED_URL)
    mocker.patch.object(
        Pipeline,
        '_create_fetcher',
        return_value=mocker.MagicMock(__aenter__=mocker.AsyncMock(), __aexit__=mocker.AsyncMock()),
    )
    fetch_result = FetchResult(url=CANNED_URL, html=CANNED_HTML, status_code=200)
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value=CLEANED_HTML)
    mocker.patch.object(Pipeline, '_discover', return_value=(DISCOVERED_SELECTORS, True))
    mocker.patch.object(Pipeline, '_resolve_root', return_value=None)
    mocker.patch.object(Pipeline, '_root_value', return_value=None)
    mocker.patch.object(Pipeline, '_verify', return_value=DISCOVERED_SELECTORS)
    mocker.patch.object(Pipeline, '_extract', return_value=EXTRACTED)
    mocker.patch.object(Pipeline, '_validate_items', return_value=[EXTRACTED])
    mocker.patch.object(Pipeline, '_finish', new=mocker.AsyncMock())

    items = await _drain(Pipeline.scrape(pipeline_stub, CANNED_URL))
    assert items == [EXTRACTED]

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Exactly one root span with the expected name.
    root_spans = [s for s in spans if s.name == EXPECTED_ROOT_SPAN]
    assert len(root_spans) == 1, f'expected 1 root span {EXPECTED_ROOT_SPAN!r}, got names: {span_names}'
    root = root_spans[0]
    assert root.attributes['url'] == CANNED_URL

    # Children: every emitted non-root span name must be in the expected set,
    # and every name in the expected set must be present.
    child_names = {s.name for s in spans if s.name != EXPECTED_ROOT_SPAN}
    assert child_names == EXPECTED_CHILD_SPANS, (
        f'span set mismatch: missing={EXPECTED_CHILD_SPANS - child_names}, '
        f'unexpected={child_names - EXPECTED_CHILD_SPANS}'
    )

    # propagate_attributes must have been called with user_id=shop.example.com.
    # session_id propagation is owned by Pipeline.process_urls (the outer wrap),
    # not Pipeline.scrape — see test_pipeline_concurrent_observability for that.
    user_calls = [c for c in captured if 'user_id' in c]
    assert any(c['user_id'] == 'shop.example.com' for c in user_calls), (
        f'expected user_id=shop.example.com in propagate_attributes calls, got: {captured}'
    )
    # The user_id call must also carry the matching tag for filtering.
    assert any(c.get('user_id') == 'shop.example.com' and c.get('tags') == ['shop.example.com'] for c in captured), (
        f'expected user_id+tags=[shop.example.com] in calls: {captured}'
    )

    # P3 — root span carries the Langfuse trace-input attribute.
    import json as _json

    raw_input = root.attributes.get('langfuse.observation.input')
    assert raw_input is not None, 'root span missing langfuse.observation.input'
    payload_in = _json.loads(raw_input)
    assert payload_in['url'] == CANNED_URL
    assert payload_in['contract']['name'] == _SimpleContract.__name__
    assert isinstance(payload_in['contract']['fields'], dict)

    # P3 — root span carries the Langfuse trace-output attribute on success.
    raw_output = root.attributes.get('langfuse.observation.output')
    assert raw_output is not None, 'root span missing langfuse.observation.output'
    payload_out = _json.loads(raw_output)
    assert payload_out['path'] == 'fresh'
    assert isinstance(payload_out['selectors'], dict)
    assert payload_out['extracted_count'] == 1
    assert payload_out['extracted_sample'] == EXTRACTED


# ────────────────────────────────────────────────────────────────────
# Reconciliation B — direct scrape() (script-mode, no process_urls wrap)
# must still propagate session_id with tags=['yosoi','script'].
# ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures('_active_observability')
async def test_direct_scrape_emits_session_with_script_tag(pipeline_stub, span_exporter, mocker, monkeypatch):
    """Test 6 — calling Pipeline.scrape() directly (no outer process_urls wrap)
    still opens an ``observability.session(...)`` propagation with
    ``tags=['yosoi','script']`` so the URL trace gets a session id."""
    monkeypatch.setenv('YOSOI_SESSION_ID', 'direct-scrape-sess')
    obs.reset_for_tests()
    # Re-active the patched _instance after reset.
    from opentelemetry import trace as _trace

    fake = mocker.MagicMock()
    fake.tracer = _trace.get_tracer('yosoi-direct-scrape-test')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)

    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))
    mocker.patch.object(Pipeline, 'normalize_url', return_value=CANNED_URL)
    mocker.patch.object(
        Pipeline,
        '_create_fetcher',
        return_value=mocker.MagicMock(__aenter__=mocker.AsyncMock(), __aexit__=mocker.AsyncMock()),
    )
    mocker.patch.object(Pipeline, '_fetch', return_value=FetchResult(url=CANNED_URL, html=CANNED_HTML, status_code=200))
    mocker.patch.object(Pipeline, '_clean', return_value=CLEANED_HTML)
    mocker.patch.object(Pipeline, '_discover', return_value=(DISCOVERED_SELECTORS, True))
    mocker.patch.object(Pipeline, '_resolve_root', return_value=None)
    mocker.patch.object(Pipeline, '_root_value', return_value=None)
    mocker.patch.object(Pipeline, '_verify', return_value=DISCOVERED_SELECTORS)
    mocker.patch.object(Pipeline, '_extract', return_value=EXTRACTED)
    mocker.patch.object(Pipeline, '_validate_items', return_value=[EXTRACTED])
    mocker.patch.object(Pipeline, '_finish', new=mocker.AsyncMock())

    await _drain(Pipeline.scrape(pipeline_stub, CANNED_URL))

    sess_calls = [c for c in captured if c.get('session_id') == 'direct-scrape-sess']
    assert sess_calls, f'direct scrape() must open a session() wrap with the resolved id; got: {captured}'
    assert any(c.get('tags') == ['yosoi', 'script'] for c in sess_calls), (
        f'expected tags=["yosoi","script"] on the session call; got: {sess_calls}'
    )


# ────────────────────────────────────────────────────────────────────
# A2.2 — Pipeline-level: real DiscoveryOrchestrator + Agent.override(TestModel)
# Asserts agent spans (from pydantic-ai instrumentation) nest correctly under
# the discover stage span.
# ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures('_active_observability')
async def test_agent_span_nests_under_discover(span_exporter, mocker):
    """Real DiscoveryOrchestrator with TestModel: agent span parent === discover span."""
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator

    Agent.instrument_all()

    storage = mocker.MagicMock()
    # Use a real provider with a fake key so create_model() succeeds; the
    # Agent.override(model=TestModel()) below swaps it out before any LLM call.
    from yosoi.core.discovery.config import LLMConfig

    llm_config = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='test-key', temperature=0.0)
    orch = DiscoveryOrchestrator(
        contract=_SimpleContract,
        llm_config=llm_config,
        storage=storage,
    )

    # Swap the underlying pydantic-ai agent's model to TestModel for deterministic output.
    with orch._agent._agent.override(model=TestModel()), obs.span('discover', url=CANNED_URL):
        await orch.discover_selectors(CLEANED_HTML, url=CANNED_URL)

    spans = span_exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}

    discover = by_name.get('discover')
    assert discover is not None, f'expected "discover" span, got {list(by_name)}'

    # orchestrator_discover_selectors nests inside discover.
    orch_span = by_name.get('orchestrator_discover_selectors')
    assert orch_span is not None
    assert orch_span.parent is not None
    assert orch_span.parent.span_id == discover.context.span_id

    # At least one agent run span exists; its parent chain ultimately leads to discover.
    agent_spans = [s for s in spans if s.name == 'agent run']
    assert len(agent_spans) >= 1, f'expected >=1 "agent run" span, got: {list(by_name)}'

    # Walk the parent chain from the agent span up; one of the ancestors must be 'discover'.
    def _ancestor_ids(span):
        ids = []
        cur = span
        while cur is not None and cur.parent is not None:
            ids.append(cur.parent.span_id)
            cur = next((s for s in spans if s.context.span_id == cur.parent.span_id), None)
        return ids

    for agent_span in agent_spans:
        ancestors = _ancestor_ids(agent_span)
        assert discover.context.span_id in ancestors, (
            f'agent span parent chain {ancestors!r} does not include discover {discover.context.span_id!r}'
        )
