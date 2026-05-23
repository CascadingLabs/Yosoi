"""Own an OpenCode server's lifecycle so examples don't need manual setup.

`opencode serve --port 0` binds an ephemeral free port and prints its URL —
so instead of hardcoding a port and passing it via env var (which collides
when several sessions run at once), we spawn the server, read the URL it
prints, and hand it back. The process we start is the process we talk to.

Usage:
    async with ensure_opencode_server():
        model = ys.opencode(...)
        ...

If OPENCODE_BASE_URL is already set, the context manager uses that server.
Otherwise it spawns one, exposes it through OPENCODE_BASE_URL for the duration
of the block, and terminates it on exit.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

_LISTEN_RE = re.compile(r'listening on (http://\S+)')


class OpenCodeServer:
    """Async context manager that spawns and reaps an `opencode serve` process."""

    def __init__(self, *, hostname: str = '127.0.0.1', startup_timeout: float = 30.0) -> None:
        self._hostname = hostname
        self._startup_timeout = startup_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self.base_url: str | None = None

    async def __aenter__(self) -> str:
        # --port 0 => OS picks a free port; we learn which from stdout.
        self._proc = await asyncio.create_subprocess_exec(
            'opencode',
            'serve',
            '--port',
            '0',
            '--hostname',
            self._hostname,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            self.base_url = await asyncio.wait_for(self._read_url(), timeout=self._startup_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            await self._terminate()
            raise RuntimeError('opencode serve did not report a listen URL in time') from None
        return self.base_url

    async def __aexit__(self, *exc: object) -> None:
        await self._terminate()

    async def _read_url(self) -> str:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError('opencode serve process was not started')
        while True:
            line = await self._proc.stdout.readline()
            if not line:  # process exited before announcing a URL
                raise RuntimeError('opencode serve exited during startup')
            match = _LISTEN_RE.search(line.decode(errors='replace'))
            if match:
                return match.group(1)

    async def _terminate(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        self._proc.terminate()
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        if self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()


@asynccontextmanager
async def ensure_opencode_server() -> AsyncIterator[None]:
    """Ensure OPENCODE_BASE_URL points at a usable OpenCode server in this block."""
    if os.getenv('OPENCODE_BASE_URL'):
        yield
        return

    old_base_url = os.environ.get('OPENCODE_BASE_URL')
    async with OpenCodeServer() as base_url:
        os.environ['OPENCODE_BASE_URL'] = base_url
        try:
            yield
        finally:
            if old_base_url is None:
                os.environ.pop('OPENCODE_BASE_URL', None)
            else:
                os.environ['OPENCODE_BASE_URL'] = old_base_url
