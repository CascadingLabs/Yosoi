"""Context-managed expectations for caller-triggered native browser downloads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Self

from pydantic import Field

from . import _native
from ._models import ImmutableModel
from .documents import (
    FileDocument,
    _FileDocument,
)
from .media import DEFAULT_FILE_LIMIT_BYTES, MAX_FILE_LIMIT_BYTES

if TYPE_CHECKING:
    from .browser import Work


async def _await_native[T](awaitable: Awaitable[T]) -> T:
    """Wrap native asyncio Futures in a coroutine accepted by create_task."""
    return await awaitable


DEFAULT_DOWNLOAD_TIMEOUT_MS = 30_000
"""Default browser download wait bound in milliseconds."""

__all__ = ["DownloadCapture", "DownloadOptions", "DEFAULT_DOWNLOAD_TIMEOUT_MS"]


class DownloadOptions(ImmutableModel):
    """Per-download byte and time bounds.

    Attributes:
        max_bytes: Largest payload accepted by Rust; defaults to 64 MiB and cannot
            exceed the 256 MiB file hard maximum.
        timeout_ms: Maximum wait for completion, measured in milliseconds.
    """

    max_bytes: int = Field(
        default=DEFAULT_FILE_LIMIT_BYTES,
        strict=True,
        ge=1,
        le=MAX_FILE_LIMIT_BYTES,
        description="Largest accepted file payload in bytes, at most 256 MiB.",
    )
    timeout_ms: int = Field(
        default=DEFAULT_DOWNLOAD_TIMEOUT_MS,
        strict=True,
        ge=1,
        le=2**64 - 1,
        description="Maximum download wait in milliseconds.",
    )


class DownloadCapture:
    """One armed native download, retained beside the Work that triggered it.

    Use ``async with work.expect_download(...) as download``. The body must perform
    the existing click, navigation, or Flow action explicitly. ``wait`` consumes the
    result; leaving the context without waiting cancels and cleans up the provider
    capture. The manager never initiates or repeats a browser action.
    """

    def __init__(self, work: Work, options: DownloadOptions) -> None:
        """Prepare lazy capture setup while retaining the caller's Work wrapper.

        Args:
            work: Existing caller-owned Work lease used for the trigger action.
            options: Byte and millisecond bounds for this one expected download.
        """
        if not isinstance(options, DownloadOptions):
            raise TypeError("options must be DownloadOptions")
        self._work = work
        self.options = options
        self._handle: _native.DownloadCapture | None = None
        self._closed = False

    async def __aenter__(self) -> Self:
        """Arm capture before returning control for the caller's triggering action.

        Raises:
            DownloadError: The engine is unsupported, limits are invalid, or capture
                cannot be armed.
            BrowserError: Work is released, unavailable, or executing another action.
        """
        if self._closed or self._handle is not None:
            raise RuntimeError("download capture cannot be entered again")
        self._handle = await self._work._expect_download(self.options)
        return self

    async def wait(self) -> FileDocument:
        """Await the one complete file and return its concrete native file type.

        The capture must be inside its async context before the caller triggers the
        browser action. Waiting performs no click, navigation, or retry.

        Raises:
            DownloadError: Transfer, timeout, cancellation, provider cleanup, or file
                validation fails. Cancellation awaits native provider cleanup before
                returning. An unrelated download is preserved in a recovery directory
                identified by ``rust_error_details``.
            pydantic.ValidationError: Native file metadata cannot form its typed view.
        """
        handle = self._require_handle()
        task = asyncio.create_task(_await_native(handle.wait()))
        from .browser import BrowserCleanupError, _settle_cleanup_task

        try:
            native_document = await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            cleanup_error: BaseException | None = None
            try:
                cleanup_cancellation = await _settle_cleanup_task(
                    asyncio.create_task(_await_native(handle.cancel()))
                )
                if cleanup_cancellation is not None:
                    cleanup_error = cleanup_cancellation
            except BaseException as error:
                cleanup_error = error
            try:
                wait_cancellation = await _settle_cleanup_task(task)
                if wait_cancellation is not None and cleanup_error is None:
                    cleanup_error = wait_cancellation
            except _native.DownloadError as wait_error:
                if (
                    cleanup_error is None
                    and getattr(wait_error, "variant", None) != "Cancelled"
                ):
                    cleanup_error = wait_error
            except BaseException as wait_error:
                if cleanup_error is None:
                    cleanup_error = wait_error
            if cleanup_error is not None:
                self._handle = None
                self._closed = True
                raise BrowserCleanupError(
                    cancellation, (cleanup_error,)
                ) from cancellation
            self._handle = None
            self._closed = True
            raise cancellation
        except BaseException:
            self._handle = None
            self._closed = True
            raise
        self._handle = None
        self._closed = True
        return _FileDocument._from_native(native_document)

    async def cancel(self) -> None:
        """Cancel the provider download and await context restoration explicitly.

        Raises:
            DownloadError: Provider cancellation or browser-context restoration fails.
        """
        handle = self._require_handle()
        task = asyncio.create_task(_await_native(handle.cancel()))
        from .browser import _settle_cleanup_task

        try:
            cancellation = await _settle_cleanup_task(task)
        except BaseException:
            self._handle = None
            self._closed = True
            raise
        self._handle = None
        self._closed = True
        if cancellation is not None:
            raise cancellation

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        """Cancel an unconsumed capture and shield cleanup from caller cancellation.

        Args:
            exc_type: Exception raised by the context body, if any.
            exc: Original context-body exception, if any.
            traceback: Original traceback supplied by async context management.

        Returns:
            False so the body exception is never suppressed.

        Raises:
            BrowserCleanupError: Provider cleanup fails while another exception is
                active; both failures remain available. ``rust_error_details`` includes
                any preserved recovery directory.
            DownloadError: Cleanup fails after an otherwise successful body.
        """
        handle = self._handle
        if handle is None:
            self._closed = True
            return False

        async def settle() -> None:
            await handle.cancel()

        task = asyncio.create_task(settle())
        from .browser import BrowserCleanupError, _settle_cleanup_task

        try:
            cancellation = await _settle_cleanup_task(task)
        except BaseException as cleanup_error:
            self._handle = None
            self._closed = True
            if exc is None:
                raise
            raise BrowserCleanupError(exc, (cleanup_error,)) from exc
        self._handle = None
        self._closed = True
        if cancellation is not None:
            if exc is not None:
                raise BrowserCleanupError(exc, (cancellation,)) from exc
            raise cancellation
        return False

    def _require_handle(self) -> _native.DownloadCapture:
        """Return the active native capture or fail before consuming Python state."""
        if self._handle is None or self._closed:
            raise RuntimeError("download capture is not active")
        return self._handle
