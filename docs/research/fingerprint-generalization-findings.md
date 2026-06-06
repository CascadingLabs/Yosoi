# Findings: page-fingerprint generalization battery

_Live run of `experiments/fingerprint_generalization.py` on 2026-06-06 — 17 real pages, 8 domains,
6 page types, static fetch, no LLM. Companion to `scrapling-adaptive-selectors.md`._

## Headline results

```
experiments meeting design prediction : 12/12
recall   (same-template pairs bucketed): 7/8
precision(diff-template pairs split)   : 126/128
```

| # | experiment | verdict | skel / sem |
|---|-----------|---------|------------|
| E1 | same-domain, same-template, diff content (yahoo AAPL~MSFT) | MATCH ✓ | 0.97 / 1.00 |
| E2 | same-domain, different template (books detail~listing) | split ✓ | 0.25 / 0.60 |
| E3 | content-volume drift (quotes p1~p2) | MATCH ✓ | 0.95 / 1.00 |
| E4 | listing pagination (books p1~p2) | MATCH ✓ | 0.97 / 1.00 |
| **E5** | **cross-locale, diff domain (wiki en~de python)** | **MATCH ✓** | **0.47 / 0.74** |
| E6 | cross-domain, same CMS diff config (wikipedia~mediawiki.org) | split ✓ | 0.23 / 0.61 |
| E7 | cross-domain, same CMS diff skin (wikipedia~archwiki) | split ✓ | 0.29 / 0.62 |
| E8 | cross-domain, same page-type, diff site (books~scrapethissite) | split ✓ | 0.01 / 0.30 |
| E9 | cross-domain unrelated (HN~wikipedia) | split ✓ | 0.01 / 0.07 |
| E10 | same-site, diff section, same template (HN front~newest) | MATCH ✓ | 0.95 / 1.00 |
| E11 | minimal page vs rich page (example.com~books) | split ✓ | 0.03 / 0.11 |
| E12 | minimal page matches itself (example.com~example.com) | MATCH ✓ | 1.00 / 1.00 |

## What generalizes — and what doesn't

- **Same template, any content / volume / locale → buckets.** Tickers (E1), paginated listings
  (E3/E4), front-vs-section (E10), and crucially **cross-locale across different domains** (E5,
  en.wikipedia ↔ de.wikipedia) all match. E5 is the headline: the redesign's whole reason to exist —
  discover once on `en`, replay on `de` with zero new discovery — is real.
- **Different template → splits**, even on the same site (E2), the same page *type* across sites
  (E8 — a listing on `books.toscrape` ≠ a listing on `scrapethissite`), and the same *CMS* across
  domains (E6/E7 — wikipedia ≠ mediawiki.org ≠ archwiki). **We bucket the TEMPLATE, not the engine
  and not the page-type.** This refutes the naive prior "same CMS should share selectors."

## The key tension this battery exposed (most important finding)

The **cross-locale reuse we want** and a **cross-MediaWiki leak we don't** live in the *same skeleton
similarity band*:

```
KEEP:  wiki:en:python ~ wiki:de:python   skel 0.47   (same template, different locale)
DROP:  wiki:en:scrape ~ arch:bash        skel 0.51   (same engine, different site)   ← false match
DROP:  wiki:en:scrape ~ mw:mediawiki     skel 0.41                                    ← false match
```

A *short* Wikipedia article (`wiki:en:scrape`, 424 shingles vs python's 868) is structurally thin
enough that its skeleton overlaps other MediaWiki sites **above** the headline cross-locale pair.
So **raising the skeleton threshold to kill the leak (>0.51) would also kill cross-locale reuse
(0.47)** — the feature and the bug are inseparable on the skeleton axis alone.

**Consequences (acted on / to act on):**
1. **The L2 semantic layer earns its place.** The two false matches have semantic scores 0.59 / 0.67;
   the cross-locale keep is 0.74. The conjunction (skel ∧ sem) is what lets these *eventually* separate
   — single-signal skeleton cannot. This is live justification for the multi-signal P5 design, not a
   theoretical one.
2. **`fingerprint`-tier atoms stay default-quarantined.** Both leaks are exactly the kind of
   "similar-but-not-equal cross-site reuse" that strict mode (`YOSOI_ATOM_TRUST=strict`, default)
   refuses. The leak only fires under opt-in `yellow` — the user has explicitly accepted that risk
   there. The default is safe.
3. **Do NOT retune the semantic threshold to 0.70 on this evidence.** It *would* fix both leaks
   (0.59/0.67 < 0.70 ≤ 0.74) while preserving E5 — but the en↔de margin is only 0.04, and a French/
   Japanese locale could fall below 0.70 and silently lose the headline reuse. Losing cross-locale
   reuse (default-on win) is worse than a precision leak that only fires in opt-in yellow mode. Left
   at 0.50; logged as a candidate to revisit once L2 carries more signal (schema.org/landmarks).

## Secondary finding: the degenerate floor admits thin-but-real pages

`example.com` produces **10** skeleton shingles — exactly the complexity of the test suite's
"small-but-real" fixtures — and clears the degenerate floor (`_MIN_SKELETON_SHINGLES = 8`). So a
minimal page is treated as reusable (E12 matches itself, correctly; E11 still splits from a rich page
on structure). The floor only quarantines *near-empty* pages.

**Trade, left deliberate:** raising the floor (e.g. to 16) would quarantine `example.com` and guard
against two-unrelated-404s/parking-pages falsely matching — but it would also reclassify genuinely
small real pages (and the existing 10-shingle test fixtures) as un-fingerprintable, trading away thin-
page reuse. Because thin-page cross-site collisions are already caught by strict-mode quarantine, this
is logged as a tunable, not silently changed. Revisit if 404/parking-page collisions show up in prod.

## Scrapling cross-check (validated live)

`page_skeleton` is the **set of depth-2 windows over Scrapling's per-element `path`** (the ancestor-tag
tuple in `_StorageTools.element_to_dict`). On `books:detailA` every depth-2 shingle reduces to a clean
`(parent_tag, child_tag)` window — e.g. `('li','a')`, `('section','div')`, `('div','h2')`. Same
primitive; Scrapling keys it per-element-per-domain (recall-first relocation), we aggregate it page-
level and demote domain to provenance (precision-first cross-domain reuse). See the consult doc for the
full contrast.
