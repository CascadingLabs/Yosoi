# Fetch page evidence

`yosoi fetch` acquires bounded page evidence without selector discovery, cache writes, or structured scraping. Use it to inspect pages, save artifacts, and decide whether `crawl`, `discover`, or `scrape` is appropriate.

Implementation: [PR #105](https://github.com/CascadingLabs/Yosoi/pull/105).

## Fetch one page

```bash
uv run yosoi fetch https://example.com --view text --chars 12000 --json
```

The default text view is bounded for safe LLM use. Inspect `truncated` and `next_page` before requesting a later page.

## Fetch multiple pages concurrently

Pass URLs directly, repeat `--url`, or provide `--file`. `--concurrency` limits the number of independent URL fetches running in each ordered batch and defaults to `5`.

```bash
uv run yosoi fetch \
  https://example.com \
  https://example.org \
  --concurrency 5 \
  --view metadata \
  --json

uv run yosoi fetch --file urls.txt --concurrency 10 --view text --json
```

Results remain in input order. A failed URL is reported in its result unit and does not stop the remaining URLs. Keep the default for browser-heavy or unfamiliar sites; raise the limit only when the selected fetcher and target sites can safely handle the parallel load.

### CLI batch controls

| Option | Default | Behavior |
| --- | --- | --- |
| `--concurrency N` | `5` | Run at most `N` URL acquisitions in an ordered batch. Values must be integers `>= 1`. |
| `--url URL` | none | Repeat for more URLs without shell positional arguments. |
| `--file PATH` | none | Read URLs from a file, then apply the same concurrency limit. |
| `--limit N` | none | Trim the combined positional, `--url`, and file URL list before acquisition. |

`--concurrency` does not change the per-page `--page-size`/`--chars` bound, nor does it turn `fetch` into a crawler.

## Choose a view

```bash
# Static HTTP source
uv run yosoi fetch URL --view raw-html --chars 20000 --json

# Browser-rendered source
uv run yosoi fetch URL --view rendered-html --chars 20000 --json

# Save reproducible artifacts
uv run yosoi fetch URL --view bundle --output .yosoi/fetches/example --json
```

Use `raw-html` for static source fidelity, `rendered-html` for JavaScript pages, and `bundle` when artifacts must be retained for review.

## Managed browser challenges

The automatic waterfall now escalates full-page Cloudflare managed challenges
from headless to headful Chrome, then gives the headful browser a bounded settle
window before declaring the page blocked. This covers interstitials that clear
after a few seconds; Yosoi does not click CAPTCHAs or attempt to solve
interactive challenges.

When a challenge remains, JSON output includes a structured `failure` object
with the vendor, indicators, terminal browser tier, and safe next actions. Do
not repeat an unchanged blocked request.

For an operator-approved dedicated VoidCrawl profile, `fetch` has the same
profile controls as `scrape`:

```bash
uv run yosoi fetch URL --profile docs-warm --fetcher auto --json
uv run yosoi fetch URL --profile-pool docs-pool --max-live-profiles 2 --fetcher auto --json
```

A newly created managed profile is **cold**: it has no browsing history or
clearance cookies. Never silently clone or use a person's daily Chrome profile;
it may contain authenticated sessions and other sensitive state. Profile pools
require `auto` or `waterfall` so Yosoi can rotate identities after a block.
Profile flags are rejected with `raw-html`, which intentionally remains a
static HTTP source view; use `rendered-html` for browser DOM.

## Python API

```python
import yosoi as ys

result = await ys.fetch(
    ["https://example.com", "https://example.org"],
    view="metadata",
    max_concurrency=5,
)
```

## Verify locally

```bash
uv run pytest tests/unit/test_operations.py tests/unit/cli/test_verb_group.py tests/unit/test_api.py -q
uv run poe ci-check
```

The full fetch workflow and agent-facing guidance live in [`yosoi-fetch`](../.agents/skills/yosoi-fetch/SKILL.md).
