"""Turn fetched HTML into a :class:`PageObservation` (network-free).

The recommender consumes cheap, capture-time observations, not raw HTML. This
adapter computes one from an HTML string: the document title, the ``<body>``
class tokens, the tag-frequency histogram, and the count of elements matched by a
caller-supplied row/item selector (the recipe's repeating unit).

It uses ``parsel`` (already a Yosoi dependency) and does no I/O, so it is safe to
call on HTML obtained from any fetcher — or on a stored fixture for deterministic,
offline tests.
"""

from __future__ import annotations

from collections import Counter

from parsel import Selector

from yosoi.generalization.fingerprint import PageObservation


def observe_html(url: str, html: str, *, row_selector: str) -> PageObservation:
    """Build a :class:`PageObservation` from an HTML document.

    Args:
        url: The URL the HTML was fetched from (used for route canonicalization).
        html: The full HTML document text.
        row_selector: CSS selector for the recipe's repeating item (e.g. the
            quote/post/product container). Its match count becomes ``rows``.

    Returns:
        A :class:`PageObservation` with title, row count, body-class tokens, and
        the tag-frequency histogram of the document body.
    """
    sel = Selector(text=html)
    title = (sel.css('title::text').get() or '').strip()
    body_class = (sel.css('body::attr(class)').get() or '').strip()

    # Tag histogram over body descendants (fall back to whole doc if no <body>).
    scope = sel.css('body') or sel
    tag_names = scope.xpath('.//*').xpath('name()').getall()
    tag_hist = dict(Counter(name.lower() for name in tag_names))

    rows = 0
    if row_selector:
        try:
            rows = len(sel.css(row_selector))
        except (ValueError, SyntaxError):
            rows = 0

    return PageObservation(
        url=url,
        title=title,
        rows=rows,
        body_class=body_class,
        tag_hist=tag_hist,
    )
