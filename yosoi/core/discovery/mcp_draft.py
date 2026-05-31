"""Structured output contract every MCP-discovery backend returns.

One schema, regardless of which backend (pydantic-ai tool loop, OpenCode, or the
Claude Agent SDK) actually drove the browser. The orchestrator distills this into
a persisted :class:`~yosoi.models.replay.DiscoveryLesson`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from yosoi.models.selectors import SelectorEntry


class MCPFieldFinding(BaseModel):
    """One field's verified selector and the value the agent observed it extract."""

    field: str = Field(description='Contract field name this selector targets.')
    selector: SelectorEntry = Field(description='The selector that extracted the right value.')
    sample_value: str = Field(description='The exact value the selector extracted on the live page.')


class MCPDiscoveryDraft(BaseModel):
    """Structured result of one MCP discovery session.

    Intentionally narrow: just the verified per-field selectors plus an optional
    repeating-item root. The replay plan is *not* part of the model's output —
    asking every backend to emit Yosoi's rich ``ReplayPlan``/``ReplayAct`` schema
    proved brittle (models invent their own act shapes). The orchestrator
    synthesizes a minimal navigate-only plan from the target URL instead;
    multi-step navigation discovery is a separate concern (CAS-79 non-goal).
    """

    fields: list[MCPFieldFinding] = Field(default_factory=list)
    root: SelectorEntry | None = Field(
        default=None,
        description='Wrapper selector for one repeating item, or null for single-item pages.',
    )
