# Field-level root + dedup smell (from the SERP discrimination finding)

Follow-on to `W5-discovery-discrimination.md`. Two user steers, both implemented:

## 1. Duplicate-selector smell (soft, never fail-fast)

A duplicate selector means the contract is ambiguous or the model conflated targets.
`yosoi/core/discovery/dedup.py`:
- `duplicate_fields(map)` — within a contract, two **fields** sharing one primary selector → warned by the orchestrator (`⚠ fields X, Y share selector S`). Soft `obs.warning`, never blocks.
- `maps_collide(a, b)` — across contracts, e.g. `AdResult` and `OrganicResult` resolving to the **identical** selector set → the SERP round prints a DEDUP SMELL flag.
- A field's `root` is part of its identity, so once roots discriminate two regions the fields are no longer "duplicates" — the smell and the fix compose.

## 2. Field-level root (the real fix for both discrimination AND over-complex selectors)

`root` used to be a `ClassVar` on the **contract** (one container, scoping every field in
multi-item extraction). Generalized to the **field/selector** level:

- `yosoi/models/selectors.py` — `FieldSelectors.root: SelectorEntry | None`. When set, the
  field's primary/fallback/tertiary resolve **relative to** the element matched by root.
- `yosoi/core/extraction/extractor.py:_scope_to_root` — scopes the parsel selector to the
  root region before resolving the field. Root set but no match → the field has no value in
  that region (no silent whole-document fallback — that would defeat discrimination).

Two payoffs, both proven by `tests/unit/core/extraction/test_field_root.py`:
- **Discrimination:** the same simple leaf (`a::attr(href)`, `h3`) rooted under `.uEierd`
  yields the sponsored row; rooted under `.MjjYud` yields the organic row. Region decides,
  not a brittle absolute path.
- **Simpler/sturdier selectors:** `root=.MjjYud` + leaf `a::attr(href)` instead of
  `div.MjjYud div.yuRUbf > a::attr(href)`. A Google reshuffle that breaks the parent path
  doesn't break the leaf, and vice versa.

## Status / next step (the architectural fork, deferred on purpose)

Implemented now: the model field + extraction + dedup + tests (full suite green, 2556).
**Not yet:** discovery **emitting** `(root, leaf)`. That needs (a) a prompt change —
"prefer a simple leaf scoped under a stable parent root; when the contract intent names a
region (e.g. a Sponsored ad), set root to it" — and (b) verifying the leaf **root-relative**
in `field_task`/`SelectorVerifier`, plus a model run to validate. The real SERP round still
shows discovery NOT discriminating (selectors collide) until that lands — which is exactly
what the dedup smell now flags. Wiring that is the recommended next commit.
