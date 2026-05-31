"""Core components for Yosoi.

Names are resolved lazily (PEP 562) so importing a leaf module (e.g.
``yosoi.core.verification.semantic`` from the validator subprocess) does not drag
in ``Pipeline`` and the whole pydantic-ai / provider-SDK graph via this package
``__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.core.configs import DebugConfig as DebugConfig
    from yosoi.core.configs import TelemetryConfig as TelemetryConfig
    from yosoi.core.configs import YosoiConfig as YosoiConfig
    from yosoi.core.configs import find_available_provider as find_available_provider
    from yosoi.core.pipeline import Pipeline as Pipeline

_LAZY: dict[str, str] = {
    'DebugConfig': 'yosoi.core.configs',
    'TelemetryConfig': 'yosoi.core.configs',
    'YosoiConfig': 'yosoi.core.configs',
    'find_available_provider': 'yosoi.core.configs',
    'Pipeline': 'yosoi.core.pipeline',
}

__all__ = ['DebugConfig', 'Pipeline', 'TelemetryConfig', 'YosoiConfig', 'find_available_provider']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
