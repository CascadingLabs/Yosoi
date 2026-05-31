"""Optional model transports for Yosoi.

Lazy (PEP 562): importing a sibling submodule such as ``validator_mcp`` must not
pull the Claude/OpenCode SDKs (and pydantic-ai) through this package ``__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.integrations.claude_sdk import ClaudeSDKModel as ClaudeSDKModel
    from yosoi.integrations.opencode import OpenCodeModel as OpenCodeModel

_LAZY: dict[str, str] = {
    'ClaudeSDKModel': 'yosoi.integrations.claude_sdk',
    'OpenCodeModel': 'yosoi.integrations.opencode',
}

__all__ = ['ClaudeSDKModel', 'OpenCodeModel']

__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
