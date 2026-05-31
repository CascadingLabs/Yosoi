# Findings: contrastive / metric learning — learn the space instead of hand-weighting it

**Branch:** `spike/cas-83-scope-canon` · **Run:** `contrastive.py` over the 13-domain / 52-sample corpus.

## The idea (yours)
Instead of hand-built fingerprints compared with a fixed-weight cosine
(`worldmodel.py` blends its 4 components *equally*), **learn** a space where pages of
the same class sit close and different classes sit far apart. That's the contrastive
objective: pull positive pairs together, push negative pairs apart. Same question for
*contracts* — how near/far are page↔contract in that space.

## Honest scoping (what's runnable vs future)
- **Deep contrastive** (SimCLR / triplet with a *learned neural encoder*) needs
  thousands of pairs — at n=52 it memorizes, not generalizes. Not honestly runnable here.
- **The trainable core IS runnable:** metric learning via **pairwise logistic
  regression** over the component similarities. For each page pair we already compute
  per-component sims (struct cosine, SimHash, body-class Jaccard, link/prose closeness);
  contrastive learning here = *fit weights* so positive pairs score high, negatives low.
  A learned linear distance — the simplest honest version of "learn the space," stdlib,
  no deps, no encoder.
- **The training pairs are FREE and already labeled:** positive = seed↔must-transfer,
  negative = seed↔must-refuse — and the deterministic content-invariant mints more at
  runtime. So a learned metric keeps improving with **zero human labeling** (the flywheel).

## Result (52 labeled pairs: 26 positive / 26 negative)
```
Hand-weighted equal blend (worldmodel baseline):
  positive mean 0.793 | negative mean 0.554 | separation 0.239
Learned linear metric (contrastive objective, full fit):
  positive mean 0.879 | negative mean 0.245 | separation 0.634   <- 2.7x wider
Learned metric, LEAVE-ONE-DOMAIN-OUT (unseen sites):
  pair-class accuracy 0.83 | leaks 4   (worldmodel 1-NN baseline 0.85 cross-domain)
Learned weights (which signals carry class):
  bodyclass +2.084 | prose_close +1.214 | struct_cos +0.901 | link_close +0.617 | simhash -0.329
```

## What this actually shows
1. **Learning the metric ~2.7× widens class separation** (0.634 vs 0.239) — it pushes
   negatives down to 0.245 where the hand blend left them at 0.554. A learned space is
   *visibly* cleaner than the equal-weight blend. This is the contrastive idea working.
2. **But cross-domain generalization is flat (0.83 vs 0.85 baseline).** Wider separation
   *in-distribution* doesn't beat the simple 1-NN out-of-distribution at this n — the
   learned weights slightly overfit the 13 training domains. Honest read: at 52 samples,
   contrastive learning **sharpens the boundary it can see but doesn't yet generalize
   better.** It needs the flywheel's volume to pay off.
3. **The learned weights are the free lunch — they're interpretable feature selection.**
   The metric independently decided `bodyclass` (+2.08) and `prose_close` (+1.21) carry
   the most class signal, `struct_cos` middling, and **`simhash` is actively unhelpful
   (−0.33)** — it's redundant with struct_cos (same source), exactly as the embedding
   findings predicted. *Even if you never ship the learned metric, run it once to learn
   which signals to keep.* It just told us to drop SimHash and weight body-class heavily.

## The "pages + contracts" half — the two-tower future
Your phrasing ("pages **+ contracts**") points at the bigger structure this enables:
**two-tower contrastive retrieval.** Embed a page in one tower, a contract in another,
train so a contract sits near the pages it successfully extracts and far from pages it
fails on. Then:
- "which of my N contracts fits this unseen page?" = nearest contract-tower vector → the
  CAS-85 recipe bank as a learned retrieval, not hand rules.
- "is this page in-class for this contract?" = page↔contract cosine in the joint space.
The labels are the *same free oracle*: a content-invariant pass = positive page↔contract
pair, a fail = negative. This is the principled version of the embedding "retrieval
index" reframe — but it needs thousands of pairs, which is exactly what CAS-118's
decision log + the runtime invariant accumulate. **Two-tower contrastive is the payoff
the labeling flywheel is for.**

## Where contrastive fits the cost ladder
- **Now:** the learned *linear* metric is a drop-in upgrade to `worldmodel.similarity()`
  — replace equal weights with weights fit on the free pairs. Cheap, no deps, and it
  already widens separation + prunes dead signals (SimHash). Use it for feature
  selection immediately; ship it as the metric once there are >few-hundred pairs.
- **Future:** a two-tower learned encoder over page + contract, trained on the
  accumulated invariant-labeled pairs, is the real cross-domain generalizer (CAS-85) and
  the thing that finally beats the hand-weighted baseline out-of-distribution. Gated on
  data volume, not on a new idea.

## Honest caveats
- n=52, 26/26 pairs, dev-skewed corpus. The full-fit separation (0.634) is in-sample;
  the LODO number (0.83) is the honest generalization estimate and it does **not** beat
  the simple baseline yet. "Contrastive helps" is proven for *separation + feature
  selection*; "contrastive generalizes better" is **not** proven at this n — it's the
  hypothesis the flywheel is meant to confirm.
- The learned linear metric is still a threshold classifier — same fail-closed /
  abstain / quarantine discipline applies; it does not change the leak-safety story,
  only the ranking quality feeding it.

## Avenues (ranked)
1. **Use the learned weights for feature selection now** — drop SimHash, up-weight
   body-class + prose in `worldmodel.similarity()`. Free, immediate.
2. **Swap equal-weight blend → learned linear metric** once CAS-118's flywheel has a few
   hundred invariant-labeled pairs; re-run LODO to see if it then beats 0.85.
3. **Two-tower contrastive (page-tower ↔ contract-tower)** as the CAS-85 retrieval engine
   — the real cross-domain generalizer, gated on thousands of pairs from the flywheel.
4. **Still the top prerequisite:** capture DOM tag-paths at scrape time — richer pair
   features make every metric (hand or learned) better.

## Files
- `contrastive.py` — pair builder + stdlib learned linear metric + LODO + weight readout.
- `results/contrastive_output.txt` — the run.
- Builds on `worldmodel.py` (the hand-weighted baseline it learns to beat) and the
  content-invariant (the free label source).
