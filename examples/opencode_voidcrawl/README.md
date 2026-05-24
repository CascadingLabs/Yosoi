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

## Tickets (followed loosely)

CAS-28 / CAS-30 (OpenCode as a pydantic-ai Model) · CAS-43 (voidcrawl MCP) ·
CAS-27 (AX-tree selectors) · CAS-13 (A3Node replay).
