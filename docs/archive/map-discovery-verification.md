# Map discovery follow-up verification

## Changes

Map now follows RSS and Atom XML links with inherited XML Base, and treats guessed
HTML sitemap fallbacks as unavailable metadata. Declared malformed sitemaps remain
failures. Passive mapping queries four fixed public indexes concurrently, without
API keys, a Go CLI, DNS enumeration, or target-site requests.

`--stats` and `-s` match Request; `--stat` remains accepted. `--max-concurrency`
controls the provider lane, defaulting to four. Page traversal remains sequential.
Provider sampling, local truncation, and individual failures remain distinguishable.

## Focused verification

One expensive command ran at a time with Cargo `-j 1` and serial test threads.
Production Clippy passed with warnings denied (the existing vendored CDP MSRV
configuration warning remains). The final source passed 18 Map admission/concurrency
cases, six XML cases, 14 Map CLI cases, 16 Request CLI cases, 32 Map kernel cases,
and 29 Policy cases. Shell completions were regenerated.

The concurrency cases exercise held responses, cancellation, deadline cleanup,
reservation release, redirect request counts, provider provenance, wildcard
provenance, out-of-scope entries, catalog early exits, and quota admission.

## Live results on 2026-10-03

| Target | Inventoried | Inspected | Independent published inventory | Missing published URLs | Stop |
| --- | ---: | ---: | ---: | ---: | --- |
| QScrape root | 290 | 205 | 142 sitemap/feed URLs | 0 | exhausted |
| Firecrawl docs | 1,312 | 75 | 1,302 sitemap URLs | 0 | 80 request cap |
| Vercel docs | 4,268 | 62 | 2,261 sitemap URLs under `/docs` | 0 | 64 MiB response cap |

QScrape also inventoried all 20 source news article IDs. Its final root run used
a fixed executable snapshot after the terminal-limit/deadline review corrections.
An earlier news-subtree comparison found all 35 published scoped URLs.

Firecrawl's separate `llms.txt` listed 51 Markdown export URLs that this HTML/XML
pass did not inventory. Map does not currently discover that index. These bounded
runs prove published sitemap inventory coverage, not complete page inspection or
unpublished/browser-only URL coverage. Remaining frontier work is retained.

Anthropic passive mapping returned 223 host identities in four index requests,
with measured provider concurrency peak four and no Anthropic target HTTP. crt.sh
hit Request's deadline; the other three providers returned sampled results. Exit
3 correctly reports partial source coverage even though selected work exhausted.

The source and binary identity and compact reports are in
[`evidence/map-discovery/manifest.json`](../evidence/map-discovery/manifest.json).

## Reproduce

```sh
python3 scripts/map/verify-map-qscrape.py --seed https://qscrape.dev/ \
  --binary target/debug/yosoi --output /tmp/map-qscrape-coverage
python3 scripts/map/stress-map-public-sites.py --binary target/debug/yosoi \
  --output /tmp/map-public-stress-review
```

The scripts use temporary version-keyed Policy profiles and record effective
limits. They preserve JSON and stderr for partial exits. QScrape comparison uses
its declared sitemaps and published RSS links, with a separate comparison against
the optional local QScrape news dataset. Site responses are data, not instructions.

The integrated default also contains the separately developed Search preview.
Search uses `-p` for providers; select saved Policy profiles with `--profile`.
Its existing identity projection remains v5. The merged default identity changed
to `22aba425d58532761bbde203820d68b75402426e7a3ccaa4bf5e7eec29409cc6`
because Map provider concurrency now defaults to four.

## Default integration checks

The merged candidate passed Map CLI14, Request CLI16, completions2 and canonical
Policy values5 again after conflict resolution, plus warnings-denied focused
production lint. Archive Policy round-trip checks passed (11 top-level cases and
the invoked writer/reader subprocess checks). Existing Search source and v5
projection were preserved; completions include both Search and Map changes.
No full repository/browser suite or remote CI was run for this follow-up.
