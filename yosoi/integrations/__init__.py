"""Optional model transports for Yosoi.

Lazy (PEP 562): importing a sibling submodule such as ``validator_mcp`` must not
pull the Claude/OpenCode SDKs (and pydantic-ai) through this package ``__init__``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.integrations.claude_sdk import ClaudeSDKModel as ClaudeSDKModel
    from yosoi.integrations.opencode import OpenCodeModel as OpenCodeModel

_LAZY: dict[str, str] = {
    'ClaudeSDKModel': 'yosoi.integrations.claude_sdk',
    'OpenCodeModel': 'yosoi.integrations.opencode',
}

__all__ = ['ClaudeSDKModel', 'OpenCodeModel']


def __getattr__(name: str) -> object:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
