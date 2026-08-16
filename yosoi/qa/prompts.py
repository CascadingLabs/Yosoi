"""QA prompt boundary reserved until indexed tool semantics stabilize."""

from __future__ import annotations


class QAPromptNotReadyError(RuntimeError):
    """Raised when scaffold code attempts to construct a production QA prompt."""


def build_qa_system_prompt() -> str:
    """Fail closed rather than shipping an unmeasured prompt with the scaffold."""
    raise QAPromptNotReadyError('QA prompts are intentionally deferred; see qa/ROADMAP.md')


__all__ = ['QAPromptNotReadyError', 'build_qa_system_prompt']
