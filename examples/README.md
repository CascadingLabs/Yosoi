# Examples

The examples are intentionally selector-free. They define data contracts and let
Yosoi discover selectors from the page structure.

## qscrape.dev

`qscrape.dev` is the maintained example target. Each level uses the same domain
with increasing rendering complexity:

- `l1/`: static HTML pages that the default auto fetcher handles at L1.
- `l2/`: JavaScript-rendered pages that the default auto fetcher promotes as needed.
- `l3/`: island-rendered pages that the default auto fetcher promotes as needed.

The scripts build a small `ys.Policy` layer and cascade it with `ys.Policy.from_env()`.
That keeps provider/model, force, discovery mode, and telemetry env switches in one
place while each example only declares the behavior it needs.

L1 scripts set `ScrapePolicy(fetcher_type='simple')`. L2/L3 scripts use the default
auto fetcher and set `ScrapePolicy(selector_level=ys.SelectorLevel.XPATH)` because
those pages exercise rendered DOM structure.

Set `YOSOI_MODEL` to choose a provider/model, and set `YOSOI_FORCE=1` when you
want to force rediscovery instead of replaying a cached contract. The examples do
not pass those as loose kwargs; `Policy.from_env()` reads them.

Each level has examples for:

- `eshop/catalog.py`
- `news/articles.py`
- `scoretap/scores.py`
- `taxes/registry.py`

Run one directly, for example:

```bash
YOSOI_MODEL=groq:llama-3.3-70b-versatile \
uv run python examples/qscrape.dev/l1/eshop/catalog.py
```

## Crawl

`crawl_qscrape_articles.py` shows the crawl-to-contract workflow. It seeds from
the qscrape.dev L1 root, lets `ys.crawl(...)` traverse the small demo domain and
build the `NewsArticle` URL candidates, then scrapes that list when a model is configured. It sets
`respect_robots=False` because qscrape.dev is the maintained demo target for
these examples.

```bash
uv run python examples/crawl_qscrape_articles.py
```

`scrape_qscrape_l2_news_articles.py` is the rendered L2 companion. It targets
the qscrape.dev L2 news archive with the built-in `ys.NewsArticle` contract and
uses the auto JS waterfall fetcher so extraction happens after rendering.

```bash
uv run python examples/scrape_qscrape_l2_news_articles.py
```

`crawl_qscrape_l2_news_articles.py` is the crawl-only rendered L2 companion. It
starts at `https://qscrape.dev/l2/`, keeps the crawl scoped to qscrape.dev, and
prints only `NewsArticle` crawl candidates.

```bash
uv run python examples/crawl_qscrape_l2_news_articles.py
```

`crawl_yahoo_finance.py` is the finance-news API example. It seeds from Yahoo
Finance news, runs a quiet host-scoped crawl, and shows only the crawler-built
`NewsArticle` URL candidates. Set `YOSOI_CRAWL_DEBUG=1` when you want the crawl
frontier diagnostics.

```bash
uv run python examples/crawl_yahoo_finance.py
```

`crawl_public_stress.py` runs 12 bounded public-web crawl cases and renders one
comparison table. Use it before a release when you want to find crawl policy,
fetching, and display rough edges across varied real sites.

```bash
uv run python examples/crawl_public_stress.py
```

`crawl_policy_article_candidates_usecase.py` is the policy-as-code companion. It
runs a small live qscrape.dev crawl and shows how crawl budgets, host
allow-lists, blocked paths, worker limits, path planning, and invalid-policy
checks behave before a large candidate crawl runs.

```bash
uv run python examples/crawl_policy_article_candidates_usecase.py
```

## Google Search

`google_search/google_search.py` is an offline replay example. It exercises
parametrized navigation, teleport settings, captcha recovery, and contract
signatures without making live Google traffic.

```bash
uv run python examples/google_search/google_search.py
```

## API Design

`api_design/policy_api_design.py` is a no-network showcase for the full public
policy tree: `ModelPolicy`, `ScrapePolicy`, `DiscoveryPolicy`, `TelemetryPolicy`,
`OutputPolicy`, `DownloadPolicy`, and `CrawlPolicy`, plus `SecretRef.env(...)`
and `ResolvedRunSpec`.

```bash
uv run python examples/api_design/policy_api_design.py
```
