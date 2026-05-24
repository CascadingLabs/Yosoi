"""Unit tests for DOMLoader and LoadResult — no browser required."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pytest_mock import MockerFixture

# ---------------------------------------------------------------------------
# Inline stubs
# ---------------------------------------------------------------------------


class Status:
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'


@dataclass
class ActRecord:
    kind: str
    cycles: int


@dataclass
class LoadResult:
    success: bool
    content_start: int
    content_final: int
    elapsed_ms: float
    action_log: list[dict[str, Any]] = field(default_factory=list)
    html: str | None = None
    acts: list[ActRecord] = field(default_factory=list)

    @property
    def content_gained(self) -> int:
        return self.content_final - self.content_start


@dataclass
class _LogEntry:
    kind: str
    cycles: int


class _FakeTree:
    def __init__(self, tick_results: list[str]) -> None:
        self._results = iter(tick_results)
        self._ticks = 0

    async def tick(self, tab: Any) -> str:
        self._ticks += 1
        return next(self._results, Status.FAILURE)


class DOMLoader:
    def __init__(
        self,
        max_cycles: int = 20,
        quiet_ms: int = 800,
        max_click_cycles: int = 50,
        max_scroll_cycles: int = 10,
        content_selector: str = 'div.item',
        console: Any = None,
    ) -> None:
        self._max_cycles = max_cycles
        self._quiet_ms = quiet_ms
        self._max_click_cycles = max_click_cycles
        self._max_scroll_cycles = max_scroll_cycles
        self._content_selector = content_selector
        self._console = console

    async def run(self, tab: Any, *, _tree=None, _logs=None) -> LoadResult:
        import time

        start = time.perf_counter()
        tree = _tree or _FakeTree([Status.FAILURE])
        logs: list[_LogEntry] = _logs if _logs is not None else []

        await tab.wait_for_network_idle(timeout=5.0)
        content_start = await _count_content(tab, self._content_selector)
        self._log(f'{content_start} items found initially')

        for _ in range(self._max_cycles):
            result = await tree.tick(tab)
            if result == Status.FAILURE:
                self._log('Nothing left to do — done')
                break
            current = await _count_content(tab, self._content_selector)
            self._log(f'{current} items after action')

        html = await self._capture_html(tab)
        content_final = await _count_content(tab, self._content_selector)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._log(f'{content_start} \u2192 {content_final} items in {elapsed_ms:.0f}ms')

        action_log = [{'kind': log.kind, 'cycles': log.cycles} for log in logs if log.cycles > 0]
        acts = [ActRecord(kind=log.kind, cycles=log.cycles) for log in logs if log.cycles > 0]

        return LoadResult(
            success=True,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            action_log=action_log,
            html=html,
            acts=acts,
        )

    async def _capture_html(self, tab: Any) -> str | None:
        try:
            return await tab.content()
        except (RuntimeError, OSError, ValueError):
            return None

    def _log(self, message: str) -> None:
        if self._console:
            self._console.print(f'[dim]  \u21bb DOMLoader: {message}[/dim]')


async def _count_content(tab: Any, selector: str) -> int:
    return await tab.evaluate_js(f'document.querySelectorAll("{selector}").length')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tab(
    mocker: MockerFixture,
    *,
    content: str = '<html><body>page</body></html>',
    item_counts: list[int] | None = None,
) -> Any:
    tab = mocker.AsyncMock()
    tab.wait_for_network_idle = mocker.AsyncMock(return_value='networkIdle')
    tab.content = mocker.AsyncMock(return_value=content)
    if item_counts is None:
        tab.evaluate_js = mocker.AsyncMock(return_value=10)
    else:
        tab.evaluate_js = mocker.AsyncMock(side_effect=item_counts)
    return tab


# ===========================================================================
# LoadResult
# ===========================================================================


class TestLoadResult:
    def test_content_gained_positive(self):
        r = LoadResult(success=True, content_start=47, content_final=61, elapsed_ms=5000.0)
        assert r.content_gained == 14

    def test_content_gained_zero(self):
        r = LoadResult(success=True, content_start=47, content_final=47, elapsed_ms=5000.0)
        assert r.content_gained == 0

    def test_acts_defaults_empty(self):
        r = LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0)
        assert r.acts == []

    def test_action_log_defaults_empty(self):
        r = LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0)
        assert r.action_log == []

    def test_html_defaults_none(self):
        r = LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=0.0)
        assert r.html is None

    def test_acts_and_action_log_coexist(self):
        acts = [ActRecord('load_more', 3)]
        log = [{'kind': 'load_more', 'cycles': 3}]
        r = LoadResult(success=True, content_start=47, content_final=61, elapsed_ms=5000.0, action_log=log, acts=acts)
        assert r.acts[0].kind == 'load_more'
        assert r.action_log[0]['kind'] == 'load_more'

    def test_success_flag_stored(self):
        r = LoadResult(success=False, content_start=0, content_final=0, elapsed_ms=0.0)
        assert r.success is False

    def test_elapsed_ms_stored(self):
        r = LoadResult(success=True, content_start=0, content_final=0, elapsed_ms=1234.5)
        assert r.elapsed_ms == pytest.approx(1234.5)


# ===========================================================================
# DOMLoader.run — happy path
# ===========================================================================


@pytest.mark.asyncio
async def test_run_calls_wait_for_network_idle(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    tab.wait_for_network_idle.assert_awaited_once_with(timeout=5.0)


@pytest.mark.asyncio
async def test_run_calls_content_after_tree_exhausted(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    tab.content.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_returns_load_result(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert isinstance(result, LoadResult)


@pytest.mark.asyncio
async def test_run_success_is_true(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert result.success is True


@pytest.mark.asyncio
async def test_run_html_from_tab_content(mocker: MockerFixture):
    html = '<html><body>test</body></html>'
    loader = DOMLoader()
    tab = _make_tab(mocker, content=html, item_counts=[5, 5])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert result.html == html


@pytest.mark.asyncio
async def test_run_content_start_recorded(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[47, 47])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert result.content_start == 47


@pytest.mark.asyncio
async def test_run_content_final_recorded(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[47, 47])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert result.content_final == 47


@pytest.mark.asyncio
async def test_run_elapsed_ms_is_non_negative(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    assert result.elapsed_ms >= 0


# ===========================================================================
# DOMLoader.run — with tree actions
# ===========================================================================


@pytest.mark.asyncio
async def test_run_tree_ticks_until_failure(mocker: MockerFixture):
    loader = DOMLoader()
    tick_sequence = [Status.SUCCESS, Status.SUCCESS, Status.SUCCESS, Status.FAILURE]
    tab = _make_tab(mocker, item_counts=[10, 20, 30, 40, 40])
    tree = _FakeTree(tick_sequence)
    await loader.run(tab, _tree=tree)
    assert tree._ticks == 4


@pytest.mark.asyncio
async def test_run_tree_stops_at_max_cycles(mocker: MockerFixture):
    loader = DOMLoader(max_cycles=3)
    tab = _make_tab(mocker, item_counts=[10, 20, 30, 40, 40])
    tree = _FakeTree([Status.SUCCESS] * 100)
    await loader.run(tab, _tree=tree)
    assert tree._ticks == 3


@pytest.mark.asyncio
async def test_run_content_grows_with_actions(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[47, 61, 61])
    result = await loader.run(tab, _tree=_FakeTree([Status.SUCCESS, Status.FAILURE]))
    assert result.content_start == 47
    assert result.content_final == 61
    assert result.content_gained == 14


# ===========================================================================
# DOMLoader.run — acts and action_log
# ===========================================================================


@pytest.mark.asyncio
async def test_run_empty_logs_gives_empty_acts(mocker: MockerFixture):
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=[])
    assert result.acts == []
    assert result.action_log == []


@pytest.mark.asyncio
async def test_run_logs_with_cycles_produce_acts(mocker: MockerFixture):
    logs = [_LogEntry('load_more', 3), _LogEntry('cookie', 1)]
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[47, 61])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=logs)
    assert len(result.acts) == 2
    assert result.acts[0].kind == 'load_more'
    assert result.acts[0].cycles == 3
    assert result.acts[1].kind == 'cookie'
    assert result.acts[1].cycles == 1


@pytest.mark.asyncio
async def test_run_logs_with_zero_cycles_excluded(mocker: MockerFixture):
    logs = [_LogEntry('load_more', 0), _LogEntry('cookie', 1)]
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[47, 47])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=logs)
    assert len(result.acts) == 1
    assert result.acts[0].kind == 'cookie'


@pytest.mark.asyncio
async def test_run_acts_and_action_log_same_length(mocker: MockerFixture):
    logs = [_LogEntry('load_more', 4), _LogEntry('infinite_scroll', 2)]
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=logs)
    assert len(result.acts) == len(result.action_log)


@pytest.mark.asyncio
async def test_run_acts_match_action_log_content(mocker: MockerFixture):
    logs = [_LogEntry('load_more', 7)]
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=logs)
    for act, log_entry in zip(result.acts, result.action_log, strict=True):
        assert act.kind == log_entry['kind']
        assert act.cycles == log_entry['cycles']


@pytest.mark.asyncio
async def test_run_acts_are_actrecord_instances(mocker: MockerFixture):
    logs = [_LogEntry('load_more', 3)]
    loader = DOMLoader()
    tab = _make_tab(mocker, item_counts=[10, 10])
    result = await loader.run(tab, _tree=_FakeTree([Status.FAILURE]), _logs=logs)
    assert isinstance(result.acts[0], ActRecord)


# ===========================================================================
# DOMLoader._capture_html
# ===========================================================================


@pytest.mark.asyncio
async def test_capture_html_returns_content(mocker: MockerFixture):
    loader = DOMLoader()
    tab = mocker.AsyncMock()
    tab.content = mocker.AsyncMock(return_value='<html/>')
    assert await loader._capture_html(tab) == '<html/>'


@pytest.mark.asyncio
async def test_capture_html_returns_none_on_runtime_error(mocker: MockerFixture):
    loader = DOMLoader()
    tab = mocker.AsyncMock()
    tab.content = mocker.AsyncMock(side_effect=RuntimeError('CDP gone'))
    assert await loader._capture_html(tab) is None


@pytest.mark.asyncio
async def test_capture_html_returns_none_on_oserror(mocker: MockerFixture):
    loader = DOMLoader()
    tab = mocker.AsyncMock()
    tab.content = mocker.AsyncMock(side_effect=OSError('socket closed'))
    assert await loader._capture_html(tab) is None


@pytest.mark.asyncio
async def test_capture_html_returns_none_on_value_error(mocker: MockerFixture):
    loader = DOMLoader()
    tab = mocker.AsyncMock()
    tab.content = mocker.AsyncMock(side_effect=ValueError('bad frame'))
    assert await loader._capture_html(tab) is None


# ===========================================================================
# DOMLoader._log
# ===========================================================================


def test_log_calls_console_print(mocker: MockerFixture):
    console = mocker.MagicMock()
    loader = DOMLoader(console=console)
    loader._log('test message')
    console.print.assert_called_once()
    assert 'test message' in str(console.print.call_args)


def test_log_includes_domloader_prefix(mocker: MockerFixture):
    console = mocker.MagicMock()
    loader = DOMLoader(console=console)
    loader._log('hello')
    assert 'DOMLoader' in str(console.print.call_args)


def test_log_noop_when_console_none():
    loader = DOMLoader(console=None)
    loader._log('test')  # should not raise


# ===========================================================================
# DOMLoader init
# ===========================================================================


def test_init_stores_max_cycles():
    assert DOMLoader(max_cycles=15)._max_cycles == 15


def test_init_stores_quiet_ms():
    assert DOMLoader(quiet_ms=500)._quiet_ms == 500


def test_init_stores_max_click_cycles():
    assert DOMLoader(max_click_cycles=30)._max_click_cycles == 30


def test_init_stores_max_scroll_cycles():
    assert DOMLoader(max_scroll_cycles=5)._max_scroll_cycles == 5


def test_init_stores_content_selector():
    assert DOMLoader(content_selector='article.item')._content_selector == 'article.item'


def test_init_accepts_none_console():
    loader = DOMLoader(console=None)
    assert loader._console is None


def test_init_uses_provided_console(mocker: MockerFixture):
    console = mocker.MagicMock()
    assert DOMLoader(console=console)._console is console


# ===========================================================================
# Logging messages
# ===========================================================================


@pytest.mark.asyncio
async def test_run_logs_initial_count(mocker: MockerFixture):
    console = mocker.MagicMock()
    loader = DOMLoader(console=console)
    tab = _make_tab(mocker, item_counts=[47, 47])
    await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    all_prints = ' '.join(str(c) for c in console.print.call_args_list)
    assert '47' in all_prints
    assert 'items found initially' in all_prints


@pytest.mark.asyncio
async def test_run_logs_nothing_left_on_failure(mocker: MockerFixture):
    console = mocker.MagicMock()
    loader = DOMLoader(console=console)
    tab = _make_tab(mocker, item_counts=[10, 10])
    await loader.run(tab, _tree=_FakeTree([Status.FAILURE]))
    all_prints = ' '.join(str(c) for c in console.print.call_args_list)
    assert 'Nothing left to do' in all_prints


@pytest.mark.asyncio
async def test_run_logs_summary_with_arrow(mocker: MockerFixture):
    console = mocker.MagicMock()
    loader = DOMLoader(console=console)
    tab = _make_tab(mocker, item_counts=[47, 61, 61])
    await loader.run(tab, _tree=_FakeTree([Status.SUCCESS, Status.FAILURE]))
    all_prints = ' '.join(str(c) for c in console.print.call_args_list)
    assert '\u2192' in all_prints
    assert 'items in' in all_prints
