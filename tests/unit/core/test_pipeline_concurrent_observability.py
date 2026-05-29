"""B2.4 — concurrent observability tests with taskiq.InMemoryBroker.

Asserts the orchestrator session wrap covers concurrent dispatch:
    Test 1 — explicit YOSOI_SESSION_ID override propagates to all spans.
    Test 2 — auto-generated session id propagates to all spans.
    Test 3 — orchestrator-process 'enqueue' span exists and carries session.id.
    Test 4 — per-URL user_id is computed correctly across mixed (sub)domains.
             (Does NOT prove cross-worker isolation — see test docstring.)
    Test 5 — outer session tags survive on per-URL traces (Langfuse merges tag lists).
"""

from __future__ import annotations

import pytest

import yosoi as ys
import yosoi.core.tasks as _tasks_mod
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.results import FetchResult
from yosoi.models.selectors import SelectorLevel
from yosoi.utils import observability as obs
from yosoi.utils.signatures import contract_signature


class _TinyContract(Contract):
    title: str = ys.Title()


CANNED_HTML = '<html><body><h1>x</h1></body></html>'
CLEAN_HTML = '<body><h1>x</h1></body>'
DISCOVERED = {'title': {'primary': 'h1'}}


def _make_pipeline_stub(mocker):
    stub = Pipeline.__new__(Pipeline)
    stub.contract = _TinyContract
    from yosoi.core.verification import SemanticValidator, field_rules_for_contract

    stub.semantic_validator = SemanticValidator()
    stub._field_rules = field_rules_for_contract(stub.contract)
    stub.console = mocker.MagicMock(quiet=True)
    stub.logger = mocker.MagicMock()
    stub.cleaner = mocker.MagicMock()
    stub.cleaner.clean_html.return_value = CLEAN_HTML
    stub.discovery = mocker.MagicMock()
    stub.discovery.discover_selectors = mocker.AsyncMock(return_value=DISCOVERED)
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
    stub.session_id = 'test-stub-session'
    stub._url_start = 0.0
    # Real LLMConfig: configure_broker validates this as LLMConfig | YosoiConfig.
    from yosoi.core.discovery.config import LLMConfig

    stub._llm_config = LLMConfig(
        provider='groq',
        model_name='llama-3.3-70b-versatile',
        api_key='test-key',
        temperature=0.0,
    )
    return stub


@pytest.fixture
def _broker_clean():
    """Clean broker module state before and after the test."""
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
    fake.tracer = trace.get_tracer('yosoi-concurrent-test')
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


def _patch_pipeline_internals(mocker):
    """Stub heavy collaborators on the worker-side Pipeline so scrape() runs without network/LLM."""
    fetch_result = FetchResult(url='', html=CANNED_HTML, status_code=200)

    async def _passthrough_normalize_url(url):
        return url

    mocker.patch.object(Pipeline, 'normalize_url', side_effect=_passthrough_normalize_url)
    mocker.patch.object(
        Pipeline,
        '_create_fetcher',
        return_value=mocker.MagicMock(__aenter__=mocker.AsyncMock(), __aexit__=mocker.AsyncMock()),
    )
    mocker.patch.object(Pipeline, '_fetch', return_value=fetch_result)
    mocker.patch.object(Pipeline, '_clean', return_value=CLEAN_HTML)
    mocker.patch.object(Pipeline, '_discover', return_value=(DISCOVERED, True))
    mocker.patch.object(Pipeline, '_resolve_root', return_value=None)
    mocker.patch.object(Pipeline, '_root_value', return_value=None)
    mocker.patch.object(Pipeline, '_verify', return_value=DISCOVERED)
    mocker.patch.object(Pipeline, '_extract', return_value={'title': 'x'})
    mocker.patch.object(Pipeline, '_validate_items', return_value=[{'title': 'x'}])
    mocker.patch.object(Pipeline, '_finish', new=mocker.AsyncMock())


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_explicit_session_id_propagates_to_all_spans(monkeypatch, span_exporter, mocker):
    """Test 1 — YOSOI_SESSION_ID override reaches every emitted span."""
    monkeypatch.setenv('YOSOI_SESSION_ID', 'pinned-sess')

    captured: list[dict] = []
    from contextlib import contextmanager

    @contextmanager
    def _fake_propagate(**kwargs):
        captured.append(kwargs)
        yield

    mocker.patch('langfuse.propagate_attributes', _fake_propagate)
    _patch_pipeline_internals(mocker)
    stub = _make_pipeline_stub(mocker)

    await Pipeline.process_urls(
        stub,
        ['https://a.example.com/x', 'https://a.example.com/y'],
        workers=1,
        origin='cli',
    )

    # The outer session wrap was opened with our pinned id.
    sess_calls = [c for c in captured if 'session_id' in c]
    assert sess_calls, f'expected at least one propagate_attributes(session_id=...) call, got: {captured}'
    assert all(c['session_id'] == 'pinned-sess' for c in sess_calls), (
        f'every session_id propagation should equal pinned-sess; got: {sess_calls}'
    )


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_auto_generated_session_id_is_stable_across_dispatch(monkeypatch, span_exporter, mocker):
    """Test 2 — without YOSOI_SESSION_ID, the orchestrator's eager-resolved id is what every span sees."""
    monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)

    captured: list[dict] = []
    from contextlib import contextmanager

    @contextmanager
    def _fake_propagate(**kwargs):
        captured.append(kwargs)
        yield

    mocker.patch('langfuse.propagate_attributes', _fake_propagate)
    _patch_pipeline_internals(mocker)
    stub = _make_pipeline_stub(mocker)

    # Capture the expected id RIGHT BEFORE we kick off process_urls so subsequent
    # process_session_id() calls return the same value.
    expected = obs.process_session_id()

    await Pipeline.process_urls(
        stub,
        ['https://a.example.com/x'],
        workers=1,
        origin='script',
    )

    sess_calls = [c['session_id'] for c in captured if 'session_id' in c]
    assert sess_calls, f'expected at least one session_id call, got: {captured}'
    assert all(s == expected for s in sess_calls), (
        f'every session_id must equal the eagerly-resolved {expected!r}; got: {sess_calls}'
    )


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_enqueue_span_emitted_alongside_per_url_root_traces(monkeypatch, span_exporter, mocker):
    """Test 3 — concurrent dispatch emits the orchestrator-side ``enqueue``
    span AND keeps per-URL ``scrape`` spans as trace roots.

    The ``enqueue`` span is created via :func:`observability.detached_span`
    (uses ``tracer.start_span`` rather than ``start_as_current_span``), so it
    is recorded by the exporter without becoming the active OTel parent.
    Worker ``scrape`` spans therefore stay at ``parent is None`` — preserving
    the "trace = per URL" model — while the enqueue metadata still appears in
    the trace exporter under the orchestrator's session id.
    """
    monkeypatch.setenv('YOSOI_SESSION_ID', 'per-url-trace-sess')

    _patch_pipeline_internals(mocker)
    stub = _make_pipeline_stub(mocker)

    urls = ['https://a.example.com/x', 'https://b.example.com/y']
    await Pipeline.process_urls(stub, urls, workers=2, origin='cli')

    spans = span_exporter.get_finished_spans()

    enqueue_spans = [s for s in spans if s.name == 'enqueue']
    assert len(enqueue_spans) == 1, f'expected exactly one "enqueue" span, got names: {[s.name for s in spans]}'
    enq = enqueue_spans[0]
    assert enq.attributes.get('count') == 2
    assert enq.attributes.get('workers') == 2
    assert enq.attributes.get('origin') == 'cli'

    scrape_spans = [s for s in spans if s.name.startswith('scrape ')]
    assert len(scrape_spans) == 2, f'expected 2 "scrape …" spans, got: {[s.name for s in spans]}'
    # Each scrape span is a root span (no parent) — required for per-URL traces.
    for s in scrape_spans:
        assert s.parent is None, f'scrape span {s.name!r} unexpectedly has parent={s.parent} (should be a trace root)'


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_per_url_user_id_correctness(monkeypatch, span_exporter, mocker):
    """Test 4 — per-URL user_id is computed-from-URL correctly.

    *Does NOT prove cross-worker isolation* — taskiq does not pin URL-to-worker
    assignment, and user_id is derived from the URL itself (not from any worker
    state), so cross-worker contamination is structurally impossible. This test
    only proves the URL→user_id mapping is wired.
    """
    monkeypatch.setenv('YOSOI_SESSION_ID', 'isolation-sess')

    captured: list[dict] = []
    from contextlib import contextmanager

    @contextmanager
    def _fake_propagate(**kwargs):
        captured.append(kwargs)
        yield

    mocker.patch('langfuse.propagate_attributes', _fake_propagate)
    _patch_pipeline_internals(mocker)
    stub = _make_pipeline_stub(mocker)

    urls = [
        'https://a.example.com/x',
        'https://b.example.com/y',
        'https://a.example.com/z',
    ]
    await Pipeline.process_urls(stub, urls, workers=2, origin='script')

    # Each URL produced at least one user_id propagation; user_id must equal
    # observability.normalize_user_id(url) for that URL — never a different domain.
    user_calls = [c for c in captured if 'user_id' in c]
    assert user_calls, 'expected per-URL user_id propagations'
    user_ids_seen = {c['user_id'] for c in user_calls}
    assert user_ids_seen == {'a.example.com', 'b.example.com'}
    # Sanity: 2 traces should be a.example.com, 1 should be b.example.com (each URL → 1+ user calls).
    a_count = sum(1 for c in user_calls if c['user_id'] == 'a.example.com')
    b_count = sum(1 for c in user_calls if c['user_id'] == 'b.example.com')
    assert a_count >= 2
    assert b_count >= 1


@pytest.mark.usefixtures('_broker_clean', '_active_obs')
async def test_outer_session_tags_survive_on_url_traces(monkeypatch, span_exporter, mocker):
    """Test 5 — outer session tags ['yosoi','cli'] are still in the propagation calls when URL traces emit.

    Per Langfuse SDK semantics (read in propagation.py:382-390), tag lists merge
    across nested propagate_attributes calls. This test verifies the orchestrator
    sets the outer tags AND the per-URL user wrap sets the domain tag, so a
    consumer filtering by either tag should find the URL trace.
    """
    monkeypatch.setenv('YOSOI_SESSION_ID', 'tag-survive-sess')

    captured: list[dict] = []
    from contextlib import contextmanager

    @contextmanager
    def _fake_propagate(**kwargs):
        captured.append(kwargs)
        yield

    mocker.patch('langfuse.propagate_attributes', _fake_propagate)
    _patch_pipeline_internals(mocker)
    stub = _make_pipeline_stub(mocker)

    await Pipeline.process_urls(stub, ['https://shop.example.com/x'], workers=1, origin='cli')

    # Outer wrap from process_urls: session_id + tags=['yosoi', 'cli']
    outer_session_calls = [c for c in captured if c.get('session_id') == 'tag-survive-sess' and 'tags' in c]
    assert any(c['tags'] == ['yosoi', 'cli'] for c in outer_session_calls), (
        f'expected outer session call with tags=["yosoi","cli"], got: {captured}'
    )

    # Inner user wrap: user_id + tags=[domain]
    inner_user_calls = [c for c in captured if c.get('user_id') == 'shop.example.com']
    assert any(c.get('tags') == ['shop.example.com'] for c in inner_user_calls), (
        f'expected inner user call with tags=["shop.example.com"], got: {captured}'
    )
