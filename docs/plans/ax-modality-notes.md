# Accessibility-tree modality (CAS-263) — implementation notes

The AX modality on the shared observation kernel: a canonical raw-AX artifact, a deterministic
pruner, AX resolution in the inspector, one real frozen capture, and a gate.

## What was built

| Piece | File | Notes |
| --- | --- | --- |
| Canonical artifact | `yosoi/observations/models/ax.py` | Schema `ax1`. Frozen pydantic, `extra='forbid'`, graph-integrity validator, `serialize_ax_snapshot`/`parse_ax_snapshot`. Flat node list mirroring `Accessibility.getFullAXTree`. |
| Shape/identity/summary primitives | `yosoi/observations/ax_tree.py` | Census, ancestry, sibling counts, durable steps, shape signature, member keys, region coverage, conditional facts — plus AX address resolution used by the inspector. |
| Pruner | `yosoi/observations/pruning/ax.py` | `AxPruner`, version `1`. One `reduce` on `SemanticPruner`; paging, collapse, ordinals and accounting stay in the kernel. |
| Inspector resolution | `yosoi/observations/index/inspect.py` | Additive: one import block, `AX_TREE` admitted in `_artifact_for`, one branch each in `inspect`/`rebind`/`expand`, one `_expand_ax` helper. |
| Capture | `scripts/capture_ax_aria.py` | VoidCrawl `BrowserPool` → `get_full_ax_tree()`; no Playwright anywhere. Freezes AX **and** rendered DOM of the same page state, with sha256 digests. |
| Boss fight | `tests/boss_fights/ax/aria_widgets/` | Controlled ARIA fixture, real frozen capture, manifest + independent ground truth, 17 offline tests. |
| Unit tests | `tests/unit/observations/test_ax_artifact.py`, `test_ax_pruning.py` | 17 + 33 tests, pytest only. |

## Measured numbers

Frozen live capture of the controlled ARIA fixture (`tests/boss_fights/ax/aria_widgets`), a real
headless Chrome through VoidCrawl:

| Measure | Value |
| --- | --- |
| AX artifact | 46,611 B |
| Nodes captured | 178, of which **28 ignored** (retained, with reasons) |
| Candidates emitted | **114** |
| Prune time | **7.4 ms** |
| Identity coverage (`ref_id`) | **100/114 (88%)** — anchor tiers: attribute 64, tag 36, refused 14 |
| Regions | 9, collapsing 26 members |
| Rendered overview | 1,763 tokens of a 3,000 budget, **not truncated** |
| Same page, DOM modality | 28,735 B artifact, 76 nodes → 58 candidates |

The 88% is higher than the rendered-DOM modality's 74% on live pages, and for an unsurprising
reason: an accessibility tree is mostly *named* things, and the accessible name is the anchor tier
this modality leads with. It is one page, so treat it as a sanity check, not a coverage claim.

Determinism, exact resolution, fail-closed on foreign/stale references, cross-capture identity
stability, and accounting are all gated rather than asserted here.

## Design decisions and why

* **Canonical evidence is raw.** `yosoi/core/fetcher/dom/ax.py`'s `AxSnapshot` is deliberately not
  reused: it drops ignored nodes and keeps only clickable role/name pairs. That is a view.
  `ignoredReasons` is the QA finding, so it has to survive into the artifact.
* **Ignored nodes are a band, not noise**, and the band is part of `ax_shape_signature`. An
  `aria-hidden` button among live buttons is a different kind of thing, not a differently
  configured one, so it gets its own entry instead of being averaged into a region's tally.
* **Shape excludes the accessible name.** Shape is role + state *names* + level + ignored band +
  child shapes. Names, values, descriptions, and property values are discriminants and live in
  region summaries, member variants, and `expand`. This is the rendered-DOM pruner's measured
  mistake (nine product cards, nine signatures, zero collapse) refused up front.
* **No keep/drop predicate.** The DOM reducer has `_should_emit`; AX deliberately has nothing like
  it. The browser already filtered this tree once, and the nodes it excluded are the ones a reader
  needs. Residency is the renderer's job.
* **Labels are executable.** An entry's label is `role "name"`, with `#n` appended only when the
  `(role, name)` pair repeats — exactly VoidCrawl's `click_by_role(role, name, nth)` signature. An
  AX address in this index is therefore already an action, with no selector to invent for a control
  the page never gave one. This is the modality's real payoff and it is cheap: the occurrence index
  is computed once per snapshot in tree order.
* **Facts only when they deviate**, with `DEFAULT_PROPERTY_VALUES` stated once on the root entry
  (`focusable=true`, `invalid=false`, …). Empty-valued properties are dropped too — `valuetext=` on
  every numeric spinbutton states nothing.
* **Relations are edges.** `labelledby`/`describedby`/`controls`/`owns`/`activedescendant`/
  `flowto`/`details`/`errormessage` are `AxRelation` values, never flattened into `child_ids`. A
  relation whose target has no AX node is kept with its `idref`, because a label pointing at a
  missing id is the defect.
* **Two capabilities are structural, not optional.** `VISIBLE_TEXT_COVERAGE` can never be declared
  available — the validator rejects it — which is "AX absence is never proof that visible
  information does not exist" as an invariant rather than a comment. `DOM_CORRELATION` is declared
  **unavailable with a reason** rather than omitted (see limitations).

## The boss fight

Controlled ARIA fixture (`fixture.html`): form with six checkboxes differing only in state, tabs,
combobox + listbox, grid, treeview, modal dialog, live region — plus a deliberate paired defect.

* **Defect visible in DOM, absent from AX.** A real, visible, clickable `<button aria-hidden="true">
  Delete account</button>`. Measured outcome: the string `Delete account` is present in the frozen
  rendered-DOM artifact and appears **nowhere** in the AX artifact — the accessible name is gone
  entirely, not merely marked. What remains is an ignored node with `ariaHiddenElement` and its
  subtree with `ariaHiddenSubtree`, and the index states that, so a reader sees an exclusion rather
  than concluding the page has nothing there. The overview carries it inside the token budget.
* **Defect obvious in AX, awkward in DOM.** Two icon-only buttons with no accessible name. In AX
  they are `button` with no name at all; the pair collapses to one region reporting two nameless
  buttons and declaring its members positional, because the page never gave them a durable key.
* **Repeated controls differing only in state.** Five wrappers collapse to one region whose summary
  reads `variants: checked=false×3, checked=true×2`.
* **Semantics only in AX.** Selected tab, selected option, `modal=true`, `live=polite`, expanded
  treeitem — all computed by the browser and only implied by the markup.

## Limitations, stated plainly

1. **`DOM_CORRELATION` is unavailable.** `backendDOMNodeId` is captured on every AX node, but the
   rendered-DOM artifact addresses nodes by JS-walk path ids, so no join key is shared. Every
   cross-modal claim in the gate is therefore made by comparing *text*, not by joining nodes. Real
   AX↔DOM contradiction detection needs the DOM producer to carry `backendDOMNodeId`; that is a DOM
   artifact change and was out of scope here.
2. **`setsize`-declared coverage is implemented and unexercised by real evidence.** The fixture
   declares `aria-setsize="50"` on five rendered options and `aria-rowcount="4"` on the grid, and
   **Chrome exposed neither as an AX property** in this capture — the strings `setsize` and
   `rowcount` do not appear in the raw CDP payload. So `ax_region_coverage` is covered by synthetic
   unit tests only, and on the real capture no region declares a total. Virtualised-list coverage
   claims are unproven for this modality.
3. **A broken `aria-labelledby` is not observable from `properties`.** Chrome reports the failed
   reference in `name.sources` (with `invalid: true`) and simply omits the `labelledby` property.
   This artifact does not retain `sources`, so the only surviving evidence is "this control has no
   accessible name". `AxRelation` supports unresolved targets and is exercised by unit tests;
   retaining `name.sources` is a candidate follow-up and would make the diagnosis exact.
4. **The text shell dominates the node count.** 90 of 178 nodes are `StaticText`/`InlineTextBox`
   restatements of their parent's name. With no keep/drop predicate they all stay addressable,
   which is doctrine, and it is also where a future *renderer* residency rule should act. Runs of
   them collapse; isolated ones do not.
5. **Ignored wrapper runs get a weak label.** `<label><input type="checkbox"> Email</label>` makes
   the AX tree repeat an unnamed `none` wrapper, so the region reads `group "Channels" > none #2`.
   The members' accessible content is inline in the summary (`"Email", "SMS", "Push" +2 more`), so
   it is discoverable, but labelling such a region by its first *named* descendant would read
   better. Not done; stated.
6. **`disabled` splits a run.** Chrome emits `disabled` only when true, so a disabled control has
   an extra state *name* and therefore a different shape. Five of the six fixture checkboxes
   collapse and the disabled one stands alone. Defensible (and useful for QA), but it means
   "repeated controls differing only in state" holds for value differences, not for
   presence-encoded ones.
7. **One page of evidence.** Identity coverage, candidate counts, and prune time come from a single
   controlled fixture. AG Grid, an ARIA Authoring Practices suite, and a GOV.UK-style form are
   named in `boss_fights.md` and are not captured yet.
8. **No AX episode.** Single snapshot only; no action-episode diff for this modality, though
   `index/diff.py` needs nothing new to do it since AX entries carry `ref_id`.
9. **No `PruningPolicy.collapse_to_fit` measurement.** Progressive collapse is wired through the
   kernel and works, but whether AX candidate mass spreads usefully across depth was not measured.

## Where the shared kernel fit, and the one place it strained

`SemanticPruner`, `index/paging.py`, `pruning/granularity.py`, `index/addressing.py`, and
`anchoring.py` were all reused unchanged; the pruner is one `reduce` plus the identity triple, as
intended. `anchoring.py` was **not** forked.

The one strain, reported rather than worked around: **the shared anchor recipe considers exactly
one positional tier — the author's first attribute — plus `id`/`data-*`/`class`, none of which an
AX node has.** So an AX anchor is a single key, while AX's natural identity is the *composite*
`role + name (+ nth)` that `click_by_role` takes. Consequences:

* Attribute order in `ax_attributes` becomes load-bearing: name first, role second. Leading with
  role would make nearly every anchor non-unique and refuse nearly every identity — the exact
  measured failure the rendered-DOM modality had before it was anchored.
* Two nodes with the same accessible name and *different* roles (a `link "Home"` and a
  `heading "Home"`) both fail the uniqueness census and are refused an identity, even though
  `role + name` would have been unique. That is a real loss of coverage, taken deliberately in
  preference to inventing a second identity recipe or smuggling a composite key in under a
  synthetic attribute name.

If composite anchors are wanted, that is a change to `anchoring.py` benefiting every modality, and
it should be made there with its own measurement — not in this module.

## Gates

* `uv run pytest tests/unit/observations -q` — 117 passed.
* `uv run poe boss-fights` — 80 passed.
* `uv run ruff check --no-fix --extend-select=RUF100 .`, `ruff format --check`, `pyrefly check`,
  `vulture`, `scripts/check_no_unittest.py` — clean for the files in this change.
* `uv run poe ci-check` cannot run **in this jj workspace**: its first step is
  `prek run --all-files`, which needs a git root, and a non-primary jj workspace has no `.git`.
  Its hooks were run individually instead (above). `uv run poe ci-test` passes 3,778 tests with
  four pre-existing, environment-caused failure clusters unrelated to this change: missing optional
  `claude_agent_sdk` in this venv, and `git rev-parse HEAD` failing in the API-docs link tests for
  the same missing-`.git` reason.
* Two pre-existing `PT018` lint errors in `tests/unit/observations/test_index_diff.py` (another
  agent's file, untouched here) — reported, not fixed, to keep the merge clean.
