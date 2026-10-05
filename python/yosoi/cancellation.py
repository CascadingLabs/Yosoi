"""Caller-controlled cancellation shared with the Rust SDK."""

from __future__ import annotations

from . import _native


class CancellationToken:
    def __init__(self) -> None:
        self._handle = _native.CancellationToken()

    @property
    def cancelled(self) -> bool:
        return self._handle.cancelled

    def cancel(self) -> None:
        self._handle.cancel()
