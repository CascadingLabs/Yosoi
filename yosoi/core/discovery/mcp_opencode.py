"""OpenCode MCP discovery backend — let a local OpenCode server run the tool loop.

OpenCode configures MCP servers at *server start*, not per request, so this
backend spawns a dedicated ``opencode serve`` whose project config registers both
the voidcrawl browser and the shared ``yosoi-validator`` server (with the
contract's field rules baked into the validator's environment). The OpenCode
agent then drives the browser natively and returns structured output, which we
parse into the same :class:`~yosoi.core.discovery.mcp_draft.MCPDiscoveryDraft`
every other backend produces.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import tempfile
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_backends import StdioServerSpec
from yosoi.core.discovery.mcp_client import (
    VOIDCRAWL_MCP_BIN,
    MCPUnavailableError,
    voidcrawl_command,
)
from yosoi.core.discovery.mcp_draft import MCPDiscoveryDraft
from yosoi.utils import observability as obs
from yosoi.utils.exceptions import LLMGenerationError

logger = logging.getLogger(__name__)

_LISTEN_RE = re.compile(r'listening on (http://\S+)')
_USER_CONFIG = Path.home() / '.config' / 'opencode' / 'opencode.json'


def _split_model(model_name: str) -> tuple[str, str]:
    """Split an OpenCode model id into (providerID, modelID)."""
    if '/' in model_name:
        provider_id, model_id = model_name.split('/', 1)
        return provider_id, model_id
    return 'openai', model_name


@lru_cache(maxsize=1)
def _voidcrawl_mcp_config() -> dict[str, object]:
    """Reuse the user's voidcrawl OpenCode config if present, else build a default."""
    with contextlib.suppress(OSError, json.JSONDecodeError, ValueError):
        data = json.loads(_USER_CONFIG.read_text())
        mcp = data.get('mcp', {})
        voidcrawl = mcp.get('voidcrawl') if isinstance(mcp, dict) else None
        if isinstance(voidcrawl, dict):
            return dict(voidcrawl)
    with contextlib.suppress(MCPUnavailableError):
        return {'type': 'local', 'command': [voidcrawl_command()], 'enabled': True}
    logger.warning('voidcrawl-mcp was not found on PATH; disabling default browser MCP entry for this run')
    return {'type': 'local', 'command': [VOIDCRAWL_MCP_BIN], 'enabled': False}


class OpenCodeBackend:
    """Drives discovery through a dedicated OpenCode server's native MCP loop."""

    name = 'opencode'

    def __init__(self, llm_config: LLMConfig, *, startup_timeout: float = 30.0):
        """Initialise from an ``opencode:<model>`` LLM config."""
        self._provider_id, self._model_id = _split_model(llm_config.model_name)
        self._startup_timeout = startup_timeout

    async def run(
        self,
        *,
        instructions: str,
        user_prompt: str,
        servers: Sequence[StdioServerSpec],
    ) -> MCPDiscoveryDraft:
        """Spawn a configured OpenCode server, run discovery, return the draft."""
        validator = next((s for s in servers if s.name == 'yosoi_validator'), None)
        config = self._build_config(validator)

        with tempfile.TemporaryDirectory(prefix='yosoi-opencode-') as tmp:
            (Path(tmp) / 'opencode.json').write_text(json.dumps(config))
            try:
                proc = await asyncio.create_subprocess_exec(
                    'opencode',
                    'serve',
                    '--port',
                    '0',
                    '--hostname',
                    '127.0.0.1',
                    cwd=tmp,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError as exc:
                raise LLMGenerationError('OpenCode binary not found on PATH: opencode') from exc
            try:
                base_url = await asyncio.wait_for(self._read_url(proc), timeout=self._startup_timeout)
                with obs.transport_span(
                    obs.BACKEND_OPENCODE, f'{self._provider_id}:{self._model_id}', structured_output=True
                ):
                    structured = await self._discover(base_url, instructions, user_prompt)
            finally:
                await self._terminate(proc)

        if structured is None:
            raise LLMGenerationError('OpenCode discovery returned no structured output')
        return MCPDiscoveryDraft.model_validate(structured)

    def _build_config(self, validator: StdioServerSpec | None) -> dict[str, object]:
        mcp: dict[str, object] = {'voidcrawl': _voidcrawl_mcp_config()}
        if validator is not None:
            mcp['yosoi_validator'] = {
                'type': 'local',
                'command': [validator.command, *validator.args],
                'environment': dict(validator.env),
                'enabled': True,
            }
        return {'$schema': 'https://opencode.ai/config.json', 'mcp': mcp}

    async def _discover(self, base_url: str, instructions: str, user_prompt: str) -> object | None:
        import httpx

        body = {
            'model': {'providerID': self._provider_id, 'modelID': self._model_id},
            'system': instructions,
            'parts': [{'type': 'text', 'text': user_prompt}],
            'format': {'type': 'json_schema', 'schema': MCPDiscoveryDraft.model_json_schema()},
        }
        try:
            client_factory = httpx.AsyncClient(base_url=base_url, timeout=300)
        except TypeError:
            client_factory = httpx.AsyncClient()

        async with client_factory as client:
            session_resp = await client.post('/session')
            session_resp.raise_for_status()
            info = session_resp.json()
            if not isinstance(info, dict) or 'id' not in info:
                session_resp = await client.post(f'{base_url}/session')
                session_resp.raise_for_status()
                info = session_resp.json()
                if not isinstance(info, dict) or 'id' not in info:
                    return None

            sid = info['id']
            resp = await client.post(f'/session/{sid}/message', json=body)
            if isinstance(resp.json(), dict) and 'info' not in resp.json():
                resp = await client.post(f'{base_url}/session/{sid}/message', json=body)
            resp.raise_for_status()
            info = resp.json().get('info', {})
            structured = info.get('structured')
            return structured if isinstance(structured, dict) else None

    async def _read_url(self, proc: asyncio.subprocess.Process) -> str:
        if proc.stdout is None:
            raise RuntimeError('opencode serve produced no stdout')
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise RuntimeError('opencode serve exited during startup')
            match = _LISTEN_RE.search(line.decode(errors='replace'))
            if match:
                return match.group(1)

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
