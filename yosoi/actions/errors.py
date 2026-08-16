"""Expected action-boundary failures safe to normalize into ledger receipts."""

from __future__ import annotations

from yosoi.actions.models import ActionErrorCode


class ActionBoundaryError(Exception):
    """Expected adapter failure carrying only a model-safe normalized code."""

    def __init__(self, code: ActionErrorCode) -> None:
        """Initialize with a normalized code; never accept raw adapter text."""
        self.code = code
        super().__init__(code.value)


__all__ = ['ActionBoundaryError']
