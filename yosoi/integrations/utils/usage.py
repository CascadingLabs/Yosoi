"""Shared token-usage mapping for subscription-backed Model transports.

The OpenCode and Claude Agent SDK backends report token usage in different
shapes, but both must land it on pydantic-ai's :class:`RequestUsage` so the
instrumentation emits ``gen_ai.usage.*`` span attributes — Langfuse derives a
generation's tokens/cost from exactly those. A backend that returns an empty
``RequestUsage()`` shows up untracked. Each backend extracts its own raw counts
and funnels them through :func:`build_request_usage` so the mapping stays in one
place.
"""

from __future__ import annotations

from pydantic_ai.usage import RequestUsage


def build_request_usage(
    *,
    input_tokens: int | None = 0,
    output_tokens: int | None = 0,
    cache_read_tokens: int | None = 0,
    cache_write_tokens: int | None = 0,
    reasoning_tokens: int | None = 0,
) -> RequestUsage:
    """Build a pydantic-ai ``RequestUsage`` from normalized token counts.

    Tolerates ``None`` for any count (coerced to 0), so callers can pass
    ``raw.get(...)`` straight through without guarding each field. Reasoning
    tokens have no dedicated ``RequestUsage`` field, so they ride along in
    ``details['reasoning_tokens']`` (only when non-zero, to keep the panel clean).
    """
    return RequestUsage(
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        cache_read_tokens=int(cache_read_tokens or 0),
        cache_write_tokens=int(cache_write_tokens or 0),
        details={'reasoning_tokens': int(reasoning_tokens)} if reasoning_tokens else {},
    )
