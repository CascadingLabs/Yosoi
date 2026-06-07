"""Behavior-tree replay + REACTION recovery regression tests (W1).

Covers the four load-bearing claims of the workstream:

1. ``ReplayPlan.compile()`` turns a flat plan into a SEQUENCE-of-LEAF tree that
   ``execute_tree`` runs identically to the legacy flat loop.
2. A REACTION fires on a simulated ``antibot.challenged`` / captcha wall, ticks a
   LEARNED recovery, and RESUMES the guarded branch.
3. An UNLEARNED reaction routes its description through a faked DiscoveryBus-fronted
   resolver, hot-swaps the learned recovery into the in-memory tree, and persists it
   so a second run handles it inline (LEARNED, no resolver hit).
4. The ``_RECOVERY_LEAVES`` dispatch-completeness invariant (in test_runtime_dispatch).
"""

from __future__ import annotations

import pytest

from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.replay.reactions import BusReactionResolver, ReactionMiss
from yosoi.core.replay.runtime import ReplayExecutionError, ReplayResult, execute_plan, execute_tree
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


class FakeTab:
    """A pooled-tab stand-in whose captcha state is scripted per tick.

    ``captcha_after`` simulates Google's /sorry/ reCAPTCHA popping at query N: the
    CAPTURE_JS eval returns a rendered widget until ``inject_token`` / ``human_click``
    "solves" it (clears ``_walled``).
    """

    def __init__(self, *, wall_on_eval: bool = False) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.url = 'https://www.google.com/search?q=a'
        self._walled = wall_on_eval

    async def goto(self, url: str) -> object:
        self.calls.append(('goto', (url,)))
        self.url = url
        return None

    async def type_into(self, selector: str, text: str) -> None:
        self.calls.append(('type_into', (selector, text)))

    async def query_selector(self, selector: str) -> object | None:
        return object()

    async def content(self) -> str:
        return '<html>ok</html>'

    async def dispatch_mouse_event(self, kind: str, x: float, y: float) -> None:
        self.calls.append(('dispatch_mouse_event', (kind, x, y)))
        # A humanized click clears the wall.
        self._walled = False

    async def eval_js(self, script: str) -> object:
        # CAPTURE_JS is the only script the recovery/guard path evals.
        if 'rectOf' in script or ('cf-turnstile-response' in script and 'function' in script):
            if self._walled:
                return {
                    'kind': 'recaptcha',
                    'widget_rendered': True,
                    'widget_rect': {'x': 10.0, 'y': 20.0, 'width': 100.0, 'height': 40.0},
                }
            return None
        # inject_token script
        if 'selectors' in script and 'written' in script:
            self._walled = False
            return 1
        if script == 'location.href':
            return self.url
        return None


def _leaf(node_id: str, act: ReplayAct, **kw: object) -> TreeNode:
    return TreeNode(
        kind=NodeKind.LEAF,
        id=node_id,
        leaf=ReplayNode(id=node_id, intent=node_id, act=act, **kw),
    )


def _type_leaf(node_id: str, text: str) -> TreeNode:
    return _leaf(
        node_id,
        ReplayAct(kind=ActKind.TYPE, text=text, targets=[_css('input[name=q]')]),
    )


def _css(value: str):
    from yosoi.models.selectors import css

    return css(value)


# --- 1. compile() flat -> tree equivalence ----------------------------------------


async def test_compile_wraps_flat_nodes_in_sequence_of_leaves():
    plan = ReplayPlan(
        nodes=[
            ReplayNode(id='a', intent='a', act=ReplayAct(kind=ActKind.WAIT)),
            ReplayNode(id='b', intent='b', act=ReplayAct(kind=ActKind.WAIT)),
        ]
    )
    tree = plan.compile()
    assert tree.kind is NodeKind.SEQUENCE
    assert [c.id for c in tree.children] == ['a', 'b']
    assert all(c.kind is NodeKind.LEAF for c in tree.children)


async def test_compile_returns_explicit_tree_verbatim():
    tree = TreeNode(kind=NodeKind.SEQUENCE, id='root', children=[])
    plan = ReplayPlan(tree=tree)
    assert plan.compile() is tree


async def test_execute_plan_runs_through_compiled_tree():
    """The flat plan and its compiled tree produce the same passed count + capture."""
    tab = FakeTab()
    plan = ReplayPlan(
        nodes=[
            ReplayNode(id='nav', intent='nav', act=ReplayAct(kind=ActKind.NAVIGATE, url='https://x/')),
            ReplayNode(
                id='grab',
                intent='grab',
                act=ReplayAct(kind=ActKind.EVAL, script='document.title', output_field='title'),
            ),
        ]
    )
    result = await execute_plan(tab, plan)
    assert result.passed == 2
    assert 'title' in result.extracted_actions

    # Direct execute_tree over the same compiled tree matches.
    ctx = ReplayResult()
    ok = await execute_tree(FakeTab(), plan.compile(), ctx)
    assert ok
    assert ctx.passed == 2


# --- 2. LEARNED reaction fires on a captcha wall and resumes -----------------------


def _learned_recovery() -> TreeNode:
    """A pinned recovery: humanized click then verify token field — LLM-free."""
    return TreeNode(
        kind=NodeKind.SEQUENCE,
        id='rec',
        children=[
            _leaf(
                'click',
                ReplayAct(kind=ActKind.HUMAN_CLICK, metadata={'offset_x': 0.5, 'offset_y': 0.5}),
            ),
        ],
    )


async def test_learned_reaction_fires_and_resumes():
    tab = FakeTab(wall_on_eval=True)
    guarded = TreeNode(
        kind=NodeKind.SEQUENCE,
        id='queries',
        children=[_type_leaf('q1', 'first'), _type_leaf('q2', 'second')],
    )
    reaction = TreeNode(
        kind=NodeKind.REACTION,
        id='captcha_guard',
        child=guarded,
        trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
        recovery=_learned_recovery(),
        state=ReactionState.LEARNED,
    )
    ctx = ReplayResult()
    ok = await execute_tree(tab, reaction, ctx)
    assert ok
    # Recovery ran the humanized click...
    assert any(c[0] == 'dispatch_mouse_event' for c in tab.calls)
    # ...and the guarded queries still completed (resumed, not aborted).
    assert any(c == ('type_into', ('input[name=q]', 'first')) for c in tab.calls)
    assert any(c == ('type_into', ('input[name=q]', 'second')) for c in tab.calls)


async def test_unlearned_reaction_without_resolver_raises_reaction_miss():
    tab = FakeTab(wall_on_eval=True)
    reaction = TreeNode(
        kind=NodeKind.REACTION,
        id='guard',
        child=_type_leaf('q1', 'x'),
        trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
        state=ReactionState.UNLEARNED,
        description='solve the reCAPTCHA challenge wall',
    )
    with pytest.raises(ReactionMiss):
        await execute_tree(tab, reaction, ReplayResult())


# --- 3. UNLEARNED -> bus resolve -> hot-swap -> persist -> second run inline -------


async def test_unlearned_reaction_routes_through_bus_and_hot_swaps():
    bus = DiscoveryBus()
    learn_calls: list[str] = []

    async def learn(domain: str, description: str, info: object) -> TreeNode:
        # PLANE B: the only place a model would run. Here it just returns a leaf.
        learn_calls.append(f'{domain}:{description}')
        return _learned_recovery()

    resolver = BusReactionResolver(bus, learn)

    reaction = TreeNode(
        kind=NodeKind.REACTION,
        id='guard',
        child=_type_leaf('q1', 'x'),
        trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
        state=ReactionState.UNLEARNED,
        description='solve the reCAPTCHA challenge wall',
    )

    tab = FakeTab(wall_on_eval=True)
    ctx = ReplayResult()
    ok = await execute_tree(tab, reaction, ctx, params={'domain': 'google.com'}, resolver=resolver)
    assert ok
    assert learn_calls == ['google.com:solve the reCAPTCHA challenge wall']
    # Hot-swap mutated the in-memory tree: the reaction is now LEARNED with a recovery.
    assert reaction.state is ReactionState.LEARNED
    assert reaction.recovery is not None

    # Second run on a fresh wall: already LEARNED, the resolver is NOT consulted again.
    tab2 = FakeTab(wall_on_eval=True)
    ok2 = await execute_tree(tab2, reaction, ReplayResult(), params={'domain': 'google.com'}, resolver=resolver)
    assert ok2
    assert learn_calls == ['google.com:solve the reCAPTCHA challenge wall']  # unchanged


async def test_bus_dedups_concurrent_resolution_to_one_learn_call():
    """Two concurrent tabs hitting the same novel description trigger ONE learn."""
    import asyncio

    bus = DiscoveryBus()
    learn_calls: list[str] = []
    gate = asyncio.Event()

    async def learn(domain: str, description: str, info: object) -> TreeNode:
        learn_calls.append(description)
        await gate.wait()  # hold the leader so the waiter parks on the bus
        return _learned_recovery()

    resolver = BusReactionResolver(bus, learn)

    def _reaction() -> TreeNode:
        return TreeNode(
            kind=NodeKind.REACTION,
            id='guard',
            child=_type_leaf('q', 'x'),
            trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
            state=ReactionState.UNLEARNED,
            description='same novel wall',
        )

    async def run() -> bool:
        return await execute_tree(
            FakeTab(wall_on_eval=True),
            _reaction(),
            ReplayResult(),
            params={'domain': 'google.com'},
            resolver=resolver,
        )

    t1 = asyncio.create_task(run())
    t2 = asyncio.create_task(run())
    await asyncio.sleep(0.05)  # let both reach the bus; one leads, one waits
    gate.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1
    assert r2
    assert learn_calls == ['same novel wall']  # exactly one resolution


# --- fail-fast: recovery that never clears the trigger exhausts and raises ---------


async def test_recovery_that_never_clears_trigger_exhausts_and_raises():
    class StuckTab(FakeTab):
        async def dispatch_mouse_event(self, kind: str, x: float, y: float) -> None:
            self.calls.append(('dispatch_mouse_event', (kind, x, y)))
            # Wall never clears -> trigger keeps holding -> retryer exhausts.

    tab = StuckTab(wall_on_eval=True)
    reaction = TreeNode(
        kind=NodeKind.REACTION,
        id='guard',
        child=_type_leaf('q', 'x'),
        trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
        recovery=_learned_recovery(),
        state=ReactionState.LEARNED,
    )
    with pytest.raises(ReplayExecutionError):
        await execute_tree(tab, reaction, ReplayResult())


# --- SELECTOR composite: first branch fails, second succeeds -----------------------


async def test_selector_falls_back_to_second_branch():
    tab = FakeTab()

    bad = _leaf(
        'bad',
        ReplayAct(kind=ActKind.NAVIGATE, url='https://x/'),
        expect=ReplayCondition(kind=AssertKind.TEXT, value='NEVER-PRESENT'),
    )
    good = _type_leaf('good', 'ok')
    selector = TreeNode(kind=NodeKind.SELECTOR, id='sel', children=[bad, good])

    ctx = ReplayResult()
    ok = await execute_tree(tab, selector, ctx)
    assert ok
    assert any(c == ('type_into', ('input[name=q]', 'ok')) for c in tab.calls)
