# Normalized network evidence (CAS-266) — what was built and what it measures

The `network` modality on the shared observation kernel: a `net2` artifact, a `NetworkPruner`, and
the seeded 400-request boss fight `boss_fights.md` specifies. Everything below is measured on this
box against that fixture unless stated otherwise.

## What exists

| File | Role |
| --- | --- |
| `yosoi/observations/models/network.py` | `net2` — frozen, `extra='forbid'`, no header/parameter/body value slots |
| `yosoi/observations/network_tree.py` | Shared primitives: classing, templating, shapes, grouping, identity, rarity, resolution |
| `yosoi/observations/pruning/network.py` | The reducer — one `reduce`, no redaction step, no keep/drop predicate |
| `tests/boss_fights/generators/network_trace.py` | The seeded 400-request trace, pure and digest-pinned |
| `tests/boss_fights/network/seeded_400/` | The gate |
| `tests/unit/observations/test_network_{artifact,pruning}.py` | 68 + 23 unit tests |

Shared files touched, all additively: one lazy-export block in `models/__init__.py`, and in
`index/inspect.py` two imports, one entry in the admitted-kind set, and three dispatch branches
(`inspect`, `rebind`, `expand`). `pruning/__init__.py` already listed `NetworkPruner`.
`tests/unit/observations/test_observations_scaffold.py` lost its `NetworkPruner` row from the
"unimplemented pruners refuse" parametrization and gained a one-line replacement.

## The security boundary is the schema, not a code path

Redaction happens before bytes become canonical, so the reducer has no redaction step and no way to
add one. `net2` simply has nowhere to put a header or parameter value:

* `QueryParam` has `name` and `value_class` and **no** `value` field.
* Header **names** are kept and validated against an RFC 9110 lowercased field-name grammar, which
  rejects `'authorization: Bearer …'` in a name slot at validation time.
* `NetworkRedaction` is all `Literal`s, so an unredacted trace is not expressible — carrying header
  values would require changing a type, which a reviewer sees.
* Raw bodies are `RestrictedBody` **pointers** to separate `Sensitivity.RESTRICTED` artifacts, and a
  trace that points at one while declaring `bodies='dropped'` fails validation.
* URL userinfo is dropped; host spelling/default ports/query order are canonicalized; percent-encoded
  IDs and common token/JWT/base64 forms are templated before the artifact is built.

Origins and literal enum-like path segments remain evidence because removing them would erase which
endpoint was called. Therefore `net2` is not a substitute for CAS-269's upstream configured-secret
sanitizer: tenant names or arbitrary short secrets embedded in hosts/paths must be redacted before
`normalize_url`. The schema prevents known value-bearing slots; it cannot infer that every ordinary
word is sensitive.

The credential-name list is copied verbatim from VoidCrawl's
`crates/mcp_server/src/tools/network.rs::SENSITIVE_HEADER_SUBSTRINGS` — deny-by-default, substring
matched, over-redacting rather than missing a novel `x-my-session-token`. Yosoi never holds the
values, so here the list is used for the opposite purpose: naming which credential-bearing headers
an endpoint *requires*, which is evidence.

The restricted band rides the two gates that already existed and adds no third switch:
`PruningPolicy.include_restricted` decides whether a reduction may **name** a retained body's
artifact digest; `InspectionBudget.allow_restricted` decides whether it can be **read**. Without the
first, the summary still says a body was retained — that one exists is not the secret — it just does
not say where.

The boss fight asserts this structurally: every JSON object key in the 205 KB artifact is a declared
schema field name, so a leak cannot hide in a field nobody thought to grep for.

## Reuse of the kernel

`SemanticPruner` owns digest validation, policy hashing, paging, progressive collapse, ordinals and
accounting; `NetworkPruner` is one `reduce` plus the `name`/`version`/`evidence_kind` triple.

`anchoring.py` fits, and fits better than expected. A request's durable key is its own structure, and
a tag plus an ordered attribute sequence is all `build_census` / `usable_anchor` need — so an origin
is `('origin', (('data-origin', 'https://api.shop.example'),))` and an endpoint is
`('endpoint', (('data-endpoint', 'GET https://api.shop.example/v1/cart'),))`. No second identity
recipe exists. Measured: **40 of 41** entries earn a `ref_id`, and all 40 page-derived identities
are identical across two captures while their `RegionRef`s necessarily differ. The bare trace root
is deliberately unmatchable: a global identity derived only from the word `trace` would collide
across unrelated pages.

The two-level tree is genuine — origin → path template → requests — so `depth` (0/1/2) means
something without inventing a hierarchy, and the shared region mechanism *is* duplicate grouping:
41 cart polls cost one region reporting `×41`, and `expand` still walks all 41.

## Measured, on the seeded 400-request trace

Composition: 250 assets, 80 telemetry, 40 duplicate API calls, 20 irrelevant JSON, 8 useful API, 2
defects. The defects hide **inside** groups: a 500 as the sixth call to an endpoint whose other five
returned 200, and a 200 whose response shape and declared item count differ from the 40 identical
polls beside it.

| Measure | Value |
| --- | --- |
| Artifact | 204,710 bytes, 400 requests |
| Index | **41 entries** — 1 trace + 5 origins + 33 endpoint regions + 2 deviating members |
| Accounting | `source_items=439`, `retained_items=41`, `omitted_items=398` |
| Index output | 5,861 bytes |
| Whole index rendered | **1,297 estimated tokens** (all 41 entries, nothing truncated) |
| Defect entries | ordinals **3 and 5** — the 4th and 6th lines of the overview |
| Rarity rank of the two defect groups | **1 and 2** of 33 |
| Reduction time | **7.2 ms** (best of 5) |
| Identity | 40/41 `ref_id`, stable across captures; generic trace root refused |
| Asset + telemetry cost | 330 requests → **8 entries** |

`omitted_items` lands exactly on 398 because the population counts every addressable thing (trace,
origins, endpoints, requests): the 398 requests that got no individual entry, each still reachable
through `expand`.

## The ranking, stated plainly

Ordering is **lexicographic over an enumerated boolean tuple**, in one declared precedence. There is
no coefficient, no weight, and no learned score, so there is nothing to overfit:

1. `status_not_success` — status class is neither 2xx nor 3xx, or no response arrived *(RFC 9110 §15)*
2. `response_shape_deviates` — key skeleton differs from the modal skeleton of its own duplicate group *(measured)*
3. `problem_mime` — media type is `application/problem+json` *(RFC 9457)*
4. `mime_deviates` — media type differs from its own duplicate group's modal type *(measured)*
5. `item_count_deviates` — declared collection size differs from its own group's modal size *(measured)*
6. `singleton_template` — this path template was requested exactly once in the trace *(measured)*

Defect A fires 1, 2, 3, 4; defect B fires 2 and 5; the 23 singleton decoys fire only 6; the 330
assets and telemetry calls fire nothing. So the defects outrank every decoy by construction of the
precedence, not by a threshold — and the gate asserts that ordering, not merely their presence.

There is no keep/drop predicate and no host or path allowlist anywhere. A test proves it: two traces
that differ only in their hostname reduce to identical summaries.

An entry gets a second, individual line **only** when it deviates from a group of more than one. A
singleton group never gets one, because its region line already states that request's facts — the
childless-exemplar cost the DOM reducer measured at 4.5% of a real index, not paid again.

`OMITTED_RANKING_SIGNALS` is printed in the root entry: DOM cardinality cross-check, size and
duration outliers, ordering/dependency chains, host reputation, SSE and WebSocket frames.

The bottom of the budget band is now closed by the shared kernel rather than modality tuning.
`bound_to_previous` survives candidate → fragment → index entry, so each deviating request inherits
its endpoint region's render tier. Both defects remain resident at exactly **1,000 tokens** while the
whole index still costs 1,297.

## Limitations, all of them

**API/DOM cardinality mismatch is half implemented.** Only the network-internal half is computed (a
declared item count that differs from its own duplicate group). The cross-modality half needs a DOM
view of the same snapshot and belongs to the cross-modality gate.

**`net2` models request/response pairs.** Server-sent events and WebSocket frames are a sequence
schema, not a request schema, and are out.

**Ordering, dependency chains, and races are not ranked on.** A chain is a relation between requests;
every rarity feature here is a property of one request against its own group.

**Path templating is class-first, never frequency-based.** A segment is templated iff its value
classes as `id`, `token`, or `timestamp`. That is deliberate — a frequency rule would be a threshold,
and this modality's ranking is not allowed a threshold — but it means an opaque high-cardinality
segment (`/v1/session-abc_def!/…`) stays literal and splits into many singleton groups.

**Odd-length hex is a `token`, not an `id`.** `_HEX` requires whole byte pairs. Asserted rather than
tidied away, because the byte-pair rule is what makes a hex id recognizable at all.

**A repeated query parameter reports one class**, the first occurrence's. Multi-valued parameters do
not report a set.

**Timing buckets are schema-fixed**, not policy-tunable. Two consumers that bucket differently cannot
compare traces.

**The fallback address is nearly unreachable**, and that is fine. `net2`'s own validators exclude the
reserved locator characters from path templates and parameter names, and the tag tier anchors a lone
origin, so `/net/node/<digest>` only appears when a trace has several origins and one of them carries
a character the locator grammar reserves. Proven directly by a unit test rather than left untested.

## Where the kernel did not quite fit

**Network resolution lives in `network_tree.py`, not in `index/inspect.py`.** The DOM equivalent
(`_resolve_dom_address`, `_dom_anchor_target`, `_DOM_STEP`) lives in the inspector. Putting the
network resolver there too would have added ~90 lines to a file every modality author is editing
simultaneously. The dispatch is three branches; the logic is in the modality's own module. If the AX
modality does the same, `index/inspect.py` becomes a pure dispatcher and the DOM half should follow.

**Validation order in `reduce_once`.** Every implemented modality now validates artifact kind,
digest, length, and sensitivity before parsing modality bytes. Wrong-modality DOM and AX inputs
therefore report `cannot consume …` instead of blaming JSON syntax.

**`Reduction.source_items` assumes every candidate is drawn from one flat population.** Network has
four kinds of addressable thing, and counting only requests made `retained_items` exceed
`source_items` on a small trace (one origin and two endpoints out of two requests). Counting all four
makes the arithmetic exact — `omitted_items` is then precisely the requests without an individual
entry — but the field's name still suggests a single population, and a future modality with the same
shape will rediscover this.

**A three-level tree is carried by `depth`, not by address nesting.** Origin and endpoint each anchor
directly, one segment, because the endpoint key already contains the origin. Nesting them would have
produced a two-segment address whose first segment is redundant with its second.

## Gates

| Gate | Result |
| --- | --- |
| `uv run pytest tests/unit/observations -q` | 150 passed |
| `uv run poe boss-fights` | 79 passed (16 network) |
| `uv run ruff check` / `ruff format` | clean |
| `uv run pyrefly check` | clean |
| `uv run vulture --min-confidence 80` | clean |
| `uv run poe ci-check` | **cannot run in this jj workspace** — `prek` shells out to `git rev-parse` and there is no `.git` here. Every hook was run individually instead (ruff, pyrefly, vulture, `check_no_unittest.py`) plus `ci-test`. |

`ci-test` leaves 6 failures and 4 errors that are environmental and pre-existing, none in
`yosoi/observations`: `claude_agent_sdk` is not installed in this workspace's `.venv` (5), and
`tests/unit/scripts/test_generate_api_docs_links.py` shells out to `git rev-parse HEAD` (4 + 1).
Two unrelated `PT018` lint findings in `tests/unit/observations/test_index_diff.py` were inherited
from the parent change and fixed in passing, since `ruff` runs over all files.
