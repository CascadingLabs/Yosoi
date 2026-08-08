# Rendered-DOM artifact schema (`dom1`)

This beta schema is the Phase-1 boundary for CAS-263. It describes one already-captured
rendered DOM; it does not acquire a browser page or prune evidence.

See [`dom-pruning-todomvc-lifecycle.md`](../../docs/plans/dom-pruning-todomvc-lifecycle.md) for
the state-by-state lifecycle visualization.

## Contract

`DomSnapshot` is immutable, self-describing JSON with:

- a snapshot identity and `rendered_dom` kind;
- an ordered element tree with stable producer-assigned `node_id` values;
- attributes preserved without class/id stripping;
- producer-reported visibility and optional geometry;
- runtime control state (`value`, `checked`, `selected`, `expanded`, etc.);
- explicit shadow-root and portal edges;
- optional declared collection counts for virtualized regions;
- capability records stating unavailable facts and why.

`serialize_dom_snapshot()` emits compact UTF-8 JSON. `parse_dom_snapshot()` validates the
payload before a pruner or inspector consumes it.

## Deliberate limits

- The schema does not define browser acquisition, CDP calls, or Playwright integration.
- It does not infer visibility from markup or geometry.
- It does not claim that an observed child list is complete; `declared_count` is only a
  producer-reported fact. The DOM pruner will turn that distinction into `RegionCoverage`.
- Sensitive runtime values must be redacted before this payload becomes a canonical artifact.
- Cross-snapshot identity and diffs remain future work.

## How the beta works

The capture boundary is intentionally separate from pruning:

```text
browser producer
  -> DomSnapshot
  -> deterministic UTF-8 JSON
  -> ArtifactRef(kind=rendered_dom, media_type=application/json)
  -> DomPruner (Phase 2)
  -> PrunedView / ObservationIndex
  -> bounded inspect / expand
```

1. A producer constructs a `DomSnapshot` for one settled page state. The root contains the
   observed light-DOM tree. Shadow content is attached through `shadow_root`; portal ownership
   is represented by `portal_target_id` rather than pretending the portal is an ordinary child.
2. Every node has a producer-assigned `node_id`. Snapshot validation walks light and shadow trees,
   rejects duplicates, rejects dangling portal targets, and rejects duplicate attributes. This
   makes malformed artifacts fail before semantic reduction.
3. Visibility, geometry, and interactive state are facts supplied by the producer. The schema
   stores them but never derives one from another. For example, `OFFSCREEN` is not inferred from
   `in_viewport`, and `UNKNOWN` is valid when the producer lacks that capability.
4. A virtualized list can retain `declared_count=10000` on its container while only serializing
   the rows present in the snapshot. The future pruner compares observed members with that fact
   and emits incomplete `RegionCoverage`; the schema itself does not claim completeness.
5. `serialize_dom_snapshot` produces the canonical payload. The artifact store hashes those bytes,
   and later consumers call `parse_dom_snapshot` before reading them. The canonical bytes remain
   unchanged when a pruned view or index is rebuilt.

This is compatible with the QA Beachhead architecture: capture is immutable, pruning is
provider- and task-neutral, and the future QA consumer receives only bounded derived views. It
also keeps CAS-263's rendered DOM and AX work separate: AX will get its own artifact contract,
while both modalities can later share index and episode boundaries without sharing semantics.

## Current boundary and next step

Phase 2 now feeds deterministic fixture snapshots through the existing `SemanticPruner` base.
`DomPruner` currently proves:

- same-state sibling collapse with region coverage;
- runtime-state-aware separation of active and completed controls;
- retention of meaningful hidden content while omitting empty hidden wrappers;
- explicit shadow-root and portal entries;
- `declared_count` versus observed-member accounting for virtualized regions.

The browser/CDP producer is not wired into Yosoi operations, but the opt-in
`scripts/capture_dom_todomvc.py` now freezes a live VoidCrawl TodoMVC episode for offline dogfood
under `tests/boss_fights/dom/todomvc_live/`. DOM-aware bounded `inspect`/`expand` resolve the
same snapshot-local node and repeat addresses as the pruner. Action episodes and cross-snapshot
diffs remain next; live acquisition should stay opt-in until those fixtures are stable.
