from __future__ import annotations

from typing import Any

import pytest

import yosoi as ys
from yosoi.core.replay.runtime import execute_plan
from yosoi.models.replay import ActKind, AssertKind
from yosoi.models.results import FetchResult


class ExampleFlow(ys.Flow):
    open_panel = ys.expect(ys.click(ys.css('#open')), ys.css('.ready'))
    load_rows = ys.expect(
        ys.scroll_until(
            ys.nearest_scroll_parent(ys.css('.row')),
            max_scrolls=ys.input('scrolls'),
        ),
        ys.count(ys.css('.row'), at_least=ys.input('limit')),
    )
    value: int = ys.Executor.js('(args) => args.value', args={'value': ys.input('value')})


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
    assert plan.nodes[3].act.script is not None
    assert plan.nodes[3].act.script.endswith('({"value":7})')


def test_collect_each_compiles_to_typed_replay_act() -> None:
    class ModalFlow(ys.Flow):
        rows: list[dict[str, object]] = ys.collect_each(
            ys.role('button', name='Summary'),
            ready=ys.css('[role="dialog"]'),
            collect=ys.Executor.js('window.modalRows'),
            close=ys.role('button', name='Close'),
            limit=ys.input('groups'),
            dedupe_by='id',
        )

    plan = ModalFlow.compile('https://example.test', inputs={'groups': 3})
    act = plan.nodes[1].act

    assert act.kind == ActKind.COLLECT_EACH
    assert act.output_field == 'rows'
    assert act.metadata['limit'] == 3
    assert act.metadata['dedupe_by'] == 'id'


def test_flow_validates_executor_outputs_from_annotations() -> None:
    assert ExampleFlow.validate_outputs({'value': '7'}) == {'value': 7}
    with pytest.raises(ValueError, match='produced no output'):
        ExampleFlow.validate_outputs({})


def test_expect_preserves_typed_executor_output_validation() -> None:
    class ExpectedOutput(ys.Flow):
        value: int = ys.expect(ys.Executor.js('window.value'), ys.css('.ready'))

    plan = ExpectedOutput.compile('https://example.test')

    assert plan.nodes[1].expect.kind == AssertKind.SELECTOR
    assert ExpectedOutput.validate_outputs({'value': '7'}) == {'value': 7}


def test_expect_rejects_invalid_and_double_wrapped_actions() -> None:
    action = ys.expect(ys.click(ys.css('#open')), ys.css('.ready'))

    with pytest.raises(TypeError, match='already wrapped'):
        ys.expect(action, ys.css('.done'))
    with pytest.raises(TypeError, match='requires a Flow action'):
        ys.expect(object(), ys.css('.done'))


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
        close = ys.expect(ys.Executor.js('true'), ys.absent(ys.css('.dialog')))

    result = await execute_plan(_AbsentTab(), CloseFlow.compile('https://example.test'))

    assert result.report.passed == 2


@pytest.mark.asyncio
async def test_scroll_until_no_growth_tolerates_one_transient_plateau() -> None:
    class ScrollFlow(ys.Flow):
        load = ys.scroll_until(
            ys.nearest_scroll_parent(ys.css('body')),
            max_scrolls=10,
            stop_when='no_growth',
            stable_rounds=2,
        )

    class ScrollTab:
        extents = iter([100, 100, 200, 200, 200])
        scrolls = 0

        async def goto(self, _url: str) -> None:
            return None

        async def eval_js(self, script: str) -> object:
            if script.startswith('(() => {'):
                self.scrolls += 1
                return True
            if script.startswith('Math.max('):
                return next(self.extents)
            return None

    tab = ScrollTab()
    plan = ScrollFlow.compile('https://example.test')
    plan.nodes[1].act.dwell_ms = 0
    await execute_plan(tab, plan)

    assert tab.scrolls == 5


@pytest.mark.asyncio
async def test_collect_each_serializes_modal_interactions_and_deduplicates() -> None:
    class ModalFlow(ys.Flow):
        rows: list[dict[str, object]] = ys.collect_each(
            ys.role('button', name='Summary'),
            ready=ys.css('[role="dialog"]'),
            collect=ys.Executor.js('window.modalRows'),
            close=ys.role('button', name='Close'),
            limit=3,
            dedupe_by='id',
        )

    class ModalTab:
        url = 'https://example.test/'
        opened: int | None = None

        async def goto(self, url: str) -> None:
            self.url = url

        async def get_full_ax_tree(self) -> list[dict[str, object]]:
            nodes = [
                {'role': {'value': 'button'}, 'name': {'value': 'Summary one'}},
                {'role': {'value': 'button'}, 'name': {'value': 'Summary two'}},
            ]
            if self.opened is not None:
                nodes.append({'role': {'value': 'button'}, 'name': {'value': 'Close'}})
            return nodes

        async def click_by_role(self, role: str, name: str, _nth: int) -> None:
            assert role == 'button'
            if name == 'Close':
                self.opened = None
            else:
                self.opened = 0 if name.endswith('one') else 1

        async def query_selector(self, selector: str) -> object | None:
            assert selector == '[role="dialog"]'
            return object() if self.opened is not None else None

        async def eval_js(self, script: str) -> object:
            if 'if (null === null)' in script:
                return 2
            if 'const target = matches[' in script:
                self.opened = 1 if 'matches[1]' in script else 0
                return True
            assert script == 'window.modalRows'
            rows = [
                [{'id': '1', 'name': 'one'}, {'id': 'shared', 'name': 'same'}],
                [{'id': '2', 'name': 'two'}, {'id': 'shared', 'name': 'same'}],
            ]
            assert self.opened is not None
            return rows[self.opened]

    result = await execute_plan(ModalTab(), ModalFlow.compile('https://example.test'))

    assert result.extracted_actions['rows'] == [
        {'id': '1', 'name': 'one'},
        {'id': 'shared', 'name': 'same'},
        {'id': '2', 'name': 'two'},
    ]


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
