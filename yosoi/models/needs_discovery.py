"""Typed cache-miss result returned by the scrape replay path.

When ``resolve()`` has no cached selectors for a (domain, contract) pair it
returns a :class:`NeedsDiscovery` instead of records.  The CLI emits this as
JSON on stdout and exits with code 2 so agents can branch on the result
without parsing free-text output::

    {
        "type": "needs_discovery",
        "domain": "example.com",
        "contract_fingerprint": "abc123def456...",
        "fields": ["headline", "author", "date"]
    }
"""

from __future__ import annotations

from pydantic import BaseModel


class NeedsDiscovery(BaseModel):
    """Typed signal that a scrape cannot replay — discovery is required first."""

    type: str = 'needs_discovery'
    domain: str
    contract_fingerprint: str
    fields: list[str]
    message: str = 'No cached selectors found. Run `yosoi discover` to populate the selector cache.'

    def to_exit_json(self) -> str:
        """Return compact JSON string for stdout emission under --json."""
        return self.model_dump_json()
