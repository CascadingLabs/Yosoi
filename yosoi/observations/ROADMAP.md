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
| `pruning/html.py` | Source HTML reduction | First vertical slice, ported from the proven spike. |
| `pruning/dom.py` | Rendered DOM reduction | Add after raw structured DOM capture exists. |
| `pruning/ax.py` | Raw accessibility-tree reduction | Preserve raw AX evidence before compaction. |
| `pruning/network.py` | Safe normalized network reduction | Add only after redaction and restricted-artifact policy are specified. |
| `index/compiler.py` | Combine pruned modality views into one flat index | Deterministic ordering and no provider-specific packing. |
| `index/addressing.py` | Validate snapshot-bound references | Stale or cross-snapshot references fail closed. |
| `index/inspect.py` | Bounded canonical-detail retrieval | Enforce byte/item limits and sensitivity permissions. |
| `index/render.py` | Tokenizer/provider-specific packing | Render an existing view/index without rerunning semantic pruning. |
| `index/diff.py` | Snapshot/index comparison | Add with multi-shot action episodes. |

## Delivery sequence

1. Static HTML artifact → `PrunedView` → flat index → bounded inspection.
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
