# Portfolio Monitor — field-atoms vs. the discovery-cost explosion

A mocked, fully-offline project that shows the field-atom corpus solving a real scaling
problem: scraping a portfolio across a large fleet of look-alike pages without paying an
LLM discovery for every field on every page.

## The problem

You monitor 8 tickers, each on 3 Yahoo-Finance hosts (`finance.`, `uk.finance.`,
`de.finance.`) → **24 quote pages**. Naively, an LLM discovers selectors per
`(page, field)`, so cost scales with `pages x fields` and repeats whenever you add a
metric or a new mirror appears.

## The fix (this repo)

A page's identity is its **shape**, not its URL. Selectors are stored as **field-atoms**
keyed by `(page_shape, region, field, type)`, so you **discover once per shape and
replay** across every same-shape page — any ticker, subdomain, or TLD. The discrimination
gate keeps the header and key-stats regions from conflating before anything is
internalized, and growing a contract by one metric costs exactly one new atom.

## Run it

```bash
uv run python mocked-projects/portfolio-monitor/run.py
```

## What it prints

```
naive  (discover every field, every page) :  168 LLM discoveries
atoms  (discover once per shape, replay)  :    4 LLM discoveries
→ 97.6% fewer discoveries  ·  corpus = 4 atoms
```

The first quote page is cold (3 discoveries, gated for region disjointness); the other 23
— different tickers, the `uk.` and `de.` subdomains — are served from the corpus for
free. Adding a `pe_ratio` metric across the whole fleet costs **one** discovery.

## How it maps to the pipeline

- `page_shape_fp` (P1) buckets every quote page together regardless of URL.
- `evaluate_discrimination` (P1.5) gates the header vs. key-stats regions before write.
- `derive_atoms` / `AtomStore` (P2) internalize a gate-accepted set, domain → provenance.
- `resolve_via_atoms` (P3) serves a contract from the corpus, fail-closed (exact shape,
  unambiguous region only) and falls back to discovery for genuine gaps.

> Mocked, deterministic, no network: a "discovery" is a counter standing in for an LLM
> call; atom hits are free replays.
