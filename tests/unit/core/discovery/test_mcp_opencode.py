"""Tests for the OpenCode MCP backend and its subprocess/HTTP wiring."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_backends import StdioServerSpec
from yosoi.core.discovery.mcp_opencode import OpenCodeBackend, _split_model, _voidcrawl_mcp_config
from yosoi.utils.exceptions import LLMGenerationError


class _Reader:
    def __init__(self, lines: list[bytes]):
        self._lines = iter(lines)

    async def readline(self) -> bytes:
        return next(self._lines, b'')


def _build_proc(url_line: bytes) -> SimpleNamespace:
    async def _wait() -> int:
        return 0

    return SimpleNamespace(
        returncode=None,
        stdout=_Reader([url_line]),
        terminate=lambda: None,
        kill=lambda: None,
        wait=_wait,
    )


@pytest.fixture(autouse=True)
def _stub_voidcrawl_command(mocker):
    _voidcrawl_mcp_config.cache_clear()
    mocker.patch('yosoi.core.discovery.mcp_opencode.voidcrawl_command', return_value='voidcrawl-mcp')
    yield
    _voidcrawl_mcp_config.cache_clear()


def test_split_model_supports_provider_prefix():
    assert _split_model('openai/gpt-5-codex') == ('openai', 'gpt-5-codex')
    assert _split_model('gpt-5-codex') == ('openai', 'gpt-5-codex')


def test_build_config_includes_validator_server_when_present():
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))
    cfg = backend._build_config(
        StdioServerSpec(
            name='yosoi_validator',
            command='validator-binary',
            args=('--serve',),
            env={'X': '1'},
        )
    )

    validator = cfg['mcp']['yosoi_validator']
    assert validator['command'] == ['validator-binary', '--serve']
    assert validator['environment'] == {'X': '1'}
    assert validator['enabled'] is True


async def test_read_url_parses_listening_url_and_raises_on_eof():
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))
    proc = SimpleNamespace(stdout=_Reader([b'booting\n', b'listening on http://127.0.0.1:4096\n']))
    assert await backend._read_url(proc) == 'http://127.0.0.1:4096'

    proc_eof = SimpleNamespace(stdout=_Reader([]))
    with pytest.raises(RuntimeError):
        await backend._read_url(proc_eof)


async def test_read_url_requires_stdout():
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))
    proc = SimpleNamespace(stdout=None)
    with pytest.raises(RuntimeError):
        await backend._read_url(proc)


async def test_discover_parses_structured_and_non_structured_payloads(monkeypatch):
    class _Response:
        def __init__(self, payload: object):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    async def _run(structured: object) -> object | None:
        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, path: str, json=None):
                if path == '/session':
                    return _Response({'id': 'session-1'})
                return _Response({'info': {'structured': structured}})

        monkeypatch.setitem(sys.modules, 'httpx', SimpleNamespace(AsyncClient=_Client))
        backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))
        return await backend._discover('http://127.0.0.1:4096', 'system', 'prompt')

    assert await _run({'fields': []}) == {'fields': []}
    assert await _run([]) is None


async def test_run_success_happy_path(mocker):
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))

    async def _create_subprocess(*_args, **_kwargs):
        return _build_proc(b'listening on http://127.0.0.1:4096\n')

    mocker.patch('yosoi.core.discovery.mcp_opencode.asyncio.create_subprocess_exec', side_effect=_create_subprocess)
    mocker.patch.object(backend, '_discover', mocker.AsyncMock(return_value={'fields': []}))

    await backend.run(instructions='i', user_prompt='p', servers=[])


async def test_run_raises_on_missing_structured_payload(mocker):
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))

    async def _create_subprocess(*_args, **_kwargs):
        return _build_proc(b'listening on http://127.0.0.1:4096\n')

    mocker.patch('yosoi.core.discovery.mcp_opencode.asyncio.create_subprocess_exec', side_effect=_create_subprocess)
    mocker.patch.object(backend, '_discover', mocker.AsyncMock(return_value=None))

    with pytest.raises(LLMGenerationError):
        await backend.run(instructions='i', user_prompt='p', servers=[])


async def test_run_raises_when_binary_missing(mocker):
    backend = OpenCodeBackend(LLMConfig(provider='opencode', model_name='gpt-5-codex'))

    async def _missing_binary(*_args, **_kwargs):
        raise FileNotFoundError('missing')

    mocker.patch('yosoi.core.discovery.mcp_opencode.asyncio.create_subprocess_exec', side_effect=_missing_binary)

    with pytest.raises(LLMGenerationError):
        await backend.run(instructions='i', user_prompt='p', servers=[])
