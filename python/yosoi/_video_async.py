"""Settle native video subprocess cleanup before exposing caller cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from . import _native
from .cancellation import CancellationToken
from .errors import rust_error_details


def video_token(cancellation: CancellationToken | None) -> _native.CancellationToken:
    """Create a per-operation child so cancelling one await preserves siblings."""
    if cancellation is None:
        return _native.CancellationToken()
    if not isinstance(cancellation, CancellationToken):
        raise TypeError("cancellation must be CancellationToken")
    return cancellation._handle.child()


async def settle_video[T](
    operation: Awaitable[T], token: _native.CancellationToken
) -> T:
    """Shield native work, signal cancellation, and await its owned child cleanup."""

    async def consume() -> T:
        return await operation

    task = asyncio.create_task(consume())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        token.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
            except Exception:
                break
        try:
            task.result()
        except Exception as cleanup_error:
            details = rust_error_details(cleanup_error)
            if details is None or details.variant != "Cancelled":
                raise cleanup_error from cancellation
        raise
