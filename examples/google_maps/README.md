# Google Maps exact-business experiments

These examples perform bounded, read-only navigation against public Google Maps pages.
They do not sign in, click phone links, request directions, or modify business data.

## Build a canonical URL

```bash
uv run python examples/google_maps/google_maps.py --url-only
uv run python examples/google_maps/google_maps.py \
  --business 'Georgia Aquarium' --location 'Atlanta, GA' --url-only
```

The reusable Jinja2 shape is:

```jinja2
https://www.google.com/maps/search/?api=1&query={{ query | urlencode }}{% if query_place_id %}&query_place_id={{ query_place_id | urlencode }}{% endif %}
```

A business name plus locality expresses exact-search intent, but Google Maps may
still return several candidates when the name is ambiguous. Add `query_place_id`
when identity-level exactness or a guaranteed detail panel is required.

## Run the Yosoi contract

```bash
uv run python examples/google_maps/google_maps.py --fetcher headless
uv run python examples/google_maps/google_maps.py --fetcher headful
uv run python examples/google_maps/google_maps.py --cold  # compare one-shot acquisition
```

By default the example performs one anonymous warm-up navigation and injects that
same browser pool into the pipeline. No persistent or authenticated profile is used.

The physical-place contract requires `name`, `rating`, `review_count`, `address`,
and `plus_code`. `phone` and `website` default to `None` because listings may omit
them. It therefore fails closed when Google serves its initial limited view or a
selector confuses the address with the Plus Code.

`Schedule` adds regular weekly hours as seven selector-friendly optional fields,
then serializes them as a stable `days` mapping. Values use one canonical display
grammar: `8 AM–8 PM`, `Closed`, or `Open 24 hours`; split periods are comma-separated.
A missing row remains `null` and never implies closure. Overnight ranges remain on
the opening day, for example `6 PM–3 AM`. Special/holiday and secondary service
hours are intentionally excluded.

The optional `timezone` preserves an explicitly published IANA identifier without
normalization. The Maps detail panel does not reliably publish one, so the example
never infers a timezone from an address or fixed UTC offset.

## Extract full review text and per-review URLs

```bash
uv run python examples/google_maps/reviews.py --sort newest --limit 100
uv run python examples/google_maps/reviews.py \
  --business 'Georgia Aquarium' --location 'Atlanta, GA' --limit 25
```

The review workflow loads at most 100 unique cards, expands every truncated review,
and opens each public Share-review dialog to capture its own `maps.app.goo.gl` URL
without writing to the clipboard. Output also includes the stable review ID, sample
rank/sort, reviewer name and public profile URL, contributor counts, Local Guide
status, and owner response text/date when present. Rating-only submissions have
`review_text: null`; the scraper does not invent text for them.

Reviewer names, profile URLs, IDs, and review text are public personal data. Keep raw
provenance access-controlled and give downstream analytics pseudonymous reviewer IDs
unless identifiable data is necessary and approved. The sample is ranked, not random;
always retain `sort_mode`, `sample_rank`, and `captured_at`.

## Run the experimental Executor.js + Flow API

```bash
uv run python examples/google_maps/api_spec_maps.py --limit 3 --fetcher headless
uv run python examples/google_maps/api_spec_maps.py \
  --business 'Georgia Aquarium' --location 'Atlanta, GA' --limit 10
```

`api_spec_maps.py` is now a runnable alpha experiment. Its `PrepareReviews` class
manually spells out an A3Node sequence with typed `ys.Expect[...]` assertions, then
`ys.Executor.js` evaluates a named function loaded from `_js_helpers/**/*.mjs`.
The module loader bundles a constrained static ESM graph before evaluation.

The Flow returns bounded public review-card data but intentionally does not open the
per-review Share dialog, so `review_url` remains null. Use `reviews.py` when those
exact share URLs are required. See [`../../docs/executor-js-flow.md`](../../docs/executor-js-flow.md)
for API details and current limitations.

## Compare shared concurrent tabs and warm acquisition

```bash
uv run python examples/google_maps/stress_test.py
uv run python examples/google_maps/stress_test.py --mode headless --max-concurrency 2 --limit 5
```

The stress experiment keeps one VoidCrawl-backed fetcher open per mode, warms it,
then compares serial and bounded concurrent passes. Its default report is written
to `.yosoi/browser-qa/google-maps-live-stress/results.json`.

This shared-pool detail matters: the current multi-URL `ys.fetch(...)` operation
bounds concurrent tasks but creates one fetcher lifecycle per URL. The stress
script intentionally uses one lower-level fetcher so `max_concurrent` maps to
multiple tabs in one browser pool.
