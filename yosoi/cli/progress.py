"""Concurrent URL processing — backwards compatibility stub.

run_concurrent() has been superseded by Pipeline.process_urls(workers=N),
which now auto-activates the Live table display when workers > 1.
"""

from __future__ import annotations

from yosoi.core.pipeline import _build_concurrent_table as _build_progress_table

__all__ = ['_build_progress_table']
