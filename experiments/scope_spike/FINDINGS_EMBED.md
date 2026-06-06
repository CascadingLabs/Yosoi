# Findings: embeddings as the missing middle rung (+ where they actually belong)

**Branch:** `spike/cas-83-scope-canon` · **Run:** `embed.py` over the 13-domain / 52-sample (65-page) corpus.
Reviewed by conservative / governance / lateral subagents before building.

## The hypothesis
Embeddings are the cost rung between free hashes and the expensive LLM: cheaper +
faster than an LLM, more *semantic* than a tag-histogram. The cases hashes miss are
semantic — `/user/spez` → "overview for spez" means *profile*, which structure can't
see (struct cosine to the listing seed = 0.993).

## The OpenRouter reality (you said "just use OpenRouter") — it works
**OpenRouter DOES serve embeddings** — `POST https://openrouter.ai/api/v1/embeddings`.
Verified live: an authed request with a bad key returns `401 "User not found"` (route
exists, key rejected), not `404` (no route). There's just no key in this env. So the
code is wired **provider-agnostic to any OpenAI-compatible `/embeddings`**; for
OpenRouter set:
```
EMBEDDINGS_BASE_URL=https://openrouter.ai/api/v1
EMBEDDINGS_API_KEY=<openrouter key>
EMBEDDINGS_MODEL=openai/text-embedding-3-small   # or any OR embeddings model
```
With no key it runs a dependency-free **proxy** (hashed char-trigram) and labels it.
(Correction: an earlier note in this spike mis-read the probe as 405/unsupported —
OpenRouter added embeddings; the live probe confirms the route is real.)

## Proxy result `[PROXY — lexical, a floor]`
```
EXP1 costume: seed "top scoring links : ted"
  listing sibling "top scoring links : Python"  emb-cos  0.816   (high = same kind ✓)
  /user/spez      "overview for spez"            emb-cos -0.046   (low  = different ✓)
EXP2 cross-domain 1-NN class accuracy (title only): 0.65
EXP3 per-domain clean separation by title-emb:      8/13
```
**EXP1 is a clean split even on the lexical proxy** — the listing sibling shares the
"top scoring links" prefix (0.816) while the profile is orthogonal (−0.046). So on
Reddit the title alone separates the costume case the *structure* couldn't (struct
cosine 0.993). **But that win is fragile and lexical:** it works because Reddit reuses
a title template; it would NOT transfer to a site whose listing/profile titles share no
characters. That's why EXP2 cross-domain is only **0.65 — below the 0.91 from plain
scalars**: a char-n-gram embedding can't relate "overview" to "profile" across sites.

This is the **proxy/real gap the governance reviewer predicted, made concrete**: the
proxy proves the *placement* (a title signal targets the semantic gap) but a real
semantic model is required for the *cross-domain* payoff (it relates meaning without
shared characters). Every number here is `[PROXY]` and a floor; **ship nothing on it.**

## The reframe the reviewers converged on (this is the real finding)

> **Embeddings don't belong in the classifier — they belong in the retrieval index for
> the cross-domain recipe bank.**

The lateral reviewer's decisive point, and the other two back into it:
- The **classifier is already solved cheaply**: scalars alone transfer cross-domain at
  0.91, the rule+hash ensemble has 0 leaks. Adding an embedding *vote* to the hot path
  buys ~nothing and adds a model dependency + latency + a threshold that can leak
  (conservative: "no-go as a hot-path vote"; governance: "only ever an abstain-band
  signal, never an ALLOW gate").
- What's genuinely **missing** is *retrieval*: "I've never scraped Glassdoor, but it
  *looks like* LinkedIn, and I have a LinkedIn recipe — try it." That's a nearest-
  neighbour query in semantic space across domains, which a tag-histogram cosine
  cannot do and an embedding can. **This is CAS-85 (the recipe bank) made buildable.**

So the placement, ranked by leverage (all three reviewers' synthesis):
1. **Cluster the abstains → judge cluster CENTROIDS, not items.** A *second* batching
   multiplier on top of signature dedup: a Shopify product page and an unseen-store
   product page embed together → the LLM judges one centroid for the whole cluster.
   The dedup factor stops being "within a domain" and becomes "across the structural
   universe." Highest leverage, runnable off the existing abstain queue.
2. **Retrieval index for the recipe bank (the 10x / moonshot):** ANN over entity
   embeddings → 0-shot cross-domain recipe transfer. Embedding lives in the *index*,
   not the pipeline.
3. **Augment (not replace) the world-model entity vector** with an embedding slot —
   stays ablation-compatible (embedding down → fall back to scalars at 0.91).
4. **A hot-path ensemble vote** — lowest leverage, highest risk. Don't.

## What to embed (the cheap experiment to run with a real key)
Not title-only (too sparse — see EXP1). The reviewer-favoured candidate: a fusion of
**title + body-class tokens + a serialized tag-path string**. The tag-path string is
the structural grounding that stops a profile from embedding as a listing even when the
histogram is identical; the title carries the semantic tell; body-class carries the
site's own label when present. With a real model, re-run EXP2 against the scalars (0.91)
and struct (0.62) baselines — it must *beat 0.91 cross-domain AND split spez from the
listing* to earn a slot.

## Guardrails the reviewers require (don't skip if this graduates)
- **Metric = leak-rate, not accuracy.** Leave-one-domain-out; every fold must hit 0
  leaks. Must reduce abstain-rate vs the SimHash+struct baseline to justify itself.
- **Pin the model by content hash** (`model_id = sha256(weights+tokenizer)`) on every
  stored vector; reads assert `query.model_id == store.model_id` or hard-error. A model
  swap is a full re-embed + atomic index swap, never in-place.
- **Real embeddings are batch/offline only** — never synchronous on the replay path
  (same rule as the LLM judge). The provider client here batches.
- **kNN is opaque** → log query model_id + top-k neighbours + cosines + classes for
  every verdict; pin behaviour with a named fixture test.
- **Ship nothing on proxy numbers.** The proxy answers "is a dense representation worth
  a real model?" — not "what's the production number."

## The cheapest-thing-that-might-beat-it (lateral's near-free alternative)
Before a transformer: try **TF-IDF over `title + body-class tokens`** (scipy/stdlib, no
model file) or **model2vec** (~5MB static, microseconds). If TF-IDF beats SimHash on the
costume case and clears 0.91 cross-domain, the "embedding" was the wrong mental model and
the middle rung is a sparse matrix multiply. Worth a one-afternoon bake-off with a real
key vs TF-IDF vs model2vec.

## Avenues (ranked)
1. **Capture DOM tag-paths at scrape time** — *still* the top prerequisite; it's the
   structural half of the best embedding input and lifts every other signal.
2. **Cluster-abstains→judge-centroids** using a real embedding — the immediate batching win.
3. **Recipe-bank retrieval index** (CAS-85) keyed on a real entity embedding — the moonshot.
4. **Provider bake-off** (real model vs TF-IDF vs model2vec) on title+bodyclass+tagpath,
   scored leak-rate / abstain-rate / costume-split, with a real `EMBEDDINGS_API_KEY`.

## Files
- `embed.py` — proxy embedding + provider-agnostic OpenAI-compatible remote client +
  3 experiments (costume split, cross-domain 1-NN, per-domain separation).
- `results/embed_output.txt` — the proxy run (labeled as a floor).
- Builds on `worldmodel.py` (the entity fingerprint the embedding augments) and
  `ensemble.py` (the abstain queue the clustering compresses).
