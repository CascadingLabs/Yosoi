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


def test_get_retryer_stop_config_respects_max_attempts():
    retryer = get_retryer(max_attempts=1)
    assert retryer.stop.max_attempt_number == 1


def test_get_retryer_wait_config():
    retryer = get_retryer(wait_min=2.0, wait_max=20.0, wait_multiplier=2.0)
    assert retryer.wait.min == 2.0
    assert retryer.wait.max == 20.0
    assert retryer.wait.multiplier == 2.0


def test_get_retryer_wait_min_default():
    retryer = get_retryer()
    assert retryer.wait.min == 1.0


def test_get_retryer_wait_max_default():
    retryer = get_retryer()
    assert retryer.wait.max == 10.0


def test_get_retryer_wait_multiplier_default():
    retryer = get_retryer()
    assert retryer.wait.multiplier == 1.0


def test_get_retryer_stop_default_max_attempts():
    retryer = get_retryer()
    assert retryer.stop.max_attempt_number == 3


def test_get_retryer_reraise_true_by_default():
    retryer = get_retryer()
    assert retryer.reraise is True


def test_get_retryer_reraise_can_be_disabled():
    retryer = get_retryer(reraise=False)
    assert retryer.reraise is False


def test_get_retryer_with_log_callback(mocker):
    callback = mocker.MagicMock()
    retryer = get_retryer(log_callback=callback)
    assert retryer.before_sleep is callback


def test_get_retryer_no_log_callback_by_default():
    retryer = get_retryer()
    assert retryer.before_sleep is None


def test_get_retryer_exception_types():
    """Test that custom exception types are used for retry logic."""
    retryer = get_retryer(exceptions=(ValueError,))
    # retry attribute should be set
    assert retryer.retry is not None


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


def test_log_retry_message_text(monkeypatch, mocker):
    logged = []
    monkeypatch.setattr(logfire, 'warn', lambda msg, **kwargs: logged.append((msg, kwargs)))

    state = mocker.MagicMock()
    state.attempt_number = 1
    state.outcome.exception.return_value = RuntimeError('something failed')

    log_retry(state)

    assert logged[0][0] == 'Retrying operation'


def test_log_retry_none_exception_uses_unknown(monkeypatch, mocker):
    logged = []
    monkeypatch.setattr(logfire, 'warn', lambda msg, **kwargs: logged.append((msg, kwargs)))

    state = mocker.MagicMock()
    state.attempt_number = 3
    state.outcome.exception.return_value = None

    log_retry(state)

    assert logged[0][1]['error'] == 'Unknown error'


def test_log_retry_uses_attempt_number(monkeypatch, mocker):
    logged = []
    monkeypatch.setattr(logfire, 'warn', lambda msg, **kwargs: logged.append((msg, kwargs)))

    state = mocker.MagicMock()
    state.attempt_number = 7
    state.outcome.exception.return_value = Exception('err')

    log_retry(state)

    assert logged[0][1]['attempt'] == 7


def test_get_retryer_default_max_attempts_is_3():
    """Default max_attempts must be exactly 3, not 2 or 4."""
    retryer = get_retryer()
    assert retryer.stop.max_attempt_number == 3


def test_get_retryer_default_wait_min_is_1():
    """Default wait_min must be exactly 1.0, not 0 or 2."""
    retryer = get_retryer()
    assert retryer.wait.min == 1.0


def test_get_retryer_default_wait_max_is_10():
    """Default wait_max must be exactly 10.0, not 5 or 20."""
    retryer = get_retryer()
    assert retryer.wait.max == 10.0


def test_get_retryer_default_wait_multiplier_is_1():
    """Default wait_multiplier must be exactly 1.0."""
    retryer = get_retryer()
    assert retryer.wait.multiplier == 1.0


def test_get_retryer_default_reraise_is_true():
    """Default reraise must be True, not False."""
    retryer = get_retryer()
    assert retryer.reraise is True


def test_get_retryer_reraise_false():
    """reraise=False must actually be stored as False."""
    retryer = get_retryer(reraise=False)
    assert retryer.reraise is False


def test_get_retryer_custom_attempts_respected():
    """Custom max_attempts must be passed through exactly."""
    for n in [1, 2, 4, 7]:
        retryer = get_retryer(max_attempts=n)
        assert retryer.stop.max_attempt_number == n


def test_get_retryer_wait_min_respected():
    """wait_min must be exactly as passed."""
    retryer = get_retryer(wait_min=3.0)
    assert retryer.wait.min == 3.0


def test_get_retryer_wait_max_respected():
    """wait_max must be exactly as passed."""
    retryer = get_retryer(wait_max=30.0)
    assert retryer.wait.max == 30.0


def test_get_retryer_no_before_sleep_by_default():
    """before_sleep should be None when no log_callback given."""
    retryer = get_retryer()
    assert retryer.before_sleep is None


def test_get_retryer_before_sleep_is_callback_when_given(mocker):
    """before_sleep must be the exact callback object passed."""
    cb = mocker.MagicMock()
    retryer = get_retryer(log_callback=cb)
    assert retryer.before_sleep is cb


def test_log_retry_error_str_is_str_of_exception(monkeypatch, mocker):
    """error kwarg must be str(exception), not repr or something else."""
    logged = []
    monkeypatch.setattr(logfire, 'warn', lambda msg, **kwargs: logged.append((msg, kwargs)))

    state = mocker.MagicMock()
    state.attempt_number = 1
    exc = ValueError('my exact error message')
    state.outcome.exception.return_value = exc

    log_retry(state)

    assert logged[0][1]['error'] == str(exc)
    assert logged[0][1]['error'] == 'my exact error message'
