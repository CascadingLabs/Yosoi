---
name: yosoi-fetch
description: Use when acquiring web page evidence with Yosoi without scraping: safe LLM-bounded content previews, raw/static HTML, rendered HTML, cleaned HTML, text/markdown, links, headers, network endpoints, accessibility snapshots, bundles, and advisory contract probes via `yosoi fetch` or `ys.fetch`.
---

# Yosoi Fetch

Use this skill when the task is: “get the page evidence safely,” “inspect what Yosoi sees,” “capture raw/rendered/clean page artifacts,” “feed an LLM a bounded page view,” or “probe whether a contract/cache likely fits this page.”

`fetch` is **page acquisition**, not scraping:

- No LLM discovery.
- No selector writes.
- No structured extraction contract result.
- Optional contract probes are advisory cache/fingerprint checks only.
- Safe default is bounded text: `--view text --chars 12000 --page 1`.

## Mental Model

Choose the command by intent:

| Intent | Use |
| --- | --- |
| Inspect/capture one or a few pages | `yosoi fetch` / `ys.fetch` |
| Walk a site/frontier | `yosoi crawl` |
| Populate selector cache for a contract | `yosoi discover` |
| Extract structured records | `yosoi scrape` |
| Find candidate URLs | `yosoi search` / `yosoi map` |

Use `fetch` before `discover`/`scrape` when you need evidence about what is actually visible, whether JS/browser rendering is needed, what links/network/AX signals exist, or whether an existing contract cache looks plausible.

## Default Safe Pattern

Always prefer a bounded first look:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch "https://example.com/page" --chars 12000 --json
```

Read:

- `status`
- `results[0].view`
- `results[0].content`
- `results[0].content_chars`
- `results[0].total_chars`
- `results[0].truncated`
- `results[0].next_page`
- `results[0].raw_html_chars`
- `results[0].cleaned_html_chars`
- `results[0].fetcher_type`

If `truncated=true`, request the next page instead of dumping all content:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch "https://example.com/page" --chars 12000 --page 2 --json
```

Never paste unbounded HTML into the LLM context unless explicitly requested and small enough.

## CLI Surface

```bash
yosoi fetch URL...
  --view text|markdown|html|clean-html|raw-html|rendered-html|ax|links|metadata|bundle
  --fetcher auto|simple|headless|headful|waterfall
  --chars N
  --page N
  --page-size N
  --include headers,network,endpoints,fingerprint,links,ax
  --contract @Contract
  --output FILE|DIR
  --json
  --dump-request
```

Notes:

- `--chars` is an alias for `--page-size`.
- `--page` is 1-indexed.
- `network` is accepted as an alias for `endpoints`.
- `--json` emits the full machine envelope.
- Human stdout emits only the selected bounded `content`.
- `yosoi content` has been removed. Use `yosoi fetch`.

## Views

### `text` — safe default

Deterministic text extraction from cleaned HTML. Best first view for LLM context.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view text --chars 12000 --json
```

Use for:

- quick page understanding;
- pricing/docs/news page summaries;
- deciding whether scrape/discover is worth doing.

### `markdown` — convenience, lossy

Markdown is deterministic and useful for lightweight reading, but it is not LLM-cleaned readability extraction. It may duplicate headings or lose layout detail. Do not treat it as source truth.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view markdown --chars 12000
```

Use for:

- human-readable notes;
- quick evidence snippets;
- never as the only artifact when precision matters.

### `raw-html` — static HTTP HTML

Static/simple fetch body. When no `--fetcher` is provided, this view forces `simple` so “raw” stays honest.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view raw-html --chars 20000 --json
```

Use for:

- comparing static source vs rendered DOM;
- checking SSR/static payloads;
- source-fidelity capture.

### `rendered-html` — browser-rendered DOM

Browser DOM after JS. When no `--fetcher` is provided, this view defaults to browser/headless.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view rendered-html --chars 20000 --json
```

Use for:

- JS-heavy/SPAs;
- seeing what Yosoi browser tiers can actually observe;
- diagnosing simple vs browser differences.

### `html` / `clean-html`

Yosoi cleaner output used for discovery-like context: boilerplate removed, main/body focused, attributes mostly preserved for selector usefulness.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view clean-html --chars 20000 --json
```

Use for:

- inspecting discovery input;
- debugging why selectors might be hard/easy;
- contract design.

### `links`

Extracted links as JSON content.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view links --json
```

Use for:

- quick source map;
- crawl seed selection;
- checking navigation coverage without a full crawl.

### `metadata`

Page metadata JSON as bounded content. Combine with `--include` for extra evidence.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view metadata --include headers,network,fingerprint,links --json
```

Use for:

- provenance packets;
- compact diagnostics;
- contract probes.

### `ax`

Compact accessibility snapshot JSON. Browser/headless is selected automatically when no fetcher is specified.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view ax --json
```

Caveat: this is Yosoi’s compact AX snapshot, not necessarily the full raw CDP accessibility tree.

### `bundle`

Writes artifacts to a directory and returns metadata. Browser/headless is selected automatically when no fetcher is specified.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view bundle --output .yosoi/fetches/example-page --json
```

Expected bundle files:

- `raw.html` — static/simple HTML when captured; otherwise fetched HTML.
- `static.html` — explicit static/simple capture.
- `rendered.html` — rendered browser DOM when different/available.
- `clean.html` — Yosoi cleaner output.
- `text.txt` — deterministic text.
- `markdown.md` — deterministic lossy Markdown.
- `links.json` — link extraction.
- `headers.json` — response headers if available.
- `network.json` — captured endpoint skeletons.
- `fingerprint.json` — page fingerprint when available.
- `ax.json` — compact accessibility snapshot when available.
- `metadata.json` — provenance/summary metadata.

Use bundle when the user wants artifacts, source fidelity, reproducibility, or later manual inspection.

## Fetcher Selection

Default `fetcher_type` comes from policy unless the view implies otherwise.

Automatic view-driven choices:

- `raw-html` → `simple`
- `rendered-html` → `headless`
- `ax` → `headless`
- `bundle` → `headless`
- `--include network/endpoints` → `headless`
- `--include ax` → `headless`

Override explicitly when needed:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --fetcher simple --view raw-html
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --fetcher headless --view rendered-html
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --fetcher auto --view text
```

Use `auto`/`waterfall` when you want Yosoi’s normal simple → headless → headful escalation and strategy cache. Use `simple` for exact static HTTP source. Use `headless`/`headful` when you know browser behavior is required.

## Pagination and LLM Safety

Default content is bounded. The model should not ask for unbounded content unless necessary.

Use:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --chars 8000 --page 1 --json
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --chars 8000 --page 2 --json
```

Interpret:

- `content` — current page of selected view.
- `content_chars` — chars returned now.
- `total_chars` — total chars in full selected view.
- `truncated` — whether more content remains.
- `next_page` — next page number or `null`.

If the user asks “get the whole thing,” prefer bundle output to file instead of dumping into chat:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view bundle --output .yosoi/fetches/name --json
```

## Includes

`--include` controls extra fields in the machine envelope and metadata view.

```bash
--include headers
--include links
--include fingerprint
--include network     # alias for endpoints
--include endpoints
--include ax
--include headers,network,fingerprint,links
```

Use includes when you need evidence beyond text:

- `headers` — content type, caching, server/CDN clues.
- `network/endpoints` — browser-observed endpoint skeletons.
- `fingerprint` — page shape/provenance/change signal.
- `links` — navigation/source map signal.
- `ax` — compact accessibility semantics.

## Contract Probes

Use contract probes to ask: “Does this page look reusable for this contract/cache?”

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --contract @NewsArticle --view metadata --json
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --contract @Product --contract @NewsArticle --view metadata --json
```

API:

```python
import yosoi as ys

result = await ys.fetch(
    "https://example.com/story",
    view="metadata",
    contracts=[ys.NewsArticle],
    include=("fingerprint", "links"),
)
```

Probe output fields:

- `contract` — contract class name.
- `contract_fingerprint` — stable contract fingerprint.
- `required_fields` — flattened discovery field names.
- `cached_fields` — fields with cached selectors for this domain/contract.
- `verified_fields` — cached fields that verified against current cleaned HTML.
- `fit_score` — verified required fields / required fields.
- `fit`:
  - `strong` — all required fields verified from cache.
  - `partial` — some required fields verified.
  - `stale` — cache exists but no required fields verify.
  - `candidate` — same-shape field atoms exist, but not verified for this page.
  - `uncached` — no domain/contract cache and no atom hint.
  - `unknown` — reserved/diagnostic.
- `page_shape` — structural page-shape bucket.
- `fingerprint_degenerate` — true when page is too thin to trust structurally.
- `atom_matches` — field-atom hints for this page shape and contract.
- `notes` — warnings and next actions.

Important boundary:

- Contract probes do **not** scrape.
- Contract probes do **not** call the LLM.
- Contract probes do **not** populate selector cache.
- A `candidate` probe is a lead; run `discover`/`scrape` to verify before reuse.

## Python API

Use `ys.fetch` for scripts. It is fully async and policy-aware.

```python
import yosoi as ys

result = await ys.fetch(
    "https://exa.ai/pricing",
    view="text",
    chars=12_000,
    page=1,
    fetcher_type="auto",
    include=("headers", "links", "fingerprint"),
    policy=ys.Policy(),
)

unit = result.results[0]
print(unit.content)
print(unit.truncated, unit.next_page)
```

Multi-URL:

```python
result = await ys.fetch(
    ["https://example.com", "https://example.org"],
    view="metadata",
    include=("links",),
)
```

Bundle from Python:

```python
result = await ys.fetch(
    "https://example.com",
    view="bundle",
    output_dir=".yosoi/fetches/example",
)
print(result.results[0].artifacts)
```

Contract probe from Python:

```python
result = await ys.fetch(
    "https://example.com/news/story",
    view="metadata",
    contracts=[ys.NewsArticle],
    include=("fingerprint",),
)
probe = result.results[0].contract_probes[0]
print(probe.fit, probe.fit_score, probe.verified_fields)
```

Lower-level operation API:

```python
from yosoi.operations import FetchRequest, run_fetch

request = FetchRequest.from_axes(
    "https://example.com",
    view="text",
    page_size=8000,
    include=["headers", "links"],
)
result = await run_fetch(request)
```

## Output Interpretation

A successful unit has:

- `url`
- `final_url`
- `status`
- `status_code`
- `title`
- `view`
- `content`
- `content_chars`
- `total_chars`
- `page`
- `page_size`
- `truncated`
- `next_page`
- `raw_html_chars`
- `cleaned_html_chars`
- `text_chars`
- `fetch_time`
- `fetcher_type`
- optional `headers`, `endpoints`, `links`, `fingerprint`, `ax_snapshot`, `contract_probes`, `artifacts`

Convenience fields:

- `result.success`
- `result.data` for single URL
- `result.documents` for successful unit payloads
- `result.errors` for failures
- `unit.data`
- `unit.metadata`

## Recommended Workflows

### 1. Quick page understanding

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --chars 12000 --json
```

Use `content` for a safe answer. If truncated, fetch the next page.

### 2. Compare static vs rendered

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view raw-html --chars 20000 --json > /tmp/static.json
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view rendered-html --chars 20000 --json > /tmp/rendered.json
```

If static is a shell and rendered has content, future scrape/discover should use browser-capable fetcher/policy.

### 3. Evidence packet / artifacts

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view bundle --output .yosoi/fetches/source-name --json
```

Inspect files rather than dumping huge content into context.

### 4. Source map before crawl

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view links --json
```

Use promising URLs as `crawl` seeds or direct `fetch` targets.

### 5. Contract feasibility before scrape

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --contract @NewsArticle --view metadata --include fingerprint --json
```

If `fit=strong`, try `yosoi scrape`. If `uncached`, run `discover` only if the page actually contains required fields. If `stale`, expect re-discovery/repair.

### 6. Debug a failed scrape/discover

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view clean-html --chars 20000 --json
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view metadata --include headers,network,fingerprint,links --json
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --contract @Contract --view metadata --json
```

Look for missing fields, bot gates, JS shells, unexpected redirects, empty/degenerate fingerprints, or stale cached selectors.

## Policies

`fetch` accepts project/global policy layers:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --policy .yosoi/policy.yaml --json
```

Python:

```python
result = await ys.fetch(
    URL,
    policy=ys.Policy(page=ys.PagePolicy(fetcher_type="headless", timeout_seconds=45)),
)
```

Use policy for timeout, fetcher, redirects, Chrome endpoints, profiles, and other page-acquisition settings. Do not bypass Yosoi’s fetchers with ad-hoc `curl`/requests when the task is to understand what Yosoi sees.

## Failure Handling

If `status=failed` or envelope `status=partial/error`:

1. Read `unit.error`, `status_code`, and `fetcher_type`.
2. Try browser if simple failed:
   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --fetcher headless --view text --json
   ```
3. Try `metadata` with headers/network when diagnosing blockers:
   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run yosoi fetch URL --view metadata --include headers,network --json
   ```
4. For likely bot walls, use Yosoi policy/profile controls. Do not introduce Playwright.
5. If still blocked, report the observed failure honestly.

## Non-Goals

Do not use `fetch` to claim structured extraction succeeded. For records, use `scrape`.

Do not treat Markdown as canonical. For source truth, save `bundle` or inspect `raw-html`/`rendered-html`/`clean-html`.

Do not treat a contract probe as validation. It is a fit signal only.

Do not use fetch as a broad site crawler. Use `crawl` for frontier traversal.

Do not silently dump huge HTML to the user. Use pagination or bundles.

## Final Answer Shape After Using Fetch

When reporting back, include:

- What was fetched: URL(s), view, fetcher, status.
- Whether content was truncated and how to get the next page.
- What artifacts were saved, if any.
- If contract probes ran: fit, fit score, cached/verified fields, and what to do next.
- Any risks: JS-only content, bot gates, stale cache, uncached contract, degenerate fingerprint, missing fields.
- Recommended next step: fetch next page, bundle, crawl, discover, or scrape.
