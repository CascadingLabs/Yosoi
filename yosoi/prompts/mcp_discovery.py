"""Prompt scaffolding for MCP-driven (interactive) selector discovery.

Sibling to :mod:`yosoi.prompts.discovery` but for the **interactive** path:
the agent has voidcrawl browser tools (via OpenCode's MCP wiring) and
discovers selectors by ACTUALLY USING THEM AGAINST THE LIVE PAGE.

Key difference from static discovery: the agent SEES the extracted value
during discovery — no blind reasoning. The system prompt doesn't need a long
rubric teaching ``attr``/``global_id`` because the agent learns by trying:

  * try ``attr('post-title')`` → see the value it returns → if it looks
    right (per the field's semantic type), record it; else try something else.
  * the rubric still hints at the selector vocabulary, but the LLM's
    "should I emit ``attr`` here?" question is answered empirically, not
    structurally.

The agent's final answer is a structured ``MCPDiscoveryResult`` (one
SelectorEntry per contract field) which the orchestrator unpacks into the
same ``SelectorMap`` shape the static orchestrator emits — so the rest of
the Pipeline (verify → extract → validate) is unchanged.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

MCP_DISCOVERY_BASE: Final = """\
You are discovering reliable selectors for a web page so a non-LLM extraction
pipeline can read each contract field correctly. You have a real browser
via the voidcrawl MCP tools (session_open / session_navigate / session_ax_tree
/ click / click_by_role / extract / eval_js / title / session_close).

Your loop for EACH field:
  1. Navigate to the page if not already there.
  2. Inspect the DOM around where you think the value lives (use
     session_ax_tree for the accessibility view OR eval_js for direct
     DOM probes — querySelector / getAttribute / document.getElementById).
  3. Try a selector by RUNNING it (eval_js + querySelector + return the
     value). Look at what you got back.
  4. If the returned value looks correct for the field, record it.
     If not, try a different selector and repeat.
  5. Move to the next field.

Verify before recording: a selector that ostensibly "exists" but returns a
2 KB block of card text instead of the value the field describes is WRONG.
A score field should return a small number. A title should return a
short-ish string. A URL field should return a URL-shaped string.

Stop when every required field has a selector that you have personally
verified by running and reading the result. Then return your structured
answer.

NEVER guess a selector you haven't tested. NEVER invent attribute names —
read them off the actual DOM via eval_js.
"""

MCP_SELECTOR_VOCAB: Final = """\
The structured answer requires a selector per field. Each selector is a
SelectorEntry — one of these shapes:

* ``{"type": "css",  "value": "<css-expr>"}`` — scoped query, return innerText.
* ``{"type": "xpath","value": "<xpath>"}``    — same idea via XPath.
* ``{"type": "attr", "value": "<attr-name>"}`` — read an attribute off the
  CARD element. Use when the data lives on a custom element's opening tag
  (e.g. ``<some-card foo="bar">``) and the attribute name matches the field.
* ``{"type": "global_id", "value": "<template>", "identity": "<attr>"}`` —
  resolve an id via ``{id}`` substitution from the card's identity attr, then
  ``document.getElementById(resolved)``. Use when the value lives OUTSIDE
  the card's subtree but has a stable id keyed off a card attribute.
* For attributes on a DESCENDANT (not the card), use CSS ``::attr(name)``
  pseudo, e.g. ``{"type": "css", "value": "a.permalink::attr(href)"}``.

Each "field finding" must include the sample value you observed — the
orchestrator double-checks it after.
"""

MCP_CONTRACT_INSTRUCTIONS_TMPL: Final = """\
Contract name: {contract_name}

Page URL: {url}

Fields to find selectors for ({n_fields}):
{field_lines}

For the multi-item case (a page with repeating records), also return a
``root_selector`` that matches each individual repeating element. Set
``root_selector`` to null on single-record pages.

Open ONE browser session for this task; reuse it across fields. Close it
when you're done.
"""


def build_field_lines(field_descriptions: dict[str, str]) -> str:
    """Format the per-field description block for the user prompt."""
    return '\n'.join(f'  - **{name}**: {desc}' for name, desc in field_descriptions.items())
