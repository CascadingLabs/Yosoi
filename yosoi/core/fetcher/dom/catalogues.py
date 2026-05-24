"""Text patterns and CSS selectors used for trigger and obstacle detection.

Pure data — no logic. Import from here rather than defining inline so
patterns are easy to extend without touching any logic files.

FUTURE: teach the discovery agent to propose or generate these catalogues,
using this module as examples instead of relying on hand-maintained lists.
"""

# ---------------------------------------------------------------------------
# Obstacle patterns — things blocking content before scraping can start
# ---------------------------------------------------------------------------

COOKIE_SELECTORS = (
    '[id*="cookie"] button',
    '[class*="cookie"] button',
    '[id*="consent"] button',
    '[class*="consent"] button',
    '[aria-label*="cookie" i] button',
    '[aria-label*="accept" i]',
    'button[id*="accept"]',
    'button[class*="accept"]',
)

POPUP_SELECTORS = (
    '[role="dialog"] [aria-label*="close" i]',
    '[role="dialog"] button[class*="close"]',
    '.modal [class*="close"]',
    '.modal button[aria-label*="close" i]',
    '[class*="popup"] [class*="close"]',
    '[class*="overlay"] [class*="close"]',
)

AGE_GATE_SELECTORS = (
    '[id*="age-gate"] button',
    '[class*="age-gate"] button',
    '[id*="age-verify"] button',
    '[class*="age-verify"] button',
)

# ---------------------------------------------------------------------------
# Content trigger patterns
# ---------------------------------------------------------------------------

LOAD_MORE_TEXTS = (
    'load more',
    'show more',
    'view more',
    'see more',
    'more results',
    'more posts',
    'more items',
    'remaining',
)

NEXT_PAGE_TEXTS = (
    'next',
    'next page',
    'older posts',
    '\u00bb',
    '\u203a',
)

PAGINATION_SELECTORS = (
    'a[rel="next"]',
    'a[aria-label="Next"]',
    'a.next',
    'a.pagination-next',
    '[data-testid="next-page"]',
)

ACCORDION_SELECTORS = (
    '[aria-expanded="false"]',
    'details:not([open])',
)

TAB_SELECTOR = '[role="tab"]:not([aria-selected="true"])'

# ---------------------------------------------------------------------------
# Content counting selector — used to measure whether actions revealed content
# ---------------------------------------------------------------------------

CONTENT_SELECTOR = (
    'article, [data-article-id], [data-item], [data-product-id], .card, .item, .result, .listing, .post, .entry'
)

# ---------------------------------------------------------------------------
# JS snippets used in actions
# ---------------------------------------------------------------------------

CLICK_BY_TEXT_JS = """
(() => {{
    const el = [...document.querySelectorAll(
        'button, a[role="button"], [type="button"]'
    )].find(e =>
        e.textContent.toLowerCase().includes({needle!r})
        && !e.disabled && e.offsetParent !== null
    );
    if (el) {{ el.click(); return true; }}
    return false;
}})()
"""

CLICK_LINK_BY_TEXT_JS = """
(() => {{
    const el = [...document.querySelectorAll('a[href]')]
        .find(e => e.textContent.trim().toLowerCase() === {needle!r});
    if (el) {{ el.click(); return true; }}
    return false;
}})()
"""
