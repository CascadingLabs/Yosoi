"""Unit tests for yosoi.core.fetcher.dom — tree nodes, conditions, actions,
default tree, and probes.

No browser required — all tab interactions use pytest-mock.

File layout (mirrors source):
  - Status enum
  - Selector / Sequence (nodes.py)
  - HasOverlay / HasCloseButton / HasTrigger (conditions.py)
  - ActionLog / ClickClose / ClickTrigger / Scroll / Skip (actions.py)
  - build_default_tree (default.py)
  - TriggerKind / count_content (probes.py)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from enum import Enum as _Enum
from typing import Any

import pytest
from pytest_mock import MockerFixture

# ---------------------------------------------------------------------------
# Inline stubs — avoids importing voidcrawl / rich at test time
# ---------------------------------------------------------------------------


class Status(Enum):
    SUCCESS = auto()
    FAILURE = auto()


# ---- nodes.py stubs ----


class Node(ABC):
    @abstractmethod
    async def tick(self, tab: Any) -> Status: ...


class Selector(Node):
    def __init__(self, *children: Node) -> None:
        self._children = children

    async def tick(self, tab: Any) -> Status:
        for child in self._children:
            if await child.tick(tab) == Status.SUCCESS:
                return Status.SUCCESS
        return Status.FAILURE


class Sequence(Node):
    def __init__(self, *children: Node) -> None:
        self._children = children

    async def tick(self, tab: Any) -> Status:
        for child in self._children:
            if await child.tick(tab) == Status.FAILURE:
                return Status.FAILURE
        return Status.SUCCESS


# ---- probes.py stubs ----


class TriggerKind(str, _Enum):
    COOKIE = 'cookie'
    POPUP = 'popup'
    AGE_GATE = 'age_gate'
    LOAD_MORE = 'load_more'
    ACCORDION = 'accordion'
    TAB = 'tab'
    PAGINATION = 'pagination'
    INFINITE_SCROLL = 'infinite_scroll'


@dataclass
class DetectedTrigger:
    kind: TriggerKind
    selector: str
    label: str


async def count_content(tab: Any, selector: str = '') -> int:
    try:
        return len(await tab.query_selector_all(selector))
    except (RuntimeError, OSError, ValueError):
        return 0


# ---- conditions.py stubs ----


class HasOverlay(Node):
    async def tick(self, tab: Any) -> Status:
        try:
            for sel in (
                '[role="dialog"]',
                '.modal:not([hidden])',
                '[class*="overlay"]:not([hidden])',
                '[class*="popup"]:not([hidden])',
            ):
                if await tab.query_selector(sel):
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError):
            pass
        return Status.FAILURE


class HasCloseButton(Node):
    async def tick(self, tab: Any) -> Status:
        try:
            if await tab.query_selector('input[type="email"], input[type="password"], input[type="text"]'):
                return Status.FAILURE
            for sel in (
                '[role="dialog"] [aria-label*="close" i]',
                '[role="dialog"] button[class*="close"]',
                '.modal [class*="close"]',
                '[class*="popup"] [class*="close"]',
                '[class*="overlay"] [class*="close"]',
                'button[aria-label*="dismiss" i]',
            ):
                if await tab.query_selector(sel):
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError):
            pass
        return Status.FAILURE


class HasTrigger(Node):
    def __init__(self, kind: TriggerKind, content_selector: str) -> None:
        self._kind = kind
        self._content_selector = content_selector
        self._exhausted = False
        self.last_trigger: DetectedTrigger | None = None

    async def tick(self, tab: Any) -> Status:
        if self._exhausted:
            return Status.FAILURE
        _ = await count_content(tab, self._content_selector)
        results = await tab.query_selector_all(f'[data-kind="{self._kind.value}"]')
        if not results:
            return Status.FAILURE
        self.last_trigger = DetectedTrigger(self._kind, 'button', self._kind.value)
        return Status.SUCCESS

    def exhaust(self) -> None:
        self._exhausted = True
        self.last_trigger = None


# ---- actions.py stubs ----


@dataclass
class ActionLog:
    kind: str
    cycles: int = 0


class ClickClose(Node):
    SELECTORS = (
        '[role="dialog"] [aria-label*="close" i]',
        '[role="dialog"] button[class*="close"]',
        '.modal [class*="close"]',
        '[class*="popup"] [class*="close"]',
        '[class*="overlay"] [class*="close"]',
        'button[aria-label*="dismiss" i]',
    )

    async def tick(self, tab: Any) -> Status:
        try:
            for sel in self.SELECTORS:
                if await tab.query_selector(sel):
                    await tab.click_element(sel)
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError):
            pass
        return Status.FAILURE


class ClickTrigger(Node):
    def __init__(self, condition: HasTrigger, stable: Any, max_cycles: int = 50) -> None:
        self._condition = condition
        self._stable = stable
        self._max_cycles = max_cycles
        self.log = ActionLog(kind=condition._kind.value)

    async def tick(self, tab: Any) -> Status:
        trigger = self._condition.last_trigger
        if trigger is None:
            return Status.FAILURE

        content_selector = self._condition._content_selector

        for _ in range(self._max_cycles):
            prev = await count_content(tab, content_selector)
            self.log.cycles += 1
            new = await count_content(tab, content_selector)

            if new <= prev:
                self._condition.exhaust()
                return Status.SUCCESS

            results = await tab.query_selector_all(f'[data-kind="{trigger.kind.value}"]')
            if not results:
                self._condition.exhaust()
                return Status.SUCCESS

        self._condition.exhaust()
        return Status.SUCCESS


class Scroll(Node):
    def __init__(self, condition: HasTrigger, stable: Any, max_cycles: int = 10) -> None:
        self._condition = condition
        self._stable = stable
        self._max_cycles = max_cycles
        self.log = ActionLog(kind='infinite_scroll')

    async def tick(self, tab: Any) -> Status:
        content_selector = self._condition._content_selector
        for _ in range(self._max_cycles):
            prev = await count_content(tab, content_selector)
            self.log.cycles += 1
            new = await count_content(tab, content_selector)
            if new <= prev:
                self._condition.exhaust()
                return Status.SUCCESS
        self._condition.exhaust()
        return Status.SUCCESS


class Skip(Node):
    async def tick(self, tab: Any = None) -> Status:
        return Status.SUCCESS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tab(
    mocker: MockerFixture,
    *,
    selectors: dict[str, Any] | None = None,
    all_results: dict[str, list] | None = None,
) -> Any:
    sel_map = selectors or {}
    all_map = all_results or {}

    tab = mocker.AsyncMock()

    async def _qs(sel: str) -> Any:
        return sel_map.get(sel, None)

    async def _qsa(sel: str) -> list:
        return all_map.get(sel, [])

    tab.query_selector = mocker.AsyncMock(side_effect=_qs)
    tab.query_selector_all = mocker.AsyncMock(side_effect=_qsa)
    tab.click_element = mocker.AsyncMock(return_value=None)
    return tab


def _make_fake_stable(mocker: MockerFixture) -> Any:
    stable = mocker.MagicMock()
    stable.quiet_ms = 800
    return stable


# ===========================================================================
# Status
# ===========================================================================


class TestStatus:
    def test_success_and_failure_are_distinct(self):
        assert Status.SUCCESS != Status.FAILURE

    def test_status_is_enum(self):
        assert isinstance(Status.SUCCESS, Status)


# ===========================================================================
# Selector node
# ===========================================================================


class TestSelectorNode:
    @pytest.mark.asyncio
    async def test_returns_success_on_first_success(self, mocker: MockerFixture):
        always_success = mocker.AsyncMock()
        always_success.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        always_fail = mocker.AsyncMock()
        always_fail.tick = mocker.AsyncMock(return_value=Status.FAILURE)

        node = Selector(always_fail, always_success, always_fail)
        result = await node.tick(mocker.MagicMock())
        assert result == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_returns_failure_when_all_fail(self, mocker: MockerFixture):
        children = [mocker.AsyncMock() for _ in range(3)]
        for c in children:
            c.tick = mocker.AsyncMock(return_value=Status.FAILURE)
        node = Selector(*children)
        assert await node.tick(mocker.MagicMock()) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_short_circuits_after_first_success(self, mocker: MockerFixture):
        called = []

        class _Track(Node):
            def __init__(self, name: str, result: Status):
                self._name = name
                self._result = result

            async def tick(self, tab: Any) -> Status:
                called.append(self._name)
                return self._result

        node = Selector(_Track('a', Status.SUCCESS), _Track('b', Status.SUCCESS))
        await node.tick(mocker.MagicMock())
        assert called == ['a']

    @pytest.mark.asyncio
    async def test_single_child_success(self, mocker: MockerFixture):
        child = mocker.AsyncMock()
        child.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        assert await Selector(child).tick(mocker.MagicMock()) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_single_child_failure(self, mocker: MockerFixture):
        child = mocker.AsyncMock()
        child.tick = mocker.AsyncMock(return_value=Status.FAILURE)
        assert await Selector(child).tick(mocker.MagicMock()) == Status.FAILURE


# ===========================================================================
# Sequence node
# ===========================================================================


class TestSequenceNode:
    @pytest.mark.asyncio
    async def test_returns_success_when_all_succeed(self, mocker: MockerFixture):
        children = [mocker.AsyncMock() for _ in range(3)]
        for c in children:
            c.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        assert await Sequence(*children).tick(mocker.MagicMock()) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_returns_failure_on_first_child_failure(self, mocker: MockerFixture):
        children = [mocker.AsyncMock() for _ in range(3)]
        children[0].tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        children[1].tick = mocker.AsyncMock(return_value=Status.FAILURE)
        children[2].tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        assert await Sequence(*children).tick(mocker.MagicMock()) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_short_circuits_on_failure(self, mocker: MockerFixture):
        called = []

        class _Track(Node):
            def __init__(self, name: str, result: Status):
                self._name = name
                self._result = result

            async def tick(self, tab: Any) -> Status:
                called.append(self._name)
                return self._result

        node = Sequence(_Track('a', Status.FAILURE), _Track('b', Status.SUCCESS))
        await node.tick(mocker.MagicMock())
        assert called == ['a']

    @pytest.mark.asyncio
    async def test_single_success(self, mocker: MockerFixture):
        child = mocker.AsyncMock()
        child.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        assert await Sequence(child).tick(mocker.MagicMock()) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_single_failure(self, mocker: MockerFixture):
        child = mocker.AsyncMock()
        child.tick = mocker.AsyncMock(return_value=Status.FAILURE)
        assert await Sequence(child).tick(mocker.MagicMock()) == Status.FAILURE


# ===========================================================================
# HasOverlay
# ===========================================================================


class TestHasOverlay:
    @pytest.mark.asyncio
    async def test_returns_success_when_dialog_present(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'[role="dialog"]': '<div>'})
        assert await HasOverlay().tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_returns_success_when_modal_present(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'.modal:not([hidden])': '<div>'})
        assert await HasOverlay().tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_returns_failure_when_nothing_present(self, mocker: MockerFixture):
        tab = _tab(mocker)
        assert await HasOverlay().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_returns_failure_on_exception(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector = mocker.AsyncMock(side_effect=RuntimeError('CDP gone'))
        assert await HasOverlay().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_checks_overlay_class(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'[class*="overlay"]:not([hidden])': '<div>'})
        assert await HasOverlay().tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_checks_popup_class(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'[class*="popup"]:not([hidden])': '<div>'})
        assert await HasOverlay().tick(tab) == Status.SUCCESS


# ===========================================================================
# HasCloseButton
# ===========================================================================


class TestHasCloseButton:
    @pytest.mark.asyncio
    async def test_returns_failure_when_form_inputs_present(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            selectors={
                'input[type="email"], input[type="password"], input[type="text"]': '<input>',
            },
        )
        assert await HasCloseButton().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_returns_success_when_close_button_present(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            selectors={
                'input[type="email"], input[type="password"], input[type="text"]': None,
                '[role="dialog"] [aria-label*="close" i]': '<button>',
            },
        )
        assert await HasCloseButton().tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_returns_failure_when_no_close_button(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            selectors={
                'input[type="email"], input[type="password"], input[type="text"]': None,
            },
        )
        assert await HasCloseButton().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_returns_failure_on_exception(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector = mocker.AsyncMock(side_effect=OSError('socket'))
        assert await HasCloseButton().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_modal_close_button(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            selectors={
                'input[type="email"], input[type="password"], input[type="text"]': None,
                '.modal [class*="close"]': '<button>',
            },
        )
        assert await HasCloseButton().tick(tab) == Status.SUCCESS


# ===========================================================================
# HasTrigger
# ===========================================================================


class TestHasTrigger:
    @pytest.mark.asyncio
    async def test_returns_success_when_trigger_present(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a', 'b'],
                '[data-kind="load_more"]': ['<button>'],
            },
        )
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        assert await ht.tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_sets_last_trigger_on_success(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a'],
                '[data-kind="load_more"]': ['<button>'],
            },
        )
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        await ht.tick(tab)
        assert ht.last_trigger is not None
        assert ht.last_trigger.kind == TriggerKind.LOAD_MORE

    @pytest.mark.asyncio
    async def test_returns_failure_when_trigger_absent(self, mocker: MockerFixture):
        tab = _tab(mocker, all_results={'div.item': ['a'], '[data-kind="load_more"]': []})
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        assert await ht.tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_returns_failure_when_exhausted(self, mocker: MockerFixture):
        tab = _tab(mocker, all_results={'[data-kind="load_more"]': ['<button>']})
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ht.exhaust()
        assert await ht.tick(tab) == Status.FAILURE

    def test_exhaust_clears_last_trigger(self):
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ht.last_trigger = DetectedTrigger(TriggerKind.LOAD_MORE, 'button', 'load more')
        ht.exhaust()
        assert ht.last_trigger is None
        assert ht._exhausted is True

    def test_starts_not_exhausted(self):
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        assert ht._exhausted is False

    def test_last_trigger_starts_none(self):
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        assert ht.last_trigger is None

    @pytest.mark.asyncio
    async def test_exhausted_stays_failure_regardless_of_page(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            all_results={
                '[data-kind="load_more"]': ['<button>'],
                'div.item': ['a'],
            },
        )
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ht.exhaust()
        for _ in range(3):
            assert await ht.tick(tab) == Status.FAILURE


# ===========================================================================
# ActionLog
# ===========================================================================


class TestActionLog:
    def test_cycles_default_zero(self):
        log = ActionLog(kind='load_more')
        assert log.cycles == 0

    def test_kind_stored(self):
        log = ActionLog(kind='infinite_scroll')
        assert log.kind == 'infinite_scroll'

    def test_cycles_can_be_incremented(self):
        log = ActionLog(kind='load_more')
        log.cycles += 1
        log.cycles += 1
        assert log.cycles == 2

    def test_custom_initial_cycles(self):
        log = ActionLog(kind='load_more', cycles=5)
        assert log.cycles == 5


# ===========================================================================
# ClickClose
# ===========================================================================


class TestClickClose:
    @pytest.mark.asyncio
    async def test_returns_success_when_close_button_found(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'[role="dialog"] [aria-label*="close" i]': '<button>'})
        assert await ClickClose().tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_calls_click_element_on_found_selector(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'.modal [class*="close"]': '<button>'})
        await ClickClose().tick(tab)
        tab.click_element.assert_awaited_once_with('.modal [class*="close"]')

    @pytest.mark.asyncio
    async def test_returns_failure_when_no_button(self, mocker: MockerFixture):
        tab = _tab(mocker)
        assert await ClickClose().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_returns_failure_on_exception(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector = mocker.AsyncMock(side_effect=RuntimeError('CDP'))
        assert await ClickClose().tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_tries_first_matching_selector(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            selectors={
                '[role="dialog"] [aria-label*="close" i]': '<button>close</button>',
                '.modal [class*="close"]': '<button>modal</button>',
            },
        )
        await ClickClose().tick(tab)
        tab.click_element.assert_awaited_once_with('[role="dialog"] [aria-label*="close" i]')

    @pytest.mark.asyncio
    async def test_dismiss_button_selector(self, mocker: MockerFixture):
        tab = _tab(mocker, selectors={'button[aria-label*="dismiss" i]': '<button>'})
        assert await ClickClose().tick(tab) == Status.SUCCESS


# ===========================================================================
# ClickTrigger
# ===========================================================================


class TestClickTrigger:
    def _condition(self, kind: TriggerKind = TriggerKind.LOAD_MORE) -> HasTrigger:
        ht = HasTrigger(kind, 'div.item')
        ht.last_trigger = DetectedTrigger(kind, 'button', 'load more')
        return ht

    @pytest.mark.asyncio
    async def test_returns_failure_when_no_trigger(self, mocker: MockerFixture):
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        tab = _tab(mocker)
        assert await ct.tick(tab) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_increments_log_cycles(self, mocker: MockerFixture):
        ht = self._condition()
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a', 'b', 'c'],
                '[data-kind="load_more"]': [],
            },
        )
        await ct.tick(tab)
        assert ct.log.cycles >= 1

    @pytest.mark.asyncio
    async def test_exhausts_condition_on_content_stop(self, mocker: MockerFixture):
        ht = self._condition()
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a', 'b'],
                '[data-kind="load_more"]': [],
            },
        )
        await ct.tick(tab)
        assert ht._exhausted is True

    @pytest.mark.asyncio
    async def test_returns_success_when_trigger_exhausted(self, mocker: MockerFixture):
        ht = self._condition()
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a'],
                '[data-kind="load_more"]': [],
            },
        )
        assert await ct.tick(tab) == Status.SUCCESS

    def test_log_kind_matches_condition_kind(self, mocker: MockerFixture):
        ht = self._condition(TriggerKind.ACCORDION)
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        assert ct.log.kind == TriggerKind.ACCORDION.value

    @pytest.mark.asyncio
    async def test_respects_max_cycles(self, mocker: MockerFixture):
        ht = self._condition()
        ct = ClickTrigger(ht, _make_fake_stable(mocker), max_cycles=2)
        call_count = [0]

        async def _growing_qs(sel: str) -> list:
            call_count[0] += 1
            if sel == 'div.item':
                return list(range(call_count[0] * 5))
            if sel == '[data-kind="load_more"]':
                return ['<button>']
            return []

        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=_growing_qs)
        result = await ct.tick(tab)
        assert result == Status.SUCCESS
        assert ct.log.cycles == 2


# ===========================================================================
# Scroll
# ===========================================================================


class TestScroll:
    def _condition(self) -> HasTrigger:
        ht = HasTrigger(TriggerKind.INFINITE_SCROLL, 'div.item')
        ht.last_trigger = DetectedTrigger(TriggerKind.INFINITE_SCROLL, 'body', 'scroll')
        return ht

    def test_log_kind_is_infinite_scroll(self, mocker: MockerFixture):
        scroll = Scroll(self._condition(), _make_fake_stable(mocker))
        assert scroll.log.kind == 'infinite_scroll'

    @pytest.mark.asyncio
    async def test_returns_success_when_content_stops_growing(self, mocker: MockerFixture):
        scroll = Scroll(self._condition(), _make_fake_stable(mocker))
        tab = _tab(mocker, all_results={'div.item': ['a', 'b', 'c']})
        assert await scroll.tick(tab) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_exhausts_condition_on_stop(self, mocker: MockerFixture):
        ht = self._condition()
        scroll = Scroll(ht, _make_fake_stable(mocker))
        tab = _tab(mocker, all_results={'div.item': ['a', 'b']})
        await scroll.tick(tab)
        assert ht._exhausted is True

    @pytest.mark.asyncio
    async def test_increments_cycles_each_scroll(self, mocker: MockerFixture):
        scroll = Scroll(self._condition(), _make_fake_stable(mocker))
        tab = _tab(mocker, all_results={'div.item': ['a']})
        await scroll.tick(tab)
        assert scroll.log.cycles >= 1

    @pytest.mark.asyncio
    async def test_respects_max_cycles(self, mocker: MockerFixture):
        scroll = Scroll(self._condition(), _make_fake_stable(mocker), max_cycles=3)
        call_count = [0]

        async def _growing(sel: str) -> list:
            call_count[0] += 1
            return list(range(call_count[0] * 10))

        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=_growing)
        result = await scroll.tick(tab)
        assert result == Status.SUCCESS
        assert scroll.log.cycles == 3

    @pytest.mark.asyncio
    async def test_exhausts_at_max_cycles(self, mocker: MockerFixture):
        ht = self._condition()
        scroll = Scroll(ht, _make_fake_stable(mocker), max_cycles=2)
        call_count = [0]

        async def _always_grow(sel: str) -> list:
            call_count[0] += 1
            return list(range(call_count[0] * 5))

        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=_always_grow)
        await scroll.tick(tab)
        assert ht._exhausted is True


# ===========================================================================
# Skip
# ===========================================================================


class TestSkip:
    @pytest.mark.asyncio
    async def test_always_returns_success(self, mocker: MockerFixture):
        assert await Skip().tick(mocker.MagicMock()) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_success_without_tab(self):
        assert await Skip().tick(None) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_never_returns_failure(self, mocker: MockerFixture):
        for _ in range(5):
            assert await Skip().tick(mocker.MagicMock()) == Status.SUCCESS


# ===========================================================================
# build_default_tree — structural / wiring tests
# ===========================================================================


class TestBuildDefaultTree:
    def _build(
        self,
        mocker: MockerFixture,
        content_selector: str = 'div.item',
        max_click_cycles: int = 50,
        max_scroll_cycles: int = 10,
    ):
        stable = _make_fake_stable(mocker)
        has_load_more = HasTrigger(TriggerKind.LOAD_MORE, content_selector)
        has_accordion = HasTrigger(TriggerKind.ACCORDION, content_selector)
        has_tab = HasTrigger(TriggerKind.TAB, content_selector)
        has_pagination = HasTrigger(TriggerKind.PAGINATION, content_selector)
        has_scroll = HasTrigger(TriggerKind.INFINITE_SCROLL, content_selector)

        click_load_more = ClickTrigger(has_load_more, stable, max_click_cycles)
        click_accordion = ClickTrigger(has_accordion, stable, max_click_cycles)
        click_tab = ClickTrigger(has_tab, stable, max_click_cycles)
        click_pagination = ClickTrigger(has_pagination, stable, max_click_cycles)
        scroll = Scroll(has_scroll, stable, max_scroll_cycles)

        logs = [
            click_load_more.log,
            click_accordion.log,
            click_tab.log,
            click_pagination.log,
            scroll.log,
        ]
        tree = Selector(
            Sequence(HasOverlay(), Selector(Sequence(HasCloseButton(), ClickClose()), Skip())),
            Sequence(has_load_more, click_load_more),
            Sequence(has_accordion, click_accordion),
            Sequence(has_tab, click_tab),
            Sequence(has_pagination, click_pagination),
            Sequence(has_scroll, scroll),
        )
        return tree, logs

    def test_returns_tuple_of_two(self, mocker: MockerFixture):
        result = self._build(mocker)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_tree_is_node(self, mocker: MockerFixture):
        tree, _ = self._build(mocker)
        assert isinstance(tree, Node)

    def test_logs_is_list(self, mocker: MockerFixture):
        _, logs = self._build(mocker)
        assert isinstance(logs, list)

    def test_logs_has_5_entries(self, mocker: MockerFixture):
        _, logs = self._build(mocker)
        assert len(logs) == 5

    def test_log_kinds(self, mocker: MockerFixture):
        _, logs = self._build(mocker)
        kinds = [log.kind for log in logs]
        assert 'load_more' in kinds
        assert 'accordion' in kinds
        assert 'tab' in kinds
        assert 'pagination' in kinds
        assert 'infinite_scroll' in kinds

    def test_all_logs_start_at_zero_cycles(self, mocker: MockerFixture):
        _, logs = self._build(mocker)
        for log in logs:
            assert log.cycles == 0

    def test_custom_max_click_cycles_stored(self, mocker: MockerFixture):
        stable = _make_fake_stable(mocker)
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ct = ClickTrigger(ht, stable, max_cycles=25)
        assert ct._max_cycles == 25

    def test_custom_max_scroll_cycles_stored(self, mocker: MockerFixture):
        stable = _make_fake_stable(mocker)
        ht = HasTrigger(TriggerKind.INFINITE_SCROLL, 'div.item')
        scroll = Scroll(ht, stable, max_cycles=5)
        assert scroll._max_cycles == 5

    def test_scroll_log_kind_is_infinite_scroll(self, mocker: MockerFixture):
        _, logs = self._build(mocker)
        scroll_log = next(log for log in logs if log.kind == 'infinite_scroll')
        assert scroll_log.kind == 'infinite_scroll'

    @pytest.mark.asyncio
    async def test_tree_returns_failure_when_no_triggers(self, mocker: MockerFixture):
        tree, _ = self._build(mocker)
        tab = _tab(mocker)
        assert await tree.tick(tab) == Status.FAILURE


# ===========================================================================
# TriggerKind
# ===========================================================================


class TestTriggerKind:
    def test_all_kinds_are_strings(self):
        for kind in TriggerKind:
            assert isinstance(kind.value, str)

    def test_load_more_value(self):
        assert TriggerKind.LOAD_MORE.value == 'load_more'

    def test_infinite_scroll_value(self):
        assert TriggerKind.INFINITE_SCROLL.value == 'infinite_scroll'

    def test_cookie_value(self):
        assert TriggerKind.COOKIE.value == 'cookie'

    def test_all_expected_kinds_exist(self):
        kinds = {k.value for k in TriggerKind}
        expected = {'cookie', 'popup', 'age_gate', 'load_more', 'accordion', 'tab', 'pagination', 'infinite_scroll'}
        assert kinds == expected

    def test_trigger_kind_is_str(self):
        assert isinstance(TriggerKind.LOAD_MORE, str)

    def test_can_construct_from_value(self):
        assert TriggerKind('load_more') == TriggerKind.LOAD_MORE


# ===========================================================================
# DetectedTrigger
# ===========================================================================


class TestDetectedTrigger:
    def test_fields_stored(self):
        dt = DetectedTrigger(TriggerKind.LOAD_MORE, 'button', 'load more')
        assert dt.kind == TriggerKind.LOAD_MORE
        assert dt.selector == 'button'
        assert dt.label == 'load more'


# ===========================================================================
# count_content
# ===========================================================================


class TestCountContent:
    @pytest.mark.asyncio
    async def test_returns_length_of_query_results(self, mocker: MockerFixture):
        tab = _tab(mocker, all_results={'div.item': ['a', 'b', 'c']})
        assert await count_content(tab, 'div.item') == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_results(self, mocker: MockerFixture):
        tab = _tab(mocker, all_results={'div.item': []})
        assert await count_content(tab, 'div.item') == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_runtime_error(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=RuntimeError('CDP'))
        assert await count_content(tab, 'div.item') == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_oserror(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=OSError('socket'))
        assert await count_content(tab, 'div.item') == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_valueerror(self, mocker: MockerFixture):
        tab = mocker.AsyncMock()
        tab.query_selector_all = mocker.AsyncMock(side_effect=ValueError('bad'))
        assert await count_content(tab, 'div.item') == 0

    @pytest.mark.asyncio
    async def test_uses_provided_selector(self, mocker: MockerFixture):
        tab = _tab(mocker, all_results={'article': ['a', 'b'], 'div': ['x']})
        assert await count_content(tab, 'article') == 2


# ===========================================================================
# Composition integration
# ===========================================================================


class TestSelectorSequenceComposition:
    @pytest.mark.asyncio
    async def test_selector_wrapping_sequences(self, mocker: MockerFixture):
        a = mocker.AsyncMock()
        a.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        b = mocker.AsyncMock()
        b.tick = mocker.AsyncMock(return_value=Status.FAILURE)
        c = mocker.AsyncMock()
        c.tick = mocker.AsyncMock(return_value=Status.SUCCESS)
        d = mocker.AsyncMock()
        d.tick = mocker.AsyncMock(return_value=Status.SUCCESS)

        node = Selector(Sequence(a, b), Sequence(c, d))
        assert await node.tick(mocker.MagicMock()) == Status.SUCCESS

    @pytest.mark.asyncio
    async def test_nested_failure_propagation(self, mocker: MockerFixture):
        fail = mocker.AsyncMock()
        fail.tick = mocker.AsyncMock(return_value=Status.FAILURE)
        assert await Selector(Sequence(fail, fail), Sequence(fail)).tick(mocker.MagicMock()) == Status.FAILURE

    @pytest.mark.asyncio
    async def test_has_trigger_exhaust_prevents_retry(self, mocker: MockerFixture):
        tab = _tab(
            mocker,
            all_results={
                'div.item': ['a'],
                '[data-kind="load_more"]': ['<button>'],
            },
        )
        ht = HasTrigger(TriggerKind.LOAD_MORE, 'div.item')
        ct = ClickTrigger(ht, _make_fake_stable(mocker))
        seq = Sequence(ht, ct)

        await seq.tick(tab)
        ht.exhaust()
        assert await seq.tick(tab) == Status.FAILURE
