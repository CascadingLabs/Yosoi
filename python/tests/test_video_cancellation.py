"""Video cancellation settles cleanup and does not cancel sibling operations."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from yosoi import _native
from yosoi._video_async import settle_video, video_token
from yosoi.cancellation import CancellationToken


def test_video_tokens_preserve_siblings_and_follow_parent_cancellation() -> None:
    parent = CancellationToken()
    first, second = video_token(parent), video_token(parent)
    first.cancel()
    assert first.cancelled
    assert not parent.cancelled
    assert not second.cancelled
    parent.cancel()
    assert second.cancelled


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("session_error", [False, True])
def test_repeated_cancellation_waits_for_cleanup_and_preserves_failure(
    cleanup_fails: bool,
    session_error: bool,
) -> None:
    async def run() -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        cleaning, release = asyncio.Event(), asyncio.Event()

        class Token:
            def cancel(self) -> None:
                cancelled.set()

        async def native_operation() -> None:
            started.set()
            await cancelled.wait()
            cleaning.set()
            await release.wait()
            if cleanup_fails:
                raise RuntimeError("decoder cleanup failed")
            error = (
                _native.SurfaceExecutionError("surface operation failed")
                if session_error
                else _native.VideoError("video processing cancelled")
            )
            error.rust_type = (
                "yosoi::surface::ExecutionError"
                if session_error
                else "yosoi::surface::video::VideoError"
            )
            error.variant = "Operation" if session_error else "Cancelled"
            error.details = {"cancelled": True} if session_error else {}
            error.source_chain = []
            raise error

        waiter = asyncio.create_task(
            settle_video(native_operation(), cast(_native.CancellationToken, Token()))
        )
        await asyncio.wait_for(started.wait(), 5)
        waiter.cancel()
        await asyncio.wait_for(cleaning.wait(), 5)
        assert not waiter.done()
        waiter.cancel()
        release.set()
        if cleanup_fails:
            with pytest.raises(RuntimeError, match="decoder cleanup failed"):
                await asyncio.wait_for(waiter, 5)
        else:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(waiter, 5)

    asyncio.run(run())
