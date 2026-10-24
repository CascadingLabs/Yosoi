"""Bounded offline DOM inspection using Rust's capture-bound View."""

from __future__ import annotations

from typing import Self

from pydantic import Field, StrictBool, StrictStr

from . import _native
from ._models import ImmutableModel
from .archive import _rust_json
from .browser import Observation
from .outcomes import NodeReference

__all__ = ["DomElementRow", "View", "ViewCaptureToken", "ViewCursor", "ViewSource"]


class ViewSource(ImmutableModel):
    """Provenance of retained evidence, without browser control authority.

    Attributes:
        observation_id: Immutable captured observation identity.
        session_id: Recorded browser Session identity.
        tab_id: Recorded tab identity.
        document_epoch: Positive captured document generation.
        url: Optional observed source URL, never fetched by View.
    """

    observation_id: StrictStr
    session_id: StrictStr
    tab_id: StrictStr
    document_epoch: int = Field(strict=True, ge=1, le=2**64 - 1)
    url: StrictStr | None = None


class ViewCaptureToken(ImmutableModel):
    """Capture binding retained by each View and continuation cursor.

    Attributes:
        source: Exact captured provenance.
        fingerprint: Advisory HTML fingerprint, not a cryptographic integrity digest.
    """

    source: ViewSource
    fingerprint: int = Field(strict=True, ge=0, le=2**64 - 1)


class ViewCursor(ImmutableModel):
    """Continuation position that Rust validates against the original capture.

    Attributes:
        capture: Binding to exact observation provenance and retained HTML.
        offset: Next element offset, checked by Rust on continuation.
        page_size: Requested row bound, at most 100.
    """

    capture: ViewCaptureToken
    offset: int = Field(strict=True, ge=0, le=2**64 - 1)
    page_size: int = Field(strict=True, ge=1, le=100)


class DomElementRow(ImmutableModel):
    """One exact DOM element reference with a bounded descendant text preview.

    Attributes:
        ordinal: Zero-based element position in captured document order.
        node: Document-bound native locator coordinates.
        text_preview: At most 512 characters of retained descendant text.
        text_truncated: Whether the complete descendant text exceeded that bound.
    """

    ordinal: int = Field(strict=True, ge=0, le=2**64 - 1)
    node: NodeReference
    text_preview: StrictStr
    text_truncated: StrictBool


class View(ImmutableModel):
    """One bounded page of captured DOM evidence, independent of a live browser.

    Attributes:
        source: Captured observation provenance.
        capture: Binding used to reject foreign or changed observations.
        rows: Up to page_size DOM element references and text previews.
        total_rows: Total elements in captured HTML, not the current live DOM.
        page_size: Requested row bound, at most 100.
        next_cursor: Validated continuation position, or None after the last page.
    """

    source: ViewSource
    capture: ViewCaptureToken
    rows: tuple[DomElementRow, ...]
    total_rows: int = Field(strict=True, ge=0, le=2**64 - 1)
    page_size: int = Field(strict=True, ge=1, le=100)
    next_cursor: ViewCursor | None = None

    @classmethod
    def from_observation(cls, observation: Observation, page_size: int = 20) -> Self:
        """Inspect captured HTML with 1–100 rows; ArchiveError reports invalid input.

        This parses retained evidence only. It does not fetch the recorded URL or
        prove current visibility. Cursors use an advisory fingerprint; Archive
        independently verifies stored payload integrity.
        """
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer from 1 to 100")
        return cls.model_validate_json(
            _native.observation_view(_rust_json(observation), page_size)
        )

    @classmethod
    def continue_from(cls, observation: Observation, cursor: ViewCursor) -> Self:
        """Read the next page; ArchiveError rejects foreign or stale cursors."""
        return cls.model_validate_json(
            _native.observation_view(
                _rust_json(observation), cursor=cursor.model_dump_json()
            )
        )
