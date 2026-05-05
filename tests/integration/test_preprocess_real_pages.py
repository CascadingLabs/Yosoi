"""CAS-18 spike validation against real-world page snapshots.

Skipped when no snapshots are present. Refresh them with::

    uv run python scripts/fetch_preprocess_snapshots.py

Each snapshot is processed end-to-end through the preprocessor and the
following spike-success conditions are asserted:

1. Median ``tokens_out / tokens_in`` < 0.7 across the snapshot set.
2. Selectors discoverable on the original tree still resolve on the
   preprocessed tree (selectors-hold proxy: structural anchors survive).
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest
from parsel import Selector

from yosoi.core.cleaning.preprocess import HTMLPreprocessor

REAL_DIR = Path(__file__).parents[1] / 'data' / 'preprocess' / 'real'


def _real_snapshots() -> list[Path]:
    return sorted(REAL_DIR.glob('*.html'))


@pytest.mark.skipif(not _real_snapshots(), reason='No real snapshots — run scripts/fetch_preprocess_snapshots.py')
def test_real_pages_meet_token_reduction_target() -> None:
    """Spike condition #1 against fetched snapshots."""
    pp = HTMLPreprocessor()
    ratios: list[float] = []
    for path in _real_snapshots():
        result = pp.preprocess(path.read_text())
        ratios.append(result.reduction_ratio)
    median_ratio = statistics.median(ratios)
    assert median_ratio < 0.7, f'median ratio {median_ratio:.3f} >= 0.7 across {len(ratios)} real pages: {ratios}'


@pytest.mark.skipif(not _real_snapshots(), reason='No real snapshots')
def test_real_pages_preserve_structural_anchors() -> None:
    """Spike condition #3 (selectors hold): content-anchor selectors survive.

    True selector validation needs the discovery LLM in the loop. As an
    offline proxy we sample structural anchors of the type the LLM actually
    discovers — semantic content tags (h1-h6, article, main, section, nav,
    aside, time) and content-area ids. SVG-internal ids and ``<script
    id=...>`` are excluded because tier-1/tier-2 deliberately drop those and
    the discovery LLM never targets them.
    """
    pp = HTMLPreprocessor()
    failures: list[str] = []
    # CSS for "ids on selector-relevant content elements" — excludes svg/path/g/
    # linearGradient/mask/clipPath/script which are scrubbed by the spike's
    # tier-1 + tier-2 transforms by design.
    content_id_css = (
        'h1[id], h2[id], h3[id], h4[id], h5[id], h6[id],'
        ' article[id], main[id], section[id], nav[id], aside[id], time[id],'
        ' div[id], span[id], p[id], a[id], ul[id], ol[id], li[id], table[id],'
        ' tr[id], td[id], th[id], header[id], footer[id], form[id], button[id],'
        ' input[id], img[id], figure[id], blockquote[id]'
    )
    semantic_tag_css = ('h1', 'h2', 'h3', 'main', 'article', 'section', 'nav', 'aside')
    for path in _real_snapshots():
        raw = path.read_text()
        out = pp.preprocess(raw).html
        before = Selector(text=raw)
        after = Selector(text=out)
        for css in (*semantic_tag_css, content_id_css):
            before_count = len(before.css(css))
            after_count = len(after.css(css))
            if before_count == 0:
                continue
            label = 'content_ids' if css == content_id_css else css
            # 30% slack: minor drops from extreme edge cases (e.g. an
            # ``id`` on an inline event-handler-only element) are
            # tolerable, but the bulk must survive.
            if after_count < before_count * 0.7:
                failures.append(f'{path.name}: {label!r} lost {before_count - after_count} of {before_count}')
    assert not failures, '\n'.join(failures)
