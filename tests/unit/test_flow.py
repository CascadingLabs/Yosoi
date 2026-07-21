from __future__ import annotations

from typing import Any

import pytest

import yosoi as ys
from yosoi.core.replay.runtime import execute_plan
from yosoi.models.replay import ActKind, AssertKind
from yosoi.models.results import FetchResult


class PanelReady(ys.State):
    condition = ys.css('.ready')


class RowsLoaded(ys.State):
    condition = ys.count(ys.css('.row'), at_least=ys.input('limit'))


class DialogAbsent(ys.State):
    condition = ys.absent(ys.css('.dialog'))


class ExampleFlow(ys.Flow):
    open_panel: ys.Expect[PanelReady] = ys.click(ys.css('#open'))
    load_rows: ys.Expect[RowsLoaded] = ys.scroll_until(
        ys.nearest_scroll_parent(ys.css('.row')),
        max_scrolls=ys.input('scrolls'),
    )
    value: int = ys.Executor.js(
        '(args) => args.value',
        args={'value': ys.input('value')},
        settle=ys.until.non_null(timeout=1, poll_interval=0.25),
    )


def test_flow_compiles_to_existing_replay_plan() -> None:
    plan = ExampleFlow.compile(
        'https://example.test/page',
        inputs={'limit': 3, 'scrolls': 4, 'value': 7},
    )

    assert [node.id for node in plan.nodes] == ['navigate', 'open_panel', 'load_rows', 'value']
    assert [node.act.kind for node in plan.nodes] == [ActKind.NAVIGATE, ActKind.CLICK, ActKind.SCROLL, ActKind.EVAL]
    assert plan.nodes[1].expect.kind == AssertKind.SELECTOR
    assert plan.nodes[2].expect.kind == AssertKind.COUNT
    assert plan.nodes[2].expect.value == 3
    assert plan.nodes[2].act.repeat is True
    assert plan.nodes[2].act.max_repeats == 4
    assert plan.nodes[3].act.output_field == 'value'
    assert plan.nodes[3].act.repeat is True
    assert plan.nodes[3].act.max_repeats == 4
    assert plan.nodes[3].act.dwell_ms == 250
    assert plan.nodes[3].act.metadata == {'until_non_null': True}
    assert plan.nodes[3].act.script is not None
    assert plan.nodes[3].act.script.endswith('({"value":7})')


def test_state_requires_a_supported_condition() -> None:
    with pytest.raises(TypeError, match=r'State\.condition must be a selector or Flow condition'):

        class InvalidState(ys.State):
            condition = object()


def test_flow_rejects_unresolved_annotations_instead_of_dropping_expectations() -> None:
    with pytest.raises(TypeError, match='annotations must resolve'):

        class InvalidFlow(ys.Flow):
            value: MissingType = ys.Executor.js('1')  # noqa: F821


def test_flow_rejects_invalid_dynamic_bounds() -> None:
    with pytest.raises(ValueError, match='count at_least must be >= 0'):
        ExampleFlow.compile(
            'https://example.test',
            inputs={'limit': -1, 'scrolls': 1, 'value': 1},
        )
    with pytest.raises(ValueError, match='click_all limit must be >= 1'):
        ys.click_all(ys.css('button'), limit=0)


def test_flow_rejects_unimplemented_no_growth_scroll_stop() -> None:
    with pytest.raises(ValueError, match="currently supports only 'expectation'"):
        ys.scroll_until(
            ys.nearest_scroll_parent(ys.css('.row')),
            max_scrolls=3,
            stop_when='no_growth',
        )


def test_flow_validates_executor_outputs_from_annotations() -> None:
    assert ExampleFlow.validate_outputs({'value': '7'}) == {'value': 7}
    with pytest.raises(ValueError, match='produced no output'):
        ExampleFlow.validate_outputs({})


class _AbsentTab:
    url = 'https://example.test/'

    async def goto(self, _url: str) -> None:
        return None

    async def query_selector(self, _selector: str) -> None:
        return None

    async def eval_js(self, _script: str) -> Any:
        return None


@pytest.mark.asyncio
async def test_absent_condition_runs_on_existing_replay_runtime() -> None:
    class CloseFlow(ys.Flow):
        close: ys.Expect[DialogAbsent] = ys.Executor.js('true')

    result = await execute_plan(_AbsentTab(), CloseFlow.compile('https://example.test'))

    assert result.report.passed == 2


@pytest.mark.asyncio
async def test_flow_run_uses_live_fetcher_plan_boundary(mocker) -> None:
    fetcher = mocker.MagicMock()
    fetcher.__aenter__ = mocker.AsyncMock(return_value=fetcher)
    fetcher.__aexit__ = mocker.AsyncMock(return_value=None)
    fetcher.fetch_with_plan = mocker.AsyncMock(
        return_value=FetchResult(
            url='https://example.test',
            html='<html>' + ('content ' * 20) + '</html>',
            status_code=200,
            fetch_time=1.25,
            js_outputs={'value': '9'},
        )
    )
    constructor = mocker.patch('yosoi.core.fetcher.voiddriver.HeadlessFetcher', return_value=fetcher)

    result = await ExampleFlow.run(
        'https://example.test',
        inputs={'limit': 1, 'scrolls': 1, 'value': 9},
    )

    assert result.values == {'value': 9}
    constructor.assert_called_once()
    plan = fetcher.fetch_with_plan.await_args.args[0]
    assert plan.nodes[0].act.kind == ActKind.NAVIGATE
