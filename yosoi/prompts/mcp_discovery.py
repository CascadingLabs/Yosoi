"""Prompt + runtime deps for MCP-driven (live-browser) selector discovery.

Static discovery needs a four-part rubric (base / field / level / page-hints)
because the LLM reasons *blind* over a cleaned-HTML string and we catch mistakes
after the fact. MCP discovery collapses that rubric: the agent drives a live
browser via the voidcrawl MCP toolset, tries selectors against the real DOM, and
*sees* what each one extracts.

Latency note: each MCP tool call is a serialized model round-trip, and the loop
(not startup) dominates discovery latency. So the prompt pushes the agent to
*batch* — perceive the page once, verify all candidate selectors in a single
``eval_js``, and only spot-check suspect values — rather than probe one field at
a time.
"""

from __future__ import annotations

from collections.abc import Mapping

_INSTRUCTIONS = """\
You discover resilient web-scraping selectors by driving a real browser. Each
tool call is a slow round-trip, so do the WHOLE job in as few calls as possible —
do NOT probe one field at a time.

Efficient loop (aim for ~3-4 tool calls total, not one-per-field):
  1. session_open, then session_navigate to the target URL.
  2. Perceive the page ONCE: a single session_ax_tree (cheap role/name outline)
     or one eval_js that returns the relevant markup. Don't re-snapshot per field.
  3. Reason about ALL fields at once, then verify them in ONE batched eval_js:
     evaluate every candidate selector in a single script and return an object
     mapping field -> the value it extracts. Read the whole result back at once.
  4. For any value that looks wrong for its field, call `check_value(field,
     value)`; if it returns anything but "ok", fix just that selector (ideally in
     the same batched re-eval) — don't restart the whole loop.
  5. session_close and return the structured draft.

Selector preferences (in order): a stable attribute (`attr`) or test id, a tight
CSS selector, then XPath. For a value held in an attribute, use a CSS
`::attr(name)` pseudo-element. Only record selectors you actually verified
against the live DOM in step 3 — never guess.

If the page shows a repeating list of items, also record a `root` selector for
the wrapper element of ONE item, and scope every field selector within it.
"""


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
