# Findings: Validation vs Tagging vs Discovery (real-data shootout)

**Branch:** `spike/cas-83-scope-canon` · **Run:** `uv run python experiments/scope_spike/run_comparison.py`
**Data:** `fixtures/reddit_observations.json` (live voidcrawl captures) + `results/{reddit,yahoo,maps}.json`

## The question

When a recipe learned on page A is replayed on page B, *what decides the reuse is
safe?* Three mechanism families, scored head-to-head on the real CAS-83 leak:

- **DISCOVERY** (status quo) — "did the selectors match anything?" (cache keyed on domain+selectors)
- **VALIDATION** (the preferred direction) — "does the content satisfy an invariant learned at discovery?"
- **TAGGING** (the backstop) — "is this the same page *class*?" (route template or body-class signal)

Ground truth from live captures: recipe discovered on `/r/ted/top`; replayed on 2
same-class pages (`/r/Python/top`, `/r/aww/hot` — must-transfer) and 2 wrong-class
pages (comments page, `/user/spez` — must-refuse).

## Result (real numbers — these surprised me)

| approach | good reuse ✓ | bad reuse blocked ✓ | **LEAKS** | false alarms |
|---|---|---|---|---|
| discovery_only | 2 | 0 | **2** | 0 |
| **validation_only** | **2** | **2** | **0** | **0** ← only perfect |
| tagging_only | 1 | 2 | 0 | **1** |
| validation+tagging | 1 | 2 | 0 | **1** |

Three findings, the last two counterintuitive:

### 1. Discovery is the bug, mechanically reproduced
`discovery_only` leaks **both** wrong pages. `/user/spez` returns 5 valid posts
from the wrong context; the comments page returns 1 ghost row. Both "succeed"
because selectors matched. This is CAS-83 in pure form. **"Matched something"
must never mean "reuse is correct."**

### 2. Validation was the ONLY perfect approach — the user's instinct was right
`validation_only` (homogeneity + cardinality) caught both wrong pages **and**
allowed both good transfers, zero false alarms. "If validation were complete,
this solves itself" — confirmed on this site. But note it took **two** stacked
guards:
- **Homogeneity alone would have MISSED the comments page** (it's single-sub,
  just like the seed). Caught only by adding **cardinality** (1 row vs 25-row seed).
- The homogeneity guard caught `/user/spez` (2 subs vs the seed's 1).

### 3. Tagging FALSE-SPLIT on the sort verb — and dragged the combo down
`tagging_only` **wrongly refused `/r/aww/hot`**: the route guard saw
`/r/{slug}/top` vs `/r/{slug}/hot` and called them different classes. **The sort
verb (`top`/`hot`) looks structural in the URL but isn't a different page class.**
This is the exact over-split failure mode the conservative reviewer predicted,
now observed live.

The deeper lesson is in `validation+tagging` being **worse than validation alone**:
in a fail-closed AND-chain, *every guard you add can only increase false alarms*.
Adding tagging closed **no** leak that validation hadn't already closed, so on
Reddit it was pure downside. **You only add a guard to a fail-closed chain if it
closes a leak the others miss.** (Note: the DOM-signal `tagging_bodyclass` guard
*would* have allowed the hot page correctly — it strips sort-flavor tokens — but
it sat behind the URL `route` guard in the chain, so the route's false-split won.
DOM-signal tag beat URL-signal tag here.)

## But Reddit alone would mislead — the other tiers show where validation needs help

`validation_only` winning on Reddit does **not** mean "validation is always enough."
The other two captured tiers show failures validation-as-built wouldn't catch and
tagging can't help with:

- **Yahoo Finance — same-page, WRONG-ENTITY leak.** The seed selectors pulled a
  *BTC price 74055* into the AAPL field from the global ticker strip. Homogeneity
  and cardinality both pass (it's one well-formed value). Route-tagging says "same
  `/quote/*` class → reuse." **Only a *value-belongs-to-entity* validation catches
  this** — a guard we haven't built. New failure class.
- **Google Maps — route-tagging is impossible.** URLs are ephemeral hash garbage
  (`g_ep` token, coord drift); `route_template` produces noise. The only tags left
  are **structural/body-class** (96% AX role similarity across places). Route-tag
  fails outright; the DOM-signal tag is the only one that works.

## Conclusion: the mechanisms are complementary, and ordering/inclusion matters

| Site tier | DISCOVERY | VALIDATION | TAGGING(route/URL) | TAGGING(structural/DOM) |
|---|---|---|---|---|
| Reddit (route) | ❌ leaks 2/2 | ✅ perfect (2 guards) | ⚠️ false-splits on sort | ✅ (body-class) |
| Yahoo (domain-wide) | ❌ | ⚠️ needs entity-ownership guard | ⚠️ allows wrong-entity | n/a |
| Maps (structural) | ❌ | ✅ | ❌ impossible (garbage URL) | ✅ required |

**Robust design = validation-first, tagging as a *targeted* backstop, never naive
AND-of-everything:**
1. **VALIDATION is the front line.** Auto-derived content invariants
   (homogeneity, cardinality band) + **value-belongs-to-entity** (the Yahoo gap).
   This is what actually caught the subtle cases.
2. **TAGGING only where it closes a validation gap, and prefer the DOM-signal tag
   over the URL tag.** The URL route-template false-splits on verbs; the body-class
   kind-token tag didn't. For garbage-URL sites (Maps) the structural tag is the
   *only* option.
3. **DISCOVERY is never a safety mechanism** — purely the cold-start path.

This refines the earlier "tagging is the front line" guess: the **measured** answer
is **validation-first**, with tagging added *surgically* (and DOM-signal, not URL)
only to cover a leak validation misses. A fail-closed chain punishes redundant
guards with false alarms — so the chain must be minimal, not maximal.

## Avenues to walk (ranked, updated by the data)

1. **Ship validation-first as the CAS-83 fix.** Layer = `validation(homogeneity,
   cardinality-band)` as primary; add `tagging_bodyclass` (DOM-signal) **only**
   for sites where validation can't form an invariant. Do **not** put URL
   route-template in the default fail-closed chain — it false-splits. Zero leaks
   on all real fixtures. *(near-term, high-confidence.)*
2. **Add value-belongs-to-entity validation.** The Yahoo BTC-into-AAPL leak is a
   distinct failure (right shape, right page, wrong entity) that nothing here
   catches. Its own guard primitive. *(medium — fills a proven gap.)*
3. **Fix route-template to not treat verbs as structure** (or demote it below the
   DOM-signal tag). If URL tagging is kept, sort/filter verbs must be recognized
   as instance flavor, not class — exactly the slug problem in a different spot.
   *(medium.)*
4. **Auto-derive invariants, don't hand-tune.** Homogeneity + cardinality band
   came free from the discovery collection. The cardinality floor passed
   `/r/Python/top` (5 rows) by zero margin — brittle. Push on derivation so
   authors don't tune thresholds. *(medium, research-y but bounded.)*
5. **Structural/AX-fingerprint tag for URL-garbage sites (Maps tier).** Generalize
   `tagging_bodyclass` into an AX-role-fingerprint tag. *(future — defer.)*
6. **Scope-inference engine stays deferred/opt-in.** None of this needs the
   Wilson-bound tier graduation; the guards work per-page, today, with no
   multi-instance learning. Keep behind `reuse="scale"`. *(future.)*

## Files
- `guards.py` — the three mechanism families as pure functions + layered policies.
- `run_comparison.py` — the shootout harness (no network; replays captures).
- `fixtures/reddit_observations.json` — live captures (5 pages, rich observation).
- `results/comparison_output.txt` — full per-page decision trace.
