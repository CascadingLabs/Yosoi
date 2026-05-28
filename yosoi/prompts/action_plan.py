"""Discovery prompt templates and runtime deps for A3Node action-plan discovery.

Sibling of :mod:`yosoi.prompts.discovery` but targeting *interaction* rather than
*extraction*. The agent receives:

  * the **rendered HTML** of the page in its just-navigated state,
  * a one-sentence **intent** describing what must be true before extraction runs
    (e.g. "load every public comment").

…and returns a list of :class:`yosoi.models.replay.A3Node` whose ``act``s drive
the page to that state. Typical shape is a single ``click_until`` node whose
target is a load-more / show-more trigger and whose ``expect`` is a
``selector_absent`` over the same trigger family (the structural 'done' for lazy
pagination).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from pydantic_ai import RunContext

# ---------------------------------------------------------------------------
# System-prompt constants
# ---------------------------------------------------------------------------

_BASE: Final = (
    'You are analyzing rendered HTML to find the actions needed to drive a page '
    'to a fully-loaded state BEFORE extraction runs. Return only actions that '
    'reference elements actually present in the provided HTML — never invent '
    'selectors. If the page already shows everything the intent asks for, '
    'return an empty list.'
)

_PRIMITIVES_GUIDE: Final = """\
Available action primitives (the A3Node `act.op` field):

* `navigate` — go to a URL. Rarely needed at this stage: the caller already
  navigated to the page you are looking at. Use only when the intent requires
  visiting a sibling URL.

* `click` (with `repeat=true` ⇒ "click_until") — click a target. When `repeat`
  is true, the executor ticks the click + checks `expect` until `expect` holds
  (bounded by `max_iters`, typically 20–40). This is the load-more / show-more
  primitive.

* `scroll` — scroll a container (`act.feed`) until at least N matches of
  `act.item` appear. Use for infinite-scroll feeds without an explicit trigger.

* `wait` — fixed pause. Use ONLY when no DOM event signals readiness (geo
  acquisition, third-party widgets that wire handlers asynchronously). The
  default is event-driven readiness via `expect`, not sleep.

`expect` (the postcondition / termination signal) options:

* `selector_absent(<trigger>)` — STRUCTURAL done. The canonical termination for
  `click_until`: keep ticking until no more triggers remain in the DOM. This is
  the RIGHT termination for reddit-style lazy pagination, because skeleton
  placeholders can satisfy a count check before content arrives.

* `min_count(N, <item>)` — at least N items matching `<item>` exist. Use only
  when the intent specifies a numeric target.

* `selector_present(<sel>)` / `url_contains(<text>)` / `text_present(<text>)` —
  for one-shot reachability assertions, not iterative loops.

When in doubt for "load every X" intents, emit ONE `click_until` whose:
  * `targets[0]` is the most specific CSS selector that matches the load-more
    trigger (button / custom element with the appropriate role),
  * `expect` is `selector_absent(<same trigger family>)`,
  * `max_iters` defaults to 30 (raise to 40-60 for deep-thread sites like reddit).
"""


# ---------------------------------------------------------------------------
# Runtime deps
# ---------------------------------------------------------------------------


@dataclass
class ActionPlanDiscoveryDeps:
    """Runtime context for action-plan discovery.

    Attributes:
        target: Stable cache key for the page kind (typically a domain or
            domain/section). Not seen by the LLM directly — used by callers for
            persistence/replay.
        intent: One-sentence description of what must be true after the actions
            run (e.g. "load every public comment on the post").
        html: Rendered HTML of the page in its just-navigated state. The agent
            uses this to ground every selector it emits.
    """

    target: str
    intent: str
    html: str


# ---------------------------------------------------------------------------
# System-prompt functions (registered on the pydantic-ai Agent)
# ---------------------------------------------------------------------------


def action_plan_base_instructions(ctx: RunContext[ActionPlanDiscoveryDeps]) -> str:
    """Core identity and task description for action-plan discovery."""
    return _BASE


def action_plan_intent_instructions(ctx: RunContext[ActionPlanDiscoveryDeps]) -> str:
    """Restate the intent so it is unambiguous to the LLM."""
    return (
        f'Intent (what must be true before extraction):\n  {ctx.deps.intent}\n\n'
        'Emit the SMALLEST list of A3Node actions sufficient to satisfy the intent. '
        'Empty list is the right answer when the page already shows everything.'
    )


def action_plan_primitives_guide(ctx: RunContext[ActionPlanDiscoveryDeps]) -> str:
    """Explain the available action primitives + termination signals."""
    return _PRIMITIVES_GUIDE


# ---------------------------------------------------------------------------
# User-prompt builder
# ---------------------------------------------------------------------------


def build_action_plan_user_prompt(deps: ActionPlanDiscoveryDeps) -> str:
    """Build the user prompt — HTML is the grounding context for selectors.

    The raw rendered HTML for a JS-heavy SPA can be 1-2 MB. Sent verbatim that
    blows up the LLM round-trip time and cost without adding signal: the agent
    only needs to *see* whether interaction triggers exist (load-more buttons,
    paginators, custom-element pagers like ``<faceplate-partial>``) and where
    they sit structurally. So we trim aggressively before prompting.
    """
    return f'Rendered HTML (trimmed for action-trigger discovery):\n{trim_for_action_plan(deps.html)}'


# ---------------------------------------------------------------------------
# HTML trimmer (action-plan-specific — NOT yosoi.core.cleaning.HTMLCleaner)
# ---------------------------------------------------------------------------


# Heuristic vocabulary the LLM looks for to identify a load-more trigger. Any
# tag that includes one of these substrings (in its text, attributes, or tag
# name) is preserved verbatim. Everything else can be lossy. This is the lever
# we tune when we see the agent miss a trigger family on a new site.
_TRIGGER_KEYWORDS: Final = (
    'load more',
    'load-more',
    'show more',
    'show-more',
    'view more',
    'view-more',
    'see more',
    'see-more',
    'more comments',
    'more-comments',
    'more replies',
    'more-replies',
    'load next',
    'next page',
    'older',
    'newer',
    'expand',
    'continue thread',
    'continue-thread',
    'paginate',
    'pagination',
    'infinite',
    'lazy',
)

# Tag names that are almost always interaction primitives — keep them verbatim
# even if the trigger keywords don't match (e.g. SPAs use bespoke names like
# ``<faceplate-partial>`` on reddit, ``<infinite-scroll>``).
_TRIGGER_TAG_HINTS: Final = (
    'partial',
    'paginat',
    'pager',
    'infinite',
    'loader',
    'load-more',
    'show-more',
)

# Attributes whose VALUES often encode the trigger semantics (e.g. reddit's
# ``faceplate-partial src="/svc/shreddit/more-comments/..."``). Keeping these
# attributes per-tag is cheap signal.
_KEEP_ATTRS: Final = frozenset(
    {
        'id',
        'class',
        'role',
        'href',
        'src',
        'data-testid',
        'data-test-id',
        'aria-label',
        'aria-controls',
        'aria-expanded',
        'type',
        'name',
    }
)

_TEXT_TRUNCATE_CHARS = 80  # any leaf text longer than this is replaced with an ellipsis
_HARD_CAP_CHARS = 60_000  # final size ceiling — keeps prompt latency / cost bounded


def _tag_is_trigger(tag: Tag) -> bool:
    """True if *tag* looks like an interaction-relevant element worth preserving verbatim."""
    name = (tag.name or '').lower()
    if any(hint in name for hint in _TRIGGER_TAG_HINTS):
        return True
    if name in ('button', 'a'):
        return True
    # Inspect attribute values + own text for trigger keywords.
    haystack_parts: list[str] = [name]
    for attr, value in tag.attrs.items():
        haystack_parts.append(attr)
        if isinstance(value, str):
            haystack_parts.append(value)
        elif isinstance(value, list):
            haystack_parts.extend(v for v in value if isinstance(v, str))
    own_text = tag.get_text(' ', strip=True)
    haystack_parts.append(own_text)
    haystack = ' '.join(haystack_parts).lower()
    return any(kw in haystack for kw in _TRIGGER_KEYWORDS)


def _drop_dead_weight(soup: BeautifulSoup) -> None:
    """Strip tags never useful to the action-plan agent (scripts, SVGs, media, comments)."""
    for tag in soup.find_all(
        ['script', 'style', 'noscript', 'svg', 'canvas', 'template', 'meta', 'link', 'picture', 'source']
    ):
        tag.decompose()
    for tag in soup.find_all(['img', 'video', 'audio', 'object', 'embed']):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()


def _prune_attrs(soup: BeautifulSoup) -> None:
    """Keep only attributes the agent uses for selector grounding; shorten long classes."""
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag) or not tag.attrs:
            continue
        new_attrs: dict[str, object] = {}
        for attr, value in tag.attrs.items():
            if attr in _KEEP_ATTRS or attr.startswith('data-'):
                if attr == 'class' and isinstance(value, list):
                    new_attrs[attr] = value[:2]
                else:
                    new_attrs[attr] = value
        tag.attrs = new_attrs


def _shorten_non_trigger_text(soup: BeautifulSoup) -> None:
    """Per-tag leaf-text truncation; triggers keep full text so keyword matching still works."""
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or _tag_is_trigger(tag):
            continue
        for child in list(tag.children):
            if isinstance(child, NavigableString) and not isinstance(child, Comment):
                s = str(child)
                if len(s) > _TEXT_TRUNCATE_CHARS:
                    child.replace_with(s[:_TEXT_TRUNCATE_CHARS] + '…')


def trim_for_action_plan(html: str, *, hard_cap: int = _HARD_CAP_CHARS) -> str:
    """Produce a short, trigger-focused HTML excerpt for the action-plan agent.

    Pipeline (each step is its own helper):
      1. ``_drop_dead_weight`` — scripts, SVGs, media, comments.
      2. ``_prune_attrs``     — keep id/class/href/data-* + a few others;
                                  shorten classes to first two tokens.
      3. ``_shorten_non_trigger_text`` — ellipsise leaf text > 80 chars on
                                  tags the agent doesn't classify as triggers.
      4. Whitespace collapse + tail-slice to ``hard_cap`` (with annotation).

    Triggers (``<faceplate-partial>``, ``<button>load more</button>``, custom
    paginators etc.) survive verbatim so the agent can match keywords + emit
    correct selectors.
    """
    soup = BeautifulSoup(html, 'lxml')
    _drop_dead_weight(soup)
    _prune_attrs(soup)
    _shorten_non_trigger_text(soup)

    out = re.sub(r'\s+\n', '\n', str(soup))
    out = re.sub(r'\n{3,}', '\n\n', out)

    if len(out) > hard_cap:
        # Triggers cluster near the top of the rendered tree (above-the-fold
        # cards + nav-region paginators) so tail-slicing is safe.
        out = out[:hard_cap] + f'\n<!-- trimmed: original was {len(out):,} chars -->'
    return out
