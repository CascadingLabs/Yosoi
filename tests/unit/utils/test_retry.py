"""Tests for get_retryer config and log_retry."""

import logfire
from tenacity import Retrying

from yosoi.utils.retry import get_retryer, log_retry


def test_get_retryer_returns_retrying_instance():
    retryer = get_retryer(max_attempts=3)
    assert isinstance(retryer, Retrying)


def test_get_retryer_stop_config():
    retryer = get_retryer(max_attempts=5)
    assert retryer.stop.max_attempt_number == 5


def test_get_retryer_wait_config():
    retryer = get_retryer(wait_min=2.0, wait_max=20.0, wait_multiplier=2.0)
    assert retryer.wait.min == 2.0
    assert retryer.wait.max == 20.0
    assert retryer.wait.multiplier == 2.0


def test_get_retryer_reraise_true_by_default():
    retryer = get_retryer()
    assert retryer.reraise is True


def test_get_retryer_reraise_can_be_disabled():
    retryer = get_retryer(reraise=False)
    assert retryer.reraise is False


def test_log_retry_calls_logfire_warn(monkeypatch, mocker):
    logged = []
    monkeypatch.setattr(logfire, 'warn', lambda msg, **kwargs: logged.append((msg, kwargs)))

    state = mocker.MagicMock()
    state.attempt_number = 2
    state.outcome.exception.return_value = ValueError('test error')

    log_retry(state)

    assert len(logged) == 1
    assert logged[0][1]['attempt'] == 2
    assert 'test error' in logged[0][1]['error']
