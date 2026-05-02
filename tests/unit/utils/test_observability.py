"""Tests for the Langfuse observability singleton."""

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
