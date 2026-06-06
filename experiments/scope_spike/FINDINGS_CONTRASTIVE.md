# Findings: contrastive / metric learning — learn the space instead of hand-weighting it

**Branch:** `spike/cas-83-scope-canon` · **Run:** `contrastive.py` over the 13-domain / 52-sample corpus.
All numbers below are verbatim from `results/contrastive_output.txt`.

## The idea (yours)
Instead of hand-built fingerprints compared with a fixed-weight cosine
(`worldmodel.py` blends its 4 components *equally*), **learn** a space where pages of
the same class sit close and different classes sit far apart — the contrastive
objective: pull positive pairs together, push negative pairs apart. Same question for
*contracts*: how near/far are page↔contract in that space.

## Honest scoping (runnable vs future)
- **Deep contrastive** (SimCLR / triplet with a *learned neural encoder*) needs
  thousands of pairs — at n=52 it memorizes, not generalizes. Not honestly runnable here.
- **The trainable core IS runnable:** metric learning via **pairwise logistic
  regression** over the component similarities. For each page pair we already compute
  per-component sims (struct cosine, SimHash, body-class Jaccard, link/prose closeness);
  contrastive learning here = *fit weights* so positive pairs score high, negatives low.
  A learned linear distance — the simplest honest "learn the space," stdlib, no encoder.
- **Training pairs are FREE and already labeled:** positive = seed↔must-transfer,
  negative = seed↔must-refuse — and the runtime content-invariant mints more. So a learned
  metric keeps improving with **zero human labeling** (the flywheel).

## Result (52 labeled pairs: 26 positive / 26 negative)
```
Hand-weighted equal blend (worldmodel baseline):
  positive mean 0.965 | negative mean 0.808 | separation 0.157
Learned linear metric (contrastive objective, full fit):
  positive mean 0.795 | negative mean 0.212 | separation 0.584   <- ~3.7x wider
Learned metric, LEAVE-ONE-DOMAIN-OUT (unseen sites):
  pair-class accuracy 0.90 | leaks 5   (worldmodel 1-NN baseline 0.85 cross-domain)
Learned weights (which signals carry class):
  simhash +7.338 | struct_cos +7.192 | bodyclass +2.425 | link_close +1.001 | prose_close -0.263
```

## What this shows
1. **Learning the metric ~3.7× widens class separation** (0.584 vs 0.157) — it drives
   negative pairs down to 0.21 where the equal-weight blend left them at 0.81. A learned
   space is dramatically cleaner. The contrastive idea works.
2. **And it generalizes at least as well cross-domain: LODO 0.90 vs the 0.85 baseline.**
   At n=52 a learned linear metric already edges the hand-weighted 1-NN on held-out
   domains — not just in-distribution. (Caveat: on 26 negative pairs one decision ≈ 4
   points, so read 0.90-vs-0.85 as "as good and plausibly better," not a settled win.)
   5 leaks remain — it is still a threshold classifier, so the fail-closed / abstain /
   quarantine discipline still applies; contrastive improves the *ranking*, not the
   leak-safety guarantee.
3. **The learned weights are a free lunch — interpretable feature selection.** The metric
   independently weighted **`simhash` (+7.34) and `struct_cos` (+7.19) as the dominant
   class signals**, body-class (+2.43) and link-closeness (+1.00) secondary, and
   **`prose_close` mildly counterproductive (−0.26)**. Honest surprise: SimHash, which
   looked redundant/dead in the *unweighted* blend and in the embedding findings, is
   *not* dead once the metric is **learned** — it co-leads. Learning recovers signal that
   equal-weighting hid. Run the fit once just to get this ranking, even if you never ship
   the metric.

## The "pages + contracts" half — the two-tower future
Your phrasing ("pages **+ contracts**") points at the bigger structure: **two-tower
contrastive retrieval.** Embed a page in one tower, a contract in another, train so a
contract sits near the pages it successfully extracts and far from pages it fails on:
- "which of my N contracts fits this unseen page?" = nearest contract-tower vector → the
  CAS-85 recipe bank as learned retrieval, not hand rules.
- "is this page in-class for this contract?" = page↔contract cosine in the joint space.
Same free oracle for labels: a content-invariant pass = positive page↔contract pair, a
fail = negative. This is the principled version of the embedding "retrieval index"
reframe — needs thousands of pairs, which is exactly what CAS-118's decision log + the
runtime invariant accumulate. **Two-tower contrastive is the payoff the flywheel is for.**

## Where contrastive fits the cost ladder
- **Now:** the learned *linear* metric is a drop-in upgrade to `worldmodel.similarity()`
  — replace equal weights with weights fit on the free pairs. Cheap, no deps, ~3.7× wider
  separation, edges the baseline cross-domain. Use the fit for feature selection
  immediately (co-weight simhash+struct, demote prose-closeness).
- **Future:** a two-tower learned encoder over page + contract, trained on the
  accumulated invariant-labeled pairs, is the real cross-domain generalizer (CAS-85).
  Gated on data volume, not a new idea.

## Honest caveats
- n=52, 26/26 pairs, dev-skewed corpus. Full-fit separation (0.584) is in-sample; the
  LODO 0.90 is the honest generalization estimate and it edges the 0.85 baseline — but at
  ~4 points/decision, treat it as "≥ baseline, plausibly better," not proven. The durable
  claims: (a) learning widens separation a lot, (b) it generalizes *no worse* than the
  hand blend while being principled, (c) the learned weights are trustworthy feature
  selection.
- Still a threshold classifier — fail-closed/abstain/quarantine discipline unchanged;
  contrastive changes ranking quality, not leak-safety (5 LODO leaks).

## Avenues (ranked)
1. **Use the learned weights for feature selection now** — adopt the fit's
   simhash+struct_cos-led weighting in `worldmodel.similarity()` instead of the equal
   blend; demote prose-closeness. Free, immediate.
2. **Swap equal-weight blend → learned linear metric** — it already edges the baseline
   cross-domain (0.90 vs 0.85); re-fit + re-run LODO as CAS-118's flywheel adds pairs to
   confirm the margin holds at larger n.
3. **Two-tower contrastive (page-tower ↔ contract-tower)** as the CAS-85 retrieval engine
   — the real cross-domain generalizer, gated on thousands of flywheel pairs.
4. **Still the top prerequisite:** capture DOM tag-paths at scrape time — richer pair
   features make every metric (hand or learned) better.

## Files
- `contrastive.py` — pair builder + stdlib learned linear metric + LODO + weight readout.
- `results/contrastive_output.txt` — the run.
- Builds on `worldmodel.py` (the hand-weighted baseline it edges) and the content-invariant
  (the free label source).
