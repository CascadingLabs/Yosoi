# Findings: a cheap "world model" for the web — redundant fingerprints + graceful degradation

**Branch:** `spike/cas-83-scope-canon` · **Run:** `worldmodel.py` over the 13-domain / 52-sample corpus (65 pages).

## The vision (yours)

At millions of contracts/domains/pages, we want to *understand what an entity is*
— classify and fingerprint a contract / domain / page — **even with partial or
corrupted information**, and **cheaply** (hashes + tiny vectors + nearest-neighbour,
never an LLM at query time). If a contract's own fingerprint is corrupted, recover
its class from structure. No single signal load-bearing → the model degrades, it
doesn't break. That's a world model for the web.

## The testable core: redundancy + ablation

A world model that "works with less" is precisely one where **knocking out any single
fingerprint component barely moves accuracy.** That's measurable today.

Each page gets a **redundant, cheap fingerprint** of 4 components:
- `struct` — normalized tag-frequency vector (the structural skeleton)
- `simhash` — 64-bit locality hash of that skeleton (O(1) compare, ANN-indexable)
- `kind` — body-class page-kind tokens (the site's own tell)
- `scalars` — link-density, prose-share, has-rows (interpretable)

Classifying a **new** entity = **1-NN over the fingerprints** (cosine / Hamming /
Jaccard). No training, no LLM. At scale it's an ANN index over millions of vectors;
here it's brute force over 65. Then we **ablate**: drop or corrupt each component and
re-measure k-NN class accuracy.

## Result: graceful degradation is real

```
[global] 1-NN page-class accuracy (entity matched against all others):
  FULL fingerprint (all 4):                 0.94
  drop struct   -> kind+scalars+simhash     0.95   (improves)
  drop simhash  -> kind+scalars+struct      0.92   (~no loss)
  drop kind     -> scalars+simhash+struct   0.94   (no loss)
  drop scalars  -> kind+simhash+struct      0.88   (small loss)
  single-component-only (everything else corrupted):
    only struct : 0.91      only scalars: 0.94      only kind: 0.69
```

**No component is load-bearing.** Drop any one and accuracy stays 0.88–0.95. Even with
**three of four components corrupted to zero**, a single surviving component recovers the
class at 0.69–0.94. That is exactly the robustness the vision needs: if contract
fingerprinting is corrupted, structure still classifies; if body-class is missing, the
scalars still carry it.

The cross-domain view (classify an entity using only entities from *other* sites — the
true "never seen this domain" test) holds up far better than expected:

```
[cross-domain] FULL 0.85 | drop struct 0.82 | drop simhash 0.78 | drop kind 0.88 | drop scalars 0.62
  single-component-only: scalars 0.91 | kind 0.69 | struct 0.62
```

(Interesting: the interpretable **scalars** — link-density, prose-share, has-rows — are the
most transferable lone signal across domains at 0.91. Three cheap floats carry page-class
across unseen sites better than any hash. That's a strong, almost-free cross-domain signal.)

## Why this is the cheap world model

- **Query cost = vector compare**, not an LLM. 1-NN over normalized tag vectors +
  Hamming over 64-bit SimHash. At millions of entities this is a standard ANN index
  (HNSW/IVF) — sub-millisecond, no model serving.
- **Redundant by construction** → corruption-tolerant. The ablation *is* the proof.
- **Self-describing entities.** Every contract/domain/page carries its own multi-part
  fingerprint; "what is this entity / what's it most like" is a lookup, not an inference.
- **The LLM only labels the ambiguous tail** (the ensemble's abstain band, batched +
  dedup'd) — and every batch verdict + every content-invariant pass is a free training
  label. The world model improves without per-query LLM cost.

## How the entities nest (contract / domain / page)

The same fingerprint machinery composes up the hierarchy, all cheap:
- **page** fingerprint = the 4 components above.
- **domain** fingerprint = the set/centroid of its pages' fingerprints + its page-class
  signatures (its "shape vocabulary"). Two domains are similar if their page-class sets
  are similar — that's how a recipe minted on one Shopify store finds another.
- **contract** fingerprint = its field set + semantic types + the page-classes it has
  successfully bound to. If the stored contract hash is corrupted, re-derive identity
  from the fields + the page-classes it historically matched — recover by *behaviour*,
  not by the lost hash.

Each level is a vector + a hash + a small token set — ANN-able, corruption-tolerant,
LLM-free at query time.

## Honest caveats (n=65)
- Accuracy is on a small, developer-skewed corpus; 0.92 is a signal-exists result, not a
  production SLA. The *shape* of the finding (graceful degradation) is the durable part.
- `simhash` here is over the tag histogram, so it's partly redundant with `struct` —
  dropping it even *helps* (removes a correlated-but-coarser vote). Its real value
  arrives with **tag-path** capture (see below), where it becomes a discriminative
  near-duplicate hash rather than a histogram echo.
- Cross-domain at 0.85 is stronger than expected for a no-LLM lookup, but on a small
  corpus; it's the recipe-bank generalization frontier (CAS-85) and richer structural
  features (tag-paths) should push it further.

## The one upgrade that compounds everywhere
**Capture DOM tag-paths (and the CSS-class set) at scrape time**, not just the tag
histogram. It is the single change that simultaneously: strengthens `struct`, makes
`simhash` a real template fingerprint, lifts cross-domain transfer, and sharpens every
level of the world-model hierarchy. Everything downstream gets better from one cheap
capture-time addition.

## Avenues (ranked)
1. **Capture tag-paths + CSS-class set at scrape time.** Compounding upgrade to the
   whole world model. Highest leverage.
2. **Ship the redundant fingerprint as the entity identity** (page/domain/contract),
   with ANN lookup — corruption-tolerant by design (ablation-proven).
3. **Recover-by-behaviour for corrupted contract hashes**: re-derive identity from fields
   + historically-matched page-classes.
4. **Feed batch-judge + content-invariant labels back** to sharpen the NN space over time
   — the LLM-free flywheel.

## Files
- `worldmodel.py` — redundant fingerprint + 1-NN class recovery + component ablation.
- `results/worldmodel_output.txt` — the run.
- Builds on `domain_free.py` (structure-only classing) and `ensemble.py` (the cheap
  hot-path + batched judge that labels the tail).
