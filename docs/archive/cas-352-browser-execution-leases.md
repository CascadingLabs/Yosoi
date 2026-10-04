# CAS-352 bounded browser execution leases

## Authority and boundary

Yosoi owns execution admission, configured limits, queueing, identities, lease scope,
accounting, lifecycle decisions, durable receipts, and terminal classification.
VoidCrawl owns concrete Chromium launch, process health, isolated-context creation,
page creation, page/context cleanup, and process close/reap facts.

Runtime `BrowserSession`, `IsolatedBrowserContext`, and `Page` handles remain private
to the concrete adapter. They are never serialized and never cross a durable result
boundary. Durable execution facts contain only Yosoi identities, bounded counters,
policy decisions, monotonic offsets, cleanup classifications, and closed secret-safe
provider reason codes.

The existing VoidCrawl `BrowserPool` is not used. Its pooled tabs deliberately share
a browser profile and retain cookies, cache, origin storage, service workers,
permissions, headers, and instrumentation state. That behavior cannot satisfy this
contract.

## Isolation model

A warm Chromium process is a mechanism container, not a mutable-state sharing
boundary.

- An independent capture lease owns one fresh disposable Chromium browser context
  and its initial blank page.
- A session tab-group lease owns one fresh disposable context. Every tab in the
  group is created inside that context and carries the owning Yosoi session identity.
- Unrelated independent captures and unrelated sessions never share a context.
- Releasing the lease disposes the entire context. Resetting a document or clearing
  selected state is not accepted as isolation.
- A tab identity is valid only while its owning session generation is active. Tabs
  cannot be detached, transferred, or used after session release.

Session tab groups intentionally share their own context state. Managed profiles,
profile persistence, profile forks, ambient contexts, and state merge are separate
work.

## Resolved limits

One validated execution policy resolves nonzero limits before launch:

- maximum warm browser processes;
- maximum active contexts globally and per process;
- maximum active tabs globally and per session;
- maximum queued requests and maximum queue wait;
- cleanup deadline; and
- normal process recycle threshold measured in completed context leases.

The total context limit cannot exceed `max_processes * max_contexts_per_process`.
The total tab limit cannot be below the total context limit because every active
context owns an initial page. All products and counter changes use checked
arithmetic.

## Admission and fairness

Admission is FIFO. A request reserves one bounded queue position before waiting.
Queue overflow fails immediately without launching Chromium or consuming capacity.
A queued request resolves exactly once as admitted, caller-cancelled, queue-deadline,
manager-closing, or provider-unavailable.

An admitted independent lease atomically owns one context unit and one tab unit.
A session owns the same initial units; each additional tab acquires one global tab
unit and must remain below the per-session cap. Cancellation or failure at any stage
returns every acquired unit through owned guards. A timeout bounds an event-driven
wait; no sleep, retry delay, or settlement polling is a readiness signal.

## Process selection, poisoning, and recycling

Only a live, non-poisoned process with per-process context capacity is selected.
Processes are selected deterministically with round-robin tie breaking. Launch is
lazy unless explicit warm-up was requested.

A provider disconnect, handler termination, failed context construction that makes
ownership ambiguous, or failed process cleanup poisons the process slot. Poisoned
slots reject new leases. Existing leases retain their own terminal and cleanup
facts; an earlier factual stop is not rewritten. After active contexts drain, Yosoi
requests bounded close/reap and may create a replacement without exceeding the
configured process limit.

Normal recycling begins only after the configured completed-context threshold. A
recycling process accepts no new leases, drains active contexts, closes and reaps,
and is replaced only when demand or explicit warmness policy requires it.

## Lease lifecycle

Execution requests transition through:

`requested -> queued -> admitted -> context_creating -> active -> releasing -> released`

Typed terminal alternatives are:

- queue full;
- queue wait deadline;
- caller cancellation;
- manager closing;
- provider unavailable or disconnected;
- tab close failure;
- context cleanup failure;
- process close/reap failure; and
- internal invariant failure.

Release is explicit and idempotent at the Yosoi boundary. A successful release
requires observed context disposal and returned capacity. Dropping a live lease
starts best-effort containment but is never durable evidence of successful cleanup.
Manager shutdown first closes admission, then requests cancellation, waits on owned
lease/task completion within its cleanup bound, disposes remaining contexts, and
closes/reaps every owned process.

## Durable execution facts

The durable receipt records:

- the exact owning capture identity;
- execution manager and lease identity;
- independent or session-group scope;
- process-slot identity and generation;
- context, session, and initial-tab identity;
- validated execution limits and terminal manager counters;
- the exact completed-context count for the process generation, including counts
  above the recycle threshold while already-admitted concurrent contexts drain;
- independent context and process cleanup classifications; and
- a closed secret-safe primary terminal reason.

Pre-admission failures use a separate closed outcome and never fabricate an admitted
execution receipt. The recycle threshold is an admission boundary, not a terminal
accounting ceiling. Runtime occurrence IDs remain in the durable receipt but are
excluded from semantic capture identity digests.

It never records provider handles, browser WebSocket endpoints, context/target IDs,
profile paths, cookies, storage values, credentials, unrestricted URLs, or raw
provider diagnostics. Execution facts are integrated with the browser result and
wire provenance; evidence-family truth and bundle-last finalization remain unchanged.

## Deterministic conformance

Tests use loopback fixtures, explicit browser/CDP events, barriers, channels,
cancellation tokens, notifications, and joined tasks. They prove fresh-context
isolation for cookies, local/session/IndexedDB/CacheStorage state, HTTP cache,
service workers, permissions, extra headers, renderer state, and page state;
session-local sharing; tab ownership; exact capacities; FIFO queueing; overflow;
cancellation and deadline races; tab/context cleanup; process failure, poisoning,
replacement and orphan reaping; idempotent shutdown; receipt validation; and
secret-safe error paths.

## Capture orchestration

`capture_attempt_managed` routes the existing capture controller through an independent
manager lease. It retains the same observation and staging behavior while releasing only
the disposable context at attempt completion; the warm process remains manager-owned.
`BrowserAdapterResult` carries the complete execution receipt as a sibling fact, and
browser finalization copies that receipt into `WebCapture`, so canonical wire output
retains admission, terminal, cleanup, accounting, slot, and generation facts without
serializing provider handles. The existing `capture_attempt` remains the explicit cold
process path for compatibility and warm-versus-cold measurement.

## Operating-envelope evidence

CAS-352 extends the browser benchmark harness with named warm-process versus cold-launch
Criterion runs and a loopback-only capacity/soak driver covering 1×1, 1×2, and 2×4
process/context/concurrency matrices. The runtime conformance tests cover FIFO queue wait,
bounded cancellation and deadline, deterministic disconnect, poison/recycle, failed-close
retry, in-flight shutdown, and last-owner containment. The soak runner records process-tree
process counts, FDs, tasks, RSS, PSS, CPU ticks, roles, remaining PIDs, orphan PIDs, and
exact residual manager capacity. Results are local evidence rather than
universal thresholds. Final evidence is produced in one harness operation: both
Criterion commands and every soak command receive the selected canonical `CHROME`
path explicitly, then finalization recomputes and compares Yosoi, VoidCrawl,
chromiumoxide, and Chromium identity before hashing metadata with command and output
artifacts. Finalization rejects source/runtime drift and requires each soak JSONL to
contain `concurrency × iterations` attempts plus one matching summary. Each final
result names exact Yosoi source, VoidCrawl source, controller and Chromium identities,
mode, fixture digest, limits, warm-up policy, recycle policy, and residual-resource
outcome.

## Verification evidence

The final local gate runs all Yosoi workspace tests serially, checks formatting and
warnings-denied Clippy, audits source-line guidance and dependency policy, compiles
every benchmark harness, and verifies that no test Chromium root remains. The paired
VoidCrawl gate checks the full workspace, runs warnings-denied Clippy, and executes
the complete core suite plus focused PyO3 and MCP compatibility tests.

Final change-scoped loopback evidence is stored under
`benchmarks/results/by-change/jj/<change-id>/browser/cas-352-execution/` and produced
by `cargo xtask benchmark browser-execution` only after source stabilization. The
evidence and Criterion manifests must both verify; metadata binds the dirty Yosoi and
VoidCrawl source snapshots, vendored chromiumoxide source, and canonical Chromium
executable. The soak covers 25 iterations at concurrency 1, 2, and 4 (25, 50, and 100
captures), while the Criterion artifacts retain ten-sample cold-process and
warm-process/fresh-context intervals for minimal, full, and growth fixtures. Final
review must read the measured values from the identity-bound artifacts rather than a
copied documentation table.

These values describe this machine and captured source/runtime identities only; they
are not universal thresholds or a guarantee of equivalent behavior on another host.

## Non-goals

This contract does not add managed profiles, profile forks or pools, generic provider
traits, ambient shared tabs, arbitrary automation, distributed scheduling, or the
CAS-351 asynchronous navigation scheduler. It does not pin or publish VoidCrawl.
