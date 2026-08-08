# Indexed Observation Runtime Roadmap

The observation runtime captures no pages and invokes no models. Producers supply policy-safe artifacts; consumers such as QA and discovery query the resulting address space.

The adversarial corpus, no-auth SPA slate, and per-pruner gates are specified in [`boss_fights.md`](boss_fights.md).

## Module map

| Module | Responsibility | Planned implementation |
| --- | --- | --- |
| `models/artifact.py` | Exact artifact identity, modality, and sensitivity | Freeze schema in the static HTML slice; add migrations before changing serialized fields. |
| `models/snapshot.py` | Run/episode/snapshot identity and capture capabilities | Start with one snapshot; preserve parent IDs for later action episodes. |
| `models/view.py` | Structured semantic reduction and separately rendered output | Keep tokenizer budgets out of semantic pruning. |
| `models/index.py` | Flat index and stable snapshot-local references | Add schema-versioned serialization and golden fixtures. |
| `artifacts/protocol.py` | Immutable content store boundary | Keep reads exact and fail closed on digest mismatch. |
| `artifacts/memory.py` | Deterministic test store | First implementation and unit-test reference. |
| `artifacts/filesystem.py` | Content-addressed local persistence | Add atomic writes, restrictive permissions, retention, and sensitivity enforcement later. |
| `artifacts/manifest.py` | Deterministic snapshot manifest serialization | Add byte-identical golden tests. |
| `pruning/protocol.py` | Explicit pruner contract and policy input | No registry; callers pass a sequence or mapping. |
| `pruning/_shared.py` | Hashing, accounting, and validation mechanics only | Never place modality semantics here. |
| `html_tree.py` | Shared HTML shape/key primitives | **Implemented (CAS-262).** One definition of skeleton signature and content key, used by both the pruner and the inspector. |
| `pruning/_base.py` | Template method for every pruner | **Implemented (CAS-262).** Owns digest validation, policy hashing, addressing, capping, accounting. A pruner is one `reduce`. |
| `pruning/html.py` | Source HTML reduction | **Implemented (CAS-262).** Two pruners: `html.declarations` (flat, metadata content) and `html.body` (MDR-style repeat collapse). |
| `pruning/dom.py` | Rendered DOM reduction | Add after raw structured DOM capture exists. |
| `pruning/ax.py` | Raw accessibility-tree reduction | Preserve raw AX evidence before compaction. |
| `pruning/network.py` | Safe normalized network reduction | Add only after redaction and restricted-artifact policy are specified. |
| `index/compiler.py` | Combine pruned modality views into one flat index | **Implemented (CAS-262).** Fixed modality ordering; duplicate addresses fail closed. |
| `index/addressing.py` | Address grammar and reference validation | **Implemented (CAS-262).** Segmented region/member addresses that survive re-snapshotting; stale, foreign, or malformed references fail closed. |
| `index/inspect.py` | Bounded detail and region expansion | **Implemented (CAS-262) for `source_html` only.** `inspect` for one thing, `expand` to page a region's members. Other modalities raise. |
| `index/render.py` | Tokenizer/provider-specific packing | Render an existing view/index without rerunning semantic pruning. |
| `index/diff.py` | Snapshot/index comparison | Add with multi-shot action episodes. |

## Static HTML scope, stated

The document is partitioned by the HTML spec's *metadata content* category — the one
enumerated set, and enumerated because the spec closes it. Metadata content goes to
`html.declarations`, everything else to `html.body`; nothing is claimed by both or neither.

`html.declarations` is flat. Each element is labelled by its own first attribute
(`meta[name=robots]`), so an unexpected declaration appears in the index rather than being
filtered by an allowlist. It is document-wide, not `<head>`-only: books.toscrape loads jQuery
over plain http from the end of `<body>`.

`html.body` is structural. Adjacent siblings sharing a skeleton signature collapse to one
region plus one exemplar (MDR, Liu et al. 2003), so 10,000 rows cost two entries and stay
individually reachable through `expand`. That is measured, not asserted: the `html/repeat_scale`
boss fight generates 10,000 rows (1.7 MB), gets the same index the 1,000-row document gets,
sweeps all 10,000 members back through `expand` with durable keys, and holds cost linear in
row count. Classes and ids are never stripped — that was the
worst-measured representation in NEXT-EVAL (arXiv:2505.17125) and it is what selectors are
made of.

Not handled: **non-contiguous** records, split by injected ads or dividers. That is DEPTA's
tag-path clustering and is recorded as an asserted limit, not left to be discovered.

Design rationale, including why one-shot extraction F1 does not transfer to a multi-shot
loop, is in [`docs/plans/observation-pruning.md`](../../docs/plans/observation-pruning.md).

## Delivery sequence

1. ~~Static HTML artifact → `PrunedView` → flat index → bounded inspection, addressing, and region expansion.~~ Done (CAS-262).
2. Golden parity and MDS regression fixtures from the QA beachhead.
3. DOM and AX artifact producers/pruners over the same contracts.
4. QA runtime dogfooding, still opt-in and read-only.
5. Indexed discovery shadow mode with independent verification.
6. Safe network evidence, action episodes, and diffs.

## Gates

- Same source, pruner version, and policy hash produce byte-identical output.
- Every emitted reference resolves against its exact snapshot and artifact digest.
- Canonical artifacts are never modified by pruning.
- Missing capabilities remain explicit; they never become empty evidence.
- Credentials never enter ordinary model-visible artifacts.
