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
    assert obs.instrumentation_settings() is False


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


def test_configure_initializes_client_with_keys():
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    c = obs.client()
    assert c is not None
    assert c.tracer is not None


def test_configure_is_idempotent():
    cfg = TelemetryConfig(
        langfuse_public_key='pk-test',
        langfuse_secret_key='sk-test',
        langfuse_host='http://localhost:3000',
    )
    obs.configure(cfg)
    first = obs.client()
    obs.configure(cfg)
    assert obs.client() is first


def test_instrumentation_settings_true_when_configured():
    obs.configure(
        TelemetryConfig(
            langfuse_public_key='pk-test',
            langfuse_secret_key='sk-test',
            langfuse_host='http://localhost:3000',
        )
    )
    assert obs.instrumentation_settings() is True


# ────────────────────────────────────────────────────────────────────
# process_session_id() — lazy resolution + reset
# ────────────────────────────────────────────────────────────────────


def test_process_session_id_stable_across_calls(monkeypatch):
    monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
    obs.reset_for_tests()
    first = obs.process_session_id()
    second = obs.process_session_id()
    assert first == second
    assert first.startswith('yosoi-')


def test_process_session_id_honours_env_var(monkeypatch):
    monkeypatch.setenv('YOSOI_SESSION_ID', 'override-abc')
    obs.reset_for_tests()
    assert obs.process_session_id() == 'override-abc'


def test_reset_for_tests_clears_singleton_and_session_id(monkeypatch):
    monkeypatch.delenv('YOSOI_SESSION_ID', raising=False)
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
