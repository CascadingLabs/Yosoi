"""Unit tests for DOMLoader A3Node action-replay — no browser required.

Exercises the real DOMLoader.replay orchestration with the heavy browser
collaborators (count_content, the trigger action primitives, HTML capture)
mocked out.
"""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from yosoi.core.fetcher.dom.flows import WaitForDOMStable
from yosoi.core.fetcher.dom.loader import _CLICK_KINDS, _SCROLL_KIND, DOMLoader
from yosoi.core.fetcher.dom.tree.actions import ClickTrigger, Scroll
from yosoi.core.fetcher.dom.tree.conditions import HasTrigger
from yosoi.models.selectors import SelectorEntry
from yosoi.storage.a3node import A3Fragment, ActRecord


class _FakeTab:
    async def wait_for_network_idle(self, timeout: float = 5.0) -> None:
        return None

    async def content(self) -> str:
        return '<html>ok</html>'


# ---------------------------------------------------------------------------
# _build_replay_action — kind → (condition, action) mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('kind', sorted(_CLICK_KINDS))
def test_build_replay_action_maps_click_kinds(kind):
    loader = DOMLoader()
    built = loader._build_replay_action(kind, WaitForDOMStable())
    assert built is not None
    condition, action = built
    assert isinstance(condition, HasTrigger)
    assert isinstance(action, ClickTrigger)


def test_build_replay_action_maps_scroll_kind():
    loader = DOMLoader()
    built = loader._build_replay_action(_SCROLL_KIND, WaitForDOMStable())
    assert built is not None
    _, action = built
    assert isinstance(action, Scroll)


@pytest.mark.parametrize('kind', ['bogus_kind'])
def test_build_replay_action_returns_none_for_unsupported(kind):
    loader = DOMLoader()
    assert loader._build_replay_action(kind, WaitForDOMStable()) is None


# ---------------------------------------------------------------------------
# replay — orchestration
# ---------------------------------------------------------------------------


def _fake_action_builder(mocker: MockerFixture, cycles: int, order: list[str]):
    """Return a _build_replay_action stand-in that records call order."""

    def build(kind: str, _stable):
        condition = mocker.MagicMock()
        condition.tick = mocker.AsyncMock()
        action = mocker.MagicMock()
        action.log = mocker.MagicMock(cycles=cycles)

        async def _tick(_tab):
            order.append(kind)

        action.tick = _tick
        return condition, action

    return build


async def test_replay_fragments_ignores_non_obstacle_fragments(mocker: MockerFixture):
    loader = DOMLoader()
    target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
    fragment = A3Fragment(fragment_key='load-more', kind='load_more', target=target, source_domain='x.example')
    target_present = mocker.patch.object(loader, '_target_present', mocker.AsyncMock(return_value=True))
    replay_target = mocker.patch.object(loader, '_replay_target', mocker.AsyncMock(return_value=1))
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', return_value=0)
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html/>'))

    result = await loader.replay_fragments(_FakeTab(), [fragment])

    assert result.acts == []
    target_present.assert_not_awaited()
    replay_target.assert_not_awaited()


async def test_replay_runs_acts_in_order_and_succeeds(mocker: MockerFixture):
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[0, 5])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'x' * 100 + '</html>'))
    order: list[str] = []
    mocker.patch.object(loader, '_build_replay_action', side_effect=_fake_action_builder(mocker, cycles=2, order=order))

    acts = [ActRecord('load_more', 3), ActRecord('infinite_scroll', 1)]
    result = await loader.replay(_FakeTab(), acts)

    assert result.success is True
    assert order == ['load_more', 'infinite_scroll']  # order preserved
    # cycles are re-derived from the live action run, not copied from the recipe
    assert [(a.kind, a.cycles) for a in result.acts] == [('load_more', 2), ('infinite_scroll', 2)]
    assert result.content_start == 0
    assert result.content_final == 5


async def test_replay_skips_unsupported_kinds(mocker: MockerFixture):
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[1, 1])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'y' * 100 + '</html>'))
    mocker.patch.object(loader, '_build_replay_action', return_value=None)  # nothing replayable

    result = await loader.replay(_FakeTab(), [ActRecord('cookie', 1)])
    assert result.acts == []
    # html present and content_final > 0 → still a success
    assert result.success is True


async def test_replay_reports_failure_when_no_content(mocker: MockerFixture):
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[0, 0])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value=None))
    mocker.patch.object(loader, '_build_replay_action', return_value=None)

    result = await loader.replay(_FakeTab(), [ActRecord('load_more', 1)])
    assert result.success is False  # caller will fall back to a full probe


async def test_replay_with_stored_target_skips_catalogue_probe(mocker: MockerFixture):
    """The core CAS-94 property: an act with a concrete target replays by clicking that
    target via build_flow directly — the legacy probe/_build_replay_action (catalogues)
    path is never used."""
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', return_value=3)
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'x' * 100 + '</html>'))
    legacy = mocker.patch.object(loader, '_build_replay_action')
    mocker.patch.object(loader, '_target_present', mocker.AsyncMock(return_value=True))
    fake_flow = mocker.MagicMock()
    fake_flow.run = mocker.AsyncMock()
    flow_builder = mocker.patch('yosoi.core.fetcher.dom.loader.build_flow', return_value=fake_flow)
    settle = mocker.MagicMock()
    settle.run = mocker.AsyncMock()
    mocker.patch('yosoi.core.fetcher.dom.loader.Flow', return_value=settle)

    target = SelectorEntry(type='role', value='button', name='Load more', nth=0)
    result = await loader.replay(_FakeTab(), [ActRecord('load_more', 2, target=target)])

    assert flow_builder.called  # stored target clicked via build_flow
    assert not legacy.called  # catalogue/probe path NOT used
    assert fake_flow.run.await_count >= 1
    assert [(a.kind, a.cycles) for a in result.acts] == [('load_more', 1)]
    assert result.acts[0].target == target  # target carried through to the replayed recipe


async def test_replay_skips_absent_stored_target_without_raising(mocker: MockerFixture):
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[2, 2])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'x' * 100 + '</html>'))
    mocker.patch.object(loader, '_target_present', mocker.AsyncMock(return_value=False))
    flow_builder = mocker.patch('yosoi.core.fetcher.dom.loader.build_flow')

    target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
    result = await loader.replay(_FakeTab(), [ActRecord('cookie', 1, target=target)])

    assert result.success is True
    assert result.acts == []
    flow_builder.assert_not_called()


async def test_replay_catches_stale_target_click_failure(mocker: MockerFixture):
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[2, 2, 2])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'x' * 100 + '</html>'))
    mocker.patch.object(loader, '_target_present', mocker.AsyncMock(return_value=True))
    mocker.patch.object(loader, '_replay_target', mocker.AsyncMock(side_effect=RuntimeError('gone')))

    target = SelectorEntry(type='role', value='button', name='Accept additional cookies', nth=0)
    result = await loader.replay(_FakeTab(), [ActRecord('cookie', 1, target=target)])

    assert result.success is True
    assert result.acts == []


async def test_replay_drops_acts_that_did_nothing(mocker: MockerFixture):
    """An action whose cycle count stays 0 (trigger absent) is not recorded."""
    loader = DOMLoader()
    mocker.patch('yosoi.core.fetcher.dom.loader.count_content', side_effect=[0, 3])
    mocker.patch.object(loader, '_capture_html', mocker.AsyncMock(return_value='<html>' + 'z' * 100 + '</html>'))
    order: list[str] = []
    mocker.patch.object(loader, '_build_replay_action', side_effect=_fake_action_builder(mocker, cycles=0, order=order))

    result = await loader.replay(_FakeTab(), [ActRecord('load_more', 2)])
    assert order == ['load_more']  # it still ran
    assert result.acts == []  # but produced no cycles, so not recorded
