"""Build stdio MCP toolsets for pydantic-ai discovery.

MCP discovery drives a *live* browser instead of reasoning over a cleaned-HTML
snapshot. The browser is the existing ``voidcrawl-mcp`` stdio server (a thin
wrapper over voidcrawl's stealth headless Chrome) — running it with no
subcommand starts the stdio MCP server, which pydantic-ai connects to as an
:class:`~pydantic_ai.mcp.MCPToolset` over a FastMCP
:class:`~fastmcp.client.transports.StdioTransport`.

We deliberately do not spin up our own MCP server (CAS-79 non-goal) and we do
not silently fall back to static discovery when the binary is missing — that is
the point of :class:`~yosoi.utils.exceptions.MCPUnavailableError`.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence

from fastmcp.client.transports import StdioTransport
from pydantic_ai.mcp import MCPToolset

from yosoi.utils.exceptions import MCPUnavailableError

#: Console-script name installed by the ``voidcrawl`` package.
VOIDCRAWL_MCP_BIN = 'voidcrawl-mcp'


def voidcrawl_command(command: str | None = None) -> str:
    """Locate the voidcrawl MCP binary, failing fast if it is missing.

    Args:
        command: Override the binary to use. Defaults to locating
            ``voidcrawl-mcp`` on ``PATH``.

    Returns:
        Absolute path (or the given override) to the voidcrawl MCP binary.

    Raises:
        MCPUnavailableError: If the binary cannot be found.

    """
    binary = command or shutil.which(VOIDCRAWL_MCP_BIN)
    if binary is None:
        raise MCPUnavailableError(
            f'{VOIDCRAWL_MCP_BIN!r} was not found on PATH. Install the voidcrawl package '
            "(`uv add voidcrawl`) or use discovery_mode='static'."
        )
    return binary


def stdio_toolset(
    command: str,
    args: Sequence[str] = (),
    *,
    env: dict[str, str] | None = None,
    id: str | None = None,
) -> MCPToolset:
    """Build a pydantic-ai ``MCPToolset`` over a stdio transport.

    This is the non-deprecated replacement for ``MCPServerStdio``: pydantic-ai
    connects to the spawned process through a FastMCP
    :class:`~fastmcp.client.transports.StdioTransport`.

    Args:
        command: Executable to launch.
        args: Command arguments.
        env: Extra environment variables for the spawned process.
        id: Stable toolset id (becomes the ``mcp__<id>__<tool>`` prefix).

    Returns:
        An :class:`~pydantic_ai.mcp.MCPToolset` ready to attach to an ``Agent``
        via ``toolsets=[...]``.

    """
    transport = StdioTransport(command=command, args=list(args), env=env)
    return MCPToolset(transport, id=id)


def voidcrawl_server(
    *,
    command: str | None = None,
    env: dict[str, str] | None = None,
    profile: str | None = None,
    headful: bool = False,
) -> MCPToolset:
    """Build an MCP toolset for the voidcrawl MCP server.

    Args:
        command: Override the binary to launch. Defaults to locating
            ``voidcrawl-mcp`` on ``PATH``.
        env: Extra environment variables for the spawned server process.
        profile: Pin the server to a warm Chrome profile (``--profile``). Useful
            for targets that fingerprint headless Chrome.
        headful: Run the pinned profile visibly (``--headful``). Only meaningful
            alongside ``profile``.

    Returns:
        A configured :class:`~pydantic_ai.mcp.MCPToolset` ready to attach to an
        ``Agent`` via ``toolsets=[...]``.

    Raises:
        MCPUnavailableError: If the voidcrawl MCP binary cannot be found. We fail
            fast rather than degrade to static discovery (see the exception's
            docstring and ``DiscoveryConfig.mcp_unavailable``).

    """
    binary = voidcrawl_command(command)

    args: list[str] = []
    if profile:
        args += ['--profile', profile]
    if headful:
        args.append('--headful')

    return stdio_toolset(binary, args, env=env, id='voidcrawl')
