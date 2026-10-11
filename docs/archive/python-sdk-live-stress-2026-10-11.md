# Python SDK live-site stress verification

The SDK was rebased as an aggregate revision directly on current main
`46f9625aa9a9a38bb4b7ead742285394a5bd63bd`. Rebased revision
`0b1dcda6c6f8760512feb2be19ba482425fdd325` has the same tree as the previous
SDK/release-preparation snapshot; previous history remains preserved.

The verified live-test source is `05995a173b988c152dc10758ab85c6c6de4ecdf1`.
A rebuilt installed Maturin wheel was used, with its native member hash checked
against the imported extension and its Python files checked against the source.
Runtime: free-threaded CPython 3.14.7 on Linux x86-64, regular sandboxed Chrome
Stable 155.0.8059.39. The existing hardened container runs with one CPU and a
3 GB memory limit; builds and validation ran serially.

## Observed results

- Nine live scenarios passed; two rendering probes were explicitly expected
  failures, not successful product flows.
- The final run recorded 41 Flow invocations and 211 step receipts, including
  intentional rejected assertions and JavaScript permission checks.
- Three managed visits verified content on Books to Scrape, Quotes to Scrape,
  and Wikipedia, with observed owned-resource cleanup.
- Three borrowed cross-site rounds exercised delayed quote hydration, next-page
  navigation, typed Contract assertions, and retained Requests extracting 20
  books per page. Captured URLs confirmed quote page 2 in every round.
- Construction-time JavaScript file/module snapshots retained their original
  values after source-file edits. Borrowed JavaScript grants could not elevate
  the caller's Session permissions, and the lease remained reusable.
- Six simulated Qscrape orders confirmed: three React pickaxe orders and three
  Solid chisel orders. Cart SKU, quantity and GS totals were checked before
  submission; confirmation required the domain order-reference element.
- Wrong-total checks stopped the dependent checkout action. Pre-cancelled
  invocation raised the documented before-dispatch error, and the unchanged
  cart was subsequently verified through the same borrowed lease.

Qscrape variants were selected explicitly through permitted JavaScript for
those controlled checkout runs. They are not evidence that every randomly
selected framework works. Separate React/Vue/Svelte/Solid probes retained the
missing visible Vue/Svelte product grids as expected failures. Andrew reports that Qscrape has not been well maintained, so these are treated
as likely site issues. The captures do not conclusively establish the root cause
and are not attributed to the SDK.

An earlier batch recorded one unknown Qscrape navigation after possible
dispatch. It stopped before subsequent actions and was not silently retried.
Later independent runs confirmed all six orders. The earlier outcome remains
in the evidence; it is not retroactively relabeled successful or fixed.

## Changes and checks

Live stress coverage is opt-in in `python/tests/test_live_sites.py`. The existing
container runner forwards its explicit opt-in and bounded iteration count.
A small Rust diagnostic change classifies fixed navigation failure messages
without exposing arbitrary provider URLs or tokens. Its focused redaction test
passed. It adds diagnostic information; it is not a claim to repair the earlier
unknown navigation.

The installed consumer regression passed 308 tests, with 18 skips including
11 opt-in live cases. Scoped Ruff and ty checks passed. Core strict Clippy
reported 456 existing diagnostics; the new classifier had no diagnostics.
The broader lint baseline remains separate from these live results.

Evidence is retained in `.local/python-live-stress/` in the default workspace:
`report.json`, `diagnostic-stress/`, rebuilt wheels, consumer/unit logs, and all
exploratory failed runs. No automatic failure retries were added. These checks
are bounded live regression evidence, not a performance ranking, full platform
matrix, full Chrome/CDP certification, or a release/publication claim.

## Reproduce

From a synced project environment with the built wheel installed:

```sh
YOSOI_LIVE_SITE_TESTS=1 YOSOI_LIVE_ITERATIONS=3 \
YOSOI_YIELD_IMAGE=yosoi-cas574-chrome155:local \
YOSOI_PYTHON_TEST_FILES='python/tests/test_live_sites.py' \
bash spikes/browser-automation/run-python-until.sh "$PWD/.local/live-sites" \
  --junitxml=/evidence/junit.xml
```

The named image is the locally verified regular-Chrome image, not a published
artifact. Iterations are limited to 1..10 to keep external-site traffic bounded.
