"""QA consumer of the task-agnostic indexed observation runtime.

This package is deliberately not re-exported from :mod:`yosoi` and has no browser,
provider, policy, or operations wiring. See ``ROADMAP.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.qa.capture import QACaptureAdapter as QACaptureAdapter
    from yosoi.qa.capture import QACaptureRequest as QACaptureRequest
    from yosoi.qa.capture import QACaptureSession as QACaptureSession
    from yosoi.qa.index import ExpandArgs as ExpandArgs
    from yosoi.qa.index import IndexCapabilities as IndexCapabilities
    from yosoi.qa.index import IndexSession as IndexSession
    from yosoi.qa.index import IndexStatus as IndexStatus
    from yosoi.qa.index import SnapshotIndexCapabilities as SnapshotIndexCapabilities
    from yosoi.qa.reports import QAFinding as QAFinding
    from yosoi.qa.reports import QAReport as QAReport
    from yosoi.qa.runtime import QARequest as QARequest
    from yosoi.qa.runtime import QAResult as QAResult
    from yosoi.qa.runtime import QARuntime as QARuntime
    from yosoi.qa.tools import QAToolHandler as QAToolHandler

_LAZY = {
    'QACaptureAdapter': 'yosoi.qa.capture',
    'QACaptureRequest': 'yosoi.qa.capture',
    'QACaptureSession': 'yosoi.qa.capture',
    'ExpandArgs': 'yosoi.qa.index',
    'IndexCapabilities': 'yosoi.qa.index',
    'IndexSession': 'yosoi.qa.index',
    'IndexStatus': 'yosoi.qa.index',
    'SnapshotIndexCapabilities': 'yosoi.qa.index',
    'QAFinding': 'yosoi.qa.reports',
    'QAReport': 'yosoi.qa.reports',
    'QARequest': 'yosoi.qa.runtime',
    'QAResult': 'yosoi.qa.runtime',
    'QARuntime': 'yosoi.qa.runtime',
    'QAToolHandler': 'yosoi.qa.tools',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
