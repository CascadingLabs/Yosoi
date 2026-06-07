"""execute_plan must forward a ReactionResolver to the behavior-tree walker (W1).

The deterministic hot path never imports a model; the only seam to concurrent
discovery (PLANE B) is the ``resolver`` an UNLEARNED REACTION resolves through.
If ``execute_plan`` did not forward it, the public replay entrypoint could never
reach that seam and every UNLEARNED reaction would fail fast — these tests pin the
wire in both directions.
"""

from __future__ import annotations

from typing import Any

import pytest

from yosoi.core.replay._captcha_js import CAPTURE_JS
from yosoi.core.replay.reactions import ReactionMiss
from yosoi.core.replay.runtime import execute_plan
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    NodeKind,
    ReactionState,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    TreeNode,
)

_CLEAR_JS = '__clear_captcha__'


class _FakeTab:
    """Minimal tab: a rendered captcha that an EVAL recovery clears."""

    def __init__(self) -> None:
        self.url = 'https://example.test/'
        self.captcha_active = True

    async def eval_js(self, script: str) -> Any:
        if script is CAPTURE_JS:
            return {'kind': 'recaptcha', 'widget_rendered': True} if self.captcha_active else None
        if script == _CLEAR_JS:
            self.captcha_active = False
            return None
        return None


def _unlearned_plan() -> ReplayPlan:
    child = TreeNode(
        kind=NodeKind.LEAF,
        id='work',
        leaf=ReplayNode(id='work', intent='do work behind the wall', act=ReplayAct(kind=ActKind.WAIT)),
    )
    return ReplayPlan(
        tree=TreeNode(
            kind=NodeKind.REACTION,
            id='guard',
            child=child,
            trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
            state=ReactionState.UNLEARNED,
            description='solve the checkpoint',
        )
    )


def _recovery_subtree() -> TreeNode:
    return TreeNode(
        kind=NodeKind.LEAF,
        id='recover',
        leaf=ReplayNode(
            id='recover',
            intent='clear the captcha',
            act=ReplayAct(kind=ActKind.EVAL, script=_CLEAR_JS),
        ),
    )


async def test_execute_plan_without_resolver_fails_fast_on_unlearned_reaction() -> None:
    """No resolver wired -> an UNLEARNED reaction honestly fails (no garbage scrape)."""
    with pytest.raises(ReactionMiss):
        await execute_plan(_FakeTab(), _unlearned_plan())


async def test_execute_plan_forwards_resolver_and_hot_swaps() -> None:
    """A forwarded resolver resolves the description, hot-swaps, and the run resumes."""
    calls: list[str] = []

    class _Resolver:
        async def resolve(self, domain: str, description: str, info: object) -> TreeNode:
            calls.append(f'{domain}:{description}')
            return _recovery_subtree()

    plan = _unlearned_plan()
    result = await execute_plan(_FakeTab(), plan, params={'domain': 'example.test'}, resolver=_Resolver())

    assert result.failed == 0
    assert calls == ['example.test:solve the checkpoint']  # resolved exactly once
    # the in-memory reaction is now LEARNED (hot-swapped) for subsequent ticks
    assert plan.tree is not None
    assert plan.tree.state is ReactionState.LEARNED
    assert plan.tree.recovery is not None
