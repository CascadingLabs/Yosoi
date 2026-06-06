# Findings: reuse-safety across 13 domains / 52 samples (the statistical run)

**Branch:** `spike/cas-83-scope-canon` · **Run:** `uv run python experiments/scope_spike/run_multidomain.py`
**Data:** `fixtures/domains/*.json` (live voidcrawl captures, one identical generic extract per page)

## Setup

13 domains, each contributing a **seed** (page a recipe was learned on) + 2
**must-transfer** siblings (same page-class, reuse SHOULD work) + 2 **must-refuse**
pages (different class same domain, reuse SHOULD be blocked). **52 replay
decisions (26 transfer / 26 refuse)** — past the 30-sample bar.

Domains: reddit, hackernews, lobsters, books.toscrape, quotes.toscrape,
webscraper.io e-com, arxiv, pypi, stackoverflow, wikipedia(EN), wikipedia(JA,
cross-language), wiktionary, sec edgar.

Four **generic, site-agnostic** mechanisms (expectation derived from the seed
only) + two fail-closed layers:
- **discovery** — rows > 0 (status quo)
- **cardinality** — replay rows within band of seed (VALIDATION, content)
- **route** — same URL route template (TAGGING via URL)
- **structural** — DOM tag-histogram cosine ≥ 0.90 (TAGGING via shape, URL-free)

## Result (real numbers, 52 samples)

| approach | good ✓ | bad ✓ | **LEAKS** | false alarms | accuracy |
|---|---|---|---|---|---|
| discovery | 24 | 18 | **8** | 2 | 0.81 |
| cardinality | 21 | 24 | 2 | 5 | 0.87 |
| route | 13 | 19 | **7** | **13** | 0.62 |
| **structural** | **26** | 22 | 4 | **0** | **0.92** |
| card+struct | 21 | 25 | **1** | 5 | 0.88 |
| card+route+struct | 10 | 26 | **0** | **16** | 0.69 |

## Scaling up overturned the single-domain conclusion

On Reddit alone, *validation* looked like the clear winner. Across 13 domains the
ranking changed — three findings, the first two are the headline:

### 1. STRUCTURAL (DOM shape) is the best single mechanism — 0.92 acc, ZERO false alarms
The tag-histogram cosine is the most reliable generic signal by a wide margin. It
never false-alarmed (every same-class sibling across all 13 domains scored ≥0.916
cosine to its seed) and leaked only 4×. **This is the cross-language win too:**
Wikipedia EN→JA category transfer passed structurally — the MediaWiki skeleton is
identical regardless of language, so a shape signal generalizes where text never
could. Measured separation:
```
must-transfer cosine: min=0.916  mean=0.989  max=1.000
must-refuse  cosine:  min=0.000  mean=0.723  max=0.993
```

### 2. ROUTE (URL template) is the WORST — 0.62 acc, fails BOTH directions
The URL is an unreliable class signal in both directions at once:
- **13 false alarms (over-split):** it treats sibling lists as different classes —
  HN `/news` vs `/newest`, lobsters `/newest`, SO `/tagged/python`, books category
  pages. Sort/filter/tag verbs look structural in a URL but aren't a page class.
- **7 leaks (over-merge):** on MediaWiki, `/wiki/Category:Film` and `/wiki/Film`
  both normalize to `/wiki/{slug}` — so route says "same class" and **leaks the
  article into the category recipe.** Same root cause as the slug problem we
  discussed: you cannot tell class from a URL without per-site knowledge.

This is decisive: **do not put URL route-template in the default safety chain.**
It was the single worst mechanism tested and it dragged `card+route+struct` to 16
false alarms.

### 3. The unkillable leak: a wrong page that wears the right costume
**Reddit `/user/spez` survives discovery, cardinality, AND structural.** It's a
profile page rendered with the *same listing template* — 5 post rows (in
cardinality band of 25) and cosine **0.993** to the seed (inside the transfer
zone). No generic shape/count signal can see it, because structurally it *is* the
listing template. The transfer/refuse cosine ranges **overlap** (refuse-max 0.993
> transfer-min 0.916) entirely because of cases like this.

What *does* catch it: a **content-semantic invariant** — the seed's posts are all
from one subreddit; the profile's are from many. That's the homogeneity guard from
the single-domain run, and it's the only thing that catches this class. **No purely
structural mechanism is sufficient; you need at least one content invariant.**

## The honest accuracy ceiling

- **No approach was perfect** (0 leaks AND 0 false alarms) across 52 samples. The
  single-domain "validation is perfect" result did **not** survive scale-up.
- **Best leak/accuracy tradeoff: `card+struct`** — 1 leak (the reddit `/user`
  costume case), 5 false alarms, 0.88 acc. The 1 leak is exactly the case that
  needs the homogeneity content-invariant on top.
- **Zero-leak was only reachable by adding route** — but route brought 16 false
  alarms (0.69 acc), i.e. it bought leak-safety by refusing a third of all *good*
  reuses. Not a real win; a fail-closed chain's false alarms are pure cost.
- **Cardinality leaked on HN comments (190 rows > 30 seed):** my floor only guards
  *below* the seed; a comments page with *more* rows than the listing sailed
  through. Cardinality needs a **two-sided band**, not just a floor.
- **Fixture caveat (kept honest):** the EN-Wikipedia seed was a "diffused"
  category (rows=1) so its siblings (rows=0) false-alarmed under cardinality. That's
  a bad-seed artifact, not a mechanism failure — flagged, not hidden. JA-Wikipedia
  (proper leaf categories, rows 55/27/8) behaved correctly.

## What generalizes (the answer to "does this hold past 30 samples?")

**Yes, with a corrected design.** The robust, measured recommendation:

1. **STRUCTURAL (DOM tag-histogram cosine) is the primary class signal.** Best
   accuracy, zero false alarms, URL-free (works on Maps-style garbage URLs and
   across languages). Threshold ~0.90 sits below every observed same-class pair.
2. **+ a content invariant (cardinality two-sided band, and homogeneity where a
   field is constant at discovery).** This is the *only* thing that catches the
   "right costume, wrong page" leak (reddit `/user`) that structure cannot.
3. **DROP URL route-template from the safety chain.** Worst mechanism; fails both
   ways. Keep route purely as a cheap *cache lookup key*, never as a *safety gate*.
4. **DISCOVERY (rows>0) is never a safety mechanism** — 8 leaks confirm it.

So the layered guard stands, but **the layers are reordered by the data**:
structure-first + content-invariant, *not* URL-first. And the residual truth: a
small set of adversarial pages (a site reusing its list template on a non-list
page) defeats every generic signal and needs a content/semantic invariant or an
explicit page-class token (`bodyClass: profile-page`) — which is the narrow,
honest place a tiny bit of per-site signal earns its keep.

## Avenues to walk (ranked, updated by 52-sample data)

1. **Ship structural-cosine + two-sided cardinality as the CAS-83 guard.** 0.88
   acc, 1 residual leak, no URL dependence. Highest-confidence deliverable.
2. **Add homogeneity (constant-field) validation for the costume case.** It's the
   only generic catch for reddit `/user`-class leaks. Auto-derived from the
   discovery collection; no tuning. *(closes the last leak.)*
3. **Make cardinality two-sided.** The HN-comments leak (190≫30) proves a floor
   isn't enough; band both directions. *(cheap, closes a leak.)*
4. **Use `bodyClass`/page-kind token as an optional high-precision tag** where the
   site emits one (reddit, SO, MediaWiki `ns-*`). It cleanly separated every case
   it was present for — the sanctioned minimal per-site signal. *(medium.)*
5. **Value-belongs-to-entity validation** for the Yahoo same-page wrong-entity leak
   (BTC price into AAPL) — a class this experiment's row-based mechanisms don't
   even test. *(medium, separate failure mode.)*
6. **Scope-inference / tier-graduation stays deferred** behind `reuse="scale"`.
   Nothing here needs multi-instance learning; the guard works per-page today.

## Files
- `run_multidomain.py` — the 13-domain shootout (no network; replays captures).
- `fixtures/domains/*.json` — 13 live-captured domain fixtures (65 pages).
- `results/multidomain_output.txt` — full aggregate + per-failure trace.
- `FINDINGS_VALIDATION_VS_TAGGING.md` — the earlier 5-page Reddit-only run (now
  superseded on the ranking by this statistical run; kept for the narrative).
