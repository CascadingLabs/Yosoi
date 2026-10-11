"""Caller-controlled cancellation shared with the Rust SDK."""

from __future__ import annotations

from . import _native


class CancellationToken:
    """Share a caller-controlled cancellation signal with SDK operations.

    Operations observe the signal cooperatively. Cancelling does not roll back
    completed work or guarantee that external effects are undone. Keep the token
    and pass it to operations that should share the same cancellation boundary.
    """

    def __init__(self) -> None:
        """Create an independent token whose cancellation signal is unset."""
        self._handle = _native.CancellationToken()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested for this token."""
        return self._handle.cancelled

    def cancel(self) -> None:
        """Request cancellation for operations sharing this token.

        Calling this method repeatedly is harmless. It returns immediately;
        operations finish observing cancellation asynchronously.
        """
        self._handle.cancel()
