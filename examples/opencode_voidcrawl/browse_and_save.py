"""OpenCode agent driving the voidcrawl MCP — with full observability + selector capture.

Ties together several Yosoi threads (tickets followed loosely, not modified):
  * CAS-28 / CAS-30 — OpenCode wrapped as a pydantic-ai Model (`OpenCodeModel`).
  * CAS-43 — the voidcrawl MCP server (agent-facing stealth browser).
  * CAS-27 — AX-tree selectors (the agent's click_by_role targets, see recipe.py).
  * CAS-13 — A3Node replay (we save what worked; recipe.py shows the promotion path).

How it fits together:
  OpenCode owns the agent loop. voidcrawl is wired in via this directory's
  opencode.json `mcp` block, so OpenCode calls the browser tools itself — we run
  `OpenCodeModel(enable_tools=True)` to hand it the loop (default suppresses tools).
  We then bridge the gap that pydantic-ai alone can't see:

    [tools]  what the agent called (live, from OpenCode's /event stream)
    [usage]  per-step + total token/cost — OpenCode's numbers tied to the
             pydantic-ai RequestUsage that lands in Langfuse
    [recipe] the successful clicks distilled into replayable selectors, saved

Run (spawns its own opencode serve + voidcrawl-mcp; needs `opencode auth login`
and `voidcrawl-mcp` on PATH):

    uv run python examples/opencode_voidcrawl/browse_and_save.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))  # recipe
sys.path.insert(0, str(HERE.parent))  # opencode_server

from dotenv import load_dotenv
from opencode_server import ensure_opencode_server
from pydantic_ai import Agent
from recipe import acts_from_tool_parts

from yosoi.integrations.opencode import OpenCodeModel

load_dotenv()

START_URL = 'https://example.com'
TASK = (
    f'Use the browser tools to open {START_URL} in a session, then click the '
    "'More information...' link, and tell me the <title> of the page you land on. "
    'Report the final title only.'
)


def _fmt_tokens(tok: dict[str, object]) -> str:
    raw = tok.get('cache')
    cache: dict[str, object] = raw if isinstance(raw, dict) else {}
    return (
        f'in={tok.get("input", 0)} out={tok.get("output", 0)} '
        f'reason={tok.get("reasoning", 0)} '
        f'cache_r={cache.get("read", 0)} cache_w={cache.get("write", 0)}'
    )


async def _stream_events(base_url: str, stop: asyncio.Event, collected: list[dict[str, Any]]) -> None:
    """Tail OpenCode's /event SSE stream and surface the agent loop, categorised.

    Bridges OpenCode's internal loop (tools + per-step usage) up to the console —
    the part pydantic-ai never sees because OpenCode runs tools server-side. This
    is also where we capture tool parts for the recipe: the final message returned
    to pydantic-ai holds only the last step's parts, but the stream sees them all.
    """
    seen: set[tuple[str, str]] = set()
    reasoned: set[str] = set()
    try:
        async with (
            httpx.AsyncClient(base_url=base_url, timeout=None) as client,
            client.stream('GET', '/event') as resp,
        ):
            async for line in resp.aiter_lines():
                if stop.is_set():
                    return
                if not line.startswith('data:'):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if evt.get('type') == 'message.part.updated':
                    _handle_part((evt.get('properties') or {}).get('part') or {}, seen, reasoned, collected)
    except (httpx.HTTPError, asyncio.CancelledError):
        return


def _handle_part(
    part: dict[str, Any],
    seen: set[tuple[str, str]],
    reasoned: set[str],
    collected: list[dict[str, Any]],
) -> None:
    """Log one part (tool / step-finish / reasoning); collect completed tool parts."""
    kind = part.get('type')
    if kind == 'tool':
        state = part.get('state') or {}
        status = state.get('status', '')
        key = (part.get('callID', ''), status)
        if status in ('running', 'completed', 'error') and key not in seen:
            seen.add(key)
            _log_tool(part.get('tool', '?'), state)
            if status == 'completed':
                collected.append(part)  # source of truth for the recipe
    elif kind == 'step-finish':
        print(f'  [usage] step  {_fmt_tokens(part.get("tokens") or {})}  cost=${part.get("cost", 0):.4f}', flush=True)
    elif kind == 'reasoning':
        pid, text = part.get('id', ''), (part.get('text') or '').strip()
        if text and pid not in reasoned:
            reasoned.add(pid)
            print(f'  [reason] {text[:100]}', flush=True)


def _log_tool(tool: str, state: dict[str, object]) -> None:
    status = state.get('status')
    inp = state.get('input') or {}
    icon = '🖱️ ' if 'click' in tool else ('🌐' if any(k in tool for k in ('fetch', 'navigate', 'session')) else '🔧')
    line = f'  [tool] {icon} [{status}] {tool}  {json.dumps(inp, ensure_ascii=False)[:130]}'  # type: ignore[arg-type]
    if status == 'completed':
        t = state.get('time') or {}
        ms = (t.get('end', 0) - t.get('start', 0)) if isinstance(t, dict) else 0
        out = str(state.get('output') or '').replace('\n', ' ')[:80]
        line += f'  ->[{ms}ms] {out}'
    elif status == 'error':
        line += f'  ->ERROR {str(state.get("error"))[:80]}'
    print(line, flush=True)


async def _list_enabled_tools(base_url: str) -> None:
    """Prove enable_tools is on. NB: /experimental/tool/ids lists *built-in* tools;
    MCP tools (voidcrawl) attach per session, so they show up in the [tool] log below
    rather than here.
    """
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
            r = await client.get('/experimental/tool/ids')
            r.raise_for_status()
            ids = r.json()
    except (httpx.HTTPError, ValueError):
        return
    ids = ids if isinstance(ids, list) else []
    print(
        f'  [cfg] enable_tools=True; {len(ids)} built-in tools live + voidcrawl MCP (per-session; see [tool] lines)',
        flush=True,
    )


async def main() -> None:
    async with ensure_opencode_server(cwd=str(HERE)):
        base_url = os.environ['OPENCODE_BASE_URL']
        model = OpenCodeModel(
            provider_id=os.getenv('OC_PROVIDER', 'openai'),
            model_id=os.getenv('OC_MODEL', 'gpt-5.3-codex'),
            enable_tools=True,  # hand the loop to OpenCode so it can call voidcrawl
        )
        agent = Agent(
            model,
            system_prompt=(
                'You are a web automation agent with voidcrawl browser tools (fetch, '
                'session_open, session_navigate, session_ax_tree, click, click_by_role, '
                'title, session_close, ...). Actually browse — do not guess. Open a '
                'session, navigate, act, then close it.'
            ),
        )

        print(f'=== OpenCode + voidcrawl browse (model={model.model_name}) ===', flush=True)
        await _list_enabled_tools(base_url)

        stop = asyncio.Event()
        tool_parts: list[dict[str, Any]] = []  # filled by the event stream — all steps, not just the last
        events = asyncio.create_task(_stream_events(base_url, stop, tool_parts))
        try:
            result = await agent.run(TASK)
            await asyncio.sleep(0.5)  # let the SSE stream drain trailing tool events
        finally:
            stop.set()
            events.cancel()

        # --- bridge: OpenCode's accounting <-> pydantic-ai's RequestUsage ---
        print('\n=== usage bridge ===', flush=True)
        print(
            f'  [opencode] tokens {_fmt_tokens(model.last_info.get("tokens") or {})} '
            f'cost=${model.last_info.get("cost", 0):.4f}',
            flush=True,
        )
        print(f'  [pydantic-ai] {result.usage()}', flush=True)

        # --- selector / A3-node capture from what the agent actually did ---
        recipe = acts_from_tool_parts(tool_parts, START_URL)
        recipe.model = model.model_name
        path = recipe.save(storage_dir=str(HERE / '.yosoi' / 'browse_recipes'))
        print('\n=== saved selectors ===', flush=True)
        for s in recipe.selectors:
            print(
                f'  - {s.type}: role={s.role!r} name={s.value!r}' if s.type == 'role' else f'  - {s.type}: {s.value}',
                flush=True,
            )
        print(f'  recipe -> {path}', flush=True)
        print(f'  A3Node acts (promotion preview): {recipe.to_a3node_acts()}', flush=True)

        print('\n=== FINAL ANSWER ===', flush=True)
        print(result.output, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
