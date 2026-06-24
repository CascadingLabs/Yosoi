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

`qscrape.dev/full_crawl.py` is a full-site crawl inventory stress example, not a
quickstart. It seeds only `https://qscrape.dev/`, keeps the crawl scoped to that
host, uses the auto static/rendered fetch waterfall, and prints neutral crawl
inventory plus advisory scrape-target URLs. It does **not** perform contract
candidate scoring or multi-contract scraping; those belong in downstream
planner/validator layers.

The example is configured for a local VoidCrawl Docker CDP farm. Override the
endpoints with `YOSOI_CHROME_WS_URLS` when needed.

```bash
YOSOI_CHROME_WS_URLS=http://127.0.0.1:9222,http://127.0.0.1:9223 \
uv run python examples/qscrape.dev/full_crawl.py
```

`qscrape.dev/full_crawl_v2.py` extends that inventory into validated-exemplar
fingerprint ranking for multiple explicit contracts. It uses small positive and
contrastive exemplar sets to rank same-domain target pages without LLM calls on
the common path, then writes selected-target and all-frontier evaluation artifacts.
Rows are still `verified=false` until optional Yosoi scrape/discovery verification
succeeds.

```bash
YOSOI_CHROME_WS_URLS=http://127.0.0.1:9222,http://127.0.0.1:9223 \
uv run python examples/qscrape.dev/full_crawl_v2.py
```

`qscrape.dev/full_crawl_v2_alt.py` is the harder binary version: it only cares
about finding `NewsArticle` targets and uses positive NewsArticle exemplars only.
Every other crawled page is a `NoContract` evaluation label, not a contrastive
scoring input. This exposes the edge: one to four same-template positives miss
another news article template, while five diverse positives cover it.

```bash
YOSOI_CHROME_WS_URLS=http://127.0.0.1:9222,http://127.0.0.1:9223 \
uv run python examples/qscrape.dev/full_crawl_v2_alt.py
```

`qscrape.dev/full_crawl_v3.py` adds the end-to-end scrape gate for that binary
NewsArticle flow. It crawls, classifies NewsArticle candidates, then scrapes every
accepted candidate with the `NewsArticle` contract and writes a per-URL scrape-gate
artifact. Set `YOSOI_FULL_CRAWL_V3_SCRAPE=0` to skip the scrape phase.

```bash
YOSOI_MODEL=groq:llama-3.3-70b-versatile \
YOSOI_CHROME_WS_URLS=http://127.0.0.1:9222,http://127.0.0.1:9223 \
uv run python examples/qscrape.dev/full_crawl_v3.py
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
