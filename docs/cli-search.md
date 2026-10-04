# Search CLI

`yosoi search "rust programming language"` uses the SDK default: Brave,
Bing, and DuckDuckGo in that order, with up to five organic results from each.
`--providers brave,bing` or `-p brave,bing` replaces that order with a
comma-separated list of the `brave`, `bing`, and `duckduckgo` enum values.
`--profile NAME` selects a saved Policy profile; matching Exact provider
profiles are retained when `--providers` overrides its order. The global
profile option has no short form so `-p` belongs to Search providers.

Current provider routes use versioned **preview** Requests profiles: Brave and
DuckDuckGo use headless Browser Requests with a rendered DOM; Bing uses Direct
HTTP. These profiles are available for local use but remain uncertified. A
browser-backed route requires the CLI's default `browser` build feature and a
configured regular Stable Chromium runtime. On this workstation the native
`/usr/bin/chromium` reports Arch Chromium 152.0.7977.82-1; Brave headless
returned HTTP 429 there even though the hardened Chrome 154 container candidate
returned results. Use the container preview for the observed positive Brave
path; the cause of the native/container difference is unproven. A build with
`--no-default-features` reports `unsupported_capability` for that route while
HTTP providers can still complete.

`--stats` or `-s` writes wall time, termination, provider and hit counts,
request attempts, and known retained source bytes to stderr. JSON output on
stdout remains one document. `--profile` remains available to other CLI
commands; its former `-p` short form is replaced by Search's provider flag.

`--per-provider-limit` and `--max-in-flight` override only the selected Search
Policy for this invocation. Search still uses the complete Yosoi Policy and
Requests lifecycle. No Google route is offered.

## Local Brave/Bing preview

[search-local-preview-policies.json](search-local-preview-policies.json) provides
a version-keyed example with two explicit Direct HTTP Requests profiles when a
saved policy should select only Brave and Bing. The Brave HTTP profile is a
historical probe option and may return `rate_limited`; the built-in Brave
preview uses headless Browser Requests.
Merge its `local-search-preview` entry into your existing `yosoi/policies.json`
store, or use it in an isolated `XDG_CONFIG_HOME`. Then run
`yosoi search "rust programming language" --profile local-search-preview`.
The response identifies these routes as Exact; the example does not claim a
certified provider default. The Policy store is read-only to this command.

## Three-provider container preview

The hardened regular-Stable container also includes `yosoi` and an optional
[saved three-provider Exact profile](search-container-preview-policies.json).
With no `--profile`, its CLI uses the five-per-provider SDK default. After
building it with `CAS520_BUILD_ONLY=1` through
`scripts/search/run-cas520-duckduckgo-probe.sh`, take the exact image ID printed in
its identity record and run:

```sh
CAS520_IMAGE_ID=sha256:<reviewed-image-id> \
  scripts/search/run-cas520-search-cli-preview.sh "rust programming language" --output json
```

The wrapper runs one bounded CLI search with Chrome's sandbox required, a
read-only root and disposable profile, and the same explicit Brave/Bing HTTP
and DuckDuckGo headless browser routes. `--providers` can select a subset;
`--profile local-search-preview` selects the saved ten-per-provider Exact
profile if desired. Both routes are local previews and neither claims provider
certification.

## JSON schema version 2

JSON output has one top-level object with `schema_version`, `cli_version`,
`policy_profile`, `policy_identity`, `termination`, and `providers`. Provider
objects stay in Policy order and include `identity`, `status`, `coverage`,
`detail`, `profile`, `request_id`, `recovery_query`, `attempts`, `hits`, `features`, `applied_filters`, `issues`,
and `cost`. The current query-only SDK emits an empty applied-filter list.

- `hits` contain only validated organic HTTP(S) destinations and provider-local
  rank and placement. Optional title, snippet, display URL, publisher, date,
  and thumbnail fields describe the provider page, not fetched target metadata.
- `features` keep sponsored, answer, image-gallery, and local-pack placements
  separate from organic hits. `coverage.rich_features: "not_collected"` means
  the adapter did not inspect those placements.
- `profile.defaults_status` reports `preview`, `certified`, `unavailable`, or
  `exact` separately from the resolved defaults version and acquisition.
- `attempts` report Request ID, capture ID, acquisition, HTTP status, exact retained
  source bytes when known, a secret-safe failure diagnostic when available,
  and terminal state. `cost.status: "unknown"` does not mean zero charge.
- `issues` and `coverage.web: "partial"` report retained but incomplete
  results. An unrecognized zero-row page is a failure, not a claimed empty set.
- Bing may serve HTTP-200 rows unrelated to a multiword query while echoing
  that query in its search box. Current Bing Preview v2 makes one more Direct
  HTTP Request with a shorter content-term query after a detected mismatch.
  The exact query appears as `recovery_query`; both Requests appear in
  `attempts`. Recovered hits have partial coverage and a `query_relaxed` issue
  because the shorter query may lose intent. Exact Bing profiles keep the
  authored single-Request behavior. If the second page is also off-query,
  Bing remains `failed(query_mismatch)`.

Exit status is 0 for all recognized, complete provider outcomes; 3 when useful
results coexist with a failure, omitted provider, issue, partial coverage, or
Search deadline; 1 when no provider succeeds or output fails; 2 for setup or
Policy errors; and 130 for Ctrl-C. Human output uses the same provider order
and shows coverage and issues. The query, cookies, and provider tokens are not
printed in ordinary output or diagnostics, except that a Bing recovery query is
shown when that second Request runs.

`Policy.search.max_retained_content_bytes` bounds retained URL and provider
text across results. It does not bound JSON framing or CLI metadata. The
Requests and Locators policies separately bound acquired and parsed input.
