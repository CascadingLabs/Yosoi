"""Prompt + runtime deps for MCP-driven (live-browser) selector discovery.

Static discovery needs a four-part rubric (base / field / level / page-hints)
because the LLM reasons *blind* over a cleaned-HTML string and we catch mistakes
after the fact. MCP discovery collapses that rubric: the agent drives a live
browser via the voidcrawl MCP toolset, tries selectors against the real DOM,
*sees* what each one extracts, and calls the ``check_value`` tool to confirm a
value matches its field before recording it. It learns by trying, so the prompt
only has to describe the loop — not teach selector taste.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from yosoi.core.verification.semantic import SemanticValidator
from yosoi.types.registry import SemanticRule

_INSTRUCTIONS = """\
You discover resilient web-scraping selectors by driving a real browser.

You have voidcrawl MCP tools: open a session, navigate to the target URL, and
inspect the live page (session_ax_tree for a cheap role/name outline; eval_js or
extract to read actual values). Prefer the accessibility tree over dumping raw
HTML.

For EACH requested field:
  1. Locate the element on the live page.
  2. Try a selector and read back the value it extracts (eval_js / extract).
  3. Call the `check_value` tool with the field name and the extracted value.
     If it returns anything other than "ok", your selector grabbed the wrong
     thing — try a different one until it passes.
  4. Record the selector that worked and the exact value you observed.

Selector preferences (in order): a stable attribute (`attr`) or test id, a tight
CSS selector, then XPath. For a value held in an attribute, use a CSS
`::attr(name)` pseudo-element. Only record selectors you actually verified
against the live DOM — never guess.

If the page shows a repeating list of items, also record a `root` selector for
the wrapper element of ONE item, and scope every field selector to within it.

Record the navigation (and any clicks/scrolls you needed to reveal the data) as
the replay_plan so later runs can reproduce the page state without an LLM.

Always close the session when finished. Return the structured draft.
"""


@dataclass
class MCPDiscoveryDeps:
    """Runtime context for the MCP discovery agent.

    Attributes:
        url: Target page URL the agent should drive.
        fields: Field name -> human-readable description to discover.
        field_rules: Field name -> semantic rule, used by the ``check_value``
            tool to validate observed values in real time.
        validator: Shared semantic validator instance.

    """

    url: str
    fields: Mapping[str, str]
    field_rules: Mapping[str, SemanticRule]
    validator: SemanticValidator


def mcp_discovery_instructions() -> str:
    """Static system prompt for the MCP discovery agent."""
    return _INSTRUCTIONS


def build_mcp_user_prompt(url: str, fields: Mapping[str, str]) -> str:
    """Build the per-run task prompt naming the URL and fields to discover."""
    field_lines = '\n'.join(f'- {name}: {desc}' for name, desc in fields.items())
    return (
        f'Discover selectors on this page: {url}\n\n'
        f'Fields to extract:\n{field_lines}\n\n'
        'Drive the live page, verify each value with check_value, and return the draft.'
    )
