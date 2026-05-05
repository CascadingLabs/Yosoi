"""Lightweight token estimation for spike-level instrumentation.

Real tokenizers vary per provider (tiktoken for OpenAI, SentencePiece for
Llama, Anthropic's own) and pulling in `tiktoken` would expand the dep tree
for a 1-week spike. The success metric is a *ratio*
(``tokens_out / tokens_in``) so a deterministic char-based proxy is fine —
the constant cancels.

We use chars / 4, the same heuristic OpenAI publishes for English text. If
later work needs exact provider counts, swap this module for a real
tokenizer; the public surface (one ``estimate_tokens`` function) stays the
same.
"""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count via the chars/4 heuristic.

    Args:
        text: Source text.

    Returns:
        Estimated token count, rounded up so a 1-char input still costs 1.
    """
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
