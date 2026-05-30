"""Core components for Yosoi.

Names are resolved lazily (PEP 562) so importing a leaf module (e.g.
``yosoi.core.verification.semantic`` from the validator subprocess) does not drag
in ``Pipeline`` and the whole pydantic-ai / provider-SDK graph via this package
``__init__``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

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


def __getattr__(name: str) -> object:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
