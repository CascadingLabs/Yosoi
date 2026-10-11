# Search provider fixtures and observations

Status: sanitized evidence package, 2026-10-03. Source: the retained CAS-502 spike artifacts named in `observations.json`. This package supports Brave/Bing Direct HTTP parsing and the first DuckDuckGo RenderedDom parser slice. It contains no provider client or live query from this fixture task. Google is out of scope.

## Observed extraction shape

| Provider | Captured evidence | Candidate fields |
| --- | --- | --- |
| Brave | Standard Direct HTTP response; 20 `.result-wrapper` rows and 20 external `a.l1` links. A later `safari26` named HTTP profile response was 429. | Row `.result-wrapper`; title link `.result-content > a.l1`; visible title `.title`; snippet `.generic-snippet > .content`. |
| Bing | Standard and `safari26` Direct HTTP responses; 10 `li.b_algo` title links per capture. Every observed title URL used the Bing `/ck/a` wrapper. Two `safari26` rows lacked the standard snippet paragraph. | Row `li.b_algo`; title `h2 > a`; snippet `.b_caption > p.b_lineclamp2`. |
| DuckDuckGo HTTP | The `html.duckduckgo.com/html/` request returned 202 with the challenge title `div.anomaly-modal__title`. | Class plus the observed marker text identify this captured challenge. |
| DuckDuckGo browser | The saved positive RenderedDom has ten `article[data-testid="result"]` rows, one `article[data-testid="ad"]`, and eleven `a[data-testid="result-title-a"]` anchors. The current-Stable empty capture has zero result/ad rows and a visible no-results marker inside `section[data-testid="mainline"]`. | The redacted provider fixtures keep result/ad row distinction, fourth-child snippet extraction even when a fifth section exists, and the scoped English empty marker. |

Brave and Bing response and profile details, source hashes, and exact sanitized counts are in `observations.json`. The `safari26` named profile is HTTP impersonation, not a Safari browser. The original CAS-502 spike notes live in a separate local workspace and are not present in this merge checkout; the observations file records the capture facts used here.

## Bing `/ck/a` destination evidence

Across both captured Bing pages, all 20 result title links had host `www.bing.com`, path `/ck/a`, and one `u` parameter whose value began `a1`. Removing `a1`, decoding the remaining unpadded URL-safe Base64, and parsing the UTF-8 output produced an absolute HTTP(S) target for every observed link. The observed captures verify that one pattern only. They do not establish handling for other Bing wrapper variants, duplicate or missing `u` parameters, locale changes, ads, nested redirects, or redirect responses.

The positive `bing-organic-row.html` href is intentionally `u=REDACTED`; it exercises row/title/snippet selection but cannot replay the decoder. The actual opaque `u` values are absent. [bing-ck-a-negative-vectors.json](bing-ck-a-negative-vectors.json) contains two harmless synthetic positive URL vectors for decoder round-trip checks and clearly labeled rejection inputs for bad prefix, invalid Base64, invalid UTF-8, and a non-HTTP scheme. Both positive vectors are synthetic and separate from the 20/20 captured-evidence count.

For a later implementation, validate the wrapper host/path and exactly one `u`, require the observed prefix, decode within a small bound, require UTF-8, parse with `Url`, and accept only HTTP(S) with a host. Treat other shapes as unverified parse cases; do not guess a destination.

## Redaction and provenance

The HTML fragments are small extracts of actual captured DOM nodes. Element names and observed classes remain. Every ordinary title/snippet string is replaced with an explicit redaction placeholder. The Brave title link retains only its observed destination scheme, host, and path; its query and fragment are removed. The Bing wrapper keeps its observed host/path while the entire query is reduced to `u=REDACTED`. The DuckDuckGo challenge fixture keeps only the short provider-owned challenge title marker. Unrelated nodes and attributes, form values, cookies, opaque IDs, scripts, and page content are omitted.

The DuckDuckGo browser artifacts are serialized RenderedDom snapshots rather than HTML. The redacted provider-source fixtures under `crates/yosoi/src/internal/engine/search/provider/` preserve the observed result/ad row distinction, fourth-child snippet with optional fifth section, and current-Stable English mainline empty marker; they substitute destinations and query text and omit unrelated nodes. The empty fixture is grounded in a hash-checked HTTP-200 browser capture. A separate synthetic browser-DOM challenge control uses the provider-owned phrase from the saved HTML 202 challenge; no browser challenge page has been observed. Unknown zero-row pages remain malformed. The early-shell artifact contains zero result-title markers, but its file does not identify the capture checkpoint.

Raw pages remain in their original `/tmp` evidence locations and are not copied here. The provenance table records each filename and SHA-256 so the sanitized observations can be checked against the retained source when it remains available. The spike implementation and notes are referenced by path and the reported CAS-502 base in `observations.json`.

## Contents

- `fixtures/brave-organic-row.html`: observed Brave row structure with redacted text and a query-free captured target URL.
- `fixtures/bing-organic-row.html`: observed Bing row structure with a redacted, non-replayable wrapper URL.
- `fixtures/duckduckgo-http-challenge.html`: minimal observed HTTP challenge marker.
- `fixtures/brave-multirow.html` and `fixtures/bing-multirow.html`: two captured rows each, with source text and tokens redacted.
- `fixtures/bing-safari26-snippetless-rows.html`: captured rows 2 and 3 without the standard snippet selector match.
- `fixtures/*-synthetic-sponsored-control.html` and `fixtures/*-synthetic-missing-href.html`: explicitly synthetic negative controls derived from captured row structures.
- `crates/yosoi/src/internal/engine/search/provider/duckduckgo-rendered-dom.json`: redacted Browser result/ad row shape with a synthetic extra section based on the retained DOM.
- `crates/yosoi/src/internal/engine/search/provider/duckduckgo-empty-rendered-dom.json`: redacted structural fixture for the observed HTTP-200 mainline empty marker.
- `crates/yosoi/src/internal/engine/search/provider/duckduckgo-synthetic-challenge-rendered-dom.json`: synthetic DOM control from the provider-owned HTML challenge phrase, not an observed browser challenge.
- `observations.json`: capture provenance, selector facts, DDG result/shell observations, and unknowns.
- `bing-ck-a-negative-vectors.json`: two synthetic positive vectors plus four synthetic rejection vectors; none are captured provider values.

## Local-only raw-capture replay

An ignored Rust test in the Bing provider module replays the retained Brave/Bing response bodies serially. It verifies manifest hashes, reports body bytes, parser classification, hit counts, URL-validation counts, issue counts, and the recorded Brave 429 status. It never prints URLs, snippets, or Bing `u` values and performs no network access. After the owner grants the serial test slot, run it with:

```sh
YS_SEARCH_CAPTURE_DIR=/tmp cargo test -p yosoi --lib replay_retained_brave_bing_captures_serially -- --ignored --nocapture --test-threads=1
```

The `safari26` entries are named HTTP impersonation profiles. Their response evidence does not establish a browser identity or a provider quota.

The DDG provider module has two additional ignored, hash-checked local replays.
They use the saved positive CAS-502 DOM and the current-Stable empty DOM,
respectively. Neither test performs network I/O or prints result content:

```sh
YS_DDG_CAPTURE_PATH=/tmp/cas502-browser-evidence/duckduckgo-web-headful-rust-programming.html \
  cargo test -p yosoi --lib replay_retained_headful_dom_reports_bounded_row_issues -- --ignored --nocapture --test-threads=1
YS_DDG_EMPTY_CAPTURE_PATH=/tmp/cas520-ddg-result.gryKbj/ddg-empty-candidate-dom.json \
  cargo test -p yosoi --lib replay_retained_empty_dom_reports_empty -- --ignored --nocapture --test-threads=1
```
