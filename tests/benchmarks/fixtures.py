"""Deterministic HTML/selector/contract fixtures for CodSpeed benchmarks.

These builders synthesize realistic page bodies offline so benchmarks have a
stable, network-free, LLM-free workload that mirrors the *cache-replay* hot
path (clean -> extract -> validate). Two page shapes stand in for the two
classes of real targets:

* **L1** — a single-record article page (news/blog). Moderate DOM, one record.
* **L2** — a repeating-item catalog/listing page (the rendered output of a
  JS-heavy site after DOMLoader settles). Large DOM, N records.

Sizes are driven by item/paragraph counts so a benchmark can sweep input
sensitivity (e.g. 20 vs 200 vs 1000 products) without touching the network.
Content is index-derived, never random, so byte size is reproducible run to run.
"""

from __future__ import annotations

from rich.console import Console

import yosoi as ys
from yosoi.models.contract import Contract

# Quiet console shared by every benchmark so measured code never pays for
# terminal I/O (the real pipeline passes a configured console in too).
QUIET_CONSOLE = Console(quiet=True)

# ---------------------------------------------------------------------------
# Contracts (mirror the real discovered books.toscrape.com / news fixtures)
# ---------------------------------------------------------------------------


class BookContract(Contract):
    """Catalog item — mirrors the cached books.toscrape.com selector shape."""

    title: str = ys.Title()
    price: float = ys.Price()
    rating: str = ys.Field(description='Star rating, expressed as a word (e.g. "Three")')


class ArticleContract(Contract):
    """Single-record article page."""

    title: str = ys.Title()
    author: str = ys.Author()
    published: str = ys.Datetime()
    body: str = ys.BodyText()


# Selector maps use the *string* shape the extractor accepts directly
# (dict[field][level] = css string). Values are copied from the real discovered
# snapshot for books.toscrape so the CSS engine does representative work.
BOOK_SELECTORS: dict[str, dict[str, str]] = {
    'title': {
        'primary': 'article.product_pod h3 a',
        'fallback': '.product_pod h3',
        'tertiary': 'h3 a',
    },
    'price': {
        'primary': 'article.product_pod p.price_color',
        'fallback': '.product_price .price_color',
        'tertiary': '.price_color',
    },
    'rating': {
        'primary': 'article.product_pod p.star-rating::attr(class)',
        'fallback': "article.product_pod p[class*='star-rating']::attr(class)",
        'tertiary': 'p.star-rating::attr(class)',
    },
}
BOOK_CONTAINER = 'article.product_pod'

ARTICLE_SELECTORS: dict[str, dict[str, str]] = {
    'title': {'primary': 'main h1.headline', 'fallback': 'h1'},
    'author': {'primary': 'main .byline .author', 'fallback': '.author'},
    'published': {'primary': 'main time.published::attr(datetime)', 'fallback': 'time::attr(datetime)'},
    'body': {'primary': 'main article.post p', 'fallback': 'article p'},
}

_RATINGS = ('One', 'Two', 'Three', 'Four', 'Five')

# A chunk of inline noise the cleaner is expected to strip (svg, script, style,
# comments, data-uri image). Kept constant so it contributes fixed overhead.
_NOISE_HEAD = """
<head>
  <style>.product_pod{margin:0}.price_color{color:green}</style>
  <script>window.__INITIAL_STATE__={};function track(){return 1}</script>
  <!-- analytics bootstrap comment that should be stripped -->
</head>
"""

_NOISE_CHROME = """
<header class="site-header"><nav class="main-nav"><ul>
  <li><a href="/">Home</a></li><li><a href="/about">About</a></li>
</ul></nav></header>
<aside class="sidebar"><div class="widget">Newsletter</div>
  <div class="advertisement"><img src="data:image/png;base64,AAAABBBBCCCCDDDD" alt="ad"/></div>
</aside>
"""

_NOISE_FOOTER = '<footer class="site-footer"><p>© Example</p></footer>'

_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2L2 22h20z"/><circle cx="12" cy="12" r="4"/></svg>'


def _product_card(i: int) -> str:
    rating = _RATINGS[i % len(_RATINGS)]
    price = f'£{10 + (i % 90)}.{i % 100:02d}'
    return (
        '<article class="product_pod">'
        f'<div class="image_container"><a href="/catalogue/book-{i}/">{_SVG}'
        f'<img src="data:image/jpeg;base64,FFFFEEEEDDDD" class="thumbnail" alt="b{i}"/></a></div>'
        f'<p class="star-rating {rating}"></p>'
        f'<h3><a href="/catalogue/book-{i}/" title="Book Number {i}">Book Number {i}</a></h3>'
        '<div class="product_price">'
        f'<p class="price_color">{price}</p>'
        '<p class="instock availability">In stock</p>'
        '<form><button type="submit" class="btn">Add to basket</button></form>'
        '</div></article>'
    )


def build_catalog_html(n_items: int) -> str:
    """Render an L2 catalog page with *n_items* repeating product cards."""
    cards = ''.join(_product_card(i) for i in range(n_items))
    return (
        '<!DOCTYPE html><html lang="en">'
        f'{_NOISE_HEAD}'
        '<body>'
        f'{_NOISE_CHROME}'
        '<main><section class="page"><div class="page_inner">'
        '<ol class="row">'
        f'{cards}'
        '</ol></div></section></main>'
        f'{_NOISE_FOOTER}'
        '</body></html>'
    )


def _paragraph(i: int) -> str:
    # Deterministic, prose-like filler of stable length.
    words = ' '.join(f'token{i}-{j}' for j in range(40))
    return f'<p>{words}.</p>'


def build_article_html(n_paragraphs: int) -> str:
    """Render an L1 single-record article page with *n_paragraphs* body paras."""
    body = ''.join(_paragraph(i) for i in range(n_paragraphs))
    return (
        '<!DOCTYPE html><html lang="en">'
        f'{_NOISE_HEAD}'
        '<body>'
        f'{_NOISE_CHROME}'
        '<main>'
        '<h1 class="headline">Markets rally as benchmarks improve across the board</h1>'
        '<div class="byline">By <span class="author">Ada Lovelace</span> · '
        '<time class="published" datetime="2026-05-30T09:30:00Z">May 30, 2026</time></div>'
        f'<article class="post">{body}</article>'
        '</main>'
        f'{_NOISE_FOOTER}'
        '</body></html>'
    )


def build_spa_html(n_items: int, heap_mb: int = 25) -> str:
    """Render an L2/SPA proxy: same catalog DOM, but *client-rendered* via JS plus
    a retained ~*heap_mb* MB V8 heap (framework runtime + app store + node refs).

    A real SPA's per-tab memory is dominated by the renderer's JavaScript heap,
    not the served HTML. A static page never allocates that, so it badly
    under-estimates SPA cost. This fixture forces the renderer to: run JS, build
    the DOM client-side from an in-memory store, and *retain* a tunable heap on
    ``window`` (defeating GC) — a deterministic, offline stand-in you can dial to
    match a real target you've profiled (``heap_mb``). It is a proxy, not any one
    real site; pass ``--url`` to the harness to calibrate against a live SPA.
    """
    # ~1 KB one-byte strings; heap_mb * 1024 of them ≈ heap_mb MB of retained data.
    n_chunks = max(0, heap_mb) * 1024
    return (
        '<!DOCTYPE html><html lang="en">'
        f'{_NOISE_HEAD}'
        '<body>'
        f'{_NOISE_CHROME}'
        '<main><div id="app">loading…</div></main>'
        f'{_NOISE_FOOTER}'
        '<script>'
        '(function(){'
        # Retained heap: simulate an app store / framework state kept alive.
        f'var heap=[];for(var h=0;h<{n_chunks};h++){{heap.push("x".repeat(1024));}}'
        'window.__store__=heap;'
        # Client-render the catalog DOM from an in-memory model (the SPA pattern).
        f'var model=[];for(var i=0;i<{n_items};i++){{'
        'model.push({id:i,title:"Book Number "+i,price:(10+(i%90))+"."+("0"+(i%100)).slice(-2),'
        'rating:["One","Two","Three","Four","Five"][i%5]});}'
        'window.__model__=model;'
        'var html="<ol class=\\"row\\">";'
        'for(var j=0;j<model.length;j++){var m=model[j];'
        'html+="<article class=\\"product_pod\\"><p class=\\"star-rating "+m.rating+"\\"></p>'
        '<h3><a href=\\"/catalogue/book-"+m.id+"/\\">"+m.title+"</a></h3>'
        '<div class=\\"product_price\\"><p class=\\"price_color\\">£"+m.price+"</p></div></article>";}'
        'html+="</ol>";'
        'var app=document.getElementById("app");app.innerHTML=html;'
        # Retain node references too (listeners/refs an SPA framework would hold).
        'window.__nodes__=Array.prototype.slice.call(document.querySelectorAll("article"));'
        '})();'
        '</script>'
        '</body></html>'
    )
