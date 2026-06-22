# PR concerns: ys.crawl candidate-removal pass

Reviewed current unstaged diff on `andberg9/policy-crawl-integrated`.

## Verified

- Removed-API scan found no stale `CandidateFit`, `CrawlCandidateEntry`, `candidates_for`, `contract_candidate`, `score_contract_fit`, `PathPlanningPolicy`, `path_planning`, `min_fit_score`, `min_fields`, or `urls_for(` references under `yosoi tests examples README.md docs scripts`.
- `uv run poe unit` → **3205 passed, 1 skipped, 92 deselected**.
- `uv run pytest tests/stubs -q` → **18 passed**.
- `uv run poe integration` → **19 passed, 9 skipped, 3270 deselected**.
- `uv run poe bench` → **40 passed**.
- `uv run poe ci-test` → **3223 passed, 1 skipped**, coverage **94.62%** (threshold 93%).
- `uv run poe coverage` → **3284 passed, 14 skipped**, coverage **96.21%** (threshold 93%).
- `uv run ruff check .` → **passed**.

## Status

No obvious blocking issue remains for `ys.crawl`. Previously noted blockers are addressed:
- `examples/qscrape.dev/full_crawl.py` is now crawl-only.
- Crawl-frontier browser fetch no longer writes the persistent strategy cache.
- XML parsing uses a hardened parser.
- Simple JS-marked HTML now needs multiple/diverse crawl links before skipping browser render.

## Remaining concerns / follow-ups

1. **Uppercase route artifact penalty follow-up is addressed.**
   - `_route_artifact_penalty()` no longer penalizes any uppercase path segment.
   - It is limited to repository/documentation artifact segments such as `AGENTS`, `README`, `LICENSE`, etc.
   - Regression coverage keeps uppercase IDs/SKUs like `/SKU/ABC123` eligible.

2. **Neutral scrape ranking is still heuristic-only.**
   - `scrape_target_urls()` now ranks by route artifact penalty, visible text evidence, outdegree, and depth.
   - Good enough for crawl inventory, but it is not contract validation. Downstream scrape/discovery must still fail fast and avoid caching selectors from wrong pages.

3. **Rendered crawl settle is better but still approximate.**
   - `_crawl_frontier_content()` waits for link-signature stability, which is a reasonable fast path.
   - A JS app can still stabilize on a nav shell before route data arrives. Worth keeping one live delayed-link regression if/when a fixture exists.

4. **Example defaults are intentionally heavy.**
   - `examples/qscrape.dev/full_crawl.py` runs up to `1_000` pages / `1_200` attempts with browser CDP endpoints.
   - `examples/README.md` now frames it as a full-site crawl inventory stress example, not a quickstart.

5. **Public API removals need release/deprecation treatment.**
   - Removed: `ys.CandidateFit`, `ys.CrawlCandidateEntry`, `PathPlanningPolicy`, `CrawlTarget.min_fields`, `CrawlTarget.min_fit_score`, `summary.candidates_for()`, `summary.urls_for()`.
   - Document in changelog/release notes or provide temporary shims with clear deprecation errors.
