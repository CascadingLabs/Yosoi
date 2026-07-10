# Fetch page evidence

`yosoi fetch` acquires bounded page evidence without selector discovery, cache writes, or structured scraping. Use it to inspect pages, save artifacts, and decide whether `crawl`, `discover`, or `scrape` is appropriate.

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

Results remain in input order. A failed or blocked URL is reported in its result unit and does not stop the remaining URLs. Keep the default for browser-heavy or unfamiliar sites; raise the limit only when the selected fetcher and target sites can safely handle the parallel load.

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

## Blocked pages

A bot wall or captcha is returned as `status: "blocked"` on the result unit. The envelope contains an `interrupts` list with the detection evidence and, for an attached browser when available, same-browser handoff metadata. Treat this as a request for human resolution or a policy/profile change; do not silently claim that content was acquired.

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
