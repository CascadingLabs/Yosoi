"""Discovery prompt templates and runtime deps for AI selector discovery."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel
from pydantic_ai import RunContext

from yosoi.models.selectors import SelectorLevel

if TYPE_CHECKING:
    from yosoi.models.contract import Contract

# ---------------------------------------------------------------------------
# System prompt constants
# ---------------------------------------------------------------------------

_BASE: Final = (
    'You are analyzing HTML to find selectors for web scraping. '
    'Return selectors that actually exist in the provided HTML. '
    'Only use selectors you can see in the HTML — never invent selectors.'
)

_FIELD_SELECTOR_GUIDE: Final = """\
For each field provide:
- primary: Most specific selector using actual classes/IDs from the HTML
- fallback: Less specific but reliable selector
- tertiary: Generic selector or null if field does not exist

Selector strategies (the `type` field on each selector). Pick by THIS rule, in order:

──────────────────────────────────────────────────────────────────────────────
RULE 1 — Card carries the value as one of its OWN HTML attributes → use `attr`.
──────────────────────────────────────────────────────────────────────────────

Use this ONLY when the rule's three-step check passes against the actual HTML
you've been given. RULE 1 is the strongest pattern when it applies AND a
common over-reach when it doesn't.

THREE-STEP CHECK (do this BEFORE emitting `attr`):
  1. Find the card element's OPENING TAG in the HTML.
  2. Read off its attribute NAMES (the words on the LEFT of the `=` signs).
  3. Pick the attribute name that matches the contract field. If NO attribute
     on the card matches, RULE 1 does NOT apply — drop to RULE 3 or 4.

If you skip step 2 and guess an attribute name that "sounds right", you will
emit a selector that extracts None at runtime. A CSS CLASS that happens to
have the same name as the field (e.g. `<span class="rank">`) is NOT an
attribute — `class` is the attribute name; `rank` is just a class value.

When the check DOES pass, the rule is unambiguous. Custom elements (tag names
containing a hyphen) almost always carry data this way:

  Suppose the HTML contains a card like:
    <some-card-tag
        title-attr="A great record"
        author-attr="someone"
        count-attr="42">
      ... descendant markup, possibly noisy ...
    </some-card-tag>

  And the contract field names are `title`, `author`, `count`. Then:
    title  → {"type": "attr", "value": "title-attr"}
    author → {"type": "attr", "value": "author-attr"}
    count  → {"type": "attr", "value": "count-attr"}

  ❌ ANTI-PATTERNS — all WRONG:
    count: {"type": "css", "value": "some-card-tag"}            # returns whole card text
    count: {"type": "css", "value": "some-card-tag::attr(...)"} # not a real CSS pseudo
    title: {"type": "css", "value": "a[href^='/foo/']"}         # returns link TEXT, not the title
    score: {"type": "attr", "value": "rank"}                    # `rank` is a CSS class, NOT an attribute on the card
    score: {"type": "attr", "value": "score"}                   # only if `score="..."` actually appears on the card's opening tag

Heuristic for field-name → attr-name (try in this order against the actual
attribute NAMES you saw in step 2 above):
  1. field name AS-IS                   (e.g. `score` → `score`)
  2. kebab-cased                        (e.g. `comment_count` → `comment-count`)
  3. with common suffixes               (e.g. `title` → `post-title`, `item-title`)
  4. prefixed with `data-`              (e.g. `price` → `data-price`)
  5. anything else with the same semantic meaning that's actually present

──────────────────────────────────────────────────────────────────────────────
RULE 2 — Value lives at an id that's TEMPLATABLE from the card's identity
         attribute → use `global_id`.
──────────────────────────────────────────────────────────────────────────────

The pattern: the card has an attribute carrying an identifier (commonly
``id``, ``thingid``, ``record-id``, ``data-id``, ``data-post-id``, ...), and
the target element's own ``id`` is built from that identifier plus a fixed
prefix or suffix. The target may be:

  (a) OUTSIDE the card's subtree entirely (slot reassignment, lazy-loaded
      content grafted into a sibling), or
  (b) in an adjacent / sibling row that scoped descendant CSS can't cleanly
      reach (table-based layouts where one logical record spans two `<tr>`s).

Both cases share the SAME shape and the SAME correct answer — `global_id`
templates over the card's identity attribute.

Generic shape:

  Card opening tag has some identifier attribute:
    <some-card identity-attr="abc">...</some-card>
  Target element with related id:
    <div id="abc-content-suffix">The actual body text here.</div>
  Or, equivalently, in an adjacent row:
    <tr id="abc">title row</tr>
    <tr><span id="metric_abc">42</span></tr>

  For the body / metric field:
    body  → {"type": "global_id", "value": "{id}-content-suffix",
             "identity": "identity-attr"}
    metric → {"type": "global_id", "value": "metric_{id}", "identity": "id"}

How to spot the pattern (look at the HTML before guessing):

  * The card has an attribute whose VALUE is a short id-like token (e.g.
    "48307887", "t3_abc", "abc").
  * Another element on the page has an ``id`` ATTRIBUTE that contains that
    same token plus a fixed prefix and/or suffix.
  * Multiple repeating cards show the SAME structural relationship — same
    prefix/suffix, just the identity token varies.

Pure descendant CSS cannot reach (a) at all, and cannot cleanly reach (b)
across sibling rows. `global_id` is the right answer for both.

──────────────────────────────────────────────────────────────────────────────
RULE 3 — Value is visible text inside a descendant element → use `css`/`xpath`.
──────────────────────────────────────────────────────────────────────────────

The classic case. The value lives in a child element's text node. Use a CSS or
XPath selector scoped under the card.

──────────────────────────────────────────────────────────────────────────────
RULE 4 — Value lives in an attribute of a DESCENDANT (not the card itself)
         → use a CSS `::attr(name)` pseudo-element.
──────────────────────────────────────────────────────────────────────────────

Examples (generic): `time::attr(datetime)`, `meta[itemprop="x"]::attr(content)`,
`a.some-link::attr(href)`. Reserve the typed `attr` selector (RULE 1) for
attributes on the CARD itself — not on descendants."""

_LEVEL_CSS_ONLY: Final = (
    'Use CSS selectors (e.g. .class-name, #id, h1 > span) as your primary '
    'parser strategy. The `attr` and `global_id` selector types are also '
    'always available — they are CSS-level reads (off the card or via a '
    'document-wide id lookup) and never count as escalation.'
)

_LEVEL_XPATH_ALLOWED: Final = (
    'You may use CSS selectors OR XPath expressions. '
    'Prefer CSS when possible. Use XPath (e.g. //div[@class="x"]/text()) '
    'only when CSS cannot express the needed structure. '
    'Prefix XPath selectors with // so they are recognisable. '
    'The `attr` and `global_id` selector types are also available at any '
    'level — they are read-mechanism choices, not escalations.'
)

_LEVEL_REGEX_ALLOWED: Final = (
    'You may use CSS selectors, XPath expressions, or regex patterns. '
    'Prefer CSS when possible. Use XPath when CSS cannot express the needed structure. '
    'Use regex only as a last resort for fields embedded in unstructured text.'
)

_LEVEL_JSONLD_ALLOWED: Final = (
    'You may use CSS selectors, XPath expressions, regex patterns, or JSON-LD extraction. '
    'Prefer CSS when possible. Use XPath when CSS cannot express the needed structure. '
    'Use regex for fields in unstructured text. '
    'Use JSON-LD for fields available in <script type="application/ld+json"> blocks.'
)

_HINT_TESTID: Final = 'Page uses data-testid attributes — prefer them over class names (they are more stable).'

_HINT_JSON_LD: Final = (
    'Page contains JSON-LD structured data inside <script type="application/ld+json"> — '
    'check it for clean structured fields like price, name, and datePublished.'
)

_HINT_DATA_QA: Final = 'Page uses data-qa/data-cy test attributes — they are stable selector targets.'

_HINT_GLOBAL_ID_TPL: Final = (
    'GLOBAL_ID CANDIDATE DETECTED: this page has multiple elements whose ids share '
    'a common prefix followed by a varying suffix — exactly the pattern RULE 2 '
    '(`global_id`) is for. Concrete examples found on the page: {examples}. '
    'For each contract field whose data lives in one of these "{prefix}<token>" '
    'elements, you SHOULD emit `global_id`, e.g. '
    '`{{"type": "global_id", "value": "{prefix}{{id}}", "identity": "id"}}`. '
    'The card whose `id` token feeds the template is typically the repeating '
    'record element (e.g. a `<tr>` in HN, a `<shreddit-comment>` on reddit). '
    'Do NOT try to reach these via descendant CSS — they are NOT under the card '
    'in the DOM tree (sibling rows or grafted nodes).'
)

_CONTAINER_GUIDANCE: Final = (
    'If the page contains multiple repeating items (e.g., product cards, article listings, '
    'search results), also provide a `root` selector for the repeating wrapper element '
    'that contains one complete item. This selector should match each individual item on the '
    'page (e.g., `.product-card`, `article.listing`). '
    'If the page shows a single item, set `root` to null.'
)

_MULTI_ITEM_FIELD_GUIDANCE: Final = (
    'IMPORTANT — repeating-item scoping: if the HTML contains multiple repeating items '
    '(product cards, listings, search results, table rows), this field belongs to ONE item, '
    'so your selector MUST match the value *inside a single repeating item* and resolve once '
    'per item. Do NOT target page-level chrome such as the page title/heading (e.g. a top-level '
    '<h1>), site header, breadcrumbs, or navigation — even when the field is named "title" or '
    '"heading", prefer the per-item element (e.g. the card\'s own heading link) over a page-wide '
    'heading. When in doubt, scope the selector under the repeating item wrapper.'
)


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class DiscoveryInput(BaseModel):
    """Typed input for selector discovery containing the source URL and HTML."""

    url: str
    html: str


# ---------------------------------------------------------------------------
# Runtime deps
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryDeps:
    """Runtime context passed to all discovery system-prompt functions.

    Attributes:
        contract: The Contract class defining fields to discover
        input: Typed discovery input containing url and html
        target_level: Maximum selector strategy level allowed

    """

    contract: type['Contract']
    input: DiscoveryInput
    target_level: SelectorLevel = field(default=SelectorLevel.CSS)


# ---------------------------------------------------------------------------
# System-prompt functions (registered on the pydantic-ai Agent)
# ---------------------------------------------------------------------------


def base_instructions(ctx: RunContext['DiscoveryDeps']) -> str:
    """Core identity and task description."""
    return _BASE


def field_instructions(ctx: RunContext['DiscoveryDeps']) -> str:
    """Describe the fields the agent must find selectors for."""
    descriptions = ctx.deps.contract.field_descriptions()
    if not descriptions:
        return ''
    fields_text = '\n'.join(f'**{name}** — {desc}' for name, desc in descriptions.items())
    container_guidance = '' if ctx.deps.contract.get_root() else f'\n\n{_CONTAINER_GUIDANCE}'
    return f'Find selectors for these fields:\n{fields_text}\n\n{_FIELD_SELECTOR_GUIDE}{container_guidance}'


def level_instructions(ctx: RunContext['DiscoveryDeps']) -> str:
    """Explain which selector strategies are allowed based on target_level."""
    if ctx.deps.target_level >= SelectorLevel.JSONLD:
        return _LEVEL_JSONLD_ALLOWED
    if ctx.deps.target_level >= SelectorLevel.REGEX:
        return _LEVEL_REGEX_ALLOWED
    if ctx.deps.target_level >= SelectorLevel.XPATH:
        return _LEVEL_XPATH_ALLOWED
    return _LEVEL_CSS_ONLY


def page_hints(ctx: RunContext['DiscoveryDeps']) -> str:
    """Detect structural signals from the HTML and surface them as hints."""
    html = ctx.deps.input.html
    hints: list[str] = []

    if 'data-testid' in html:
        hints.append(_HINT_TESTID)
    if '"@type"' in html or '"@context"' in html:
        hints.append(_HINT_JSON_LD)
    if 'data-qa' in html or 'data-cy' in html:
        hints.append(_HINT_DATA_QA)
    global_id_hint = _detect_global_id_pattern(html)
    if global_id_hint is not None:
        hints.append(global_id_hint)

    return '\n'.join(hints)


# ---------------------------------------------------------------------------
# global_id pattern detector — mechanical, surfaces RULE 2 candidates
# ---------------------------------------------------------------------------

# Match id values shaped `<head><sep><tail>` where head and tail are word-ish.
# We catch BOTH shared-head and shared-tail patterns:
#   * HN: `score_48307887` (head="score", tail varies per story) — shared head
#   * reddit comments: `t1_abc-post-rtjson-content` (head varies, tail shared) —
#                      shared tail
_ID_TEMPLATE_RE = __import__('re').compile(
    # Head: first alphanumeric token (no `-` so we don't greedily eat past the
    # FIRST separator). Tail: anything word-or-dash that follows.
    r'\bid\s*=\s*["\']([a-zA-Z]\w{0,30})([_\-:])([\w][\w-]{2,60})["\']'
)
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {'main', 'page', 'site', 'app', 'header', 'footer', 'nav', 'sidebar', 'content', 'wrapper', 'root'}
)


def _detect_global_id_pattern(html: str) -> str | None:
    """Return a hint when the HTML contains a global_id-shaped id pattern.

    Two shapes both qualify:

      * **shared head**: many ids share the same prefix word + separator with a
        varying suffix token (HN: ``score_48307887``, ``score_48308912``, ...).
        Template: ``score_{id}`` keyed off the card's ``id``.

      * **shared tail**: many ids share the same suffix with a varying head
        token (reddit: ``t1_abc-post-rtjson-content``,
        ``t1_xyz-post-rtjson-content``). Template: ``{id}-post-rtjson-content``
        keyed off the card's identity attribute.

    Either way, surfaces the template + concrete examples so the LLM can
    pattern-match instead of having to discover the relationship unaided.
    """
    if 'id=' not in html:
        return None

    head_groups: dict[tuple[str, str], list[str]] = {}
    tail_groups: dict[tuple[str, str], list[str]] = {}
    for match in _ID_TEMPLATE_RE.finditer(html):
        head, sep, tail = match.group(1), match.group(2), match.group(3)
        if head.lower() in _GENERIC_TOKENS or tail.lower() in _GENERIC_TOKENS:
            continue
        head_groups.setdefault((head, sep), []).append(tail)
        tail_groups.setdefault((tail, sep), []).append(head)

    best_head = _pick_best_group(head_groups)
    best_tail = _pick_best_group(tail_groups)

    # Prefer whichever group has more distinct examples; head wins on tie because
    # the typical id-anchor pattern (HN style) is more common than slot grafts.
    if best_head is None and best_tail is None:
        return None
    if best_head is not None and (best_tail is None or len(best_head[2]) >= len(best_tail[2])):
        head, sep, tails = best_head
        template_prefix = f'{head}{sep}'
        sample_ids = ', '.join(f'"{template_prefix}{t}"' for t in tails[:3])
        template_value = f'{template_prefix}{{id}}'
    else:
        assert best_tail is not None
        tail, sep, heads = best_tail
        template_prefix = f'{{id}}{sep}{tail}'
        sample_ids = ', '.join(f'"{h}{sep}{tail}"' for h in heads[:3])
        template_value = template_prefix
    return _HINT_GLOBAL_ID_TPL.format(prefix=template_value, examples=sample_ids)


def _pick_best_group(groups: dict[tuple[str, str], list[str]]) -> tuple[str, str, list[str]] | None:
    """Pick the (key, sep, tokens) with the most distinct varying parts (>=2)."""
    best: tuple[str, str, list[str]] | None = None
    for (key, sep), tokens in groups.items():
        unique_tokens = sorted(set(tokens))
        if len(unique_tokens) < 2:
            continue
        if best is None or len(unique_tokens) > len(best[2]):
            best = (key, sep, unique_tokens)
    return best


# ---------------------------------------------------------------------------
# Per-field deps and prompt functions
# ---------------------------------------------------------------------------


@dataclass
class FieldDiscoveryDeps:
    """Runtime context for single-field selector discovery.

    Attributes:
        field_name: Name of the field to discover selectors for
        field_description: Human-readable description of the field
        field_hint: Optional AI hint from the contract field definition
        input: Typed discovery input containing url and html
        target_level: Maximum selector strategy level allowed
        is_container: True if discovering the yosoi_container selector
        feedback: Diagnosis from a prior failed attempt — surfaced verbatim
            in the system prompt so the LLM can self-correct without losing
            the per-field context. None on the first attempt.

    """

    field_name: str
    field_description: str
    field_hint: str | None
    input: DiscoveryInput
    target_level: SelectorLevel = field(default=SelectorLevel.CSS)
    is_container: bool = False
    feedback: str | None = None


def field_single_base_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Core identity and task description for single-field discovery."""
    return _BASE


def field_single_field_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Describe the single field the agent must find selectors for."""
    deps = ctx.deps
    hint_text = f'\n    Hint: {deps.field_hint}' if deps.field_hint else ''
    text = (
        f'Find selectors for this field:\n'
        f'**{deps.field_name}** — {deps.field_description}{hint_text}\n\n'
        f'{_FIELD_SELECTOR_GUIDE}'
    )
    if deps.is_container:
        text += f'\n\n{_CONTAINER_GUIDANCE}'
    else:
        # Content fields are discovered in parallel with `root`, so they can't
        # see the container selector. Tell them to scope within a single
        # repeating item so ambiguous fields (e.g. title vs. page heading)
        # don't latch onto page-level chrome.
        text += f'\n\n{_MULTI_ITEM_FIELD_GUIDANCE}'
    return text


def field_single_level_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Explain which selector strategies are allowed based on target_level."""
    if ctx.deps.target_level >= SelectorLevel.JSONLD:
        return _LEVEL_JSONLD_ALLOWED
    if ctx.deps.target_level >= SelectorLevel.REGEX:
        return _LEVEL_REGEX_ALLOWED
    if ctx.deps.target_level >= SelectorLevel.XPATH:
        return _LEVEL_XPATH_ALLOWED
    return _LEVEL_CSS_ONLY


def field_single_page_hints(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Detect structural signals from the HTML and surface them as hints."""
    html = ctx.deps.input.html
    hints: list[str] = []

    if 'data-testid' in html:
        hints.append(_HINT_TESTID)
    if '"@type"' in html or '"@context"' in html:
        hints.append(_HINT_JSON_LD)
    if 'data-qa' in html or 'data-cy' in html:
        hints.append(_HINT_DATA_QA)
    global_id_hint = _detect_global_id_pattern(html)
    if global_id_hint is not None:
        hints.append(global_id_hint)

    return '\n'.join(hints)


def field_single_feedback_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Surface prior-attempt failure diagnosis to the LLM.

    Empty string on the first attempt — has no effect on the prompt. On retry,
    the message from ``SemanticValidator`` (via ``render_feedback``) lands here
    so the LLM sees exactly why its previous selector returned wrong-shape data
    and which rubric rule to reach for instead.
    """
    fb = ctx.deps.feedback
    if not fb:
        return ''
    return (
        '⚠ PREVIOUS ATTEMPT FAILED VALIDATION — DO NOT REPEAT THE SAME MISTAKE.\n'
        f'{fb}\n'
        'Re-read the selector strategy guide above. If the data lives in an '
        'attribute on the card element itself, RULE 1 applies and you MUST '
        'emit `{"type": "attr", "value": "<attr-name>"}` — not a CSS selector '
        'targeting the card, which returns the full card text.'
    )


# ---------------------------------------------------------------------------
# User-prompt builders
# ---------------------------------------------------------------------------


def build_user_prompt(discovery_input: DiscoveryInput) -> str:
    """Build the user prompt for the deps-based agent (system prompts handle context)."""
    return discovery_input.model_dump_json()
