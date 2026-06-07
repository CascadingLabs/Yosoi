"""Tests for the Langfuse observability singleton."""

from contextlib import contextmanager

import pytest

from yosoi.core.configs import TelemetryConfig
from yosoi.utils import observability as obs


@pytest.fixture(autouse=True)
def reset_singleton():
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


def test_configure_noop_without_keys():
    obs.configure(TelemetryConfig())
    assert obs.client() is None
    assert obs.agent_capabilities() == []


def test_configure_noop_with_only_public_key():
    obs.configure(TelemetryConfig(langfuse_public_key='pk-only'))
    assert obs.client() is None


def test_span_yields_none_when_off():
    with obs.span('foo', x=1) as s:
        assert s is None


def test_warning_safe_when_off():
    obs.warning('hello', a=1)


def test_flush_safe_when_off():
    obs.flush()


def _mock_langfuse_success(mocker):
    fake_sdk = mocker.MagicMock()
    fake_sdk.auth_check.return_value = True
    mocker.patch.object(obs, '_langfuse_preflight_error', return_value=None)
    mocker.patch.object(obs, 'Langfuse', return_value=fake_sdk)
    mocker.patch('pydantic_ai.agent.Agent.instrument_all')
    return fake_sdk


def test_configure_initializes_client_with_keys(mocker):
    _mock_langfuse_success(mocker)
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    c = obs.client()
    assert c is not None
    assert c.tracer is not None


def test_configure_disables_client_when_langfuse_unreachable(caplog):
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    assert obs.client() is None
    assert 'scraping continues without trace export' in caplog.text


def test_configure_is_idempotent(mocker):
    _mock_langfuse_success(mocker)
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    first = obs.client()
    obs.configure(cfg)
    assert obs.client() is first


def test_agent_capabilities_instrumented_when_configured(mocker):
    from pydantic_ai.capabilities import Instrumentation

    _mock_langfuse_success(mocker)
    obs.configure(
        TelemetryConfig(
            langfuse_public_key='pk-test',
            langfuse_secret_key='sk-test',
            langfuse_host='http://localhost:3000',
        )
    )
    caps = obs.agent_capabilities()
    assert len(caps) == 1
    assert isinstance(caps[0], Instrumentation)


# ────────────────────────────────────────────────────────────────────
# process_session_id() — lazy resolution + reset
# ────────────────────────────────────────────────────────────────────


def test_process_session_id_stable_across_calls(monkeypatch):
    import uuid as _uuid

    monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
    obs.reset_for_tests()
    first = obs.process_session_id()
    second = obs.process_session_id()
    assert first == second
    # Canonical UUID4 — joins cleanly across DBs / services without prefix stripping.
    parsed = _uuid.UUID(first)
    assert parsed.version == 4
    assert str(parsed) == first


def test_process_session_id_honours_env_var(monkeypatch):
    monkeypatch.setenv('YOSOI_SESSION_ID', 'override-abc')
    obs.reset_for_tests()
    assert obs.process_session_id() == 'override-abc'


def test_cross_session_fresh_import_simulation(monkeypatch):
    """Replaces the punted Phase 4 subprocess test (B4.2/B4.3).

    Each subprocess starts with a fresh ``observability`` import. The
    first call to ``process_session_id()`` reads ``YOSOI_SESSION_ID``
    once, caches it, and serves it to every subsequent caller.
    Simulate that contract via reset_for_tests() (== fresh import) +
    monkeypatch.setenv (== env var present at process start) +
    process_session_id() (== first Pipeline construction).
    """
    monkeypatch.setenv('YOSOI_SESSION_ID', 'cross-session-foo')
    obs.reset_for_tests()
    # First resolution caches.
    first = obs.process_session_id()
    assert first == 'cross-session-foo'
    # Subsequent calls return the cached value, even if the env var is changed.
    monkeypatch.setenv('YOSOI_SESSION_ID', 'something-else')
    assert obs.process_session_id() == 'cross-session-foo'


def test_reset_for_tests_clears_singleton_and_session_id(monkeypatch, mocker):
    monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
    _mock_langfuse_success(mocker)
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    first_sid = obs.process_session_id()
    assert obs.client() is not None

    obs.reset_for_tests()
    assert obs.client() is None
    # New session id is generated post-reset.
    second_sid = obs.process_session_id()
    assert first_sid != second_sid


# ────────────────────────────────────────────────────────────────────
# session() / user() — no-op branches when client is None
# ────────────────────────────────────────────────────────────────────


def test_session_no_op_branch_does_not_call_propagate(mocker):
    """When client() is None, session() must not import or call propagate_attributes."""
    spy = mocker.patch('langfuse.propagate_attributes')
    assert obs.client() is None
    with obs.session('sess-x', tags=['yosoi']):
        pass
    spy.assert_not_called()


def test_user_no_op_branch_does_not_call_propagate(mocker):
    spy = mocker.patch('langfuse.propagate_attributes')
    assert obs.client() is None
    with obs.user('shop.example.com', tags=['shop.example.com']):
        pass
    spy.assert_not_called()


def test_span_no_op_yields_none_and_does_not_touch_tracer(mocker):
    """span() must not even open a tracer span when client is None."""
    fake_tracer = mocker.MagicMock()
    mocker.patch('opentelemetry.trace.get_tracer', return_value=fake_tracer)
    with obs.span('s', k=1) as s:
        assert s is None
    fake_tracer.start_as_current_span.assert_not_called()


# ────────────────────────────────────────────────────────────────────
# session() / user() — active-path: propagate_attributes is called
# correctly. We replace the langfuse singleton with a stand-in and
# patch propagate_attributes with a contextmanager that captures kwargs.
# ────────────────────────────────────────────────────────────────────


@pytest.fixture
def _fake_active_client(mocker):
    fake = mocker.MagicMock()
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    return fake


def _capturing_propagate(captured: list[dict]):
    @contextmanager
    def _fake(**kwargs):
        captured.append(kwargs)
        yield

    return _fake


@pytest.mark.usefixtures('_fake_active_client')
def test_session_active_forwards_session_id_and_attrs(mocker):
    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))

    with obs.session('sess-42', tags=['yosoi', 'cli'], user_id='example.com'):
        pass

    assert len(captured) == 1
    assert captured[0] == {'session_id': 'sess-42', 'tags': ['yosoi', 'cli'], 'user_id': 'example.com'}


@pytest.mark.usefixtures('_fake_active_client')
def test_user_active_forwards_user_id_and_tags(mocker):
    captured: list[dict] = []
    mocker.patch('langfuse.propagate_attributes', _capturing_propagate(captured))

    with obs.user('shop.example.com', tags=['shop.example.com']):
        pass

    assert captured == [{'user_id': 'shop.example.com', 'tags': ['shop.example.com']}]


@pytest.mark.usefixtures('_fake_active_client')
def test_span_active_emits_span_with_attributes(span_exporter):
    """span() opens a real OTel span on the configured tracer with the right attributes."""
    from opentelemetry import trace

    obs.LangfuseClient._instance.tracer = trace.get_tracer('yosoi-test')

    with obs.span('do-thing', url='https://example.com', count=3):
        pass

    spans = [s for s in span_exporter.get_finished_spans() if s.name == 'do-thing']
    assert len(spans) == 1
    assert spans[0].attributes['url'] == 'https://example.com'
    assert spans[0].attributes['count'] == 3


def test_flush_calls_sdk_flush(mocker):
    fake = mocker.MagicMock()
    mocker.patch.object(obs.LangfuseClient, '_instance', fake)
    obs.flush()
    fake.sdk.flush.assert_called_once_with()


# ────────────────────────────────────────────────────────────────────
# normalize_user_id — domain canonicalisation rules
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        # Combined: lowercase + www-strip + port-strip in one shot.
        ('https://WWW.Example.com:8080/path', 'example.com'),
        # Individual rules.
        ('https://WWW.Example.com', 'example.com'),
        ('https://example.com:8080', 'example.com'),
        ('https://user@example.com', 'example.com'),
        ('https://user:pw@example.com:8080', 'example.com'),
        # Subdomains stay distinct.
        ('https://shop.example.com', 'shop.example.com'),
        ('https://blog.example.com/path', 'blog.example.com'),
        # Strip exactly one leading www.
        ('https://www.www.example.com', 'www.example.com'),
        # IDN / punycode round-trip unchanged.
        ('https://例え.jp', '例え.jp'),
        ('https://xn--r8jz45g.jp', 'xn--r8jz45g.jp'),
        # Bare hostname (no scheme) is treated as a path by urlparse, so hostname is empty.
        # Documented behaviour: callers should pass scheme-qualified URLs.
        # Edge-case URLs without a host return None.
        ('file:///x', None),
        ('data:text/plain,hi', None),
        ('https://', None),
    ],
)
def test_normalize_user_id(url, expected):
    assert obs.normalize_user_id(url) == expected


def test_normalize_user_id_subdomain_distinct_from_apex():
    """shop.example.com must not collide with example.com — the whole point of per-subdomain user_ids."""
    assert obs.normalize_user_id('https://shop.example.com') != obs.normalize_user_id('https://example.com')


# ────────────────────────────────────────────────────────────────────
# P3 — set_trace_input / set_trace_output helpers
# ────────────────────────────────────────────────────────────────────


def test_set_trace_input_noop_when_client_off(mocker):
    obs.reset_for_tests()
    fake_span = mocker.MagicMock()
    obs.set_trace_input(fake_span, {'x': 1})
    fake_span.set_attribute.assert_not_called()


def test_set_trace_output_noop_when_client_off(mocker):
    obs.reset_for_tests()
    fake_span = mocker.MagicMock()
    obs.set_trace_output(fake_span, {'x': 1})
    fake_span.set_attribute.assert_not_called()


# ────────────────────────────────────────────────────────────────────
# Standard span-attribute contract — _apply guard + annotate_* helpers
#
# The module comment promises emission and tests never drift; these
# round-trips assert the exact ATTR_* constants land on real OTel spans.
# ────────────────────────────────────────────────────────────────────


def _emitting_tracer():
    """Point the faked active client at the in-memory test TracerProvider."""
    from opentelemetry import trace

    obs.LangfuseClient._instance.tracer = trace.get_tracer('yosoi-test')


def _attrs_of(span_exporter, name):
    spans = [s for s in span_exporter.get_finished_spans() if s.name == name]
    assert len(spans) == 1
    return spans[0].attributes


# -- _apply guard semantics -------------------------------------------


@pytest.mark.parametrize(
    'call',
    [
        lambda s: obs.annotate_a3node(s, mode=obs.A3_MODE_REPLAY),
        lambda s: obs.annotate_cache(s, path=obs.CACHE_FRESH),
        lambda s: obs.annotate_llm(s, provider='groq', model='llama'),
    ],
)
def test_annotate_helpers_noop_when_client_off(mocker, call):
    obs.reset_for_tests()
    fake_span = mocker.MagicMock()
    call(fake_span)
    fake_span.set_attribute.assert_not_called()


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_helpers_noop_on_none_target():
    # Active client, but no span in scope — must not raise.
    obs.annotate_a3node(None, mode=obs.A3_MODE_REPLAY)
    obs.annotate_cache(None, path=obs.CACHE_FRESH)
    obs.annotate_llm(None, provider='groq', model='llama')


@pytest.mark.usefixtures('_fake_active_client')
def test_apply_skips_none_but_keeps_false_and_zero(span_exporter):
    """None values are dropped; False / 0 are real signal and must be emitted."""
    _emitting_tracer()
    with obs.span('fetch') as s:
        # replayed defaults False, acts/replay_count default 0 → all kept.
        obs.annotate_a3node(s, mode=obs.A3_MODE_PROBE)
    attrs = _attrs_of(span_exporter, 'fetch')
    assert attrs[obs.ATTR_A3_REPLAYED] is False
    assert attrs[obs.ATTR_A3_FELL_BACK] is False
    assert attrs[obs.ATTR_A3_ACTS] == 0
    assert attrs[obs.ATTR_A3_SETTLE_SECONDS] == 0.0


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_cache_omits_none_field_counts(span_exporter):
    _emitting_tracer()
    with obs.span('scrape') as s:
        obs.annotate_cache(s, path=obs.CACHE_FRESH)  # fresh/stale default None
    attrs = _attrs_of(span_exporter, 'scrape')
    assert attrs[obs.ATTR_CACHE_PATH] == 'fresh'
    assert obs.ATTR_CACHE_FRESH_FIELDS not in attrs
    assert obs.ATTR_CACHE_STALE_FIELDS not in attrs


# -- per-helper round-trips against the exact contract ----------------


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_a3node_emits_full_schema(span_exporter):
    _emitting_tracer()
    with obs.span('fetch') as s:
        obs.annotate_a3node(s, mode=obs.A3_MODE_REPLAY, replayed=True, acts=2, replay_count=3, settle_seconds=1.5)
    attrs = _attrs_of(span_exporter, 'fetch')
    assert attrs[obs.ATTR_A3_MODE] == 'replay'
    assert attrs[obs.ATTR_A3_REPLAYED] is True
    assert attrs[obs.ATTR_A3_ACTS] == 2
    assert attrs[obs.ATTR_A3_REPLAY_COUNT] == 3
    assert attrs[obs.ATTR_A3_SETTLE_SECONDS] == 1.5


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_a3node_accepts_replay_attrs_splat(span_exporter):
    """The A3ReplayAttrs TypedDict splats cleanly alongside an explicit flag."""
    _emitting_tracer()
    replay_attrs: obs.A3ReplayAttrs = {
        'mode': obs.A3_MODE_REPLAY,
        'acts': 1,
        'replay_count': 0,
        'settle_seconds': 0.0,
    }
    with obs.span('fetch') as s:
        obs.annotate_a3node(s, fell_back=True, **replay_attrs)
    attrs = _attrs_of(span_exporter, 'fetch')
    assert attrs[obs.ATTR_A3_MODE] == 'replay'
    assert attrs[obs.ATTR_A3_FELL_BACK] is True
    assert attrs[obs.ATTR_A3_ACTS] == 1


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_cache_emits_path_and_counts(span_exporter):
    _emitting_tracer()
    with obs.span('scrape') as s:
        obs.annotate_cache(s, path=obs.CACHE_PARTIAL, fresh_fields=2, stale_fields=3)
    attrs = _attrs_of(span_exporter, 'scrape')
    assert attrs[obs.ATTR_CACHE_PATH] == 'partial'
    assert attrs[obs.ATTR_CACHE_FRESH_FIELDS] == 2
    assert attrs[obs.ATTR_CACHE_STALE_FIELDS] == 3


@pytest.mark.usefixtures('_fake_active_client')
def test_annotate_llm_maps_provider_to_backend(span_exporter):
    _emitting_tracer()
    with obs.span('discovery') as s:
        obs.annotate_llm(s, provider='groq', model='llama-3.3-70b')
    attrs = _attrs_of(span_exporter, 'discovery')
    assert attrs[obs.ATTR_LLM_BACKEND] == 'api'
    assert attrs[obs.ATTR_LLM_PROVIDER] == 'groq'
    assert attrs[obs.ATTR_LLM_MODEL] == 'llama-3.3-70b'


@pytest.mark.usefixtures('_fake_active_client')
def test_transport_span_emits_backend_schema_and_namespaces_extra(span_exporter):
    _emitting_tracer()
    with obs.transport_span(obs.BACKEND_OPENCODE, 'sonnet', structured_output=True, base_url='http://x'):
        pass
    attrs = _attrs_of(span_exporter, obs.LLM_TRANSPORT_SPAN)
    assert attrs[obs.ATTR_LLM_BACKEND] == 'opencode'
    assert attrs[obs.ATTR_LLM_MODEL] == 'sonnet'
    assert attrs[obs.ATTR_LLM_STRUCTURED] is True
    assert attrs['yosoi.llm.base_url'] == 'http://x'  # **extra lands under the yosoi.llm.* namespace


@pytest.mark.parametrize(
    ('provider', 'expected'),
    [
        ('claude-sdk', 'claude-sdk'),
        ('opencode', 'opencode'),
        ('OPENCODE', 'opencode'),  # case-insensitive
        ('groq', 'api'),
        ('anthropic', 'api'),
        ('openai', 'api'),
    ],
)
def test_llm_backend_mapping(provider, expected):
    assert obs.llm_backend(provider) == expected


@pytest.mark.usefixtures('_fake_active_client')
def test_set_trace_input_noop_when_span_none():
    obs.set_trace_input(None, {'x': 1})  # must not raise


@pytest.mark.usefixtures('_fake_active_client')
def test_set_trace_output_noop_when_span_none():
    obs.set_trace_output(None, {'x': 1})  # must not raise


@pytest.mark.usefixtures('_fake_active_client')
def test_set_trace_input_active_sets_observation_input(mocker):
    import json

    fake_span = mocker.MagicMock()
    obs.set_trace_input(fake_span, {'url': 'https://x', 'n': 1})
    fake_span.set_attribute.assert_called_once()
    key, val = fake_span.set_attribute.call_args.args
    assert key == 'langfuse.observation.input'
    assert json.loads(val) == {'url': 'https://x', 'n': 1}


@pytest.mark.usefixtures('_fake_active_client')
def test_set_trace_output_active_sets_observation_output(mocker):
    import json

    fake_span = mocker.MagicMock()
    obs.set_trace_output(fake_span, {'path': 'fresh', 'extracted_count': 3})
    fake_span.set_attribute.assert_called_once()
    key, val = fake_span.set_attribute.call_args.args
    assert key == 'langfuse.observation.output'
    assert json.loads(val) == {'path': 'fresh', 'extracted_count': 3}


@pytest.mark.usefixtures('_fake_active_client')
def test_set_trace_input_serializes_non_json_types(mocker):
    """default=str fallback must keep Pydantic-like / arbitrary objects from raising."""
    import json
    from datetime import datetime

    fake_span = mocker.MagicMock()
    payload = {'when': datetime(2026, 1, 1), 'obj': object()}
    obs.set_trace_input(fake_span, payload)
    _, val = fake_span.set_attribute.call_args.args
    decoded = json.loads(val)
    assert isinstance(decoded['when'], str)
    assert decoded['when'].startswith('2026-01-01')


def test_detached_span_is_noop_when_client_is_none():
    """detached_span() yields None immediately when no Langfuse client (lines 174-175)."""
    from yosoi.utils import observability as obs

    obs.reset_for_tests()  # ensures client() returns None
    from yosoi.utils.observability import detached_span

    with detached_span('test_span') as span:
        assert span is None  # no-op path
