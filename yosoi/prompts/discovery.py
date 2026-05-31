"""Discovery prompt templates and runtime deps for AI selector discovery."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field
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

If the value lives in an ATTRIBUTE rather than visible text, target the
attribute with a CSS `::attr(name)` pseudo-element so extraction returns the
attribute string. Common cases: a rating encoded in a class
(`p.star-rating::attr(class)`), a machine date (`time::attr(datetime)`), a
price in microdata (`meta[itemprop="price"]::attr(content)`), or an input's
`value`. Use `::attr(...)` whenever the matched element carries no useful
text node."""

_LEVEL_CSS_ONLY: Final = 'Use CSS selectors only (e.g. .class-name, #id, h1 > span).'

_LEVEL_XPATH_ALLOWED: Final = (
    'You may use CSS selectors OR XPath expressions. '
    'Prefer CSS when possible. Use XPath (e.g. //div[@class="x"]/text()) '
    'only when CSS cannot express the needed structure. '
    'Prefix XPath selectors with // so they are recognisable.'
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
    # Compact accessibility hint (role: name lines) from the rendered page.
    # Excluded from the user-prompt JSON dump — surfaced via a system prompt instead.
    ax_hint: str = Field(default='', exclude=True)


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


@dataclass(frozen=True)
class FieldFeedback:
    """Corrective feedback for a semantic-validation discovery retry.

    Attributes:
        message: Human-readable explanation of why the previous selector was
            wrong, prepended to the user prompt.
        failed_selectors: Selector value strings already tried for this field.
            Enforced by an output validator so the LLM cannot return them again.

    """

    message: str
    failed_selectors: tuple[str, ...] = ()


@dataclass
class FieldDiscoveryDeps:
    """Runtime context for single-field selector discovery.

    Attributes:
        field_name: Name of the field to discover selectors for
        field_description: Human-readable description of the field
        input: Typed discovery input containing url and html
        target_level: Maximum selector strategy level allowed
        is_container: True if discovering the yosoi_container selector
        forbidden_selectors: Selector values that already failed and must not be
            returned again (enforced via a pydantic-ai output validator).

    """

    field_name: str
    field_description: str
    input: DiscoveryInput
    target_level: SelectorLevel = field(default=SelectorLevel.CSS)
    is_container: bool = False
    forbidden_selectors: tuple[str, ...] = ()


def field_single_base_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Core identity and task description for single-field discovery."""
    return _BASE


def field_single_field_instructions(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Describe the single field the agent must find selectors for."""
    deps = ctx.deps
    text = (
        f'Find selectors for this field:\n**{deps.field_name}** — {deps.field_description}\n\n{_FIELD_SELECTOR_GUIDE}'
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


def field_single_ax_hints(ctx: RunContext['FieldDiscoveryDeps']) -> str:
    """Surface the rendered-page accessibility outline, when available.

    The AX tree gives a role/name view of the *rendered* DOM — more stable than
    class soup on thin or obfuscated markup — so the model can anchor selectors
    on semantics it can see.
    """
    ax_hint = ctx.deps.input.ax_hint
    if not ax_hint:
        return ''
    return (
        'Accessibility outline of the rendered page (role: accessible name). '
        'Use it to locate elements semantically:\n'
        f'{ax_hint}'
    )


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


# ---------------------------------------------------------------------------
# User-prompt builders
# ---------------------------------------------------------------------------


def build_user_prompt(discovery_input: DiscoveryInput) -> str:
    """Build the user prompt for the deps-based agent (system prompts handle context)."""
    return discovery_input.model_dump_json()


def build_field_user_prompt(discovery_input: DiscoveryInput, feedback: str | None = None) -> str:
    """Build the single-field user prompt, optionally prefixed with retry feedback.

    When ``feedback`` is provided, a "Previous attempt failed because" block is
    prepended so the LLM can correct a selector that structurally verified but
    extracted the wrong kind of value (see CAS-78 / ``SemanticValidator``).
    """
    base = build_user_prompt(discovery_input)
    if not feedback:
        return base
    return (
        'Previous attempt failed because:\n'
        f'{feedback}\n\n'
        'Find a better selector for the field described above that fixes this. '
        'Do not repeat the selector that failed.\n\n'
        f'{base}'
    )
