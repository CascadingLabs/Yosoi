---
title: 'Workspace plan: decisions, code and proof'
description: 'A concrete implementation sequence for every item in the refinement project.'
order: 1
---

# Workspace plan: decisions, code and proof

[Open this plan in Linear](https://linear.app/cascadinglabs/document/browser-automation-workspace-implementation-plan-9b7255623678)

This plan covers the **15 current issues** in the cleanup project, inspected on
October 10. It is a plan, not a claim that the changes are implemented or an
instruction to resume the paused runtime work.

The [refinement notebook](refinement.md) preserves the discussion. Linear owns
execution state; this page maps that work to the workspace.

## The decisions just settled

**A parked Flow keeps exclusive tab ownership and yields worker capacity.**
It also releases foreground resources once the current operation has safely
settled. Another tab can progress. Another workflow cannot mutate the parked
Flow's tab. Giving up tab ownership is an advanced policy requiring separate
conflict/revalidation rules, not the default path.

**If a borrowed lease cannot be safely released within its cleanup budget,
leave the tab fenced and return an error. Do not close it automatically.**

The other agreed fundamentals remain: automatic ownership through `invoke()`,
optional `with_lease`, optional external `with_cancellation`, integer millisecond
timeout inputs and one deadline per complete action. A Flow timeout supplies an
inherited per-action default; it is not a cumulative total-run deadline.

## What Andrew needs to decide

You do not need to specify mutexes, Tokio plumbing or every internal type.
Review these product behaviors and the examples that exercise them:

1. **Lifecycle budgets:** acquisition and cleanup bounds, and whether callers
   may override them per invocation. The 10-second Policy action fallback and
   millisecond delay/condition inputs are implemented; no silent reinterpretation
   of older persisted microsecond fields is allowed.
2. **Typed authoring:** field/control binding spelling, assertion expectations,
   child Flow composition, bounded repetition/grouped fill, and exact quantity/GS
   conversion for the Qscrape example.
3. **Networking first slice:** direct HTTP versus browser guarantees, supported
   source/interface binding, and exact proxy-egress promises. These need an
   enforcement feasibility result before the scope can be promised.
4. **Release assignment:** whether JS file helpers, Python, Archive and Views must
   ship in 0.2.0. Durable resumption, distributed scheduling, full modules and
   continuous raw network/AX streams remain separately shaped capabilities.

We will supply concrete examples and recommended defaults for each decision.
Accepted choices are recorded; open ones are not silently decided during coding.

## How work enters the workspace

Use `browser-actions--Yosoi` as the current review/integration checkout. Preserve
its partial timing/cancellation changes before any revision or workspace operation.
The current files include `timing.rs`, timed Step/Flow metadata, optional external
cancellation and executor deadline changes; these are not a passing implementation.

Do not land or silently cherry-pick the existing Qscrape example as the final SDK.
Its separate `qscrape-flow-example` workspace contains useful browser evidence,
but currently flattens child recipes and uses CSS/data attributes directly.

For the serious implementation, use WTF to create an isolated JJ workspace based
on the verified, snapshotted integration revision. Choose the exact base after
reviewing concurrent work. Keep the local docs preview on the integration source
while each completed slice is reconciled into it with JJ and its evidence recorded.

Suggested main feature bookmark: `browser-lifecycle-refinement`. Use bounded
follow-ons such as `typed-flow-qscrape` and `network-routing-policy` only when their
independent scopes are approved. Share model decisions first; separate workspaces
must not develop conflicting versions of Step, Flow, receipts or Session authority.

## Implementation order

| Pass              | Items                                                                 | Result                                                                                             |
| ----------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Contract          | CAS-563, CAS-564; authoring shape from CAS-575                        | One ownership model, deadline propagation, park/resume rules and compatible recipe/outcome schema. |
| Shared lifecycle  | CAS-568, CAS-569, CAS-570, CAS-571, CAS-572                           | Implement deadlines, cancellation, safe handoff, execution permits and deferred checks together.   |
| Integration proof | CAS-575, with CAS-566/CAS-567 changes required by its schema/evidence | Reusable typed Qscrape recipes, native composition and positive/negative lifecycle proof.          |
| Opt-in follow-ons | CAS-565, CAS-573, CAS-574                                             | Approved JS ergonomics and Python API on the settled lifecycle.                                    |
| Networking        | CAS-576                                                               | Independently shaped enforcement, integrated with policy identity and resource reuse.              |
| Release gate      | CAS-562                                                               | Explicit capability/package matrix and current release evidence.                                   |

Archive compatibility is designed before the first new persisted shape, even
though broader Archive hardening remains a later item. View identity needed by
deferred checks is earlier shared evidence work, not a requirement to finish
every View feature before Flows can run.

## CAS-563 — lifecycle umbrella

**Your part:** review the transition examples. Parking and uncertain borrowed
release defaults are agreed; advanced overrides remain separately shaped.

**Code:** use the existing `crates/yosoi/src/session.rs`,
`crates/yosoi-engine/src/session.rs` and browser execution manager. Define
acquiring, held, parked, settling, released, closed and fenced/quarantined states.
Separate tab ownership from runnable work and foreground control. Reconcile
Request borrowing and Session cancellation with the same state machine.

**Proof:** state-transition fixtures covering acquisition failure, waiter
cancellation, close revocation, ordinary release and uncertain dispatch.

**Dependencies:** shared contract for CAS-568 through CAS-572. This issue owns
integration of its children; it is not another duplicate implementation pass.

## CAS-568 — timing

**Implementation update:** use the approved [nearest-scope timeout contract](timeout-scopes.md).
Child overrides replace inherited limits, even when longer; the earlier total
Flow stopwatch/minimum model is superseded. CAS-568 is integrated in the review
workspace. Other runtime work remains paused for its own review.

**Your part:** review the implemented inheritance API. Policy defaults to 10,000
ms; positive overrides must fit a checked monotonic deadline.

**Code:** the existing executor resolves Policy → parent Flow → nested Flow →
action. One selected action deadline covers lookup, foreground wait, provider
completion and required capture. Flow-dispatched Work respects that deadline;
standalone Work retains its existing operation defaults. Acquisition and cleanup
retain separate safety budgets. Versioned records preserve old microsecond units.

**Proof:** multiple internal calls consume one action budget; each action receives
the nearest inherited timeout. A longer child completes beyond its parent's
default, siblings restore the parent scope, and concurrent scopes remain isolated.
Zero/overflow and legacy wire values are handled. No cumulative Flow stopwatch
clips a descendant override.

**Dependencies:** CAS-563, the child-Flow schema choice in CAS-575, and CAS-566
for persisted compatibility. Implement alongside cancellation and cleanup.

## CAS-569 — cancellation

**Your part:** no further decision on ordinary usage. Cancellation is always
internal; external control remains optional. Review outcomes for interrupted work.

**Approved continuation contract:** [Continue or stop](continuation.md). Failure
and local cancellation default to Continue. Policy/parent/child/leaf overrides
resolve independently, including explicit Continue over a global Stop. CurrentFlow
stops only the nearest child; Invocation stops all remaining work. Root/Session
cancellation and uncertain tab state remain hard safety boundaries. Andrew
authorized implementation and the Final Boss integration into default.

**Code:** settle invocation contexts and child cancellation scopes in Flow,
Session, Work and acquisition. Ordinary `invoke()` and optional
`with_cancellation(...).invoke()` use one executor. Track dispatch progress
separately from the stop cause. A dropped invocation signals its owner without
losing receipts or relinquishing unsafe control. Update existing callers together.

**Proof:** pre-cancelled invocation, cancelled waiter, in-flight cancellation,
Session-wide cancellation, child isolation and future drop. A cancelled task
does not imply the browser/server rolled back an effect.

**Dependencies:** same lifecycle/cleanup context as CAS-568 and CAS-570; child
recipes in CAS-575 inherit the same cancellation scope.

## CAS-570 — release and cleanup

**Your part:** the uncertain borrowed-tab default is agreed: retain the fence
and return an error. Review the result/error shape; automatic-close overrides
need separate shaping.

**Code:** replace release-by-drop-only semantics with an explicit safe handoff
result. Reuse `browser_execution/control.rs`, `tab.rs` and `cleanup.rs`; give
the runtime owner bounded settlement/cleanup after caller drop. Preserve work
and cleanup errors together. Keep admission permits quarantined when shutdown
cannot establish safety. Closing and parking are distinct from releasing control.

**Proof:** clean release retains state; dropped/failed release cannot expose a
tab; a closed resource never grants control; cleanup times out independently;
borrowed Flow completion does not close or release its caller's resources.

**Dependencies:** the same dispatch/progress record used by CAS-569 and scheduler
handoff in CAS-571. These must not be independent cleanup implementations.

## CAS-571 — parked scheduling

**Your part:** the default is now approved: retain tab ownership, yield worker
capacity. Review fairness/concurrency defaults when we show the A/B/C/D example.

**Code:** extend the existing manager-backed scheduler in
`browser_execution/scheduler.rs` and its worker/admission/progress modules.
It already has per-tab FIFO and cross-session round-robin navigation admission;
reuse its bounded machinery instead of creating another executor. Define which
permits cover active controller work and release them at safe park points.
Foreground input/capture locking in VoidCrawl remains a separate resource.

**Proof:** with concurrency two, parked A/B do not prevent runnable C/D; a
parked Flow's tab remains unavailable to unrelated writers; cancellation and
timeouts release runnable capacity without breaking logical ownership; no busy
polling, unbounded queue or focus race. Measure latency; do not promise 10 ms.

**Dependencies:** CAS-568/569/570 and CAS-572. Advanced yield-tab ownership remains
separate until conflict/revalidation behavior is shaped and approved.

## CAS-572 — deferred assertions

**Your part:** review current-state checks versus action postconditions and the
proposed typed assertion syntax with CAS-575.

**Code:** represent pending checks with session/tab, document generation,
originating operation, predicate, deadline and cancellation. Reuse condition
observation, including the existing MutationObserver path, with bounded
subscriptions and scheduler requeueing. Capture expected/observed values and
reject stale/foreign/conflicting evidence. Origin association is not proof of
server-side causality. Visual checks may require foreground resources; DOM reads
should not activate a tab unnecessarily.

**Proof:** rerender/navigation invalidation, two observers, slow subscriber,
park/resume and timeout. A foreign writer cannot satisfy another invocation's
postcondition if an advanced ownership policy is introduced. Typed unsupported
checks remain unsupported; no blanket network/AX feature is implied.

**Dependencies:** CAS-571, CAS-575 and the minimal identity work in CAS-567.

## CAS-564 — Flow ergonomics umbrella

**Your part:** review the typed recipe examples. Keep plain calls easy and
advanced authority explicit; do not make callers configure cancellation normally.

**Code:** consolidate the public Action/Flow vocabulary and error/results surface.
Use the existing Conditions, Documents, Locators and Contracts where they fit.
Coordinate child recipes and the Python API rather than adding a separate DSL.

**Proof:** reviewed examples construct no browser work; results distinguish
successful invocation transport from failed/unknown business checks; the same
recipe can use managed or borrowed execution.

**Dependencies:** CAS-572/575 and the settled lifecycle. Children carry the
bounded changes; this umbrella owns coherent public behavior and docs.

## CAS-575 — typed Qscrape composition

**Your part:** choose field/control binding spelling, Contract expectation syntax,
native child composition, repetition/fill semantics and quantity/GS conversion.

**Code:** shape real child Flow nodes, not a flattening-only helper. Preserve child
paths and inherit authority, deadlines and cancellation. Bound nesting depth,
expanded operations, repetition and evidence. Reuse Documents/Locators Plans,
`yosoi-contracts`, derive and validation crates for observations. Keep live controls
distinct from immutable text/JSON/XML references. Add scoped exact quantity and
GS decimal conversion rather than inventing unrestricted currency support.

Bring forward the useful example from `qscrape-flow-example` after its base and
diff are verified. Replace CSS scattered through recipe logic with explicit site
bindings. Preparation and submission remain separate invocations.

**Proof:** the same native recipes handle pickaxe ×10 / 145.00 GS and chisel ×3 /
19.50 GS; reject wrong SKU, starting quantity, total, duplicates, incomplete
captures and unsupported projections. Verify the confirmation record, not URL
alone. Preserve observed blank-grid failures instead of rerunning until a preferred
framework appears. Existing example evidence does not prove this proposed API.

**Dependencies:** CAS-568–572, CAS-566 and minimal CAS-567 identity. Live evidence
supplements deterministic fixtures. Use synthetic fixture checkout details.

## CAS-565 — JavaScript hardening

**Your part:** approve supported frame/world behavior and release scope. JS still
requires both a lease and explicit permission; cancellation is never rollback.

**Code:** enforce bounds, targeting/generation checks and diagnostics through the
same Work/action context. Review transient allocations separately from retained
result limits. Reconcile exceptions and uncertain mutation with lifecycle receipts.

**Proof:** denied default, allowed value/mutation, exception, oversized result,
stale frame/document and cancellation after possible mutation. No module or
isolated-world claim follows from ordinary evaluation.

**Dependencies:** lifecycle context; CAS-573 adds separately approved ergonomics.

## CAS-573 — JS files, modules and managed permission

**Approved October 10:** include JS files and modules now in the default workspace.
Use construction-time snapshots and explicit managed JS opt-in.

**Code:** `action::evaluate_file` snapshots script text. Explicit
`action::run_module` actions capture local module graphs, preserving import/export
semantics and exact source/provenance. `.mjs` alone does not select module
execution. `.bind(&policy).allow_javascript().invoke()` acquires managed authority;
a borrowed lease retains its Session's existing permission.

**Proof:** missing/oversized/invalid UTF-8 files, source changing after construction,
Archive fidelity, imports/re-exports/cycles/live bindings/top-level await,
permission denial, child recipe propagation and truthful uncertain outcomes.

**Dependencies:** existing Work execution and bounded recipe/provenance shape.
CAS-573 records focused Rust and controlled-browser results before Final Boss.

## CAS-574 — Python parity

**Your part:** approve Python-native syntax and whether Python is required for
this release. Optional-lease invocation has already been chosen.

**Code:** reconcile `crates/yosoi-python/src/browser.rs`, `python/yosoi/browser.py`,
stubs and exports with the settled Rust model. Async context managers preserve
ownership and combined failures. Propagate Python cancellation through the owner
without blocking its event loop or releasing unresolved control. Map validated
millisecond inputs and optional external stop references consistently.

**Proof:** installed wheel workflows, cancellation in acquisition/execution,
exceptional context exit, Watch shutdown, lease borrowing and cross-language
record/reference interchange. Existing bridge call-site edits are not parity proof.

**Dependencies:** settled Rust authoring/lifecycle and Archive schema. Deferred
until Python is re-enabled; no parallel divergent Python lifecycle design.

## CAS-566 — Archive compatibility and replay

**Your part:** approve compatibility support and whether Archive ships in 0.2.0.

**Code:** choose a versioned encoding before persisting timed/nested recipes and
new outcomes. Extend `automation_record.rs` and Archive validation while keeping
old immutable payloads and references meaningful. Verify digests before decoding;
never rewrite stored bytes to hide a schema change. Preserve policy/source lineage,
child paths, redaction and bounded retention.

**Proof:** legacy records, new record round-trip, corrupt/truncated/missing
payloads, interrupted writes and fresh-process offline replay. Live rerun is fresh
execution; durable lease restoration is not part of replay.

**Dependencies:** model design starts alongside CAS-568/575; broader hardening
follows approved release scope. Changes required by persisted models are not optional.

## CAS-567 — View identity and bounds

**Your part:** approve supported modalities and release assignment. No new AI
discovery feature is assumed.

**Code:** reuse `view.rs` and observation identities for stable capture-bound
references, pagination and explicit stale/partial/unsupported results. Apply
aggregate memory/evidence limits; ensure deferred checks never mix generations.

**Proof:** old cursor against new capture, large/partial evidence, wrong document,
offline/live projection agreement for supported checks, unsupported offline Visible.

**Dependencies:** minimal identity joins CAS-572/575 early; broader polish can wait.

## CAS-576 — networking and strict IPv6

**Your part:** choose acquisition paths and platforms for the first guarantee,
source/interface controls, proxy-egress semantics and release assignment.

**Code:** first inventory enforcement in `yosoi-policy`, policy resolution,
`yosoi-web-capture-direct-http` (including `executor.rs` and `redirect.rs`), and
VoidCrawl/Session configuration. Then shape typed family/routing policy and identity.
Enforce each DNS/redirect hop, reject IPv4 literals/fallback in strict mode, and
partition pooled connections/browser processes by compatible effective policy.
Browser subresources and proxy destination egress need their own feasibility proof;
unsupported guarantees must fail explicitly. Binding to a local IPv6 address alone
is not assumed to prove all requested routing guarantees.

**Proof:** controlled IPv6-only, IPv4-only and dual-stack services; redirects;
incompatible bindings; resource reuse after policy changes; browser subresources
and proxy boundary. Observe connection family and zero IPv4 attempts in strict
mode. Report unavailable host IPv6 coverage explicitly.

**Dependencies:** networking feasibility can be investigated independently; policy
identity, timeout/cancellation and resource reuse integrate with the lifecycle.
Do not implement broad custom DNS/per-destination routing without separate scope.

## CAS-562 — release gate

**Your part:** choose the shipping capability/platform matrix and make the final
release decision. Only Andrew advances Final Boss to Ready to land.

**Code:** integrate approved feature revisions, finalize docs/examples, perform
version metadata/release notes work through existing xtask, build the supported
artifacts and verify consumer installs. Recheck the current Stable Chrome baseline.

**Proof:** exact revision, focused local checks, browser/container evidence, live
example limits, installed Python artifacts if included, required hosted CI and a
concise decision memo. Preserve these as separate evidence levels. No passing
historical spike log certifies the new implementation.

**Dependencies:** only capabilities selected for the release. Backlog ideas do
not automatically become blockers or shipping promises.

## First concrete implementation checkpoint

After the remaining lifecycle choices are approved, reconcile the paused edits
and implement one integrated slice: total/per-action deadlines, intrinsic scoped
cancellation, safe release outcomes, and automatic worker-capacity yielding while
retaining tab ownership. Include one parked assertion and a two-worker/four-tab
fixture. That checkpoint connects CAS-568–572 rather than producing five
incompatible mini-implementations.

First run focused compilation/model tests with one worker, then the controlled
browser fixture. Do not run the full workspace suite or repeat passing checks
without a change. Bring its SDK example, receipts, timing and cleanup results back
for review before completing typed Qscrape composition and optional follow-ons.

## Decision to review

Start with the remaining timeout defaults and explicit unit migration.
Then review the typed Qscrape authoring proposal. Those decisions unlock the next
bounded implementation; the networking guarantee and release matrix can be shaped
without holding up every part of the shared lifecycle design.
