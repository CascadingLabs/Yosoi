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
| `anchoring.py` | The identity recipe, shared by every modality | **Implemented.** Single and first-two-attribute composite tiers, uniqueness census, and reserved-character rules live here; HTML, DOM, AX, and network all call it. |
| `html_tree.py` | Shared HTML shape/key primitives | **Implemented (CAS-262).** One definition of skeleton signature, content key, and durable anchor, used by both the pruner and the inspector. |
| `pruning/_base.py` | Template method for every pruner | **Implemented (CAS-262).** Owns digest validation, policy hashing, addressing, capping, accounting. A pruner is one `reduce`. |
| `pruning/html.py` | Source HTML reduction | **Implemented (CAS-262).** Two pruners: `html.declarations` (flat, metadata content) and `html.body` (MDR-style repeat collapse). |
| `pruning/dom.py` | Rendered DOM reduction | **Implemented.** Shape-based collapse, partitioned declarations, folded wrapper chains, and anchored addresses that earn `ref_id` through the shared recipe. |
| `pruning/ax.py` | Raw accessibility-tree reduction | **Implemented (CAS-263).** Iterative shape collapse, ignored-node band, exact resolution, and AX capability caveats; authenticated model-safe use still requires CAS-269 sanitization. |
| `pruning/network.py` | Safe normalized network reduction | **Implemented (CAS-266).** `net2` canonical URLs, value-classed parameters, complete shape digests, grouped endpoints, and rarity-ranked deviations. |
| `index/compiler.py` | Combine pruned modality views into one flat index | **Implemented (CAS-262).** Fixed modality ordering; duplicate addresses fail closed. |
| `index/addressing.py` | Address grammar, anchoring, and snapshot-independent identity | **Implemented (CAS-262).** Segmented region/member addresses anchored to durable ancestors; `ref_id` for the ones that earned it; stale, foreign, or malformed references fail closed. |
| `index/inspect.py` | Bounded detail, region expansion, branch rebinding | **Implemented for source HTML, rendered DOM, AX, and network.** `inspect` reads one thing, `expand` pages a region, and `rebind` carries an exemplar route onto another branch. |
| `index/render.py` | Tokenizer/provider-specific packing | **Implemented (CAS-262).** Budgeted overview from an existing index; headings before regions; omission always stated. Estimator-based token counting until a provider tokenizer is wired. |
| `index/diff.py` | Snapshot/index comparison | **Implemented.** Matches on `ref_id`, ignores ordinals, counts unmatchable entries rather than reporting them as churn, refuses fuzzy pairing, and pages like every other bounded surface. |
| `index/paging.py` | Explicit windows over a large candidate space | **Implemented.** Global ordinals, exact tiling via `next_offset = offset + returned`, fuzzy boundaries that keep a region with its exemplar. Replaced blind prefix truncation. |

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

## Location and identity are different things

A `RegionRef` locates bytes inside one exact capture. Two of its four fields are the snapshot
id and the artifact digest, so it can never compare equal across captures — by construction,
not by accident. Comparing two snapshots therefore needs a second value, and `IndexEntry.ref_id`
is it: a digest over what the *page* provides (anchor key, shape, member key, local path) and
nothing the *capture* provides.

An address earns an identity only when all three hold:

* **anchored** — the first segment starts from a document-unique attribute key or a
  once-occurring tag, not from `/html/body/…`. Only this survives an edit *above* the node.
  `html`, `head`, and `body` are excluded from the tag tier: unique in every document, so
  anchoring there is a root path with extra steps.
* **stable** — no segment fell back to `&ordinal=`.
* **positional-free** — no step anywhere selects a sibling by position (`./div[3]/p`). An
  address can be anchored and keyed and still rot on an insert inside the anchor's subtree.

Otherwise `ref_id` is `None`. Refusal, not a weaker id: the reference still resolves exactly
within its own snapshot, it simply may not claim to name the same thing in the next one.
Anchor tiers, most to least intentional: `id` → `data-*` → `class` → the author's first
attribute → a once-occurring tag. Nothing is enumerated, for the same reason declarations are
not — an allowlist can only anchor what someone thought of in advance.

Measured identity coverage, `tests/boss_fights/html/reference_stability`:

| Workload | With identity | Refused |
| --- | --- | --- |
| books.toscrape (frozen, real) | 59/79 (74%) | 19 positional tails, 1 unkeyed member |
| repeat_scale (10,000 rows) | 17/17 (100%) | — |
| reference_stability (generated) | 19/21 (90%) | 2 positional tails |

Cross-*document* identity — the same template served at two URLs — is deliberately not this
tier's job. That is the fingerprint's, and treating a shared skeleton as shared identity is the
confusion the fingerprint work already measured.

Design rationale, including why one-shot extraction F1 does not transfer to a multi-shot
loop, is in [`docs/plans/observation-pruning.md`](../../docs/plans/observation-pruning.md).

## Delivery sequence

1. ~~Static HTML artifact → `PrunedView` → flat index → bounded inspection, addressing, and region expansion.~~ Done (CAS-262).
2. ~~Anchored addresses and snapshot-independent `ref_id`, gated by a mutation corpus.~~ Done (CAS-262).
3. ~~Token-budget rendering, gated by the Wikipedia negative control.~~ Done (CAS-262).
4. `index/diff.py` over `ref_id`, now that identity exists to diff on.
5. Golden parity and MDS regression fixtures from the QA beachhead.
6. DOM and AX artifact producers/pruners over the same contracts.
7. QA runtime dogfooding, still opt-in and read-only.
8. Indexed discovery shadow mode with independent verification.
9. Safe network evidence and action episodes.

## Gates

- Same source, pruner version, and policy hash produce byte-identical output.
- Every emitted reference resolves against its exact snapshot and artifact digest.
- Two captures of an unchanged page mint identical `ref_id`s; an address that has not earned
  one gets `None` rather than a weaker id.
- Canonical artifacts are never modified by pruning.
- Missing capabilities remain explicit; they never become empty evidence.
- Credentials never enter ordinary model-visible artifacts.

## The indexing ceiling

Pruning does not remove the ceiling, it moves it. Measured on live captures: the HTML Living
Standard reduces to 271,134 addressable candidates, the ECMAScript spec to 166,355, one
Wikipedia list to 22,976. Those reductions are correct — that content really is that large and
mostly unique — and none of them fit in a context window or in one useful overview.

`index/paging.py` makes the ceiling explicit instead of silent: a page states the true total,
ordinals are global, and `next_offset` tiles the space exactly. Two things it deliberately does
not solve, recorded so they are not rediscovered:

* **A page is not a map.** Progressive collapse (`pruning/granularity.py`, opt-in via
  `PruningPolicy.collapse_to_fit`) answers this by describing the whole document at coarser
  depth — but only where candidate mass spreads across depth. Measured: `List of Unicode
  characters` collapses usefully to depth 10 of 24 (930 entries, whole document, 419 of them
  inspectable to descend), while the HTML Living Standard is **wide** — depth 0 holds 3
  candidates and depth 1 holds 10,016, so no cut exists between them and collapse can only
  offer 3 entries. Depth is the wrong axis for a wide document; paging is. The reported
  `Granularity` makes which case you are in visible instead of implicit. Collapsing by
  *breadth* would mean a second routing level, which the compiler's own evidence
  (arXiv:2607.17598) measured as hurting retrieval — so it is not the obvious next step.
* ~~**Paging re-reduces.**~~ **Fixed.** `reduce_once()` returns the reusable candidate space and
  `view()` builds a page from it, so a sweep costs one walk. The HTML spec went from ~49 minutes
  (272 walks) to **10.7s walk + 5.6s for all 272 pages**, tiling still exact at 271,134/271,134.
  `prune()` remains the one-shot convenience. Deliberately an explicit value, not an internal
  cache: caching a quarter-million candidates for a caller that wanted one page is the kind of
  hidden global state this package avoids.

`DEFAULT_PAGE_LIMIT = 1_000` is a working ceiling, not a measured one. A principled limit would
come from a **complexity measure over the reduction** — how branched and how repetitive the
document is, in the spirit of a cyclomatic/McCabe score — so that 1,000 near-identical table
rows and 1,000 unique specification paragraphs are not treated as the same load on a reader.
That measure does not exist yet and is the natural successor to the flat count.

## Performance backlog (measured, deliberately deferred)

Not correctness issues and not on the critical path — recorded with numbers so they are a
decision rather than a discovery. All measured on the frozen HTML Living Standard capture
(15.6 MB source, 109 MB DOM JSON, 333,492 nodes, 271,134 candidates).

| Cost | Measured | Cause | Fix when it matters |
| --- | --- | --- | --- |
| Sibling scan when minting a step | fixed: 180.3s → 10.2s | `dom_step` scanned a node's siblings to test uniqueness, quadratic in the width of a level — the HTML spec holds 10,016 nodes at one level | Fixed by `SiblingIndex`: per-parent counts built once. Kept in this table because width, not depth, is what makes a real document expensive |
| Duplicate parse per reduction | ~2.9s of a 10.7s walk | `DomPruner.reduce_once` parses to bind the payload to its artifact, then `reduce` parses the same bytes again to walk them | Parse once in `reduce_once` and hand the snapshot to the walk; puts the walk nearer 8s |
| Peak memory | 3.9 GB, ~36x the artifact | Whole artifact validated into pydantic models, whole candidate tuple materialised | Streaming walk, or a candidate iterator instead of a tuple |
| Artifact size | 441 B/node vs 93 B/node for source HTML | ~20% geometry at capture precision, ~18% always-serialized nulls (`exclude_none=False`) | Round geometry and omit nulls — but this re-digests every artifact and invalidates every frozen fixture, so it is a schema change, not a tweak |

Capture is separate from and larger than indexing on a document this size: 5.9s navigate +
11.1s in-browser serialize + 7.2s validate = 26.8s, against 16.3s to index exhaustively.

## Rendered-DOM identity

DOM addresses were `/dom/node/<producer node id>` — never anchored, so `ref_id` refused every one
of them and identity coverage measured **0 across ten live pages**. That made `index/diff.py`, any
S0-action-S1 comparison, and fingerprint-assisted reuse unbuildable for the modality they matter
most for.

DOM now anchors through `anchoring.py`, the same recipe source HTML uses, with a `_Minter` that
mirrors the HTML one: nearest durable ancestor, then durable relative steps, falling back to the
producer node id when the snapshot offers nothing — which `ref_id` then declines an identity for,
as refusal rather than a weaker id.

Measured identity coverage on the live qscrape.dev captures:

| Page | With `ref_id` |
| --- | --- |
| l2_eshop | 312/320 (98%) |
| l3_news | 89/96 (93%) |
| l1_eshop | 64/76 (84%) |
| l1_taxes | 33/41 (80%) |
| l2_news | 268/339 (79%) |
| l2_taxes | 191/250 (76%) |
| l2_scoretap | 156/249 (63%) |
| l1_news | 132/230 (57%) |
| l1_scoretap | 68/185 (37%) |
| **total** | **1,355/1,834 (74%)** |

74% is the same figure books.toscrape gives on the source-HTML side, which is the point: one
recipe, comparable durability. Anchor tiers used across four pages: attribute 388, class 206,
data 123, tag 17, id 9, refused 88.

Gated by two properties, not by the coverage number: two captures of an unchanged page mint
identical `ref_id`s while their `RegionRef`s necessarily differ, and a node the page offers no
durable key for is refused an identity while still resolving exactly inside its own snapshot.

Only two DOM-specific pieces exist, and neither is part of the identity recipe: ancestry comes
from a parent map because a `DomNode` tree has no parent pointers, and relative steps are limited
to `./tag` and `./tag[@name="value"]`, resolved by unique match among siblings. A step that would
need a sibling index is refused — `./div[3]` is a positional guess wearing a durable address's
clothes.

### A shared-grammar bug this surfaced

An anchor value containing `"`, `#`, or `|` cannot round-trip through a locator. `href="#/active"`
— an ordinary TodoMVC filter link — produced `//*[@href="#/active"]#anchor=…`, which parses as a
path of `//*[@href="` and a qualifier of `/active"]#anchor`. Only `"` had been excluded.
`anchoring.LOCATOR_RESERVED` now excludes all three. Found through a live DOM capture, but the
grammar is shared: any HTML page with a fragment link was one anchor tier away from the same
failure. Producers of unexpressible tag names (a shadow root is `#shadow-root`) are refused the
tag tier for the same reason.

## Index diffing

Keyed on `ref_id`, which is what the identity tier was for. Three rules, each because its opposite
produces a convincing lie:

* **Position is not identity.** Ordinals are excluded from comparison. `section_above` shifts every
  ordinal below the insertion and removes no identity; a position-keyed diff calls that whole page
  churn.
* **An entry with no identity is not "added".** A quarter of a real page earns no `ref_id`. Treating
  those as added-and-removed would report 20 removals and 20 additions for an unchanged
  books.toscrape. They are counted as `without_identity_before/after` and named in `describe()`.
* **No fuzzy pairing.** A vanished identity beside a new one is two facts. Pairing them would turn
  a real removal plus a real addition into a fabricated modification — the "probably the same
  thing" inference the identity tier exists to refuse.

Measured against the existing `reference_stability` corpus, and it agrees with the identity table
that corpus already produced — the point being that a diff which quietly disagrees with the
identities it is built on is the more dangerous of the two:

| Mutation | changed | added | removed | unchanged |
| --- | --- | --- | --- | --- |
| re-captured unchanged | 0 | 0 | 0 | 19 |
| `section_above` | 2 | 2 | 0 | 17 |
| `row_inserted` | 4 | 0 | 0 | 15 |
| `rows_reordered` | 1 | 3 | 3 | 15 |
| `column_added` | 1 | 4 | 4 | 14 |
| `prose_reworded` | 2 | 1 | 1 | 16 |
| `class_restyled` | 0 | 4 | 4 | 15 |

`row_inserted` is the interesting row: a new row lands inside a collapsed region, so it costs no
new entry and the region's own summary moves instead. Compression and diffing have to agree about
that, or a reader sees "nothing added" for a page that grew.

Gated on the frozen live TodoMVC episode too — one committed action, a bounded diff:

| Transition | result |
| --- | --- |
| S0 empty → S1 three active | 11 changed, 7 added, 0 removed, 34 unchanged |
| S1 → S2 (check one todo) | **5 changed, 0 added, 0 removed, 47 unchanged** |
| S2 → S3 (filter to completed) | 1 changed, 5 added, 8 removed, 43 unchanged |

S1→S2 is the shape an action episode should have: five changes for one click, including the
remaining-count moving `"3"` → `"2"`, and the rest of the page reported as holding still.

### A finding: filtering re-identifies a region

S2→S3 is noisier than a reader would expect, and the cause is structural rather than a bug. A
region's address carries the shape digest of its members — that is what distinguishes two different
runs under one container — so filtering a list to its completed items changes the shape, changes the
address, and therefore changes the `ref_id`. The diff reports the old region removed and a new one
added. Defensible (the DOM really did replace those children) and less direct than "the list went
from 3 items to 1".

Fixing it would mean a second identity for regions, computed from the container alone — a second
identity recipe, which is exactly the thing the shared `anchoring` module exists to prevent. Left
as a stated limitation rather than resolved, pending a decision.
