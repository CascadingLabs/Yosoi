"""Google SERP use case — the runnable dogfood for the hotpath-dogfood spike.

This is the "thing to run off of": it drives the REAL new engine end-to-end against
a Google search program, exercising every workstream the spike shipped:

  * W3  teleport-before-first-paint  -> ReplayPlan.teleport (set BEFORE the first goto)
  * W4  parametrized replay          -> ONE program, params={'q': ...} bound into act.url
  * W1  behavior-tree + reaction     -> an UNLEARNED captcha REACTION guarding the SERP
        extraction; a mid-scrape reCAPTCHA is a tick event, not a fatal error
  * W1  discovery<->extraction seam  -> the UNLEARNED reaction resolves its DESCRIPTION
        through the DiscoveryBus (leader/waiter dedup), hot-swaps the learned recovery
        into the running tree, and RESUMES — captcha-recovery and selector-drift-repair
        are the same mechanism
  * W5  ad-vs-organic contracts      -> OrganicResult / AdResult differ ONLY by docstring
        yet get DISTINCT cache signatures; to_model() exports to a plain pydantic/ODM model

WHAT RUNS TODAY (default, offline, deterministic):
  A FakeTab models a Google search. We "hammer" N queries; on the Kth, the tab raises a
  rendered reCAPTCHA widget. The engine's behavior tree catches it via the captcha guard,
  resolves the description through the bus (a single learn() call — the LLM/discovery
  stand-in), hot-swaps a humanized-click recovery recipe, the click clears the widget, and
  the SAME extraction node resumes. No network, no LLM, no flakiness — it proves the wiring.

WHAT NEEDS VOIDCRAWL (the --real path, gated):
  The live loop drives a pooled VoidCrawl tab. Two known gaps keep it from fully firing yet:
    1. The installed VoidCrawl PageResponse has no `antibot` field, so the W4 goto-level
       challenge gate is inert (it degrades to "no signal", never a false block).
    2. capture/inject/solve_captcha are not bound on PooledTab, so the captcha PROBE runs
       a pure-JS port (works) but a real solver token must come from PLANE B.
  The captcha guard here uses the CAPTURE_JS widget probe (which DOES work on a pooled tab),
  so the reaction path is live-capable the moment a discovery agent emits the program.

Run:
    uv run python examples/serp_google/google_serp.py            # offline demo (default)
    uv run python examples/serp_google/google_serp.py --queries 30
    uv run python examples/serp_google/google_serp.py --real     # prints the live-path status
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import yosoi as ys
from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.core.replay._captcha_js import CAPTURE_JS
from yosoi.core.replay.reactions import BusReactionResolver
from yosoi.core.replay.runtime import execute_plan
from yosoi.models.contract import Contract
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    NodeKind,
    ReactionState,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    TeleportSpec,
    TreeNode,
)

# --------------------------------------------------------------------------- #
# W5 — two redundant SERP contracts that differ ONLY by natural-language intent
# --------------------------------------------------------------------------- #


class SerpResult(Contract):
    """A result row on a Google SERP: its link and visible title."""

    url: str = ys.Url()
    title: str = ys.Title()


# Same field set {url, title}; the docstring is the only differentiator. Before W5
# these collided into one per-domain cache slot; now each gets a DISTINCT signature
# AND a distinct discovery-agent prompt so the model can pick the right container.
OrganicResult = SerpResult.variant(
    'OrganicResult',
    'An ORGANIC (unpaid) Google result from the main #rso list — NOT an ad.',
)
AdResult = SerpResult.variant(
    'AdResult',
    'A SPONSORED Google result from the #tads ad rail — a paid advertisement.',
)


# --------------------------------------------------------------------------- #
# The Google search program (parametrized, teleported, captcha-guarded)
# --------------------------------------------------------------------------- #

# Pure-JS SERP extraction (identity-compared by FakeTab; NEVER templated by _bind).
EXTRACT_JS = r"""(() => {
  const host = a => { try { return new URL(a.href).hostname.replace(/^www\./,''); } catch(e){ return null; } };
  const out = [];
  for (const h of document.querySelectorAll('#rso a h3')) {
    const a = h.closest('a'); if (!a) continue;
    const u = host(a); if (u) out.push({url: a.href, title: h.textContent});
  }
  return out.slice(0, 15);
})()"""


def build_google_program(*, latitude: float, longitude: float) -> ReplayPlan:
    """Build the learned Google-search behavior tree.

    teleport-before-first-paint (W3) is a per-plan field, so the geo override is
    installed before the first goto. The SERP fetch+extract sequence is wrapped in
    an UNLEARNED captcha REACTION (W1): if a reCAPTCHA renders mid-scrape, the guard
    fires and PLANE B resolves the recovery from the description.
    """
    navigate = TreeNode(
        kind=NodeKind.LEAF,
        id='serp.navigate',
        leaf=ReplayNode(
            id='serp.navigate',
            intent='open the Google results page for the query',
            act=ReplayAct(kind=ActKind.NAVIGATE, url='https://www.google.com/search?q={q}'),
        ),
    )
    extract = TreeNode(
        kind=NodeKind.LEAF,
        id='serp.extract',
        leaf=ReplayNode(
            id='serp.extract',
            intent='extract the organic result hosts + titles',
            act=ReplayAct(kind=ActKind.EVAL, script=EXTRACT_JS, output_field='organic'),
        ),
    )
    guarded = TreeNode(kind=NodeKind.SEQUENCE, id='serp.fetch', children=[navigate, extract])
    reaction = TreeNode(
        kind=NodeKind.REACTION,
        id='serp.captcha_guard',
        child=guarded,
        trigger=ReplayCondition(kind=AssertKind.CAPTCHA),
        state=ReactionState.UNLEARNED,
        description='solve the reCAPTCHA checkpoint blocking the Google results',
    )
    return ReplayPlan(
        tree=reaction,
        teleport=TeleportSpec(latitude=latitude, longitude=longitude, timezone='America/New_York'),
    )


# A LEARNED recovery recipe: a humanized checkbox click, rect-relative so it survives
# layout shift. In production PLANE B (an LLM/discovery agent) PRODUCES this from the
# description; here learn() returns it directly to keep the demo deterministic.
def humanized_click_recovery() -> TreeNode:
    """The recovery subtree a discovery agent would emit for the captcha description."""
    return TreeNode(
        kind=NodeKind.LEAF,
        id='serp.captcha_recovery',
        leaf=ReplayNode(
            id='serp.captcha_recovery',
            intent='humanized click on the reCAPTCHA checkbox',
            act=ReplayAct(kind=ActKind.HUMAN_CLICK, metadata={'offset_x': 0.12, 'offset_y': 0.5}),
        ),
    )


# --------------------------------------------------------------------------- #
# Offline substrate: a FakeTab that models Google (incl. a mid-scrape reCAPTCHA)
# --------------------------------------------------------------------------- #


class FakeTab:
    """A deterministic stand-in for a pooled VoidCrawl tab.

    Implements exactly the surface the replay walker calls: goto / eval_js /
    set_geolocation+timezone+locale (teleport) / dispatch_mouse_event (humanized
    click). It recognises the engine's CAPTURE_JS probe and the program's
    EXTRACT_JS by identity, so no brittle JS parsing is involved.
    """

    def __init__(self) -> None:
        self.url = 'about:blank'
        self.captcha_active = False
        self._arm_captcha_on_next_goto = False
        # observability for the narrative / tests
        self.geo: tuple[float, float] | None = None
        self.timezone: str | None = None
        self.mouse_events: list[tuple[str, float, float]] = []
        self.captcha_episodes = 0

    def arm_captcha(self) -> None:
        """Make the NEXT search raise a rendered reCAPTCHA after navigation."""
        self._arm_captcha_on_next_goto = True

    async def goto(self, url: str | None) -> None:
        self.url = url or self.url
        if self._arm_captcha_on_next_goto:
            self.captcha_active = True
            self._arm_captcha_on_next_goto = False
            self.captcha_episodes += 1
        # PageResponse has no antibot field on the installed VoidCrawl build, so the
        # W4 goto-gate is intentionally inert here — the captcha is surfaced via the
        # CAPTURE_JS widget probe instead (the path that works on a pooled tab).
        return

    async def eval_js(self, script: str) -> Any:
        if script is CAPTURE_JS:
            if self.captcha_active:
                return {
                    'kind': 'recaptcha',
                    'widget_rendered': True,
                    'widget_rect': {'x': 380.0, 'y': 300.0, 'width': 300.0, 'height': 74.0},
                }
            return None
        if script is EXTRACT_JS:
            return [
                {'url': 'https://carebuildersathome.com/louisville/', 'title': 'CareBuilders at Home — Louisville'},
                {'url': 'https://example-competitor.com/', 'title': 'A Competitor'},
            ]
        return None

    async def set_geolocation(self, latitude: float, longitude: float) -> None:
        self.geo = (latitude, longitude)

    async def set_timezone(self, tz: str) -> None:
        self.timezone = tz

    async def set_locale(self, locale: str) -> None:  # pragma: no cover - not exercised
        pass

    async def dispatch_mouse_event(self, kind: str, x: float, y: float) -> None:
        self.mouse_events.append((kind, x, y))
        if kind == 'mouseReleased':
            # the humanized click solved the challenge — the widget clears
            self.captcha_active = False


# --------------------------------------------------------------------------- #
# Demo driver
# --------------------------------------------------------------------------- #


async def run_demo(*, queries: int, captcha_on: int) -> dict[str, Any]:
    """Hammer `queries` Google searches; fire a reCAPTCHA on search #captcha_on.

    Returns a small report the CLI prints and the test asserts on.
    """
    tab = FakeTab()
    plan = build_google_program(latitude=38.2527, longitude=-85.7585)  # Louisville, KY

    learn_calls: list[str] = []

    async def learn(domain: str, description: str, info: object) -> TreeNode:
        """PLANE-B resolver stand-in: description -> recovery recipe (LLM in prod)."""
        learn_calls.append(f'{domain}:{description}')
        return humanized_click_recovery()

    resolver = BusReactionResolver(DiscoveryBus(), learn)

    extracted: list[int] = []
    terms = ['home care louisville', 'senior care near me', 'in home caregivers ky']
    for i in range(1, queries + 1):
        if i == captcha_on:
            tab.arm_captcha()
        q = terms[i % len(terms)]
        result = await execute_plan(tab, plan, params={'q': q, 'domain': 'google.com'}, resolver=resolver)
        rows = result.extracted_actions.get('organic') or []
        extracted.append(len(rows))

    return {
        'queries': queries,
        'rows_per_query': extracted,
        'captcha_episodes': tab.captcha_episodes,
        'learn_calls': learn_calls,
        'mouse_events': tab.mouse_events,
        'teleport_geo': tab.geo,
        'teleport_tz': tab.timezone,
        # after the first resolve the reaction is LEARNED in the live tree:
        'reaction_state_after': plan.tree.state.value,
    }


def _print_contract_facts() -> None:
    from yosoi.utils.signatures import contract_signature

    org = contract_signature(OrganicResult)
    ad = contract_signature(AdResult)
    print('W5 — ad-vs-organic contracts (same {url,title}, differ only by docstring):')
    print(f'  OrganicResult signature: {org}')
    print(f'  AdResult      signature: {ad}')
    print(f'  distinct? {org != ad}  (before W5 these collided into one cache slot)')
    Exported = OrganicResult.to_model(name='OrganicResultDoc')  # -> plain pydantic/ODM-ready model
    print(f'  to_model() export -> {Exported.__name__} fields={sorted(Exported.model_fields)}\n')


async def _amain() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', type=int, default=8, help='number of searches to hammer')
    ap.add_argument('--captcha-on', type=int, default=4, help='fire a reCAPTCHA on this search #')
    ap.add_argument('--real', action='store_true', help='describe the live VoidCrawl path (gated)')
    a = ap.parse_args()

    _print_contract_facts()

    if a.real:
        print('--real: the live path drives _VoidCrawlFetcher.fetch_with_plan(plan, params).')
        print('Gated until VoidCrawl exposes PageResponse.antibot + binds capture/solve_captcha')
        print('on PooledTab. The captcha guard')
        print('uses the CAPTURE_JS widget probe, which already works on a pooled tab.\n')
        return

    rep = await run_demo(queries=a.queries, captcha_on=a.captcha_on)
    print(f'W3 — teleport applied BEFORE first paint: geo={rep["teleport_geo"]} tz={rep["teleport_tz"]}')
    print(f'W4 — one parametrized program replayed across {rep["queries"]} queries')
    print(f'     rows extracted per query: {rep["rows_per_query"]}')
    print(
        f'W1 — reCAPTCHA episodes: {rep["captcha_episodes"]}; '
        f'bus learn() calls: {len(rep["learn_calls"])} (deduped); '
        f'humanized-click events: {len(rep["mouse_events"])}'
    )
    print(
        f'     reaction state after first solve: {rep["reaction_state_after"]} '
        f'(UNLEARNED -> hot-swapped to LEARNED, resumed, kept scraping)'
    )
    ok = (
        all(n == 2 for n in rep['rows_per_query'])
        and rep['captcha_episodes'] == 1
        and len(rep['learn_calls']) == 1
        and rep['reaction_state_after'] == 'learned'
    )
    print(f'\nRESULT: {"PASS — captcha reacted-and-resumed, every query still extracted" if ok else "UNEXPECTED"}')


def main() -> None:
    asyncio.run(_amain())


if __name__ == '__main__':
    main()
