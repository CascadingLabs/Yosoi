"""Measure warm-vs-cold startup costs of the MCP-discovery SDK backends.

None of this involves an LLM, so it isolates exactly what *warming* (reusing a
persistent runtime + a keep-alive MCP subprocess + a warm Chrome pool) saves per
discovery. The dominant cost is launching Chrome inside voidcrawl-mcp; the rest
is agent-runtime startup (opencode serve / Claude SDK client).

Run: uv run python experiments/mcp_warm_vs_cold.py
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import suppress

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from yosoi.core.discovery.mcp_client import voidcrawl_command

_LISTEN_RE = re.compile(r'listening on (http://\S+)')
_ENV = {'CHROME_HEADLESS': '1', 'BROWSER_COUNT': '1', 'TABS_PER_BROWSER': '5'}
_URL = 'https://news.ycombinator.com/'


async def _cycle(transport: StdioTransport) -> tuple[float, float]:
    """One connect→open→navigate→disconnect cycle. Returns (connect_s, navigate_s)."""
    client = Client(transport)
    t0 = time.monotonic()
    await client.__aenter__()  # connect: spawn process + Chrome (cold) or reuse (warm)
    connect_s = time.monotonic() - t0
    t1 = time.monotonic()
    res = await client.call_tool('session_open', {})
    data = res.data
    sid = data['session_id'] if isinstance(data, dict) else data.session_id
    await client.call_tool('session_navigate', {'session_id': sid, 'url': _URL})
    navigate_s = time.monotonic() - t1
    with suppress(Exception):
        await client.call_tool('session_close', {'session_id': sid})
    await client.__aexit__(None, None, None)
    return connect_s, navigate_s


async def measure_voidcrawl() -> None:
    print('\n[voidcrawl-mcp] connect (spawn+Chrome) vs navigate — cold spawn vs keep-alive reuse')

    print('  -- no keep_alive (fresh subprocess + Chrome each cycle = today) --')
    for i in (1, 2):
        transport = StdioTransport(command=voidcrawl_command(), args=[], env=_ENV, keep_alive=False)
        connect_s, navigate_s = await _cycle(transport)
        print(f'     cycle {i}: connect={connect_s:6.2f}s  navigate={navigate_s:6.2f}s')

    print('  -- keep_alive=True (one transport, subprocess + Chrome persist) --')
    transport = StdioTransport(command=voidcrawl_command(), args=[], env=_ENV, keep_alive=True)
    connects: list[float] = []
    for i in (1, 2, 3):
        connect_s, navigate_s = await _cycle(transport)
        tag = 'COLD' if i == 1 else 'WARM'
        print(f'     cycle {i} ({tag}): connect={connect_s:6.2f}s  navigate={navigate_s:6.2f}s')
        connects.append(connect_s)
    with suppress(Exception):
        await transport.close()
    if len(connects) >= 2:
        print(f'  => keep_alive connect saving after first: ~{connects[0] - connects[-1]:5.2f}s')


async def measure_opencode_serve() -> None:
    print('\n[opencode serve] cold start (spawn -> listening) — paid once if warm, per-run if not')
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        'opencode',
        'serve',
        '--port',
        '0',
        '--hostname',
        '127.0.0.1',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                break
            if _LISTEN_RE.search(line.decode(errors='replace')):
                print(f'     serve listening: {time.monotonic() - t0:6.2f}s')
                break
    finally:
        proc.terminate()
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5)


async def measure_claude_connect() -> None:
    print('\n[claude-sdk] ClaudeSDKClient.connect (CLI + MCP + Chrome) — paid once if warm, per-run if not')
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    except Exception as e:
        print('     (claude_agent_sdk unavailable):', e)
        return
    options = ClaudeAgentOptions(
        model='claude-opus-4-7',
        mcp_servers={'voidcrawl': {'type': 'stdio', 'command': voidcrawl_command(), 'args': [], 'env': _ENV}},
        allowed_tools=['mcp__voidcrawl__session_open'],
        permission_mode='bypassPermissions',
    )
    client = ClaudeSDKClient(options=options)
    t0 = time.monotonic()
    await client.connect()
    print(f'     connected: {time.monotonic() - t0:6.2f}s')
    with suppress(Exception):
        await client.disconnect()


async def main() -> None:
    await measure_voidcrawl()
    await measure_opencode_serve()
    await measure_claude_connect()


if __name__ == '__main__':
    asyncio.run(main())
