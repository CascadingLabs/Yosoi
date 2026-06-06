"""Yahoo Finance fixtures: page_shape across subdomains, domains, and sub-page paths.

The point of the page-shape fingerprint is that it is keyed on a page's STRUCTURE, not
its URL — so every Yahoo Finance *quote* page collapses into one shape bucket whether
it is served from ``finance.yahoo.com/quote/AAPL``, ``finance.yahoo.com/quote/MSFT``
(a different path), or ``uk.finance.yahoo.com/quote/MSFT`` (a different subdomain). A
genuinely different template (news feed, screener table) must land in a DIFFERENT
bucket. These fixtures make both halves testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass


def quote_page(name: str, ticker: str, price: str) -> str:
    """One Yahoo-Finance-style QUOTE page. Same structural template for every ticker —
    only the human-readable content (name/ticker/price) changes, so the tag skeleton
    (and thus the page shape) is identical across tickers."""
    return f"""<body class="quote-page">
  <header><nav><a href="/">Finance</a><a href="/watchlists">Watchlists</a></nav></header>
  <div id="quote-header-info">
    <h1>{name} ({ticker})</h1>
    <fin-streamer data-field="regularMarketPrice">{price}</fin-streamer>
    <fin-streamer data-field="regularMarketChange">+1.23</fin-streamer>
  </div>
  <div id="quote-summary">
    <table><tbody>
      <tr><td>Previous Close</td><td>171.05</td></tr>
      <tr><td>Open</td><td>171.91</td></tr>
      <tr><td>Market Cap</td><td>2.7T</td></tr>
    </tbody></table>
  </div>
  <nav class="quote-tabs"><a href="#summary">Summary</a><a href="#news">News</a><a href="#chart">Chart</a></nav>
</body>"""


# Quote pages — same template, varied ticker / path / subdomain / TLD.
AAPL_US = quote_page('Apple Inc.', 'AAPL', '171.52')
MSFT_US = quote_page('Microsoft Corporation', 'MSFT', '378.91')
MSFT_UK = quote_page('Microsoft Corporation', 'MSFT', '378.91')  # uk.finance.yahoo.com

# A different Yahoo Finance template: a NEWS feed (articles, no quote header/summary).
NEWS_PAGE = """<body class="news-page">
  <header><nav><a href="/">Finance</a><a href="/news">News</a></nav></header>
  <main>
    <article><h3><a href="/news/markets-rally">Markets rally on earnings</a></h3><p>Stocks climbed...</p><time>2h ago</time></article>
    <article><h3><a href="/news/fed-rates">Fed holds rates steady</a></h3><p>The central bank...</p><time>4h ago</time></article>
    <article><h3><a href="/news/oil-up">Oil prices rise</a></h3><p>Crude futures...</p><time>6h ago</time></article>
  </main>
</body>"""

# Another different template: a SCREENER table (many rows of th/td, no articles).
SCREENER_PAGE = """<body class="screener-page">
  <header><nav><a href="/">Finance</a><a href="/screener">Screener</a></nav></header>
  <table class="screener">
    <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th>Volume</th></tr></thead>
    <tbody>
      <tr><td>AAPL</td><td>171.52</td><td>+1.23</td><td>54M</td></tr>
      <tr><td>MSFT</td><td>378.91</td><td>+2.10</td><td>22M</td></tr>
      <tr><td>AMZN</td><td>146.80</td><td>-0.45</td><td>41M</td></tr>
      <tr><td>GOOG</td><td>139.10</td><td>+0.88</td><td>18M</td></tr>
    </tbody>
  </table>
</body>"""


@dataclass(frozen=True)
class YahooPage:
    """A fixture page + the URL it stands in for + its shape-family label."""

    url: str
    html: str
    family: str  # pages sharing a family must share a page_shape bucket


PAGES: list[YahooPage] = [
    YahooPage('https://finance.yahoo.com/quote/AAPL', AAPL_US, 'quote'),
    YahooPage('https://finance.yahoo.com/quote/MSFT', MSFT_US, 'quote'),
    YahooPage('https://uk.finance.yahoo.com/quote/MSFT', MSFT_UK, 'quote'),
    YahooPage('https://finance.yahoo.com/news', NEWS_PAGE, 'news'),
    YahooPage('https://finance.yahoo.com/screener', SCREENER_PAGE, 'screener'),
]
