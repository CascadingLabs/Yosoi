"""Coverage for uncovered branches in the replay runtime.

Exercises: repeat-exhaustion, condition None-guards, selector type dispatch,
click/type/eval fallback methods, _wait_for_dom_stable quiet_ms path, and
the _call synchronous-method and missing-method paths.
"""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import (
    ReplayExecutionError,
    _ax_target_exists,
    _call,
    _condition_holds,
    _eval,
    _type_first,
    execute_plan,
    verify_plan,
)
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
)
from yosoi.models.selectors import css, role, xpath

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(name: str, act: ReplayAct, *, assess=None, expect=None) -> ReplayNode:
    return ReplayNode(
        id=name,
        intent=name,
        assess=assess or ReplayCondition(kind=AssertKind.NONE),
        act=act,
        expect=expect or ReplayCondition(kind=AssertKind.NONE),
    )


class _PresentTab:
    """Minimal fake tab where query_selector always returns something."""

    def __init__(self, present: bool = True) -> None:
        self._present = present
        self.calls: list[tuple] = []

    async def query_selector(self, sel: str) -> object | None:
        return object() if self._present else None

    async def query_selector_all(self, sel: str) -> list[object]:
        return [object()] * 3 if self._present else []

    async def eval_js(self, script: str) -> object:
        self.calls.append(('eval_js', script))
        return None

    async def content(self) -> str:
        return ''

    async def click_element(self, sel: str) -> None:
        self.calls.append(('click_element', sel))

    async def click_by_role(self, role_name: str, name: str, nth: int) -> None:
        self.calls.append(('click_by_role', role_name, name, nth))

    async def fill(self, sel: str, text: str) -> None:
        self.calls.append(('fill', sel, text))

    async def get_full_ax_tree(self) -> list[dict]:
        return []


# ---------------------------------------------------------------------------
# Repeat exhaustion (lines 105-107)
# ---------------------------------------------------------------------------


async def test_repeat_exhausts_max_repeats_then_fails_assertion():
    """repeat=True with condition never holding exhausts max_repeats and then fails the assert."""
    plan = ReplayPlan(
        nodes=[
            _node(
                'scroll_repeat',
                ReplayAct(
                    kind=ActKind.SCROLL,
                    repeat=True,
                    max_repeats=2,
                    metadata={'pixels': 100},
                ),
                expect=ReplayCondition(kind=AssertKind.SELECTOR, selector=css('.never')),
            )
        ]
    )
    tab = _PresentTab(present=False)
    report = await verify_plan(tab, plan)
    assert report.failed == 1
    assert 'assert failed' in report.failures[0]


# ---------------------------------------------------------------------------
# Condition None-guard branches
# ---------------------------------------------------------------------------


async def test_ax_target_condition_none_selector_returns_false():
    """AX_TARGET condition with selector=None returns False immediately (line 151)."""
    condition = ReplayCondition(kind=AssertKind.AX_TARGET)  # selector is None by default
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


async def test_selector_condition_none_selector_returns_false():
    """SELECTOR condition with selector=None returns False (line 158)."""
    condition = ReplayCondition(kind=AssertKind.SELECTOR)  # selector is None
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


async def test_count_condition_none_selector_returns_false():
    """COUNT condition with selector=None returns False (line 164)."""
    condition = ReplayCondition(kind=AssertKind.COUNT, value=3)  # selector is None
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


async def test_count_condition_non_int_value_returns_false():
    """COUNT condition with a non-int value returns False (line 164)."""
    condition = ReplayCondition(kind=AssertKind.COUNT, selector=css('div'), value='three')
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


async def test_text_condition_none_value_returns_false():
    """TEXT condition with value=None returns False (line 170)."""
    condition = ReplayCondition(kind=AssertKind.TEXT)  # value is None
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


async def test_url_condition_none_value_returns_false():
    """URL condition with value=None returns False (line 177)."""
    condition = ReplayCondition(kind=AssertKind.URL)  # value is None
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False


# ---------------------------------------------------------------------------
# _selector_exists type dispatch (lines 184, 186)
# ---------------------------------------------------------------------------


async def test_selector_exists_role_dispatches_to_ax():
    """A role-type SELECTOR condition is routed to _ax_target_exists (line 184)."""
    condition = ReplayCondition(kind=AssertKind.SELECTOR, selector=role('button', 'Submit'))
    tab = _PresentTab()

    result = await _condition_holds(tab, condition)

    assert result is False  # empty AX tree → no match


async def test_selector_exists_unsupported_type_raises():
    """A non-css non-role SELECTOR condition raises ReplayExecutionError (line 186)."""
    condition = ReplayCondition(kind=AssertKind.SELECTOR, selector=xpath('//button'))
    tab = _PresentTab()

    with pytest.raises(ReplayExecutionError, match='conditions are not supported'):
        await _condition_holds(tab, condition)


# ---------------------------------------------------------------------------
# _selector_count unsupported type (line 192)
# ---------------------------------------------------------------------------


async def test_count_condition_xpath_selector_raises():
    """COUNT condition with a non-css selector type raises ReplayExecutionError (line 192)."""
    condition = ReplayCondition(kind=AssertKind.COUNT, selector=xpath('//li'), value=3)
    tab = _PresentTab()

    with pytest.raises(ReplayExecutionError, match='count conditions are not supported'):
        await _condition_holds(tab, condition)


# ---------------------------------------------------------------------------
# _ax_target_exists (lines 199, 201, 209)
# ---------------------------------------------------------------------------


async def test_ax_target_exists_non_role_type_raises():
    """_ax_target_exists raises when selector type is not 'role' (line 199)."""
    with pytest.raises(ReplayExecutionError, match='AX conditions are not supported'):
        await _ax_target_exists(object(), css('button'))


async def test_ax_target_exists_tab_without_ax_tree_returns_false():
    """_ax_target_exists returns False when tab lacks get_full_ax_tree (line 201)."""

    class NoAxTab:
        pass

    result = await _ax_target_exists(NoAxTab(), role('button', 'OK'))

    assert result is False


async def test_ax_target_exists_no_matching_node_returns_false():
    """_ax_target_exists returns False when AX tree has no matching node (line 209)."""
    tab = _PresentTab()  # get_full_ax_tree returns []

    result = await _ax_target_exists(tab, role('button', 'Nonexistent'))

    assert result is False


# ---------------------------------------------------------------------------
# _click_target fallback and unknown type (lines 237-239, 243)
# ---------------------------------------------------------------------------


async def test_click_css_without_click_element_uses_click_method():
    """CSS click with no click_element method falls back to tab.click (lines 238-239)."""

    class ClickOnlyTab:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def click(self, sel: str) -> None:
            self.calls.append(('click', sel))

    tab = ClickOnlyTab()
    plan = ReplayPlan(nodes=[_node('click', ReplayAct(kind=ActKind.CLICK, targets=[css('button.cta')]))])

    await execute_plan(tab, plan)

    assert ('click', 'button.cta') in tab.calls


async def test_click_unsupported_target_type_raises():
    """A click target with an unsupported type raises ReplayExecutionError (line 243)."""
    plan = ReplayPlan(nodes=[_node('click', ReplayAct(kind=ActKind.CLICK, targets=[xpath('//button')]))])
    tab = _PresentTab()

    with pytest.raises(ReplayExecutionError, match='click targets are not supported'):
        await execute_plan(tab, plan)


# ---------------------------------------------------------------------------
# _type_first: non-css target skipped, raises; and 'type' fallback (lines 249, 253-255)
# ---------------------------------------------------------------------------


async def test_type_first_skips_non_css_targets_then_raises():
    """TYPE act with only non-css targets skips all of them and raises (lines 249, 255)."""
    plan = ReplayPlan(
        nodes=[
            _node(
                'type',
                ReplayAct(kind=ActKind.TYPE, targets=[role('textbox', 'Search')], text='hello'),
            )
        ]
    )
    tab = _PresentTab()

    with pytest.raises(ReplayExecutionError, match='require a css target'):
        await execute_plan(tab, plan)


async def test_type_first_uses_type_method_when_fill_absent():
    """TYPE act falls back to tab.type() when tab lacks fill() (lines 253-254)."""

    class TypeMethodTab:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def type(self, sel: str, text: str) -> None:
            self.calls.append(('type', sel, text))

    tab = TypeMethodTab()
    await _type_first(tab, [css('input#q')], 'search text')

    assert ('type', 'input#q', 'search text') in tab.calls


# ---------------------------------------------------------------------------
# _wait_for_dom_stable quiet_ms path (lines 277-278)
# ---------------------------------------------------------------------------


async def test_dom_stable_uses_quiet_ms_when_no_network_idle():
    """DOM_STABLE condition with quiet_ms sleeps when tab lacks wait_for_network_idle (lines 277-278)."""

    class NoIdleTab:
        pass

    condition = ReplayCondition(kind=AssertKind.DOM_STABLE, timeout_ms=100, quiet_ms=1)
    # Should not raise; the quiet_ms branch runs asyncio.sleep
    result = await _condition_holds(NoIdleTab(), condition)
    assert result is True


# ---------------------------------------------------------------------------
# _click_target css with click_element succeeds (line 237)
# ---------------------------------------------------------------------------


async def test_click_css_with_click_element_uses_click_element():
    """CSS click target invokes tab.click_element when it exists and succeeds (line 237)."""

    class ClickElementTab:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def click_element(self, sel: str) -> None:
            self.calls.append(('click_element', sel))

    tab = ClickElementTab()
    plan = ReplayPlan(nodes=[_node('click', ReplayAct(kind=ActKind.CLICK, targets=[css('button.submit')]))])

    await execute_plan(tab, plan)

    assert ('click_element', 'button.submit') in tab.calls


# ---------------------------------------------------------------------------
# _eval evaluate_js and evaluate fallbacks (lines 296, 297)
# ---------------------------------------------------------------------------


async def test_eval_uses_evaluate_js_when_eval_js_absent():
    """_eval uses evaluate_js when eval_js is not present on the tab (line 296)."""

    class EvaluateJsTab:
        async def evaluate_js(self, script: str) -> str:
            return 'result_value'

    result = await _eval(EvaluateJsTab(), 'document.title')

    assert result == 'result_value'


async def test_eval_falls_back_to_evaluate_when_neither_eval_js_nor_evaluate_js():
    """_eval falls back to tab.evaluate when neither eval_js nor evaluate_js exist (line 297)."""

    class LegacyTab:
        async def evaluate(self, script: str) -> str:
            return 'legacy_result'

    result = await _eval(LegacyTab(), 'document.title')

    assert result == 'legacy_result'


# ---------------------------------------------------------------------------
# _call: missing method and synchronous method (lines 302-303, 308)
# ---------------------------------------------------------------------------


async def test_call_raises_for_missing_method():
    """_call raises ReplayExecutionError when the method does not exist (line 302-303)."""

    class EmptyTab:
        pass

    with pytest.raises(ReplayExecutionError, match='does not support nonexistent'):
        await _call(EmptyTab(), 'nonexistent')


async def test_call_invokes_synchronous_method():
    """_call returns the value from a synchronous (non-async) method (line 308)."""

    class SyncTab:
        def get_name(self) -> str:
            return 'sync_value'

    result = await _call(SyncTab(), 'get_name')

    assert result == 'sync_value'
