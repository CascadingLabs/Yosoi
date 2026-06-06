# Findings: ensemble + BATCHED judge + quarantine + domain-free classing

**Branch:** `spike/cas-83-scope-canon`
**Runs:** `ensemble.py`, `provenance.py`, `domain_free.py` over the 13-domain / 52-sample fixtures.

This lands four ideas from the design thread as runnable code with real numbers.

## 1. "Do both" — ensemble on the hot path, LLM judge in a batch off it

The objection to the LLM judge was never accuracy — it was **synchronous LLM in the
replay path**. Batching dissolves it: the hot path is a deterministic ensemble; the
uncertain band is *queued*, not blocked on.

`ensemble.py` runs a **cost-asymmetric cascade** of cheap signals (typed rules +
tag-cosine + SimHash Hamming + body-class agreement): trust a high-precision REFUSE
immediately; ALLOW only on multi-signal agreement; otherwise **ABSTAIN → batch queue.**

```
hot-path verdicts: allow=21  refuse=21  abstain(queued)=10
  LEAKS=0   false_alarms=0   abstain rate=19%

BATCHED-JUDGE ECONOMICS:
  naive LLM-per-page (hot path):    52 calls
  LLM only on abstains:             10 calls   (81% eliminated by the ensemble)
  ... batched & dedup by signature: 10 distinct signatures judged
  net vs naive:                     52 -> 10    (81% fewer judge calls)
```

**0 leaks, 0 false alarms, and the LLM touches only 19% of decisions — asynchronously.**

## 2. The batching multiplier: dedup by page-class signature

The batch isn't "the same calls, later." Abstains are **deduplicated by a coarse
page-class signature** before judging — so you judge a *kind* of page once, then
cache the verdict for every page that shares the signature. Proven directly:

```
spez     -> refuse | sig: old.reddit.com|listing->listing,profile-page|rows0=False|cos~1.0
kn0thing -> refuse | sig: old.reddit.com|listing->listing,profile-page|rows0=False|cos~1.0
SAME SIGNATURE (judged once for both): True
```

On 52 unique fixtures the dedup factor is ~1.0 (every fixture is a different
page-class by construction). **In production it's the opposite:** 10,000 reddit
`/user/*` pages share one signature → **one** judge call. The batch size is the number
of *distinct page-classes*, not pages — and signatures recur across runs, so the
judge cost per page → ~0. This is what makes the LLM affordable: it pays once per
*kind* of ambiguity, ever.

## 3. Quarantine — "use the unverified data, but mark it" (`provenance.py`)

An ensemble ALLOW on cheap signals is *usable but not trusted*. Instead of silently
emitting it (a leak) we put it in a typed, monotonic trust lattice:

```
QUARANTINED ──judge/invariant: ok──> VERIFIED
     └────────judge/invariant: wrong──> REJECTED
```

On the 52 samples: **21 REJECTED** (a deterministic refuse fired — safe, blocks reuse,
emits nothing) + **31 QUARANTINED** (allowed on cheap signals → usable downstream *only
if it tolerates quarantine*, flagged, and queued for the batch judge). **Nothing is
auto-VERIFIED without a judge or a deterministic content invariant.** That is the
fail-fast ethos applied to data integrity, and it mirrors the `DownloadRecord`
quarantine-dir pattern (CAS-105): produce into quarantine, adjudicate, then promote.

Downstream consumers choose their risk: a cost-comparison scrape may use quarantined
rows immediately (marked); a contract that demands verified data waits for promotion.
Either way **unverified data is never indistinguishable from verified** — the cardinal
sin is structurally impossible.

## 4. Domain-free DOM classing — the north star, measured (`domain_free.py`)

Your vision: predict page-class from the **DOM alone, no domain, no URL**. Tested two
ways on all 65 pages:

- **Q1 separability** (a tiny interpretable score: link-density − prose-share + has-rows,
  *zero* url/domain features, 65 pages): listings vs details separate at **acc 0.88**
  (listing-score mean 0.65 vs detail-score mean −0.08; 34 listings + 23 details correct,
  3+5 misses).
- **Q2 cross-domain nearest neighbour** (each page's nearest neighbour *by structure in a
  different domain*): **62%** share the same class — a listing on site A looks more like a
  listing on site B than like a detail page, using shape alone.

**Verdict: domain-free classing already works at 0.88 from a coarse signal; the
cross-domain transfer (0.62) is the part with headroom** — and that's exactly where your
SimHash point lands. The honest limitation:

> Our fixtures only captured the **tag-frequency histogram**, which is a *coarse*
> structural signal (and the SimHash over it is partly redundant with cosine — it scored
> 0 rescues here). The web-dedup literature fingerprints **DOM tag-PATHS**
> (`html>body>div.main>ul>li>a`), not tag counts. Tag-path SimHash is far more
> discriminative and is what would push domain-free classing from 0.60 toward the
> ensemble's 0.83+. **Capturing tag-paths at scrape time is the single highest-leverage
> upgrade to fingerprinting** — it strengthens the ensemble's structural signal AND is the
> prerequisite for the domain-free recipe bank (CAS-85).

If domain-free classing gets strong, reuse scope stops being "same site?" and becomes
"same structural class?" — and a recipe minted on one site replays on a structurally
identical page anywhere, no per-site rules.

## The architecture this lands

```
REPLAY (hot path, synchronous, free, deterministic):
  ensemble(rules + cosine + simhash + body-class)
    REFUSE  -> REJECTED  (block reuse, re-discover; safe)
    ALLOW   -> QUARANTINED (emit MARKED; usable if consumer tolerates it)
    ABSTAIN -> QUARANTINED + enqueue(signature)

OFF HOT PATH (async, batched, dedup'd):
  batch judge over DISTINCT signatures (one call per page-class kind)
    -> promote QUARANTINED to VERIFIED / REJECTED
    -> cache verdict per signature (free for all future matches)
    -> every verdict is a labeled example -> train the custom model later

ALWAYS (free oracle):
  deterministic content invariant (row.subreddit == requested) can VERIFY or
  REJECT a quarantined row at runtime with no LLM at all.
```

The LLM is never in the hot path, pays once per page-class kind, and bootstraps a
training set for a future custom classifier — at which point the batch judge cost drops
again. Quarantine guarantees no unverified data is ever mistaken for verified.

## Avenues (ranked)
1. **Capture DOM tag-paths at scrape time** → strengthens the ensemble's structural
   signal and unlocks domain-free classing + SimHash that actually adds lift. Highest leverage.
2. **Ship ensemble + quarantine** as the CAS-83 guard: 0 leaks, 81% LLM eliminated, marked
   data. The batch-judge path is async and dedup'd.
3. **Batch-judge worker** keyed on page-class signature, verdict cache, label log.
4. **Custom model** trained on the accumulated batch-judge + content-invariant labels —
   the endgame where the LLM is needed only for genuinely novel structures.

## Files
- `ensemble.py` — cascade + SimHash + batched-judge economics + signature dedup.
- `provenance.py` — the VERIFIED/QUARANTINED/REJECTED trust lattice + promote().
- `domain_free.py` — DOM-only class separability + cross-domain NN transfer.
- `results/{ensemble,domain_free}_output.txt` — the runs.
- Prior: `FINDINGS_DISTILL.md` (rules), `FINDINGS_LLM_JUDGE.md` (the teacher).
