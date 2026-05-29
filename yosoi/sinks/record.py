"""The content record contract shared by every :class:`ContentSink` backend.

This is Yosoi's public output shape for extracted content. It is deliberately
narrow and makes no assumptions about the database underneath: a record is just
*what* was scraped (``content``), *where* from (``url`` / ``source``), and
*when* (``scraped_at``). Entity resolution and canonicalisation belong in the
downstream consumer, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, JsonValue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContentRecord(BaseModel):
    """A single append-only unit of extracted content.

    Every scrape produces a new record; sinks never overwrite. ``scraped_at``
    is what distinguishes successive versions of the same ``url``.

    Attributes:
        url: The page the content was extracted from.
        content: The extracted payload. Any JSON-serialisable value — typically
            a dict for single-item pages or a list of dicts for multi-item pages.
        scraped_at: Timezone-aware capture time. Defaults to ``now()`` in UTC.
        source: Free-form provenance label (e.g. the fetcher tier, pipeline
            name, or run id) chosen by the producer.

    """

    url: str
    content: JsonValue
    scraped_at: datetime = Field(default_factory=_utc_now)
    source: str
