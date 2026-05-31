"""Tests for the voidcrawl MCP toolset builder."""

import pytest
from pydantic_ai.mcp import MCPToolset

from yosoi.core.discovery import mcp_client
from yosoi.core.discovery.mcp_client import VOIDCRAWL_MCP_BIN, stdio_toolset, voidcrawl_server
from yosoi.utils.exceptions import MCPUnavailableError


def test_stdio_toolset_builds_mcp_toolset():
    toolset = stdio_toolset('some-cmd', ['--flag'], env={'A': 'B'}, id='thing')

    assert isinstance(toolset, MCPToolset)
    assert toolset.id == 'thing'


def test_returns_toolset_when_binary_present(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value='/usr/bin/voidcrawl-mcp')

    server = voidcrawl_server()

    assert isinstance(server, MCPToolset)
    assert server.id == 'voidcrawl'


def test_explicit_command_skips_path_lookup(mocker):
    which = mocker.patch.object(mcp_client.shutil, 'which')

    server = voidcrawl_server(command='/opt/voidcrawl-mcp')

    assert isinstance(server, MCPToolset)
    which.assert_not_called()


def test_profile_and_headful_build_toolset(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value='/usr/bin/voidcrawl-mcp')

    server = voidcrawl_server(profile='warm', headful=True)

    assert isinstance(server, MCPToolset)


def test_fails_fast_when_binary_missing(mocker):
    mocker.patch.object(mcp_client.shutil, 'which', return_value=None)

    with pytest.raises(MCPUnavailableError) as exc:
        voidcrawl_server()

    assert VOIDCRAWL_MCP_BIN in str(exc.value)
