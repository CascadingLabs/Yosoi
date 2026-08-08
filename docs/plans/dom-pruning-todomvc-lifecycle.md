# DOM pruning lifecycle — TodoMVC control

This is the rendered-DOM companion to the static-HTML pruning writeup. It explains the
lifecycle that CAS-263 should prove first with a deterministic TodoMVC capture. The opt-in
VoidCrawl capture script now produces a frozen live episode, while the beta `DomPruner` consumes
synthetic and frozen structured snapshots; browser acquisition is still not wired into Yosoi
operations.

## One-sentence model

Capture one settled TodoMVC page state exactly, build a small state-aware map, inspect only the
needed node or repeat member, then capture the next state as a child snapshot.

```text
browser state
    │
    ▼
DomSnapshot (immutable structured JSON)
    │  node ids, attributes, visibility, geometry, runtime state
    ▼
content-addressed rendered-DOM artifact
    │
    ▼
DomPruner
    │  controls + stateful repeat regions + honest coverage
    ▼
flat ObservationIndex
    │
    ├── inspect(exact ref) ──▶ canonical node/subtree detail
    ├── expand(region) ──────▶ bounded todo-member page
    └── action / settle ─────▶ next snapshot with parent_snapshot_id
```

The raw DOM is never replaced by the map. The map is a deterministic routing layer over the
exact artifact, matching the QA Beachhead rule that the agent starts bounded and zooms only when
evidence requires it.

## TodoMVC control shape

The control is intentionally small and stateful rather than visually complex:

```text
html
└── body
    └── section#todoapp
        ├── header.header
        │   ├── h1              "todos"
        │   └── input#new-todo  runtime.value
        ├── section#main
        │   ├── input#toggle-all       runtime.checked
        │   └── ul#todo-list
        │       ├── li.todo             runtime/state: active
        │       │   ├── input.toggle   runtime.checked=false
        │       │   ├── label           text
        │       │   └── button.destroy
        │       ├── li.todo.completed   runtime.checked=true
        │       └── li.todo             runtime/state: active
        └── footer#footer
            ├── span#todo-count
            ├── ul.filters
            └── button#clear-completed
```

The exact framework markup may differ. The fixture's ground truth should name semantic facts
and independent selectors, not prescribe emitted `RegionRef` locators.

## Lifecycle walkthrough

### S0 — initial settled state

The producer waits for the page to settle, then captures the current DOM. Assume three todos:

```text
S0  route=all
    todos observed: 3
    active: 2
    completed: 1
    new-todo input: empty
    clear-completed: visible
```

The producer creates one `DomSnapshot`:

```text
DomSnapshot(snapshot_id=S0)
├── capabilities
│   ├── visibility: available
│   ├── geometry: available
│   ├── runtime_state: available
│   ├── shadow_dom: available / none observed
│   ├── portals: available / none observed
│   └── declared_counts: available or explicitly unavailable
└── root: html
    └── ...todoapp...
```

Each node keeps its captured attributes, producer node ID, text, visibility, optional box, and
runtime state. A checked checkbox is not reconstructed from a CSS class; it is retained as
`runtime.checked=true` when the producer can observe it.

### S0 — canonical artifact and semantic reduction

```text
S0 DomSnapshot
   │ serialize_dom_snapshot()
   ▼
application/json bytes ──SHA-256──▶ ArtifactRef(RENDERED_DOM, S0)
   │
   └── parse + DomPruner
          │
          ├── document / todoapp controls
          ├── todo-list repeat region ×3
          ├── one todo exemplar with runtime state
          └── footer/filter controls
```

A likely overview is compact and state-aware:

```text
html > body > section#todoapp          application shell; 3 todos; route=all
ul#todo-list                           ×3 todo members; observed=3; complete=true
li.todo                                exemplar; active; checked=false
li.todo.completed                      completed member/state is discoverable
footer#footer                          2 active; 1 completed; filters available
```

The repeated list costs a region plus an exemplar, not one overview entry per todo. `expand`
can page all three members. If the fixture has unique `data-id` values, those become candidate
member keys; otherwise the address explicitly reports positional instability.

### Zoom — bounded evidence retrieval

The QA agent begins with the flat overview and follows one address:

```text
inspect(todo-list region)
    └── exact list/container detail

expand(todo-list region, offset=0, limit=2)
    ├── todo A: active, label="Buy milk"
    └── todo B: completed, label="Read design"
```

`inspect` and `expand` resolve against the exact S0 artifact. They do not read summaries as if
they were canonical data, and they do not mutate the source snapshot.

### Action 1 — complete an active todo

The agent or test clicks one checkbox. The action layer is outside the pruner; after the action
and DOM settle, the producer captures a new state:

```text
S0: todo A active, checked=false
        │ click checkbox
        │ settle
        ▼
S1: todo A completed, checked=true
```

The new snapshot keeps episode lineage:

```text
S1.parent_snapshot_id = S0.snapshot_id
S1.episode_id        = S0.episode_id
```

The same logical todo may receive a new snapshot-local node ID. Cross-snapshot matching is not
silently assumed; stable `data-id`/`id` keys can support it later when `index/diff.py` exists.

### S1 — state-aware re-index

The second index should make the state transition visible without treating the entire list as
new content:

```text
S1 route=all
    todo-list region ×3
    active: 1
    completed: 2

    exemplar/state entries:
    ├── active todo, checked=false
    └── completed todo, checked=true
```

Two same-shaped `<li>` nodes must not be merged if the captured runtime state is materially
different for the task. The DOM pruner's repeat signature therefore needs to include the state
fields required by the modality policy, while still ignoring ordinary member text for repetition
recognition.

### Action 2 — filter to completed

```text
S1 route=all
        │ click "Completed"
        │ settle
        ▼
S2 route=completed
```

S2 demonstrates why DOM pruning is not source-HTML pruning:

```text
S2
├── filter control: selected=completed
├── completed todos: visible
├── active todos: present but hidden/display-none, or absent
└── footer count/filter state: updated
```

Hidden nodes are not silently discarded. If they remain in the captured DOM, their visibility
state is retained and the index can summarize the distinction. If the application removes them,
the snapshot records only what was observed and the capability/episode context explains that the
current view is filtered.

### Action 3 — edit and delete

```text
S2  completed filter
 │ double-click label
 │ type replacement
 │ blur/Enter
 ▼
S3  edited label + runtime input state settled
 │ click destroy
 │ settle
 ▼
S4  member removed; region coverage and counts recomputed
```

Editing is a useful runtime-state check: the temporary edit input, its `value`, focus state, and
visibility belong to S3 even though those facts may not exist in the source HTML. Deletion is a
membership check: S4 must not preserve a stale member reference as if it still resolved.

## State and coverage matrix

| TodoMVC fact | DOM artifact field | Index/pruner meaning |
|---|---|---|
| Active todo | class/attributes + runtime state | active member summary |
| Completed todo | `checked=true`, state/class | distinct stateful exemplar/member |
| Filtered-out todo | `visibility=hidden` or `display_none` | retained as hidden evidence when observed |
| Edit field value | `runtime.value` | inspectable exact transient state |
| Focused edit field | `runtime.focused=true` | action-state evidence |
| Todo count | text plus declared/derived count | consistency check against members |
| Virtualized list | `declared_count` > observed members | `RegionCoverage.complete=false` |
| No declared count | capability or policy says unavailable | never infer completeness from silence |

TodoMVC is a control, not a virtualization workload. A complete three-member region is valid
only when the capture capability and producer contract support that claim. The later 10,000-row
virtualized fixture must exercise the incomplete branch explicitly.

## QA Beachhead lifecycle boundary

```text
capture window
  ├── acquire settled browser state
  ├── capture rendered DOM artifact
  ├── record capabilities and sensitivity
  └── close the window

pure observation kernel
  ├── validate canonical bytes
  ├── prune deterministically
  ├── compile flat index
  └── resolve bounded inspect/expand

QA consumer (later)
  ├── show overview to provider
  ├── request exact evidence
  ├── perform an opt-in read-only check/action
  ├── capture child snapshot
  └── compare/report with deterministic references
```

The browser producer and QA runtime coordinate the capture window, but neither is allowed to
change the semantics of the artifact or pruner. This preserves the Linear QA Beachhead contract:
canonical evidence is immutable, modality views are deterministic, missing capabilities are
explicit, and a model never receives unbounded raw evidence by default.

## TodoMVC acceptance gates

Before moving beyond the control:

1. The same TodoMVC capture produces byte-identical `DomSnapshot` JSON and pruned output.
2. Every emitted reference resolves against the exact S0/S1/S2 artifact it names.
3. A checked/completed state remains distinguishable from an active state.
4. Filtered nodes remain explicitly hidden when they still exist in the DOM.
5. Edit input value and focus are reachable through bounded inspection.
6. Deletion produces a new snapshot and no stale member is presented as current evidence.
7. Capability absence and incomplete coverage are explicit, never represented as empty evidence.
8. The control remains offline, deterministic, provider-free, and independent of live TodoMVC drift.

After these pass, the same lifecycle can be reused for portals, shadow DOM, and virtualization
boss fights without changing the snapshot/index boundary.
