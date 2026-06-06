# P5 — Waterfall-Aware Page Fingerprint (L0–L3 multi-signal identity)

> Separate initiative from the field-atom **P4** (scheme bump). This is the "next level"
> of `page_shape_fp`: identity built from the whole fetch waterfall, not static HTML alone.

## Context — why this is unblocked work, proven on real data

`page_shape_fp` today is **static-HTML only** (significant-tag histogram above a 0.5% floor +
body-class kind tokens; `yosoi/generalization/fingerprint.py:194`) and is an **exact 16-hex
SHA** used as the *first component of the field-atom cache key* (`storage/atoms.py:78`,
read at `core/atom_read.py:65` — exact `==` only).

Measured failure (live, 2026-06-05): real Yahoo Finance quote pages do **not** bucket.

```
s1:64932f32fe97b0d3   finance.yahoo.com/quote/AAPL     (1.28 MB)
s1:356af6ab0dc39784   finance.yahoo.com/quote/MSFT     (1.38 MB)
s1:7213a9fc1c391279   uk.finance.yahoo.com/quote/MSFT  (0.81 MB)
s1:e52167219080b131   finance.yahoo.com/markets/       (different template)
```

Ad slots / recommended-ticker rails / news modules / locale chrome change the tag mass enough
to flip tags across the floor, and SHA's avalanche destroys the residual similarity. Clean
template sites (quotes.toscrape.com — every page `s1:ca66fc32002c7f3d`) bucket fine; production
pages don't. The static fingerprint measures *document mass*; mass is exactly what
personalization varies. (Note: Yahoo quote pages are **not** paywalled — they fetch on the
simple HTTP tier, SSR HTML, 200, `regularMarketPrice` present. VoidCrawl headful + the waterfall
fetcher are available for tiers that must escalate.)

## The five lenses (each "spoke a different language")

| Lens | Core contribution |
|---|---|
| **Network / CDP** | The **data-plane endpoint set** is the strongest cross-ticker invariant — a Yahoo quote calls the *same* `query1.finance.yahoo.com/v*/finance/...` endpoints for every ticker, and `uk.` hits the same data hosts. Plus response-header-name set, `Set-Cookie` name set, CDN/antibot vendor. |
| **LSH / IR** | Replace the exact hash with **weighted SimHash + banding**: cosine over L2-normalized tag vectors is *volume-invariant* (the actual AAPL/MSFT fix). Two-stage: SimHash = recall (candidate generation, a perf knob); the recommender = precision (the only safety gate). Decouple the fuzzy hash from the dangerous decision. |
| **Accessibility / semantic** | The **AX landmark spine + heading-outline shape + schema.org/JSON-LD `@type` set** is content-invariant by contract (breaking it breaks screen readers + SEO). JSON-LD is the cross-tier bridge (identical static at L0 and rendered at L2). |
| **Compiler / AST** | **Anti-unification**: per parent, run-length-collapse repeated siblings to a Kleene-`{+}`, then hash the depth-D **path-shingle set** of the collapsed skeleton. 12 vs 30 recommended rows → both `{+}` → AAPL and MSFT converge; a news feed stays distinct. `region_role` = the identity-bearing nonterminals; `{+}` gives the discrimination gate real arity. |
| **Adversarial / anti-bot** | **Trust-rank by adversary-cost**: identity attrs (`id/data-testid/aria-label/href`-template), AX roles, network endpoints, CDN vendor are *expensive* to randomize; tag/class are *cheap*. Identity must be **conjunctive on expensive tiers**; a fingerprint flip + `challenged` verdict = a **cloaking event → quarantine**, not a redesign. |

## Convergent design (where all five agreed)

1. **Exact-hash equality is the root bug.** Move to **candidate-generate → verify**, never a single avalanche hash as the authority.
2. **The static tag histogram is the weakest signal** — demote to corroboration; it can *refine within* an agreeing bucket but can never *create* a merge.
3. **Layered L0–L3, each fingerprint records which layers it carries.** Compare only on the *highest common* layer; **never cross-layer false-merge**.
4. **Fail-closed is the invariant.** A false-**merge** = silent, validated-looking data corruption (catastrophic). A false-**split** = one cheap re-discovery. So: fuzzy matching only *generates candidates*; a conjunctive agreement on high-trust signals *authorizes* reuse; anything uncertain ABSTAINS → discovery.
5. **Three signals are already captured and thrown away — the cheap wins:**
   - `ElementObservation` / identity attrs (`fingerprint.py:288`) — **orphaned, zero callers**.
   - `ax_snapshot` (`models/results.py:68`) — captured, used only as an LLM discovery hint.
   - antibot verdict + headers (CAS-139, `voiddriver.py`) — **dropped before reaching `FetchResult`**.

## The unified fingerprint

Identity is **not one hash**. It is three things computed from one capture:

- **Bucket key** — a stable string for the atom dict, derived from the most stable *available* layers, scheme- and layer-stamped (`f2l<layers>:<hex>`), so a scheme/layer change is an observable miss, never a silent collision (mirrors `SHAPE_SCHEME_VERSION`).
- **Candidate index** — LSH bands / inverted index over the SimHash signature for near-shape lookup.
- **Verifier** — conjunctive agreement on high-trust layers (identity-attr signature + skeleton containment + anchor-landmark set), via the fail-closed recommender. Authorizes any reuse; ABSTAINs otherwise.

### Layer table

| Layer | Signals | Source | Tier available | Adversary-cost |
|---|---|---|---|---|
| **L0 — coarse** | route-template (URL), CDN/antibot **vendor** (header-tier), tag-cosine class | headers + HTML | all (even simple) | vendor high / tags low |
| **L1 — template skeleton (static AST)** | anti-unified path-shingle set (`{+}` collapsed), **identity-attr** presence signature, landmark elements + heading outline + **JSON-LD `@type` set** | raw HTML (parsel) | all | high |
| **L2 — rendered / semantic** | computed **AX landmark spine** + role multiset, rendered-DOM skeleton | `ax_snapshot` / browser tier | headless/headful | high |
| **L3 — behavioral** | **XHR/fetch endpoint-path skeleton**, response-header-name set, `Set-Cookie` name set, cookie/session class | CDP network capture | headful (CDP) | very high |

**Matching:** bucket on L0+L1 → LSH candidate search → **verify on the highest common layer** (conjunctive: identity-attr agreement AND skeleton containment ≥ τ AND anchor-landmark set match) → exactly one surviving bucket reuses; 0 or >1 → ABSTAIN → discover. Quarantine (no write, no read) when `challenged` or the fingerprint flips under a bot signal.

## Staging — falsifiable experiment first

- **WF0 — Plumbing (low-risk, unblocks all).** Surface already-captured signals onto
  `FetchResult` → `PageObservation`: response **headers**, **antibot verdict** (CAS-139),
  `ax_snapshot` (already on `FetchResult` — thread into `PageObservation`), and wire the
  orphaned `ElementObservation`. Advisory/log-only — zero behavior change (mirrors P1).
  Surface any missing CDP capability (e.g. network request log) as a **VoidCrawl wrapper gap**,
  not a Playwright side-path (per AGENTS.md).
- **WF1 — Template skeleton (L1), advisory — THE EXPERIMENT.** Implement the AST anti-unification
  path-shingle fingerprint (the single highest-leverage fix). Compute alongside `page_shape_fp`,
  log on the **real AAPL / MSFT / uk. / markets corpus**. Gate: *does the skeleton fingerprint
  actually collapse AAPL+MSFT+uk to one bucket while keeping markets distinct?* If yes, the
  direction is validated cheaply before any LSH/network build. If no, learn and re-scope.
- **WF2 — Candidate-then-verify reads.** Re-pull cas-85 `recommend.py` (the fail-closed
  ALLOW/REFUSE/ABSTAIN verifier — **not in this tree today**; only `fingerprint.py`/`capture.py`
  were kept in P1). Add SimHash banding + an inverted index; change `resolve_via_atoms` from exact
  `==` to candidate→verify→abstain. Behind a flag (extends P3's `YOSOI_ATOM_READS`).
- **WF3 — Semantic + behavioral layers (L2/L3).** AX landmark spine; network endpoint skeleton
  (needs the WF0 capture); CDN vendor coarse bucket. Cross-tier rule: compare on the lower tier's
  layer set; never match a rich seed to a thin replay on absence.
- **WF4 — Adversarial hardening.** Conjunctive trust weighting; quarantine on
  `challenged` / fingerprint-flip; treat cloaking as an identity event.

## Fail-closed invariants (non-negotiable, all lenses)

- Fuzzy similarity **generates candidates only**; the conjunctive verifier is the **sole** merge authority.
- Identity requires agreement on **adversary-expensive** layers; cheap layers (tags/classes) can refine but never merge.
- **Never cross-layer merge**; thinner-than-seed replay → ABSTAIN.
- Degenerate / thin AX / `challenged` → sentinel bucket → no write, no serve → discovery.
- Asymmetry: false-merge is catastrophic, false-split is cheap → tune deep on the precision side; any uncertainty discovers.

## Dependencies / open items

- **`recommend.py` is absent** in this worktree (trimmed in P1 to fingerprint+capture). WF2 must
  re-pull it from `feat/cas-85-generalization` — the verifier the LSH/AST designs depend on.
- **`FetchResult` plumbing** (WF0) is the prerequisite for L2/L3 — headers/antibot/network are
  computed but dropped today.
- **VoidCrawl network capture**: confirm `PooledTab` exposes a request log; if not, surface as a
  wrapper gap.
- Atom key becomes a *bucket representative* (assigned once per similarity class at internalize
  time) + an inverted index for lookup — the store stays content-addressed/stable.

## Critical files
- `yosoi/generalization/fingerprint.py` — skeleton extraction, SimHash, layered composite, scheme/layer versioning
- `yosoi/generalization/capture.py` — thread new signals into `PageObservation`
- `yosoi/models/results.py` + `yosoi/core/fetcher/voiddriver.py` — surface headers/antibot/network/ax onto `FetchResult`
- `yosoi/core/atom_read.py` — exact `==` → candidate→verify→abstain; LSH inverted index
- `yosoi/storage/atoms.py` — bucket-representative key; region_role ↔ skeleton nonterminal
- (re-pull) `yosoi/generalization/recommend.py` — the fail-closed verifier (WF2)
