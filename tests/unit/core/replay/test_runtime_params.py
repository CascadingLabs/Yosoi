"""Regression tests for parametrized replay (W4 PR1).

Covers the four W4-mandated invariants for the hotpath foundation:

1. ``_bind`` substitutes ``{d}``/``{q}`` into ``act.url``/``act.text`` only.
2. A missing param fail-fasts (``str.format_map`` via the strict mapping) —
   never a silent empty substitution that would produce a garbage URL.
3. A brace-dense ``act.script`` (arrow funcs, object literals, regex
   quantifiers) round-trips UNTOUCHED — templating must never corrupt JS.
4. NAVIGATE fail-fasts on an antibot challenge surfaced by ``goto``'s
   ``PageResponse.antibot.challenged`` (the existing substrate signal), and
   TYPE drives a pooled tab that exposes only ``type_into``.
"""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import ReplayExecutionError, _bind, execute_plan
from yosoi.models.replay import ActKind, ReplayAct, ReplayNode, ReplayPlan
from yosoi.models.selectors import css

# A brace-heavy extraction body: arrow func, object literal, AND a regex quantifier.
# str.format_map would raise/corrupt on the FIRST brace — _bind must never touch it.
_BRACE_HEAVY_SCRIPT = 'document.querySelectorAll("a").map(a => ({href: a.href, m: a.text.match(/\\w{0,40}/)}))'


def test_bind_substitutes_url_and_text_only():
    act = ReplayAct(
        kind=ActKind.NAVIGATE,
        url='https://www.similarweb.com/website/{d}/',
        text='query {q}',
    )
    bound = _bind(act, {'d': 'example.com', 'q': 'home care'})
    assert bound.url == 'https://www.similarweb.com/website/example.com/'
    assert bound.text == 'query home care'


def test_bind_missing_key_fails_fast():
    act = ReplayAct(kind=ActKind.NAVIGATE, url='https://x/{d}/')
    with pytest.raises(ReplayExecutionError, match=r'param \{d\} is missing'):
        _bind(act, {'q': 'unrelated'})


def test_bind_never_templates_script_brace_heavy_roundtrips_untouched():
    act = ReplayAct(kind=ActKind.EVAL, script=_BRACE_HEAVY_SCRIPT, output_field='rows')
    # params present AND containing a key that appears nowhere — proves script is
    # excluded from templating entirely (no raise, no mangling).
    bound = _bind(act, {'d': 'example.com'})
    assert bound.script == _BRACE_HEAVY_SCRIPT


def test_bind_empty_params_is_identity():
    act = ReplayAct(kind=ActKind.NAVIGATE, url='https://literal/{notaparam}')
    # No params → no substitution attempted, so a literal brace survives untouched.
    assert _bind(act, {}) is act


class _ParamTab:
    """Minimal pooled-tab-shaped fake: ``goto`` returns a PageResponse-like object."""

    class _Resp:
        def __init__(self, challenged: bool) -> None:
            self.antibot = type('AntiBot', (), {'challenged': challenged})()

    def __init__(self, challenged: bool = False) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._challenged = challenged
        self.html = '<main>ok</main>'

    async def goto(self, url: str) -> _ParamTab._Resp:
        self.calls.append(('goto', (url,)))
        return self._Resp(self._challenged)

    async def type_into(self, selector: str, text: str) -> None:
        self.calls.append(('type_into', (selector, text)))

    async def content(self) -> str:
        return self.html


async def test_execute_plan_navigate_substitutes_param():
    tab = _ParamTab()
    plan = ReplayPlan(
        nodes=[
            ReplayNode(
                id='nav',
                intent='open engine for target',
                act=ReplayAct(kind=ActKind.NAVIGATE, url='https://e/{d}/'),
            )
        ]
    )
    await execute_plan(tab, plan, params={'d': 'acme.com'})
    assert ('goto', ('https://e/acme.com/',)) in tab.calls


async def test_execute_plan_navigate_fails_fast_on_antibot_challenge():
    tab = _ParamTab(challenged=True)
    plan = ReplayPlan(
        nodes=[ReplayNode(id='nav', intent='open', act=ReplayAct(kind=ActKind.NAVIGATE, url='https://e/'))]
    )
    with pytest.raises(ReplayExecutionError, match='antibot challenge detected'):
        await execute_plan(tab, plan)


async def test_execute_plan_type_uses_type_into_on_pooled_tab():
    tab = _ParamTab()
    plan = ReplayPlan(
        nodes=[
            ReplayNode(
                id='type',
                intent='type the SERP query',
                act=ReplayAct(kind=ActKind.TYPE, targets=[css('input[name=q]')], text='{q}'),
            )
        ]
    )
    await execute_plan(tab, plan, params={'q': 'home care arlington va'})
    assert ('type_into', ('input[name=q]', 'home care arlington va')) in tab.calls


async def test_execute_plan_missing_param_fails_fast_at_dispatch():
    tab = _ParamTab()
    plan = ReplayPlan(
        nodes=[ReplayNode(id='nav', intent='open', act=ReplayAct(kind=ActKind.NAVIGATE, url='https://e/{d}/'))]
    )
    # A non-empty params dict that lacks the referenced key is the real wiring
    # bug: the strict mapping raises rather than substituting an empty string.
    with pytest.raises(ReplayExecutionError, match=r'param \{d\} is missing'):
        await execute_plan(tab, plan, params={'q': 'wrong key'})
