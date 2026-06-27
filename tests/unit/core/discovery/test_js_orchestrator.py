"""Tests for JsDiscoveryOrchestrator — pre-probe, LLM loop, cache."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from yosoi.core.discovery.js_orchestrator import JsDiscoveryOrchestrator, _repr
from yosoi.storage.js_scripts import JsScriptStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(
    mocker: MockerFixture,
    llm_responses: list[str | None],
    eval_results: list[Any],
    storage: JsScriptStorage | None = None,
) -> tuple[JsDiscoveryOrchestrator, Any]:
    """Build an orchestrator whose LLM and tab are fully mocked."""
    llm_config = mocker.MagicMock()
    llm_config.model_name = 'test-model'
    llm_config.provider = 'test'

    orch = JsDiscoveryOrchestrator.__new__(JsDiscoveryOrchestrator)
    orch._llm_config = llm_config
    orch._storage = storage or _noop_storage(mocker)
    orch._console = mocker.MagicMock()
    orch._max_attempts = 3
    orch.model_name = 'test-model'

    # Mock the pydantic-ai agent
    llm_iter = iter(llm_responses)

    async def _run(prompt: str, deps: Any) -> Any:
        val = next(llm_iter, None)
        if val is None:
            raise RuntimeError('LLM exhausted')
        result = mocker.MagicMock()
        result.output = val
        return result

    agent_mock = mocker.MagicMock()
    agent_mock.run = mocker.AsyncMock(side_effect=_run)
    orch._agent = agent_mock

    # Mock tab — explicit async side_effect so Python None is returned literally.
    # mocker.AsyncMock(side_effect=[None, ...]) treats None as "use return_value";
    # an async function ensures the actual None value is returned.
    results_iter = iter(eval_results)

    async def _eval_js(*_args: Any, **_kwargs: Any) -> Any:
        try:
            return next(results_iter)
        except StopIteration:
            return None

    # _tab_eval (from runtime._eval) prefers eval_js — Yosoi's canonical name,
    # the method the pooled voidcrawl tabs actually expose.
    tab = mocker.AsyncMock()
    tab.eval_js = mocker.AsyncMock(side_effect=_eval_js)

    return orch, tab


def _noop_storage(mocker: MockerFixture) -> JsScriptStorage:
    """Storage that never reads or writes (for isolated tests)."""
    s = mocker.MagicMock(spec=JsScriptStorage)
    s.save_entries = mocker.AsyncMock()
    return s


# ---------------------------------------------------------------------------
# _repr helper
# ---------------------------------------------------------------------------


def test_repr_short_value():
    assert _repr({'x': 1}) == repr({'x': 1})


def test_repr_truncates_long_value():
    long = {'key': 'x' * 300}
    result = _repr(long)
    assert result.endswith('…')
    assert len(result) <= 205


# ---------------------------------------------------------------------------
# _pre_probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_probe_returns_dict_on_success(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], [{'script_srcs': ['a.js'], 'window_keys': []}])
    result = await orch._pre_probe(tab)
    assert result == {'script_srcs': ['a.js'], 'window_keys': []}


@pytest.mark.asyncio
async def test_pre_probe_returns_empty_dict_for_non_dict_result(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], ['not a dict'])
    result = await orch._pre_probe(tab)
    assert result == {}


@pytest.mark.asyncio
async def test_pre_probe_returns_none_on_exception(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], [])
    tab.eval_js = mocker.AsyncMock(side_effect=RuntimeError('tab error'))
    result = await orch._pre_probe(tab)
    assert result is None


# ---------------------------------------------------------------------------
# _verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_returns_true_for_non_null_result(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], [{'has_alita': True}])
    verified, output = await orch._verify(tab, '(() => ({has_alita: true}))()', 'signals')
    assert verified is True
    assert output is not None


@pytest.mark.asyncio
async def test_verify_returns_false_for_null(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], [None])
    verified, output = await orch._verify(tab, '(() => null)()', 'signals')
    assert verified is False
    assert output == 'null'


@pytest.mark.asyncio
async def test_verify_returns_false_on_exception(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, [], [])
    tab.eval_js = mocker.AsyncMock(side_effect=RuntimeError('syntax error'))
    verified, output = await orch._verify(tab, 'bad js', 'signals')
    assert verified is False
    assert 'syntax error' in (output or '')


def _count_contract():
    """A contract whose ys.js review_count is int-typed with comma + range validators."""
    from typing import Annotated

    from pydantic import BeforeValidator

    import yosoi as ys

    def _strip(v: object) -> int:
        s = str(v).strip()
        return int(s.replace(',', '')) if s and s != 'None' else 0

    class Counts(ys.Contract):
        review_count: Annotated[int, BeforeValidator(_strip)] = ys.js(description='count', default=0)
        signals: dict = ys.js(description='structured signals', default_factory=dict)

    return Counts


@pytest.mark.asyncio
async def test_verify_rejects_blob_for_typed_field(mocker: MockerFixture):
    # CAS-114: the field's declared type is the oracle — a review_count:int script
    # that returns a non-numeric blob is rejected, and the error feeds the retry.
    coercer = _count_contract().coerce_field
    orch, tab = _make_orchestrator(mocker, [], ['totally non-numeric prose blob'])

    verified, reason = await orch._verify(tab, '(() => document.body.innerText)()', 'review_count', coercer)

    assert verified is False
    assert reason  # carries the pydantic validation message


@pytest.mark.asyncio
async def test_verify_coerces_native_and_comma_values(mocker: MockerFixture):
    coercer = _count_contract().coerce_field

    # native int → valid
    orch, tab = _make_orchestrator(mocker, [], [1234])
    assert (await orch._verify(tab, '(() => reviewCount)()', 'review_count', coercer))[0] is True

    # comma string → BeforeValidator coerces "1,234" → 1234 → valid
    orch2, tab2 = _make_orchestrator(mocker, [], ['1,234'])
    assert (await orch2._verify(tab2, '(() => txt)()', 'review_count', coercer))[0] is True


@pytest.mark.asyncio
async def test_verify_untyped_field_accepts_structured(mocker: MockerFixture):
    # A dict-typed ys.js field (no scalar constraint) accepts structured output.
    coercer = _count_contract().coerce_field
    orch, tab = _make_orchestrator(mocker, [], [{'has_alita': True}])
    verified, _ = await orch._verify(tab, '(() => ({has_alita:true}))()', 'signals', coercer)
    assert verified is True


# ---------------------------------------------------------------------------
# _discover_field — iterative loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_field_succeeds_on_first_attempt(mocker: MockerFixture):
    script = '(() => ({has_alita: true}))()'
    orch, tab = _make_orchestrator(mocker, [script], [{'has_alita': True}])
    result = await orch._discover_field(tab, 'signals', 'detect alita', {'script_srcs': []})
    assert result is not None
    verified_script, attempts = result
    assert verified_script == script
    assert attempts == 1


@pytest.mark.asyncio
async def test_discover_field_retries_on_null_then_succeeds(mocker: MockerFixture):
    script_bad = '(() => null)()'
    script_good = '(() => ({has_alita: true}))()'
    orch, tab = _make_orchestrator(mocker, [script_bad, script_good], [None, {'has_alita': True}])
    result = await orch._discover_field(tab, 'signals', 'detect alita', {})
    assert result is not None
    verified_script, attempts = result
    assert verified_script == script_good
    assert attempts == 2  # took 2 attempts


@pytest.mark.asyncio
async def test_discover_field_returns_none_after_max_attempts(mocker: MockerFixture):
    orch, tab = _make_orchestrator(
        mocker,
        ['(() => null)()', '(() => null)()', '(() => null)()'],
        [None, None, None],
    )
    result = await orch._discover_field(tab, 'signals', 'detect alita', {})
    assert result is None


# ---------------------------------------------------------------------------
# discover — full integration (mocked tab + storage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_caches_verified_scripts(mocker: MockerFixture):
    script = '(() => ({has_alita: true}))()'
    storage = _noop_storage(mocker)
    orch, tab = _make_orchestrator(
        mocker,
        llm_responses=[script],
        eval_results=[
            {'script_srcs': []},  # pre-probe
            {'has_alita': True},  # verify
        ],
        storage=storage,
    )

    fetcher = mocker.MagicMock()
    fetcher.browse = mocker.MagicMock()
    fetcher.browse.return_value.__aenter__ = mocker.AsyncMock(return_value=tab)
    fetcher.browse.return_value.__aexit__ = mocker.AsyncMock(return_value=False)

    result = await orch.discover(
        url='https://example.com',
        domain='example.com',
        fields={'signals': 'detect alita embed'},
        fetcher=fetcher,
    )

    assert result == {'signals': script}
    storage.save_entries.assert_called_once()


@pytest.mark.asyncio
async def test_discover_returns_empty_when_pre_probe_fails(mocker: MockerFixture):
    orch, tab = _make_orchestrator(mocker, llm_responses=[], eval_results=[])
    tab.eval_js = mocker.AsyncMock(side_effect=RuntimeError('CDP error'))

    fetcher = mocker.MagicMock()
    fetcher.browse = mocker.MagicMock()
    fetcher.browse.return_value.__aenter__ = mocker.AsyncMock(return_value=tab)
    fetcher.browse.return_value.__aexit__ = mocker.AsyncMock(return_value=False)

    result = await orch.discover(
        url='https://example.com',
        domain='example.com',
        fields={'signals': 'detect'},
        fetcher=fetcher,
    )
    assert result == {}
