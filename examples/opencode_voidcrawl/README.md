# OpenCode agent × voidcrawl MCP — observable browse + selector capture

An OpenCode (Codex) agent that drives the **voidcrawl** MCP browser, logs the
whole loop (tools, per-step + total token/cost), and saves the clicks it landed
as replayable selectors.

## Why it's shaped this way

OpenCode is an agent, not a raw model — it owns its own tool loop and loads MCP
servers from its project config. So voidcrawl is wired in through this directory's
[`opencode.json`](./opencode.json) `mcp` block, and we run the pydantic-ai model
with `OpenCodeModel(enable_tools=True)` to hand it the loop. (The default,
`enable_tools=False`, suppresses tools so the model is a pure selector-discovery
extractor — that path is unchanged.)

pydantic-ai alone only sees the final text + usage. This example **bridges the gap**
by tailing OpenCode's `/event` stream:

- `[cfg]`    — proves `enable_tools` by listing the live tools (incl. voidcrawl)
- `[tool]`   — every tool call as it runs (the click log), with timing
- `[usage]`  — per-step tokens/cost from OpenCode, plus a final reconciliation
               against the pydantic-ai `RequestUsage` that lands in Langfuse
- `[recipe]` — successful clicks distilled into selectors and saved per-domain

## Selectors & A3 nodes

Successful tool calls become an ordered recipe in
`.yosoi/browse_recipes/recipe_<domain>.json`. `click_by_role` becomes an
**accessibility-tree selector** (`type: role`, role+name) — the AX-tree selector
extension tracked in **CAS-27**. Errored clicks are skipped, mirroring A3Node's
"save what worked" (**CAS-13**); `recipe.to_a3node_acts()` shows the promotion path
onto the existing `{kind, cycles}` A3Node schema.

## Run

```sh
opencode auth login              # one-time, pick OpenAI/Codex
uv tool install voidcrawl-mcp    # binary on PATH (0.3.1+ ships it separately)
uv run python examples/opencode_voidcrawl/browse_and_save.py
```

Override the model with `OC_MODEL` (default `gpt-5.3-codex`). Set
`OPENCODE_BASE_URL` to attach to an existing server instead of spawning one —
but then ensure *that* server was launched from a dir whose `opencode.json` wires
voidcrawl.

## `maps_teleport.py` — geolocation teleport, scripted PyO3 + AX-tree selectors

The same query ("guitar shops near me") run in three cities where the city is set
**only** by teleporting the browser's geolocation (CAS-45). The fixed
teleport→navigate→scroll recipe runs in-script over the **PyO3 binding** (no LLM in
the browsing loop), and extraction uses **accessibility-tree selectors** (`ax_extract.py`,
CAS-27) instead of CSS.

Why AX over CSS here: each result is `role="article"` with the shop name as its
accessible name, and the rating is a descendant `role="image"` named
`"4.4 stars 2,980 Reviews"`. Those roles + names are stable and human-readable, where
Maps' obfuscated classes (`a.hfpxzc`, `MW4etd`) churn. Because the AX semantics are
clear, **no LLM discovery is needed at all** — the AX selector is a tiny readable
recipe (`AxField('rating', role='image', pattern=r'([\d.]+)\s*stars')`). For a site
with murkier semantics, the same recipe could be discovered once from the compact AX
*outline* (cheaper to read than HTML) — the discover-once path, on AX.

Two things the script gets right that are easy to miss:
- **Fresh `BrowserSession` per city.** A recycled pool tab keeps the prior page's
  resolved location, so cities bleed together. Teleport docs require a fresh session.
- **"near me" query.** Maps only consults `navigator.geolocation` (what teleport
  overrides) for "near me"; a plain query centers on the IP-based viewport.

```sh
uv run python examples/opencode_voidcrawl/maps_teleport.py
# New York   : Guitar Center (4.4★, 2980) 25 W 14th St · Rudy's Music Soho (4.6) 461 Broome St
# Los Angeles: International House of Music (4.2) 821 South Los Angeles Street
# Chicago    : Guitar Center (4.4, 1551) 2633 North Halsted Street
```

Needs `voidcrawl>=0.3.2` (teleport landed in the 0.3.x PyO3 binding; 0.2.3 has no
`set_geolocation`). No OpenCode/MCP server needed — this path uses the library directly.

## Tickets (followed loosely)

CAS-28 / CAS-30 (OpenCode as a pydantic-ai Model) · CAS-43 (voidcrawl MCP) ·
CAS-45 (teleport / emulation) · CAS-27 (AX-tree selectors) · CAS-13 (A3Node replay).
