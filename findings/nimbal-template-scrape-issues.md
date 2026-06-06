# Nimbal SERP-template scrape on Yosoi — issues found scaling up

`examples/serp_google/nimbal_template_scrape.py` loads the real HubSpot CSV (57 companies),
renders Nimbal's `render_matrix` template queries, builds the Google search URLs, and drives
the new `ys.scrape([urls], [block_contracts])`. Instrumented to surface issues at each stage.
Ran dry (`--limit 3`) and live (`--limit 1 --live`, Claude SDK, simple fetcher).

## The framing win

Nimbal's `serp_contracts.py` was **forced** into ONE page-contract + a `sponsored` field
because *"running several block-contracts against the SAME url … the second pass clobbers the
first"* — the W5 per-domain cache clobber. The spike **lifts that**: docstring-aware
signatures + field-level root + the Tier-1 discrimination gate let separate `AdResult` /
`OrganicResult` / `LocalPackResult` contracts coexist, and `ys.scrape([urls],[contracts])`
drives the grid. So the harness uses *separate* block contracts — the thing Nimbal couldn't.

## Issues found (concrete, from running it)

1. **SERP scraping with the `simple` fetcher is nondeterministic / gets blocked.** Two
   identical live runs: one returned 1 row per contract, the next returned **0 rows for all
   contracts** (Google served a consent/block page). This is the anti-bot reality. → needs a
   browser fetcher (`headless`/`headful`) + **W1** captcha-reaction + **W2** profile cascade.
   The whole point of the spike; not yet wired into `ys.scrape`'s default lane.

2. **Teleport has no hook in `ys.scrape`.** `render_matrix` emits `teleport` queries (drop the
   location words, expect a GPS spoof). `ys.scrape` has no teleport param, so a teleport query
   returns NON-local results — a wrong "local presence" signal. → wire **W3** `TeleportSpec`
   (per-URL lat/lng from geocoding the company city) into the scrape call.

3. **SERP blocks are LISTS; the contracts are single-record.** When it worked, each contract
   returned exactly 1 row. Nimbal needs ALL organic rows (rank rollup), not the first. → the
   block contracts must be repeating (`list[...]`) / use a container root, not scalar fields.

4. **`ys.scrape` does not enforce the Tier-1 discrimination gate** (it's a `# FUTURE` there).
   So with separate Ad/Organic/LocalPack contracts there is no guarantee `Ad.url != Organic.url`
   — they could conflate and you wouldn't know. The deterministic gate exists
   (`discrimination.py`) but isn't run in the production path. → wire it in (+ the divergence
   re-discover loop) so the multi-contract scrape is *verified* discriminated.

5. **`ys.scrape` needs a model/key.** With no provider key, `auto_config()` raises
   `ValueError`. Fine once configured (the harness passes `ys.claude_sdk()`), but worth noting
   for an unattended scale run — pick the model explicitly.

6. **The 2×2 grid fetches per (url, contract) — N× anti-bot exposure.** `scale: 18 urls × 3
   contracts = 54 units` for just 3 companies; 57 companies ≈ 1000+ units, each a fetch. The
   `fetch-once` FUTURE (share one fetched HTML across the contracts for a URL) is not an
   optimization here — it's a *survival* requirement against Google's rate/anti-bot limits.

## Mapping to spike work (most are already built, need wiring into scrape)

| issue | spike asset | gap |
|------|-------------|-----|
| 1 anti-bot/block | W1 captcha reaction, W2 profile cascade | not in `scrape`'s default fetch lane |
| 2 teleport | W3 `TeleportSpec` + geopy | no teleport param on `scrape` |
| 3 list rows | container/root extraction exists | block contracts authored scalar |
| 4 discrimination | Tier-1 gate + Tier-2 loop (`discrimination.py`) | `# FUTURE` in `_scrape` grid |
| 6 fetch-once | — | `# FUTURE` in `scrape` |

## Headful / Chromium-profile finding (user-confirmed) + multi-engine

**Google needs headful or at least a trusted Chromium profile** (matches Nimbal's `_real.py`:
`headless=False, stealth=True, extra_args=['--user-data-dir=…','--profile-directory=Default']`).
The empirical proof: the `simple` fetcher returned 1-row-then-0-rows (blocked) across two
identical runs.

- **The profile path EXISTS in the fetcher but is unreachable via `ys.scrape`.** W2 already
  wired it: `_VoidCrawlFetcher.__init__(identity: BrowserIdentity | None)` →
  `--user-data-dir={ident.profile_dir}` (voiddriver.py:164-167). BUT `Pipeline._create_fetcher`
  forwards only `console`/`a3node`/`downloads` (base.py:259-273) — no identity — and `ys.scrape`
  has no identity/profile param. So even `fetcher_type='headful'` launches a FRESH browser
  without the trusted profile Google needs. → thread `BrowserIdentity`/profile through
  `scrape → Pipeline → create_fetcher`.

- **Concurrent multi-engine (brave/bing/google) works TODAY** via the URL axis:
  `ys.scrape([google_url, bing_url, brave_url], [contracts])` runs all engines concurrently on
  the VoidCrawl tab pool (harness: 39 urls × 3 contracts = 117 units, all concurrent). The gap:
  **one `fetcher_type` for the whole call.** Engines need DIFFERENT tiers (`google:
  headful+profile`, `bing`/`brave`: `headless`), which one scrape call can't express. →
  per-URL (or per-engine) fetcher + identity selection; plus a concurrency semaphore so 117
  simultaneous tabs don't self-DOS / trip anti-bot.

## Next step (recommended order)
1. Make the block contracts repeating (list rows) — cheap, unblocks real rank rollup.
2. Wire the Tier-1 gate into the multi-contract scrape (verified discrimination).
3. Wire teleport (per-URL GPS from the company city) — the SERP signal is wrong without it.
4. fetch-once + browser fetcher + W1/W2 — the anti-bot survival path for scale.
