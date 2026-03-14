"""Tests for get_retryer, get_async_retryer config and log_retry."""

import logfire
from tenacity import AsyncRetrying, Retrying

from yosoi.utils.retry import get_async_retryer, get_retryer, log_retry


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


# ──────────────────────────────────────────────────────────────────────
# get_async_retryer
# ──────────────────────────────────────────────────────────────────────


def test_get_async_retryer_returns_async_retrying():
    retryer = get_async_retryer(max_attempts=3)
    assert isinstance(retryer, AsyncRetrying)


def test_get_async_retryer_stop_config():
    retryer = get_async_retryer(max_attempts=5)
    assert retryer.stop.max_attempt_number == 5


def test_get_async_retryer_wait_config():
    retryer = get_async_retryer(wait_min=2.0, wait_max=20.0, wait_multiplier=2.0)
    assert retryer.wait.min == 2.0
    assert retryer.wait.max == 20.0
    assert retryer.wait.multiplier == 2.0


def test_get_async_retryer_defaults_match_sync():
    sync = get_retryer()
    async_ = get_async_retryer()
    assert sync.stop.max_attempt_number == async_.stop.max_attempt_number
    assert sync.wait.min == async_.wait.min
    assert sync.wait.max == async_.wait.max
    assert sync.wait.multiplier == async_.wait.multiplier
    assert sync.reraise == async_.reraise
    assert sync.before_sleep == async_.before_sleep


def test_get_async_retryer_with_log_callback(mocker):
    cb = mocker.MagicMock()
    retryer = get_async_retryer(log_callback=cb)
    assert retryer.before_sleep is cb


def test_get_async_retryer_reraise_defaults_true():
    assert get_async_retryer().reraise is True


def test_get_async_retryer_reraise_can_be_disabled():
    assert get_async_retryer(reraise=False).reraise is False


async def test_async_retryer_retries_on_failure():
    """AsyncRetrying actually retries and uses asyncio.sleep (non-blocking)."""
    call_count = 0

    async for attempt in get_async_retryer(max_attempts=3, wait_min=0, wait_max=0):
        with attempt:
            call_count += 1
            if call_count < 3:
                raise ValueError('not yet')

    assert call_count == 3


async def test_async_retryer_succeeds_on_first_try():
    call_count = 0

    async for attempt in get_async_retryer(max_attempts=3, wait_min=0, wait_max=0):
        with attempt:
            call_count += 1

    assert call_count == 1
