"""Canonical replay schema, built on one primitive (A3Node) and one selector model.

We align on the primitive *and* reuse the selector model — there's no second
selector vocabulary. An `A3Node` is the atomic, self-verifying unit:

  * **Assess**  — an optional precondition that must hold before acting.
  * **Act**     — the action; its `targets` are an ordered `SelectorEntry` *fallback
                  cascade* (AX `role` -> css -> visual), the same `SelectorEntry`
                  used for extraction and discovery elsewhere in Yosoi.
  * **Assert**  — an optional postcondition (`expect`); the verify signal. A repeating
                  node (`repeat=True`) ticks the act until `expect` holds.

Extraction reuses Yosoi's selector machinery too: a field is a `FieldSelectors`
cascade (primary/fallback/tertiary of `SelectorEntry`), and the *value* comes from the
field's Yosoi coercion `type` (Rating, Price, Title, …) — not a bespoke regex on the
recipe. The selector finds the node; the type extracts the value.

Composition over nodes (`ReplayPlan.nodes`) is intentionally flat for now and can
become a behavior tree later without touching the primitive.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from yosoi.models.selectors import FieldSelectors, SelectorEntry, attr, css, global_id, role, visual

__all__ = [  # noqa: RUF022 — grouped by concern, not alphabetical
    'Act',
    'A3Node',
    'Parallel',
    'Assertion',
    'ExtractField',
    'ExtractRecipe',
    'ReplayPlan',
    'StepAnnotation',
    'AgentAnnotations',
    'NodeResult',
    'VerifyReport',
    'merge_annotations',
    'ANNOTATION_PROMPT',
    'min_count',
    'selector_present',
    'selector_absent',
    'url_contains',
    'navigate',
    'teleport',
    'click',
    'click_until',
    'scroll_until',
    'fill',
    'wait',
    'parallel',
    # re-exported unified selector vocabulary
    'SelectorEntry',
    'FieldSelectors',
    'css',
    'role',
    'visual',
    'attr',
    'global_id',
]


class Assertion(BaseModel):
    """A condition used as an assess (pre) or assert (post) — the verify signal."""

    kind: Literal['min_count', 'selector_present', 'selector_absent', 'url_contains', 'text_present']
    count: int | None = None
    text: str | None = None
    selector: SelectorEntry | None = None


class Act(BaseModel):
    """What to do. For click/type, `targets` is an ordered SelectorEntry cascade."""

    op: Literal['navigate', 'click', 'type', 'scroll', 'teleport', 'wait']
    targets: list[SelectorEntry] = Field(default_factory=list)  # role -> css -> visual
    url: str | None = None
    text: str | None = None
    feed: str | None = None
    item: str | None = None
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None
    locale: str | None = None
    # Fixed pause for a 'wait' op, ONLY for a state change with no observable signal
    # (e.g. Maps acquiring the teleported geolocation). Everything else is event-driven.
    seconds: float | None = None


class A3Node(BaseModel):
    """The primitive: Assess -> Act -> Assert, verifiable in isolation.

    Both `assess` (precondition) and `expect` (postcondition) are *event-driven*: the
    executor polls each until it holds, never sleeps. An act is thus verified by its
    effect — there is no fixed wait. `repeat=True` ticks `act` until `expect` holds (up
    to `max_iters`) — the only control flow the primitive needs.
    """

    act: Act
    assess: Assertion | None = None  # precondition — readiness is gated on this (polled), not a sleep
    expect: Assertion | None = None  # postcondition (the 'assert') — the act's verified effect, polled
    repeat: bool = False
    max_iters: int = 1
    intent: str | None = None


class Parallel(BaseModel):
    """A fan-out group: its `nodes` are independent and run concurrently.

    The first real composition above the primitive. Use it for steps with no
    inter-dependency (e.g. N independent form fields) so they don't each pay a
    sequential settle — the group asserts readiness once (`assess`), then fans out.
    Distinguished from A3Node structurally (it has `nodes`, not `act`), so plans
    round-trip without a discriminator.
    """

    nodes: list[A3Node]
    assess: Assertion | None = None  # group precondition, checked once before fan-out
    intent: str | None = None


class ExtractField(BaseModel):
    """One extracted field: a selector cascade + the Yosoi coercion type for its value.

    No regex on the recipe — `selectors` finds the node, `type` (a registered Yosoi
    coercion like 'rating'/'title'/'price') turns its text into the value.
    """

    key: str
    type: str = 'text'
    selectors: FieldSelectors
    config: dict[str, object] = Field(default_factory=dict)  # forwarded to the coercer (e.g. as_float)


class ExtractRecipe(BaseModel):
    """How to read records off the final page: a card selector + typed fields.

    A recipe can target the AX tree (`card_role` — the AX-rich path used by Maps), or
    the DOM (`card` — any `SelectorEntry`, used for AX-blind / aggregating sites like
    reddit, where deep replies collapse into 'Comment thread level N' wrappers and per-
    card 1:1 AX alignment is lost). When both are set, the DOM `card` selector wins —
    it is the more specific instruction. An agent can emit either shape; the unified
    SelectorEntry model is the same vocabulary either way.
    """

    card_role: str | None = None  # AX path — card is an AX node with this role
    card: SelectorEntry | None = None  # DOM path — card is any css/xpath SelectorEntry
    fields: list[ExtractField] = Field(default_factory=list)
    skip_prefixes: list[str] = Field(default_factory=list)


class ReplayPlan(BaseModel):
    """Persistable replay artifact: a sequence of A3Nodes and/or Parallel fan-out groups."""

    target: str
    task: str
    nodes: list[A3Node | Parallel]
    extract: ExtractRecipe | None = None
    source: Literal['mcp-agent', 'scripted', 'hand'] = 'scripted'
    discovered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    replay_count: int = 0


# ── reusable parts (builders) ────────────────────────────────────────────────


def min_count(n: int, sel: SelectorEntry | None = None) -> Assertion:
    """Assert at least `n` items are present — matching `sel`, else the node's act.item."""
    return Assertion(kind='min_count', count=n, selector=sel)


def selector_present(sel: SelectorEntry) -> Assertion:
    """Assert an element matching `sel` is present."""
    return Assertion(kind='selector_present', selector=sel)


def selector_absent(sel: SelectorEntry) -> Assertion:
    """Assert no element matching `sel` is present — the structural 'done' for lazy pagination.

    The natural twin of `selector_present`: where present says "this exists, the act
    landed", absent says "this is gone, there is no more". The canonical use is the
    termination of a `click_until` over a load-more trigger: stop when no more triggers
    remain, not when some downstream count appears to be reached (which can pass on
    not-yet-hydrated skeleton elements).
    """
    return Assertion(kind='selector_absent', selector=sel)


def url_contains(text: str) -> Assertion:
    """Assert the current URL contains `text`."""
    return Assertion(kind='url_contains', text=text)


def navigate(url: str, *, expect: Assertion | None = None) -> A3Node:
    """A navigate node. `expect` is the event-driven readiness signal (e.g. results present)."""
    return A3Node(act=Act(op='navigate', url=url), expect=expect)


def teleport(lat: float, lon: float, tz: str | None = None, locale: str | None = None) -> A3Node:
    """A geolocation-teleport node (set before navigating)."""
    return A3Node(act=Act(op='teleport', lat=lat, lon=lon, timezone=tz, locale=locale))


def click(*targets: SelectorEntry, expect: Assertion | None = None, intent: str | None = None) -> A3Node:
    """A click with an ordered fallback cascade (first target that lands wins)."""
    return A3Node(act=Act(op='click', targets=list(targets)), expect=expect, intent=intent)


def click_until(*targets: SelectorEntry, expect: Assertion, max_iters: int = 20, intent: str | None = None) -> A3Node:
    """Repeating click — tick until `expect` holds (e.g. paginated 'load more' triggers).

    Each tick clicks the first matching element of the cascade; the act is allowed to
    fail silently when the trigger is gone (no more partials to expand), at which point
    the next `expect` check is decisive. Pairs with `min_count` to load lazy feeds.
    """
    return A3Node(
        act=Act(op='click', targets=list(targets)), expect=expect, repeat=True, max_iters=max_iters, intent=intent
    )


def scroll_until(feed: str, item: str, n: int, *, max_iters: int = 15, intent: str | None = None) -> A3Node:
    """A repeating scroll node: tick until at least `n` `item`s are in `feed`."""
    return A3Node(
        act=Act(op='scroll', feed=feed, item=item), expect=min_count(n), repeat=True, max_iters=max_iters, intent=intent
    )


def fill(selector: str, text: str, *, intent: str | None = None) -> A3Node:
    """A type node: set `text` into the css `selector` (an extraction-style css target)."""
    return A3Node(act=Act(op='type', targets=[css(selector)], text=text), intent=intent)


def wait(seconds: float, *, expect: Assertion | None = None, intent: str | None = None) -> A3Node:
    """A fixed pause — the ONE escape hatch from event-driven settling.

    For a state change with no observable signal (e.g. Maps acquiring a teleported
    geolocation, which its app requests internally with no DOM effect). Use sparingly;
    prefer `assess`/`expect`.
    """
    return A3Node(act=Act(op='wait', seconds=seconds), expect=expect, intent=intent)


def parallel(*nodes: A3Node, intent: str | None = None) -> Parallel:
    """Group independent nodes to run concurrently (fan-out)."""
    return Parallel(nodes=list(nodes), intent=intent)


# ── hybrid emission: agent output + merge ────────────────────────────────────


class StepAnnotation(BaseModel):
    """Agent-authored annotation for one captured node, keyed by its index."""

    step: int
    intent: str | None = None
    expect: Assertion | None = None  # the 'assert' postcondition the agent proposes


class AgentAnnotations(BaseModel):
    """The agent's structured phase-2 output (use as a pydantic-ai output_type)."""

    annotations: list[StepAnnotation] = Field(default_factory=list)


def merge_annotations(nodes: list[A3Node], annotations: list[StepAnnotation]) -> list[A3Node]:
    """Fold agent intent/assert onto captured (ground-truth) nodes, by index."""
    by_step = {a.step: a for a in annotations}
    for i, node in enumerate(nodes):
        ann = by_step.get(i)
        if ann is None:
            continue
        if ann.intent:
            node.intent = ann.intent
        if ann.expect:
            node.expect = ann.expect
    return nodes


ANNOTATION_PROMPT = (
    'You just performed a browser task. Below is the exact ordered list of actions you '
    'executed (ground truth). For each step that matters for *replaying* this task later, '
    'return a StepAnnotation with: the step index, a short `intent` (why the step exists), '
    'and an `assert` postcondition that should hold once the step succeeds — one of '
    'min_count (count), selector_present (selector), url_contains (text), or text_present '
    '(text). Skip trivial steps; do not invent steps that are not in the list.'
)


# ── verify by rerun ──────────────────────────────────────────────────────────


class NodeResult(BaseModel):
    """Outcome of replaying one node — its assert (`expect`) passed or not."""

    index: int
    op: str
    passed: bool
    detail: str | None = None


class VerifyReport(BaseModel):
    """Quality of a replay: per-node pass/fail + an overall score (pass rate)."""

    results: list[NodeResult] = Field(default_factory=list)

    @property
    def score(self) -> float:
        """Pass rate across nodes (0.0 to 1.0)."""
        return sum(r.passed for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def ok(self) -> bool:
        """True when every node's assert passed."""
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def failures(self) -> list[NodeResult]:
        """Nodes whose assert failed on replay."""
        return [r for r in self.results if not r.passed]
