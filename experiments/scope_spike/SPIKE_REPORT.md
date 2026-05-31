# Spike report: reuse-scope canonicalization — real-data findings

**Date:** 2026-05-30 · **Branch:** `spike/cas-83-scope-canon` · **Tickets:** CAS-83 (leak), CAS-85 (recipe bank), CAS-102 (reconcile A3Node vs ReplayPlan)

Probes run via voidcrawl (stealth headless Chrome). Three Claude Code SDK subagents
(Sonnet, parallel — for cost), one per stability tier. Raw data in `results/*.json`.

## TL;DR

All three tiers of the stability ladder are **empirically real** — and reuse scope
genuinely differs per site, confirming the "strongest-available-signal wins" model.
But the headline finding is a **surprise that inverts a design assumption**:

> **On Reddit, the verify gate does NOT catch wrong-template reuse.** old.reddit
> renders `div.thing.link` rows on listings, comment pages, *and* user profiles, all
> with 5/5 valid fields. Reusing a listing recipe on `/user/spez` returns real,
> well-formed post data from the wrong context — and passes every "non-empty +
> fields populated" check. **The route-distinguishing key is therefore load-bearing,
> not an optimization.** "Verify on replay" alone is not a sufficient CAS-83 fix.

## Results by tier

| Tier | Site | Transfer (must-reuse) | Refusal (must-decline) | Verdict |
|------|------|----------------------|------------------------|---------|
| 1 — domain-wide (`data-*`) | finance.yahoo.com | ✅ AAPL→MSFT,TSLA, 0 selector changes | ✅ `/markets/` returns null | **Confirmed** |
| 2 — route template | old.reddit.com | ✅ `/r/ted/top`→`/r/python/top`,`/r/aww/hot` (24/25 rows, 5/5 fields) | ❌ **comments + user pages pass anyway** | **Transfer yes; refusal needs the KEY** |
| 3 — structural / AX | google.com/maps | ✅ AX role skeleton 96% similar across 2 places | URL non-templatable (ephemeral `g_ep` token, coord drift, proto `data=`) | **Confirmed** |

### Tier 1 — Yahoo Finance: domain-wide transfer is real, but hooks must be *scoped*
- `[data-testid="qsp-price"]`, `[data-testid="quote-title"]` resolve identically on
  every `/quote/<TICKER>` page, zero changes. Discover once, replay across the domain.
- **Caveat:** bare `fin-streamer[data-field="regularMarketPrice"]` is ambiguous — it
  matched the global header ticker strip (returned a BTC price `74055`, not AAPL
  `312.06`). Stable hooks need a scope anchor (`data-symbol` / ancestor), or you leak
  *cross-asset on the same page*. The `qsp-*` testids are pre-scoped to the quote panel.
- Scope boundary is `/quote/*` (the summary panel persists across `/news`, `/history`
  sub-tabs) vs non-quote pages — broader than per-sub-tab.

### Tier 2 — Reddit: the verify-gate blind spot (most important finding)
- **Transfer:** flawless. Listing selectors frozen from `/r/ted/top` → 24 rows on
  `/r/python/top`, 25 on `/r/aww/hot`, 5/5 fields each.
- **Refusal failure:** old.reddit's `div.thing.link` is universal.
  - `/r/{sub}/comments/{id}/...` → 1 "ghost" row (the parent post). A **cardinality**
    assertion (expected ~25, got 1) *would* catch this.
  - `/user/{name}` → 5 full rows of real, valid post data. **Nothing structural or
    semantic distinguishes it from a subreddit listing** — it genuinely *is* posts,
    just from the wrong context. Cardinality won't save you; the value looks correct.
- **Why this matters:** the route key encodes user *intent* (which page-class they
  pointed Yosoi at) that selectors alone cannot recover. The earlier design leaned on
  "the key is an optimization; the verify gate is the safety property." Reddit
  disproves that ordering. **Route-distinguishing key = primary defense; verify =
  secondary (and add a cardinality assertion).**

### Tier 3 — Google Maps: URL useless, structure stable
- Both place URLs are non-canonicalizable: per-request `g_ep` experiment token,
  floating-point coordinate drift, opaque proto-encoded `data=` segment.
- AX role fingerprint **96% similar** across Eiffel Tower vs Statue of Liberty
  (21/22 roles shared, identical rank order, deterministic section ordering).
- `data-item-id` is sparse (4 elements, 0.18%); `data-cid` absent. **`aria-label` is
  the viable anchor** (~300 elements, 13.5% density) — and it maps straight onto the
  AX roles. Structural/AX tier needs aria/role addressing, not `data-*` hooks.

## Design implications

1. **The key must be page-class-distinguishing, deterministically, before verify.**
   Proven by Reddit. Cheapest form = route-template normalization where URLs are
   meaningful (Tier 2); falls back to AX/structural class where URLs are garbage
   (Tier 3). CAS-83 cannot be closed by verify-on-replay alone.
2. **Reuse scope is per-site, not global.** Yahoo = domain-wide; Reddit = per-route;
   Maps = per-structural-class. The ladder model holds; pick the strongest signal the
   site actually offers.
3. **Stable hooks still need scope anchors.** Even Tier-1 `data-field` leaks
   cross-asset without a `data-symbol` qualifier — the verifier must check the value
   belongs to the requested entity, not just that *a* value resolved.
4. **Verify gate upgrade:** add a **cardinality / expected-count** assertion (catches
   Reddit comments, Yahoo header-strip mismatch) — necessary but, per `/user`, still
   not sufficient alone. Key + cardinality + value-belongs-to-entity together.
5. **Decoupling stands:** get-this-page-right (discovery + verify) is first-class and
   always on; reuse-scope inference stays passive / opt-in / future (`reuse="scale"`),
   never issues its own fetches. One-off scrapes default to island scope, pay nothing.

## Recommended next step
Land the **CAS-83 implementation**: make the live A3Node/selector cache key
page-class-distinguishing (route template where available), add a cardinality
assertion to the replay verify, default reuse scope to island. The tier-inference
engine (Wilson-bound scope graduation) is the deferred follow-up behind `reuse="scale"`.
