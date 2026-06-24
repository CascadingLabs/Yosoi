# Fingerprinting technology stack

Yosoi fingerprints pages so selector reuse is explainable instead of heuristic. The rule is:

> The fingerprint proposes; the trust policy decides.

A page fingerprint never silently serves data by itself. It can explain why two pages look like the same template, but `fingerprint`-sourced reuse stays lower trust and is quarantined by the read policy unless a higher-trust path verifies it.

## Demo story

For a Monday demo, describe the stack as a waterfall of evidence:

1. **L0/L1 static HTML** — parse the HTML once and extract a template skeleton.
2. **L2 rendered browser view** — when VoidCrawl renders the page, add accessibility-tree roles from the browser-computed AX snapshot.
3. **L2+ runtime/transport evidence** — add response header/cookie names and browser-captured XHR/fetch endpoint paths when the fetch tier carried them.
4. **Conjunctive comparison** — two pages match only when every carried layer clears its weighted threshold.
5. **Fail-closed trust** — blank/thin pages abstain; optional layers abstain when too sparse; reuse remains subject to trust policy.

`L3` is reserved for antibot/browser-identity health (profile, proxy/IP, cookies, locale, block attribution), not page-template fingerprinting.

This lets the demo answer, “why did Yosoi think these pages are the same kind of page?” with layer-by-layer evidence rather than a single opaque score.

## Layers

| Layer | Source | What is fingerprinted | Why it is explainable | Privacy rule |
| --- | --- | --- | --- | --- |
| Shape bucket | `PageObservation` tag histogram + body class kind tokens | Significant tag names and page-kind classes | Fast cache bucket for pages with the same broad template | No raw HTML retained |
| Skeleton | HTML tree | Depth-limited structural paths | Shows whether the DOM template is similar despite row/content drift | Text/content values excluded |
| Static semantics | HTML | Landmarks, roles, heading count bands, schema.org types | Captures page meaning: article/listing/search/profile signals | Heading text excluded; only bands/types |
| Identity attrs | HTML/rendered HTML | `data-*` attribute keys | Framework/component signature that is expensive to randomize | Attribute values excluded |
| Rendered AX spine | VoidCrawl browser AX snapshot | Distinct accessibility roles | Browser’s rendered perception of the page | Accessible names excluded |
| Network signature | Fetch response | Header names + `Set-Cookie` cookie names | CDN/framework/backend signature | Header/cookie values excluded |
| Endpoint skeleton | VoidCrawl CDP endpoint capture | Host + normalized path for XHR/fetch calls | Strong invariant for apps that fetch the same APIs per entity | Query, fragment, userinfo, secrets, and ID-like path segments excluded/collapsed |

Implementation entry point: `yosoi.generalization.fingerprint.PageFingerprint.of(...)`.

## How matching works

`PageFingerprint.similarity(other)` returns a nested `PageSimilarity`. Each carried layer is a small model:

```python
{
    'jaccard': 0.82,       # raw set overlap, kept for audit/debugging
    'weighted': 0.88,      # weighted Jaccard, used by same_shape thresholds
    'containment': 0.96,   # smaller-set inclusion, explains subset/superset cases
}
```

The page model contains:

- `score` / `weighted_score`: aggregate weighted score over carried layers.
- `containment_score`: aggregate containment over carried layers.
- `skeleton`: structural layer model.
- `semantic`: landmark/heading/schema layer model.
- `identity`: optional `data-*` key layer model, or `None` when not carried by both pages.
- `ax`: optional rendered accessibility-role layer model, or `None`.
- `network`: optional header/cookie-name layer model, or `None`.
- `endpoint`: optional endpoint-path layer model, or `None`.
- `same_shape`: final conjunctive verdict.

The final verdict is deliberately conservative:

- degenerate fingerprints never match;
- skeleton and semantic weighted scores must pass;
- optional layers only vote when both sides carry enough features;
- every voting optional layer is a veto if its weighted score misses its threshold.

Raw Jaccard remains visible, but weighted Jaccard is the decision score. Containment is explanatory; it helps show "same template plus extra module" without becoming a standalone authorization gate.

## Explainability output to show

For a compact demo, print the layer scores and the final verdict:

```python
from yosoi.generalization.fingerprint import PageFingerprint

seed = PageFingerprint.of(seed_html, ax_snapshot=seed_ax, headers=seed_headers, endpoints=seed_endpoints)
replay = PageFingerprint.of(replay_html, ax_snapshot=replay_ax, headers=replay_headers, endpoints=replay_endpoints)

sim = seed.similarity(replay)
print(sim.model_dump())
```

Example shape of the output:

```python
{
    'score': 0.84,
    'containment_score': 0.92,
    'skeleton': {'jaccard': 0.82, 'weighted': 0.87, 'containment': 0.95},
    'semantic': {'jaccard': 0.75, 'weighted': 0.81, 'containment': 0.88},
    'identity': None,
    'ax': {'jaccard': 0.67, 'weighted': 0.70, 'containment': 0.80},
    'network': {'jaccard': 0.58, 'weighted': 0.62, 'containment': 0.78},
    'endpoint': {'jaccard': 0.91, 'weighted': 0.91, 'containment': 1.0},
    'same_shape': True,
}
```

Narration:

- `None` means “not enough shared evidence to vote,” not success.
- `same_shape=True` means “eligible to propose reuse,” not “serve without verification.”
- `same_shape=False` should show which layer vetoed the match.

## Current safety boundaries

- No Playwright path exists in Yosoi. Browser evidence comes from VoidCrawl-backed fetchers.
- Fingerprints avoid content values, cookies values, endpoint queries, fragments, and userinfo.
- Thin pages and malformed optional data degrade to “not carried” or degenerate instead of raising or matching.
- Optional thresholds are provisional until more rendered/live batteries are collected.
- Cross-tier comparison is intentionally cautious: richer browser evidence should not be treated as mandatory unless both pages carry it.
- MinHash is a future performance/indexing optimization only: shortlist candidate references, then run exact nested similarity for the auditable decision.
- SimHash and learned classifiers belong to production health checks, not page-template reuse authority: SimHash is better suited to extracted/body content drift and near-duplicate checks; classifiers need labeled reuse outcomes.

## Code map

- `yosoi/generalization/fingerprint.py` — fingerprint extraction, layer comparison, thresholds, `PageSimilarity`.
- `yosoi/core/fetcher/voiddriver.py` — VoidCrawl browser fetcher; carries AX snapshots, response headers, endpoints.
- `yosoi/models/results.py` — fetch result fields that transport AX/header/endpoint evidence.
- `yosoi/policy/fingerprint.py` — opt-in off-path fingerprint signal lane policy.
- `yosoi/core/pipeline/signal.py` — background fingerprint gathering, not trust/action.
- `yosoi/storage/atoms.py` — source trust model; `fingerprint` source is lowest trust and default-quarantined.

## Monday demo checklist

- Show one static HTML pair: skeleton + semantics explain same-template matching.
- Show one rendered pair: AX roles appear only when the browser tier runs.
- Show one app/API pair: endpoint skeleton survives entity changes after ID normalization.
- Show one negative pair: a single vetoing layer makes `same_shape=False`.
- Close with the trust boundary: fingerprint explains and proposes; verification/policy decides serving.
