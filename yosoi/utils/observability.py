"""Langfuse-based observability for Yosoi.

Bundles a singleton Langfuse SDK client plus a project-owned OpenTelemetry
``TracerProvider`` that pydantic-ai Agents emit spans into. When the required
env vars / config fields are missing, every helper degrades to a no-op so the
pipeline runs unchanged.

Usage::

    from yosoi.utils import observability as obs

    obs.configure(yosoi_cfg.telemetry)            # idempotent, no-op without keys
    caps = obs.agent_capabilities()               # pass to Agent(capabilities=...)

    with obs.span('process_urls', total=10):
        ...

    obs.warning('retrying', attempt=2)
    obs.flush()                                   # before short-lived processes exit
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import TYPE_CHECKING, Any, TypedDict
from urllib.parse import urlparse

from langfuse import Langfuse
from opentelemetry import context as otel_context
from opentelemetry import trace
from pydantic_ai.capabilities import Instrumentation

if TYPE_CHECKING:
    from pydantic_ai.capabilities import AgentCapability

    from yosoi.core.configs import TelemetryConfig

_logger = logging.getLogger(__name__)
_lock = Lock()
_configure_called = False

# One session per process invocation (CLI run / script). Resolved lazily on
# first access so that callers (e.g. the CLI ``--session-id`` flag) can set
# ``YOSOI_SESSION_ID`` after this module has been imported but before any
# Pipeline is constructed. Override via ``YOSOI_SESSION_ID`` for resumed runs
# or external orchestration.
_PROCESS_SESSION_ID: str | None = None


def process_session_id() -> str:
    """Return the session id shared by all pipelines in this process.

    Auto-generated form is a canonical UUID4 (e.g.
    ``3f4a9c2e-8b1d-4f7c-9e2a-5b6c7d8e9f01``) so the id joins cleanly across
    Postgres / ClickHouse / external services without prefix stripping. Origin
    labelling ('yosoi', 'cli'|'script') lives on session tags, not the id.

    Override via ``YOSOI_SESSION_ID`` for resumed runs or external orchestration
    — overrides accept any string (not just UUIDs), so users can pass
    human-meaningful labels like ``batch-2026-05-02`` when they want them.

    Resolved on first call; subsequent calls return the cached value.
    Double-checked locking guards against concurrent first-call races.
    """
    global _PROCESS_SESSION_ID
    if _PROCESS_SESSION_ID is None:
        with _lock:
            if _PROCESS_SESSION_ID is None:
                _PROCESS_SESSION_ID = os.getenv('YOSOI_SESSION_ID') or str(uuid.uuid4())
    return _PROCESS_SESSION_ID


class LangfuseClient:
    """Singleton bundling the Langfuse SDK and the OTel TracerProvider it owns.

    Langfuse 4.x sets itself up as the global TracerProvider when no provider
    is passed, and registers its export pipeline there. Pydantic-ai then picks
    that global provider up via ``Agent.instrument_all()`` / ``instrument=True``,
    so spans land in Langfuse without any per-Agent wiring.
    """

    _instance: LangfuseClient | None = None

    def __init__(self, cfg: TelemetryConfig) -> None:
        """Construct the SDK, install OTel instrumentation, and run an auth probe."""
        self.sdk = Langfuse(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=cfg.langfuse_host,
            # Default Langfuse filter only exports spans from known LLM
            # instrumentation scopes; allow our `yosoi` tracer spans too.
            should_export_span=lambda _s: True,
        )
        from pydantic_ai.agent import Agent

        Agent.instrument_all()
        self.tracer = trace.get_tracer('yosoi')
        try:
            if not self.sdk.auth_check():
                _logger.warning('Langfuse auth check failed — verify LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL')
        except Exception as e:  # noqa: BLE001 - probe must never break pipeline init
            _logger.warning('Langfuse auth check errored (%s) — traces may not export', e)


def configure(cfg: TelemetryConfig) -> None:
    """Initialize the Langfuse client. Idempotent; no-op without keys.

    Repeat calls (e.g. ``Pipeline()`` re-instantiated per queued URL) short-circuit
    on the first-call sentinel so we never re-run ``Agent.instrument_all()`` or
    re-emit the missing-keys warning under concurrent worker construction.
    """
    global _configure_called
    with _lock:
        if _configure_called:
            return
        _configure_called = True
        if not (cfg.langfuse_public_key and cfg.langfuse_secret_key):
            _logger.warning('Langfuse not initialized — set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable')
            return
        if LangfuseClient._instance is None:
            LangfuseClient._instance = LangfuseClient(cfg)


def client() -> LangfuseClient | None:
    """Return the active Langfuse client, or None when telemetry is off."""
    return LangfuseClient._instance


def agent_capabilities() -> list[AgentCapability[Any]]:
    """Return the pydantic-ai capabilities that wire Agents into telemetry.

    Yields ``[Instrumentation()]`` when Langfuse is active so Agents emit spans,
    else ``[]``. Once :func:`configure` runs successfully, it has already wired
    pydantic-ai to the global TracerProvider that Langfuse installed, so the
    default :class:`Instrumentation` capability picks it up. Pass the result to
    ``Agent(capabilities=...)``.
    """
    if client() is None:
        return []
    return [Instrumentation()]


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Start a span on the shared tracer. No-op when telemetry is off."""
    c = client()
    if c is None:
        yield None
        return
    with c.tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s


@contextmanager
def detached_span(name: str, **attrs: Any) -> Iterator[Any]:
    """Emit a span without attaching it to the current OTel context.

    Unlike :func:`span` (which uses ``start_as_current_span`` and becomes the
    parent of any subsequent span), this uses ``start_span`` so the span is
    recorded by the exporter but does NOT become the OTel parent. Used at the
    orchestrator level to emit observability metadata (e.g. ``enqueue``)
    without collapsing per-URL worker traces under one parent.

    Langfuse's :class:`LangfuseSpanProcessor.on_start` still enriches the
    detached span with ``session.id`` from the surrounding
    ``propagate_attributes`` context, so it appears under the right session
    in the UI even though it is parentless.

    No-op when telemetry is off.
    """
    c = client()
    if c is None:
        yield None
        return
    # Clear the current span from the context so the new span becomes a true
    # root (parentless) span while preserving baggage and other context values.
    detached_ctx = trace.set_span_in_context(trace.INVALID_SPAN, otel_context.get_current())
    s = c.tracer.start_span(name, context=detached_ctx)
    try:
        for k, v in attrs.items():
            s.set_attribute(k, v)
        yield s
    finally:
        s.end()


@contextmanager
def session(session_id: str, **attrs: Any) -> Iterator[None]:
    """Group every span produced inside this block under one Langfuse session.

    Wraps Langfuse's :func:`langfuse.propagate_attributes` so that traces
    emitted by pydantic-ai (and our own ``span()`` calls) inherit ``session_id``
    plus any extra ``user_id`` / ``tags`` / metadata. No-op when telemetry is off.
    """
    c = client()
    if c is None:
        yield
        return
    from langfuse import propagate_attributes

    with propagate_attributes(session_id=session_id, **attrs):
        yield


@contextmanager
def user(user_id: str, **attrs: Any) -> Iterator[None]:
    """Bind ``user_id`` (and any extra tags / metadata) to spans created inside this block.

    Used to associate a per-URL trace with the (sub)domain it belongs to,
    so the Langfuse UI can filter by user and aggregate per-site behaviour.
    Nests inside :func:`session` — outer session_id stays in scope.
    No-op when telemetry is off.
    """
    c = client()
    if c is None:
        yield
        return
    from langfuse import propagate_attributes

    with propagate_attributes(user_id=user_id, **attrs):
        yield


def normalize_user_id(url: str) -> str | None:
    """Normalize a URL to a stable Langfuse ``user_id`` string.

    Rules:
      * Lowercase the host.
      * Strip exactly **one** leading ``www.`` (e.g. ``www.www.example.com`` →
        ``www.example.com``). Recursive stripping mangles real hostnames like
        ``www.foo.com`` where the ``www`` is the canonical site label.
      * Strip port (``example.com:8080`` → ``example.com``).
      * Strip userinfo (``user:pw@example.com`` → ``example.com``).
      * Keep IDN / punycode unchanged — Langfuse handles unicode user_ids and
        re-encoding would split traces between the two forms.

    Returns ``None`` for URLs without a host (``file://``, ``data:…``, schemes
    with empty netloc). Callers skip the :func:`user` wrap on ``None``.

    Args:
        url: URL string. Accepts bare hostnames; missing scheme is fine.

    Returns:
        Normalized host, or ``None`` if the URL has no host.

    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return None
    host = host.lower()
    if host.startswith('www.') and len(host) > 4:
        host = host[4:]
    return host


def warning(msg: str, **attrs: Any) -> None:
    """Emit a warning to stdlib logging and (if active) the current span."""
    _logger.warning(msg, extra=attrs)
    c = client()
    if c is None:
        return
    current = trace.get_current_span()
    if current.is_recording():
        current.add_event(msg, attributes={k: str(v) for k, v in attrs.items()})


def flush() -> None:
    """Flush pending spans + Langfuse events. Call before short-lived processes exit."""
    c = client()
    if c is None:
        return
    c.sdk.flush()


def _serialize_for_langfuse(payload: Any) -> str:
    """JSON-encode payload for Langfuse I/O attributes.

    Uses ``default=str`` so Pydantic models, datetimes, and other non-JSON
    types serialize without raising.
    """
    return json.dumps(payload, default=str, ensure_ascii=False)


def set_trace_input(span: Any | None, payload: Any) -> None:
    """Set the trace-level input panel on the per-URL root span.

    No-op when telemetry is off or *span* is ``None`` (e.g. :func:`span`
    yielded ``None`` because :func:`client` is ``None``). Sets
    ``langfuse.observation.input`` — Langfuse 4.x server-side enrichment
    lifts this onto the trace input header in the UI.
    """
    if span is None or client() is None:
        return
    span.set_attribute('langfuse.observation.input', _serialize_for_langfuse(payload))


def set_trace_output(span: Any | None, payload: Any) -> None:
    """Set the trace-level output panel on the per-URL root span.

    No-op rules same as :func:`set_trace_input`.
    """
    if span is None or client() is None:
        return
    span.set_attribute('langfuse.observation.output', _serialize_for_langfuse(payload))


# ---------------------------------------------------------------------------
# Standard span attribute contract
# ---------------------------------------------------------------------------
# One queryable schema so every "view" — the three LLM backends, A3Node
# replay/probe, and the selector cache — reports the same attribute keys in
# Langfuse. Call sites set values through the helpers below; the round-trip
# tests in ``tests/unit/utils/test_observability.py`` assert the emitted spans
# carry these exact constants, so emission and tests never drift.

# -- LLM transport ----------------------------------------------------------
# ``LLM_TRANSPORT_SPAN`` replaces the per-backend ``claude_sdk.query`` /
# ``opencode.message`` spans with one name + attribute schema. The same
# ``yosoi.llm.*`` identity is also stamped on the discovery span that wraps any
# ``agent.run()`` (via :func:`annotate_llm`) so it is queryable uniformly for
# direct-API providers too, which have no custom transport span of their own.
LLM_TRANSPORT_SPAN = 'llm.transport'
ATTR_LLM_BACKEND = 'yosoi.llm.backend'  # 'api' | 'claude-sdk' | 'opencode'
ATTR_LLM_PROVIDER = 'yosoi.llm.provider'  # raw provider, e.g. 'groq'
ATTR_LLM_MODEL = 'yosoi.llm.model'
ATTR_LLM_STRUCTURED = 'yosoi.llm.structured_output'

BACKEND_API = 'api'
BACKEND_CLAUDE_SDK = 'claude-sdk'
BACKEND_OPENCODE = 'opencode'

# -- A3Node DOM-stability recipe (fetch span) -------------------------------
# ``mode`` records the *attempted* path, not the HTML's final provenance: a
# replay that falls short keeps ``mode='replay'`` with ``fell_back=True`` even
# though it ultimately re-probed. Query ``fell_back`` (not ``mode``) to isolate
# replays that did not produce the served HTML.
ATTR_A3_MODE = 'yosoi.a3node.mode'  # 'disabled' | 'probe' | 'replay' (attempt-intent)
ATTR_A3_REPLAYED = 'yosoi.a3node.replayed'  # replay produced usable HTML
ATTR_A3_FELL_BACK = 'yosoi.a3node.fell_back'  # replay fell short → re-probed
ATTR_A3_ACTS = 'yosoi.a3node.acts'  # DOMLoader act count in the recipe
ATTR_A3_REPLAY_COUNT = 'yosoi.a3node.replay_count'  # prior successful replays
ATTR_A3_SETTLE_SECONDS = 'yosoi.a3node.settle_seconds'

A3_MODE_DISABLED = 'disabled'
A3_MODE_PROBE = 'probe'
A3_MODE_REPLAY = 'replay'

# -- Selector cache outcome (root scrape span) ------------------------------
ATTR_CACHE_PATH = 'yosoi.cache.path'  # 'fresh' | 'cached' | 'partial'
ATTR_CACHE_FRESH_FIELDS = 'yosoi.cache.fresh_fields'
ATTR_CACHE_STALE_FIELDS = 'yosoi.cache.stale_fields'

CACHE_FRESH = 'fresh'  # full fresh discovery, no usable cache
CACHE_CACHED = 'cached'  # every field served from cache, no LLM
CACHE_PARTIAL = 'partial'  # some fields cached, some re-discovered


def llm_backend(provider: str) -> str:
    """Map a raw provider name onto the standard LLM backend label.

    Subscription transports (``claude-sdk``, ``opencode``) keep their own
    label; every direct-API provider (groq, anthropic, openai, …) collapses to
    ``api`` so a single Langfuse filter separates "our own transports" from
    "vendor APIs".
    """
    p = provider.lower()
    if p == BACKEND_CLAUDE_SDK:
        return BACKEND_CLAUDE_SDK
    if p == BACKEND_OPENCODE:
        return BACKEND_OPENCODE
    return BACKEND_API


def current_span() -> Any:
    """Return the active OTel span so callers can annotate it via the helpers.

    May be a non-recording no-op span when no span is in scope; the annotate
    helpers guard on :func:`client` so this is always safe to pass.
    """
    return trace.get_current_span()


def _apply(target: Any | None, attrs: dict[str, Any]) -> None:
    """Set the non-None *attrs* on *target* span. No-op when telemetry is off.

    Centralizes the None-skipping + active-client guard so every annotate
    helper is a one-liner and OTel never sees a ``None`` attribute value.
    """
    if target is None or client() is None:
        return
    for k, v in attrs.items():
        if v is not None:
            target.set_attribute(k, v)


@contextmanager
def transport_span(backend: str, model: str, *, structured_output: bool, **extra: Any) -> Iterator[Any]:
    """Span around a custom LLM Model's raw transport call.

    Standardizes the previously divergent per-backend spans onto one name
    (:data:`LLM_TRANSPORT_SPAN`) and attribute schema, so a single Langfuse
    view covers every backend. ``**extra`` carries backend-specific detail
    (e.g. ``base_url``) under the ``yosoi.llm.`` namespace. No-op when
    telemetry is off.
    """
    with span(LLM_TRANSPORT_SPAN) as s:
        _apply(
            s,
            {
                ATTR_LLM_BACKEND: backend,
                ATTR_LLM_MODEL: model,
                ATTR_LLM_STRUCTURED: structured_output,
                **{f'yosoi.llm.{k}': v for k, v in extra.items()},
            },
        )
        yield s


def annotate_llm(target: Any | None, *, provider: str, model: str) -> None:
    """Tag the discovery span wrapping ``agent.run()`` with uniform LLM identity.

    Applied for every backend so ``yosoi.llm.backend`` / ``provider`` / ``model``
    sit on the same keys regardless of transport. No-op when telemetry is off.
    """
    _apply(target, {ATTR_LLM_BACKEND: llm_backend(provider), ATTR_LLM_PROVIDER: provider, ATTR_LLM_MODEL: model})


class A3ReplayAttrs(TypedDict):
    """Shared A3Node replay-span fields, splat into :func:`annotate_a3node`.

    Excludes ``replayed``/``fell_back`` so each exit point can set its own
    outcome flag while reusing the common metadata.
    """

    mode: str
    acts: int
    replay_count: int
    settle_seconds: float


def annotate_a3node(
    target: Any | None,
    *,
    mode: str,
    replayed: bool = False,
    fell_back: bool = False,
    acts: int = 0,
    replay_count: int = 0,
    settle_seconds: float = 0.0,
) -> None:
    """Tag the fetch span with the A3Node recipe outcome. No-op when off."""
    _apply(
        target,
        {
            ATTR_A3_MODE: mode,
            ATTR_A3_REPLAYED: replayed,
            ATTR_A3_FELL_BACK: fell_back,
            ATTR_A3_ACTS: acts,
            ATTR_A3_REPLAY_COUNT: replay_count,
            ATTR_A3_SETTLE_SECONDS: settle_seconds,
        },
    )


def annotate_cache(
    target: Any | None, *, path: str, fresh_fields: int | None = None, stale_fields: int | None = None
) -> None:
    """Tag the root scrape span with the selector-cache outcome. No-op when off.

    ``fresh_fields`` / ``stale_fields`` are optional so a common emit point can
    stamp ``path`` alone without clobbering counts set earlier at a branch that
    actually computed them (``_apply`` skips ``None`` values).
    """
    _apply(
        target, {ATTR_CACHE_PATH: path, ATTR_CACHE_FRESH_FIELDS: fresh_fields, ATTR_CACHE_STALE_FIELDS: stale_fields}
    )


def reset_for_tests() -> None:
    """Reset the singleton and the lazy session id. Test-only."""
    global _PROCESS_SESSION_ID, _configure_called
    LangfuseClient._instance = None
    _PROCESS_SESSION_ID = None
    _configure_called = False
