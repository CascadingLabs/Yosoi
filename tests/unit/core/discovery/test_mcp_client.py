"""Tests for the voidcrawl MCP server launcher."""

import pytest
from pydantic_ai.mcp import MCPServerStdio

from yosoi.core.discovery import mcp_client
from yosoi.core.discovery.mcp_client import VOIDCRAWL_MCP_BIN, voidcrawl_server
from yosoi.utils.exceptions import MCPUnavailableError


def test_returns_stdio_server_when_binary_present(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value='/usr/bin/voidcrawl-mcp')

    server = voidcrawl_server()

    assert isinstance(server, MCPServerStdio)


def test_explicit_command_skips_path_lookup(mocker):
    which = mocker.patch.object(mcp_client.shutil, 'which')

    server = voidcrawl_server(command='/opt/voidcrawl-mcp')

    assert isinstance(server, MCPServerStdio)
    which.assert_not_called()


def test_profile_and_headful_become_args(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value='/usr/bin/voidcrawl-mcp')

    server = voidcrawl_server(profile='warm', headful=True)

    # The args land on the spawned process config.
    assert isinstance(server, MCPServerStdio)


def test_fails_fast_when_binary_missing(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value=None)

    with pytest.raises(MCPUnavailableError) as exc:
        voidcrawl_server()

    assert VOIDCRAWL_MCP_BIN in str(exc.value)
