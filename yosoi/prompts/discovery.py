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

If the card element (the repeating wrapper itself) carries the value as an
HTML attribute on its OPENING TAG, you MUST emit `attr` — do NOT emit a CSS
selector that targets the card. A CSS selector returns the card's full text
content, which is wrong.

How to spot the pattern in the HTML you've been given:

  * The tag is a "custom element" — its name contains a hyphen, e.g. any tag
    that isn't a standard HTML5 element (div/span/article/a/...).
  * Look at the opening tag's attributes. If an attribute name matches (or
    closely matches) the field name from the contract, that attribute IS the
    value. Read it directly.

Generic worked example (the actual attribute and tag names will differ on
THIS page — work them out from the HTML you have):

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

  ❌ ANTI-PATTERN — what you might be tempted to emit, all WRONG:
    count: {"type": "css", "value": "some-card-tag"}            # returns whole card text
    count: {"type": "css", "value": "some-card-tag::attr(...)"} # not a real CSS pseudo
    title: {"type": "css", "value": "a[href^='/foo/']"}         # returns link TEXT, not the title

Heuristic for field-name → attr-name (try in this order against the actual
attributes you see on the card in the HTML you've been given):
  1. field name AS-IS                   (e.g. `score` → `score`)
  2. kebab-cased                        (e.g. `comment_count` → `comment-count`)
  3. with common suffixes               (e.g. `title` → `post-title`, `item-title`)
  4. prefixed with `data-`              (e.g. `price` → `data-price`)
  5. anything else with the same semantic meaning that's actually present

You MUST verify the attribute exists on the card BEFORE emitting `attr`. If
no attribute on the card matches the field, drop to RULE 3 or 4.

──────────────────────────────────────────────────────────────────────────────
RULE 2 — Value lives OUTSIDE the card's subtree but has a stable id template
         → use `global_id`.
──────────────────────────────────────────────────────────────────────────────

Sometimes lazy-loaded or slot-reassigned content is grafted into a sibling's
light DOM. The card has an identity attribute (the value of an attribute like
`id`, `thingid`, `record-id`); the content node lives at an element whose own
`id` is built from that identity plus a fixed suffix or prefix. A scoped CSS
query inside the card MISSES it.

Generic shape (the attribute name and id pattern will differ on THIS page):

  Suppose the HTML contains:
    <some-card identity-attr="abc">...</some-card>
    <div id="abc-content-suffix">The actual body text here.</div>

  And the contract field is `body`. Then:
    body → {"type": "global_id", "value": "{id}-content-suffix",
            "identity": "identity-attr"}

  The extractor resolves `{id}` from the card's `identity-attr`, then runs
  `document.getElementById("abc-content-suffix")`. Pure CSS cannot express
  this from inside the card — global_id is the only correct answer.

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

    return '\n'.join(hints)


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
