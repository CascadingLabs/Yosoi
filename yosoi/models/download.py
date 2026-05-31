"""Models and the annotation→output-view resolver for the ``ys.File`` download lane.

This module holds the per-field spec, the result/provenance record, and the mapping from
a field's declared type to its output view.

The field's declared Python type drives what a ``ys.File`` resolves to (annotation-directed
output — consistent with ``ys.Title``/``ys.Price`` and ``ys.js``). ``output_view_for_annotation``
maps a supported type to one of a small, closed set of views and *raises* on anything else,
so an unsupported/ambiguous annotation fails loudly at contract-definition time.
"""

from __future__ import annotations

from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from yosoi.models.replay import utc_now

DownloadMode = Literal['retrigger', 'refetch']

# Closed set of output projections a ys.File() field can resolve to.
#   record → DownloadRecord handle | path → Path | bytes → raw | text → decoded str
#   parsed → file parsed (csv/json by content-type) then validated against the annotation
OutputView = Literal['record', 'path', 'bytes', 'text', 'parsed']


class DownloadRecord(BaseModel):
    """Provenance for one downloaded file (and the value of a ``ys.DownloadRecord`` field).

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
    ``output`` is the view selected by the field's declared type.
    """

    field: str
    mode: DownloadMode = 'retrigger'
    trigger: str | None = None  # CSS selector to click (retrigger)
    href: str | None = None  # CSS selector yielding an href (refetch)
    url: str | None = None  # literal URL (refetch)
    allowed_types: tuple[str, ...] = ()
    output: OutputView = 'record'
    max_bytes: int | None = None


class DownloadResult(BaseModel):
    """A completed download: its provenance record plus the field's resolved value.

    ``value`` is the view chosen by the field's annotation (path / bytes / text / parsed
    structure), or the ``DownloadRecord`` itself for a ``record`` field. The merge step
    writes ``value`` into the extracted record; ``record`` stays available for provenance.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    record: DownloadRecord
    value: Any = None
    # True when this field's bytes differ from the last recorded download (drift), per the
    # per-domain content-addressed index. None when drift wasn't evaluated.
    changed: bool | None = None


def _strip_optional(annotation: Any) -> Any:
    """Unwrap ``Optional[X]`` / ``X | None`` to ``X`` (leaves other types untouched)."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def output_view_for_annotation(annotation: Any) -> OutputView:
    """Map a ys.File field's declared type to its output view, or raise if unsupported.

    Called both at contract-definition time (fail-loud guard) and when building specs.
    """
    ann = _strip_optional(annotation)
    if ann is DownloadRecord:
        return 'record'
    if ann is Path:
        return 'path'
    if ann is bytes:
        return 'bytes'
    if ann is str:
        return 'text'
    origin = get_origin(ann)
    if ann is dict or ann is list or origin is dict or origin is list:
        return 'parsed'
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return 'parsed'
    raise ValueError(
        f'ys.File field type {annotation!r} is not supported. Annotate one of: '
        'ys.DownloadRecord, pathlib.Path, bytes, str, dict, list (or list[...]), '
        'or a Pydantic model.'
    )


__all__ = [
    'DownloadMode',
    'DownloadRecord',
    'DownloadResult',
    'DownloadSpec',
    'OutputView',
    'output_view_for_annotation',
]
