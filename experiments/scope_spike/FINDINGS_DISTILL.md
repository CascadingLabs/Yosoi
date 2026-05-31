# Findings: distilling the LLM judge into a cheap, typed, regression-tested detector

**Branch:** `spike/cas-83-scope-canon`
**Runs:** `distill.py` (logistic, leave-one-domain-out) · `detector.py` + `test_detector.py` (typed rules) · `breakdown.py`
**Data:** same 13-domain / 52-sample fixtures.

## The problem (your framing)

The LLM judge is perfect (1.00) but **economically infeasible** to call per page or
per data source — that breaks the "discover once, replay forever, no-LLM-on-the-hot-path"
cost model that justifies the whole cache. The LLM isn't the gate; it's the **teacher**.
We distill its judgment into something free, and pin it with a typed pytest suite so
regressions surface instantly.

## Two distillations, both validated

### A) Logistic regression, leave-one-domain-out (the honest generalization test)
`distill.py` fits a hand-rolled logistic (stdlib, **no sklearn**) on free features and
evaluates **leave-one-domain-out** — train on 12 domains, predict the 13th it has never
seen. That's the real economic question: *does it work on a domain we didn't pay to label?*

| detector | leaks | false alarms | accuracy |
|---|---|---|---|
| body_class alone | 15 | 8 | 0.56 |
| struct_cosine ≥ 0.90 | 4 | 0 | 0.92 |
| **LogReg (leave-one-domain-out)** | **0** | 4 | 0.92 |

**Zero leaks on unseen domains.** Learned weights are interpretable: `struct_cosine`
(+5.0) and `rows_ratio` (+3.5) push allow; `title_len_ratio` (−2.0, articles are long)
and `url_depth_delta` (−1.6) push refuse. The model learned exactly the signals the LLM
named in its reasons.

### B) Typed rules — the design the reviewers converged on (shipped)
The lateral reviewer's decisive point: this is a **pairwise** judgment ("is replay the
same KIND as seed?"), not an absolute label — so a logistic over replay-only features is
wrong by construction whenever the seed's class flips the answer. Distill into **typed,
git-diffable rules** instead. `detector.py` transcribes the LLM's plain-text reasons into
6 named pairwise rules. Real result on all 52 samples (`breakdown.py`):

```
allow=22  refuse=21  abstain=9     LEAKS=0  false_alarms=0  abstain_rate=17%
rule firings: structural_allow 22 | zero_rows 16 | (abstain/none) 9 |
              detail_bodyclass 2 | ns_mismatch 2 | row_explosion 1 | profile_title 0
```

**0 leaks, 0 false alarms** — it never ships wrong data and never wrongly refuses a good
transfer. The tradeoff vs the logistic: the logistic answered all 52 (with 4 false alarms);
the rules answer 43 confidently and **abstain on 9 (17%) → escalate to the cached LLM
judge**. Both have zero leaks. Abstain is not free — it's a deferred LLM call — so **17% is
the real economic number** (the headline cost, not a rounding note). Zero runtime LLM on the
43 confident cases, zero deps, runs in 0.03s.

## What the data proved (reviewer predictions, confirmed)

1. **`rows==0` is the freest signal and does most of the work** (lateral): one rule —
   "listing seed but replay matched nothing" — fires **16 times, all correct refuses**, the
   single biggest refuse contributor. (Lateral eyeballed 18/26; the rule guards on
   `seed.rows>3`, so the EN-Wikipedia bad-seed case with 1 row correctly abstains instead.)
2. **body_class alone is NOT enough** (lateral, against the obvious guess): 0.56 accuracy
   — 7 of 13 domains emit no discriminating token (arxiv `with-cu-identity`, pypi, empty
   HN). It's a *targeted* rule, not the backbone — but where present it's decisive (see #3).
3. **The costume case is caught by the body-class token, not a magic title rule** — an
   honest correction to my own earlier claim. Reddit `/user/spez` (cosine 0.993, 5 rows in
   band) defeated the pure-numeric guards in the multidomain run, but old.reddit *emits*
   `body_class="listing-page profile-page"` — so `detail_bodyclass` catches it on the
   `profile-page` token, the SAME rule that catches the comments page. The semantic
   `profile_title` rule fired **0 times** here (it's defensive for sites that emit no token,
   e.g. HN `/user?id=` — which abstains to the LLM instead). Pinned by
   `test_costume_case_caught`.
4. **The HN 190-row trap needs a two-sided + prose check** (governance): `row_explosion`
   catches a comments page with *more* rows than the seed, which a one-sided floor missed.
5. **Abstain, never guess** (conservative): 2 cases fire no rule → `ABSTAIN` → escalate to
   the cached LLM judge. ALLOW is never the default. Fail-closed.

## The regression harness (your explicit ask)

`test_detector.py` — 56 tests, runs in 0.03s, **no network**:
- **per-case, parametrized & named:** every must-refuse fixture asserted individually.
  A regression fails as `test_no_leak[reddit::must-refuse::/user/spez]` — pointing at the
  exact domain+page that broke, not a mystery accuracy delta.
- **headline gate:** `leaks == 0` is the only hard pass/fail (leaks = silently wrong data
  = the cardinal sin); false alarms have a ratcheting budget.
- **economics gate:** `abstain_rate <= 25%` — if too many cases escalate to the LLM, the
  cost model is broken. (Currently 17% — 9/52; the headline cost number.)
- **costume pin + fixture-presence guard** so the harness can't pass vacuously.

This is what "radically typed → catch regressions fast" buys: a `Verdict` enum +
`Obs`/`Decision` dataclasses mean a fixture-shape drift or a rule change is a *named test
failure*, not a silent accuracy loss.

## The honest caveats (don't over-claim n=52)

- **0 leaks on 26 refuse cases ≈ leak-rate ≤ ~13% at 95% Wilson.** "Zero" here means "zero
  on these fixtures," strong evidence the *signal class* (semantic + structural rules)
  dominates pure geometry — not a production guarantee.
- **Rules are seed-relative.** Every rule is `seed has X AND replay has Y` — correct only
  because the fixtures' seeds are listings. A profile-seeded contract would need its own
  rules. This is inherent to pairwise judgment, not a bug, but it means the rule-bank is
  keyed by *seed page-class*, not global.
- **The fixtures are frozen point-in-time captures.** Sites drift; labels rot. Governance's
  ask: a quarterly re-fetch that flags any seed whose cosine to its frozen fixture drops
  below 0.90 for re-capture. Not automated — human reviews the diff.

## The architecture this lands (the synthesis)

**Hot path, free, every replay:** typed rule detector (`detector.py`).
- fires ALLOW/REFUSE on 83% of cases with 0 leaks → no LLM.
- **ABSTAIN (17%) → cached LLM judge**, verdict cached per `(seed-class, replay-class)`
  signature → LLM pays once per *kind* of ambiguity, then free forever. The 17% is where
  the rule-bank is still thin; it shrinks as rules accrue (flywheel below).
- **deterministic content invariant** (`row.subreddit == requested`) is the final kill for
  the adversarial tail, and — the lateral flywheel — every invariant pass/fail at runtime
  is a *free new label* to extend the rule-bank with zero LLM after bootstrap.

So: **rules (free) → LLM judge at the abstain boundary (cached, rare) → content invariant
(free oracle + label source).** The LLM cost asymptotes toward zero as the rule-bank fills,
and a public/shared rule-bank ("MediaWiki ns-14→ns-0 = refuse") amortizes one label across
every wiki on earth.

## Avenues to walk (ranked)
1. **Ship `detector.py` + `test_detector.py` as the CAS-83 guard.** 0 leaks, 0 false alarms,
   17% escalation, typed regression CI. Highest-confidence deliverable.
2. **Wire the abstain → cached-LLM-judge path** with per-signature caching. The 17% is where
   the LLM earns its keep — and where new rules come from to shrink it.
3. **Build the content-invariant flywheel:** invariant pass/fail at runtime auto-labels new
   cases; promote a rule when a domain accumulates N consistent negatives. Zero LLM after
   bootstrap.
4. **Seed a shared rule-bank** (MediaWiki, Shopify, Discourse families) — one label, many sites.
5. **Grow fixtures to ≥20 diverse domains** (non-English, SaaS dashboards) before trusting
   the logistic over the rules; at n=52 the rules win and are honest.

## Files
- `distill.py` — logistic + leave-one-domain-out + single-feature baselines (no sklearn).
- `detector.py` — the 6 typed pairwise rules + 3-way `Verdict` (allow/refuse/**abstain**).
- `test_detector.py` — the 56-test regression harness (the deliverable you asked for).
- `breakdown.py` / `results/detector_breakdown.txt` — verdict + rule-firing tally.
- Prior: `FINDINGS_LLM_JUDGE.md` (the teacher), `FINDINGS_MULTIDOMAIN.md` (the algorithms).
