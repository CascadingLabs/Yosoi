# Subscription-backed discovery: OpenCode vs. Claude Agent SDK

Most Yosoi providers (groq, gemini, openai, …) are function-calling APIs billed
per token via an API key. Two providers are different: **OpenCode** and the
**Claude Agent SDK** run their own native MCP tool loop against a local
subscription-backed CLI instead of a metered API, so no `*_API_KEY` is
required (see `NO_API_KEY_REQUIRED_PROVIDERS` in
`yosoi/core/discovery/config.py`).

## OpenCode is the default subscription backend

`ys.opencode()` is the supported, first-class way to do subscription-backed
selector/agent discovery:

```python
import yosoi as ys

config = ys.opencode('openai/gpt-5.3-codex-spark')  # or YOSOI_MODEL=opencode:openai/gpt-5.3-codex-spark
```

If you explicitly opt an agent-driven discovery run into MCP mode
(`ys.Policy(discovery=ys.DiscoveryPolicy(mode='mcp'))`, or
`YOSOI_DISCOVERY_MODE=mcp`) and configure **no model at all** — no
`YOSOI_MODEL`, no API key for any of the function-calling fallback providers —
Policy resolution defaults to OpenCode. It never falls back to Claude, and it
never silently guesses in any other discovery mode: without `mode='mcp'`,
missing configuration still fails fast with an actionable error, per Yosoi's
no-fallback-heuristics rule (see `AGENTS.md`).

If the OpenCode server is unreachable, discovery fails with a clear
`ModuleNotFoundError`/connection error from `OpenCodeModel.preflight()` — it
does not silently retry against Claude.

## Claude Agent SDK is opt-in — both in config and at install time

Claude now limits usage credits more aggressively, so the Claude Agent SDK is
never selected automatically. Two explicit opt-ins are required to use it:

1. **Explicit provider selection** — call `ys.claude_sdk('claude-opus-4-7')`,
   or set `provider='claude-sdk'` / `YOSOI_MODEL=claude-sdk:...` yourself.
   There is no code path that reaches this provider without you naming it.
2. **Explicit install** — the `claude-agent-sdk` package is a large, optional
   dependency (`yosoi[claude-sdk]`), not part of the base install:

   ```bash
   uv add 'yosoi[claude-sdk]'
   # or: pip install 'yosoi[claude-sdk]'
   ```

   Selecting `claude-sdk` without installing the extra raises an actionable
   `ModuleNotFoundError` pointing at the install command above — it does not
   silently fall back to OpenCode or any other provider.

## Migration

If you were previously relying on Claude SDK for subscription-backed
discovery (explicitly, via `ys.claude_sdk()` / `provider='claude-sdk'`), that
continues to work unchanged as long as the `claude-sdk` extra is installed.
Switching to the new default is a one-line change:

```python
# Before
config = ys.claude_sdk('claude-opus-4-7')

# After — no install extra needed, no usage credits consumed
config = ys.opencode('openai/gpt-5.3-codex-spark')
```
