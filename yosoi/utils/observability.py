"""Langfuse-based observability for Yosoi.

Bundles a singleton Langfuse SDK client plus a project-owned OpenTelemetry
``TracerProvider`` that pydantic-ai Agents emit spans into. When the required
env vars / config fields are missing, every helper degrades to a no-op so the
pipeline runs unchanged.

Usage::

    from yosoi.utils import observability as obs

    obs.configure(yosoi_cfg.telemetry)            # idempotent, no-op without keys
    settings = obs.instrumentation_settings()     # pass to Agent(instrument=...)

    with obs.span('process_urls', total=10):
        ...

    obs.warning('retrying', attempt=2)
    obs.flush()                                   # before short-lived processes exit
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from langfuse import Langfuse
from opentelemetry import trace

if TYPE_CHECKING:
    from yosoi.core.configs import TelemetryConfig

_logger = logging.getLogger(__name__)
_lock = Lock()

# One session per process invocation (CLI run / script). Resolved lazily on
# first access so that callers (e.g. the CLI ``--session-id`` flag) can set
# ``YOSOI_SESSION_ID`` after this module has been imported but before any
# Pipeline is constructed. Override via ``YOSOI_SESSION_ID`` for resumed runs
# or external orchestration.
_PROCESS_SESSION_ID: str | None = None


def process_session_id() -> str:
    """Return the session id shared by all pipelines in this process.

    Resolved on first call; subsequent calls return the cached value.
    """
    global _PROCESS_SESSION_ID
    if _PROCESS_SESSION_ID is None:
        _PROCESS_SESSION_ID = os.getenv('YOSOI_SESSION_ID') or f'yosoi-{uuid.uuid4().hex[:12]}'
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
    """Initialize the Langfuse client. Idempotent; no-op without keys."""
    if not (cfg.langfuse_public_key and cfg.langfuse_secret_key):
        _logger.warning('Langfuse not initialized — set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable')
        return
    with _lock:
        if LangfuseClient._instance is None:
            LangfuseClient._instance = LangfuseClient(cfg)


def client() -> LangfuseClient | None:
    """Return the active Langfuse client, or None when telemetry is off."""
    return LangfuseClient._instance


def instrumentation_settings() -> bool:
    """Return True when Langfuse is active so Agents emit spans, else False.

    Once :func:`configure` runs successfully, ``Agent.instrument_all()`` has
    already wired pydantic-ai to the global TracerProvider that Langfuse
    installed, so passing ``instrument=True`` is sufficient.
    """
    return client() is not None


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


def reset_for_tests() -> None:
    """Reset the singleton and the lazy session id. Test-only."""
    global _PROCESS_SESSION_ID
    LangfuseClient._instance = None
    _PROCESS_SESSION_ID = None
