"""Launch the voidcrawl MCP server as a pydantic-ai toolset.

MCP discovery drives a *live* browser instead of reasoning over a cleaned-HTML
snapshot. The browser is the existing ``voidcrawl-mcp`` stdio server (a thin
wrapper over voidcrawl's stealth headless Chrome) — running it with no
subcommand starts the stdio MCP server, which pydantic-ai connects to as an
:class:`~pydantic_ai.mcp.MCPServerStdio` toolset.

We deliberately do not spin up our own MCP server (CAS-79 non-goal) and we do
not silently fall back to static discovery when the binary is missing — that is
the point of :class:`~yosoi.utils.exceptions.MCPUnavailableError`.
"""

from __future__ import annotations

import shutil

from pydantic_ai.mcp import MCPServerStdio

from yosoi.utils.exceptions import MCPUnavailableError

#: Console-script name installed by the ``voidcrawl`` package.
VOIDCRAWL_MCP_BIN = 'voidcrawl-mcp'


def voidcrawl_server(
    *,
    command: str | None = None,
    env: dict[str, str] | None = None,
    profile: str | None = None,
    headful: bool = False,
) -> MCPServerStdio:
    """Build an ``MCPServerStdio`` toolset for the voidcrawl MCP server.

    Args:
        command: Override the binary to launch. Defaults to locating
            ``voidcrawl-mcp`` on ``PATH``.
        env: Extra environment variables for the spawned server process.
        profile: Pin the server to a warm Chrome profile (``--profile``). Useful
            for targets that fingerprint headless Chrome.
        headful: Run the pinned profile visibly (``--headful``). Only meaningful
            alongside ``profile``.

    Returns:
        A configured :class:`~pydantic_ai.mcp.MCPServerStdio` ready to attach to
        an ``Agent`` via ``toolsets=[...]``.

    Raises:
        MCPUnavailableError: If the voidcrawl MCP binary cannot be found. We fail
            fast rather than degrade to static discovery (see the exception's
            docstring and ``DiscoveryConfig.mcp_unavailable``).

    """
    binary = command or shutil.which(VOIDCRAWL_MCP_BIN)
    if binary is None:
        raise MCPUnavailableError(
            f'{VOIDCRAWL_MCP_BIN!r} was not found on PATH. Install the voidcrawl package '
            "(`uv add voidcrawl`) or use discovery_mode='static'."
        )

    args: list[str] = []
    if profile:
        args += ['--profile', profile]
    if headful:
        args.append('--headful')

    # FUTURE: MCPServerStdio is deprecated for removal in pydantic-ai v2 in favor
    # of MCPToolset(StdioTransport(...)), which currently requires the optional
    # `fastmcp` dependency. Migrate here when we take that dep or pin past v2.
    return MCPServerStdio(binary, args=args, env=env)
