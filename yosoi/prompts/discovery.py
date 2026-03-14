"""Discovery prompt templates and runtime deps for AI selector discovery."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

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
- tertiary: Generic selector or null if field does not exist"""

_LEVEL_CSS_ONLY: Final = 'Use CSS selectors only (e.g. .class-name, #id, h1 > span).'

_LEVEL_XPATH_ALLOWED: Final = (
    'You may use CSS selectors OR XPath expressions. '
    'Prefer CSS when possible. Use XPath (e.g. //div[@class="x"]/text()) '
    'only when CSS cannot express the needed structure. '
    'Prefix XPath selectors with // so they are recognisable.'
)

_HINT_TESTID: Final = 'Page uses data-testid attributes — prefer them over class names (they are more stable).'

_HINT_JSON_LD: Final = (
    'Page contains JSON-LD structured data inside <script type="application/ld+json"> — '
    'check it for clean structured fields like price, name, and datePublished.'
)

_HINT_DATA_QA: Final = 'Page uses data-qa/data-cy test attributes — they are stable selector targets.'

# ---------------------------------------------------------------------------
# User prompt templates
# ---------------------------------------------------------------------------

_USER_PROMPT: Final = 'Analyze this HTML from {url}:\n```html\n{html}\n```'

_CUSTOM_AGENT_SELECTOR_GUIDE: Final = """\
For each field provide:
- primary: Most specific selector using actual classes/IDs
- fallback: Less specific but reliable
- tertiary: Generic or null if not found"""


# ---------------------------------------------------------------------------
# Runtime deps
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryDeps:
    """Runtime context passed to all discovery system-prompt functions.

    Attributes:
        contract: The Contract class defining fields to discover
        url: Source URL for context
        target_level: Maximum selector strategy level allowed
        html: Raw HTML used for page-signal detection in hints

    """

    contract: type['Contract']
    url: str
    target_level: SelectorLevel = field(default=SelectorLevel.CSS)
    html: str = field(default='')


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
    return f'Find selectors for these fields:\n{fields_text}\n\n{_FIELD_SELECTOR_GUIDE}'


def level_instructions(ctx: RunContext['DiscoveryDeps']) -> str:
    """Explain which selector strategies are allowed based on target_level."""
    if ctx.deps.target_level >= SelectorLevel.XPATH:
        return _LEVEL_XPATH_ALLOWED
    return _LEVEL_CSS_ONLY


def page_hints(ctx: RunContext['DiscoveryDeps']) -> str:
    """Detect structural signals from the HTML and surface them as hints."""
    html = ctx.deps.html
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


def build_user_prompt(url: str, html: str) -> str:
    """Build the user prompt for the deps-based agent (system prompts handle context)."""
    return _USER_PROMPT.format(url=url, html=html)


def build_custom_agent_prompt(url: str, html: str, fields_text: str) -> str:
    """Build the user prompt for custom agents (no system-prompt injection)."""
    return (
        f'{_USER_PROMPT.format(url=url, html=html)}\n\n'
        f'Find selectors for these fields:\n{fields_text}\n\n'
        f'{_CUSTOM_AGENT_SELECTOR_GUIDE}'
    )
