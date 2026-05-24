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

## `maps_teleport.py` — canonical ReplayPlan, executed + verified, no LLM

The same query ("guitar shops near me") run in three cities where the city is set
**only** by teleporting the browser's geolocation (CAS-45). The flow is the canonical
**ReplayPlan** (`yosoi.models.replay`, CAS-13/27): a sequence of A3Node parts
(`teleport → navigate ×2 → scroll-until`) built from reusable helpers, then **executed
and verified by rerun** (`replay_runtime`) — each node's `assert` is checked, giving a
`VerifyReport` quality score. Extraction uses **AX role+name selectors**
(`yosoi.core.fetcher.dom.ax.extract_records`). Zero LLM at runtime.

The same plan an MCP agent emits (`replay_runtime.plan_from_tool_parts`, fed by the
hybrid capture in `browse_and_save.py`) is what runs here — agent discovers once, the
plan is locked in, PyO3 replays forever.

**Settling is event-driven** (the A3 "Assess"): a node waits until its precondition
holds (feed present = prior step loaded), terminal on timeout — the SPA's network never
idles, so readiness is gated on structure. The one exception is `navigate`: Maps resolves
the teleported geolocation with **no DOM signal**, so a fixed dwell is the deliberate
small-sleep fallback for when structure can't observe readiness.

```sh
uv run python examples/opencode_voidcrawl/maps_teleport.py
# New York: Moe's Guitars (5.0) · Los Angeles: International House of Music · Chicago: Reckless Records
# each: 20 shops, verify 100%
```

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
