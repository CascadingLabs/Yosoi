"""Crawler mixin — frontier/crawl helpers and future CAS-52 gating methods.

Currently a placeholder for _discover_and_push and related link expansion logic
that will land with CAS-52 (related-link expansion with relevance gating).
"""

from __future__ import annotations


class PipelineCrawlerMixin:
    """Frontier and crawl-related helpers.

    This mixin is intentionally sparse today. CAS-52 (related-link expansion
    with relevance gating) will add ``_discover_and_push`` and related methods
    here without touching the rest of the pipeline.
    """
