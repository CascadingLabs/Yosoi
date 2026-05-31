"""Models for the ``ys.File`` download lane: the per-field spec and the result record.

``DownloadRecord`` is the provenance-carrying value a ``ys.File()`` field resolves to
(or sits alongside the parsed value when ``parse=`` is set). ``DownloadSpec`` is the
resolved, fetcher-facing instruction built from a contract's file action field.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from yosoi.models.replay import utc_now

DownloadMode = Literal['retrigger', 'refetch']


class DownloadRecord(BaseModel):
    """Provenance for one downloaded file (the value of a ``ys.File`` field).

    Treat ``path`` as a quarantined location: the bytes have passed the
    ``allowed_types`` gate but should still be handled as untrusted input.
    """

    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    content_type: str | None = None  # server-declared Content-Type (parameters stripped)
    source_url: str | None = None  # final URL after redirects, when known
    requested_url: str | None = None  # URL/selector target originally asked for
    downloaded_at: AwareDatetime = Field(default_factory=utc_now)
    scan_verdict: str | None = None  # populated when the optional scan extra runs

    def __str__(self) -> str:
        """Compact, human-friendly summary for logs and the console."""
        ct = self.content_type or 'unknown'
        return f'DownloadRecord({self.path}, {self.size_bytes}B, {ct}, sha256={self.sha256[:12]}…)'


class DownloadSpec(BaseModel):
    """Resolved per-field download instruction handed to the fetcher.

    Exactly one of ``trigger`` / ``href`` / ``url`` drives the download (``description``
    is resolved to one of those by discovery before a spec is built). ``allowed_types``
    is the already-normalised, canonical allowlist; an empty tuple means default-deny.
    """

    field: str
    mode: DownloadMode = 'retrigger'
    trigger: str | None = None  # CSS selector to click (retrigger)
    href: str | None = None  # CSS selector yielding an href (refetch)
    url: str | None = None  # literal URL (refetch)
    allowed_types: tuple[str, ...] = ()
    parse: str | None = None
    max_bytes: int | None = None


class DownloadResult(BaseModel):
    """A completed download: its provenance record plus the field's resolved value.

    ``value`` is the parsed content when the field set ``parse=`` (e.g. CSV rows),
    otherwise it is the ``DownloadRecord`` itself. The merge step writes ``value`` into
    the extracted record; ``record`` stays available for the provenance manifest.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    record: DownloadRecord
    value: Any = None


__all__ = ['DownloadMode', 'DownloadRecord', 'DownloadResult', 'DownloadSpec']
