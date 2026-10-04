# CAS-294: Bounded Observation Log and Streaming Capture Options

Status: proposed type-system direction; no collector, event loop, binary codec, or settlement detector implementation

Linear: [CAS-294](https://linear.app/cascadinglabs/issue/CAS-294/define-bounded-capture-windows-and-termination-outcomes)

## Goal

Define the data-model foundation for observing a changing web surface over time. The model should support a future adaptive agent during discovery and deterministic recipe replay afterward without claiming that a modern page reaches one universal "done" state.

This note is deliberately ahead of the current artifact payload vocabulary. It explores how future network, DOM, accessibility, rendering, lifecycle, and agent-action observations could share one bounded temporal model. The Rust snippets are illustrative shapes, not proposed production APIs.

## The central idea

A capture is not only a final page snapshot. It is a bounded observation of several asynchronous sources:

```text
Network producer ───────┐
DOM producer ───────────┤
Accessibility producer ─┼→ observation coordinator → append-only log
Rendering producer ─────┤                              │
Agent actions ──────────┘                              ├→ durable artifacts
                                                       └→ live checkpoints
```

The browser and its providers produce observations. A future coordinator orders their arrival, enforces bounds, records loss, and exposes projections. An LLM or another controller decides whether the available evidence is useful enough to extract, interact, continue observing, or finish.

The durable model should serialize observations and decisions. It should not serialize Rust futures, tasks, channels, executors, or provider callbacks.

## Human and agent behavior

A human generally does not wait for global network or DOM silence. They begin when the part needed for their next decision is useful:

- read a headline while advertisements continue loading;
- click the first search result before all images arrive;
- type into an enabled form while analytics requests remain active;
- pause and reorient when a relevant control moves or disappears;
- scroll an infinite document that never settles globally.

An adaptive discovery loop has the same shape:

```text
observe enough evidence
→ form a provisional interpretation
→ extract or interact
→ observe consequences
→ revise the interpretation
→ continue or finish
```

Therefore transport activity, representation stability, and task readiness are different facts:

| Dimension | Example question | What it does not prove |
| --- | --- | --- |
| Transport activity | Are requests or bytes still active? | That useful content is unavailable |
| Representation activity | Are DOM, AX, layout, or pixels changing? | That the relevant target is changing |
| Affordance readiness | Is the target present, enabled, visible, and interpretable? | That the rest of the page is quiet |
| Task sufficiency | Does the controller have the advertisement token and URL? | That the browser is globally complete |

CAS-294 should provide signals and bounded evidence. It should not make a universal usefulness decision for the controller.

## Relationship between contract, recipe, capture, and discovery

These concepts should remain distinct:

- **Contract:** semantic data wanted by the caller, such as an advertisement token and URL.
- **Recipe:** a deterministic acquisition and extraction procedure learned during discovery.
- **Capture:** evidence observed while discovering or replaying a recipe.
- **Checkpoint:** a bounded "known as of" projection used during a live session.
- **Receipt:** immutable terminal facts explaining how a bounded observation ended.
- **Environment:** representation-affecting HTTP or browser context from CAS-291.

A static recipe does not need to use fixed sleeps. It can encode deterministic conditions and bounds:

```text
After first paint:
  inspect the known advertisement attributes.

If the token is absent:
  observe matching network responses.

If still absent:
  observe relevant DOM mutations for at most two seconds.

Ignore for readiness:
  images, analytics, long-lived sockets, and unrelated subtree mutations.

Accept only if:
  the token and URL satisfy the contract's validators.
```

Discovery may use an LLM to choose this procedure. Replay can execute the resulting recipe without making the same open-ended decision again.

## Design constraints

- Five-second and ten-second configured windows must remain distinguishable even if both stop earlier.
- Wall-clock timestamps are correlation anchors; monotonic elapsed time is the duration authority.
- Event timestamps must be relative to an explicit observation origin in serialized artifacts.
- Concurrent sources are only partially ordered. The model must not invent browser causality.
- Quiet-period satisfaction is a timestamped observation, not proof that a page will remain quiet.
- A never-settling page must still produce a valid bounded result.
- The controller finding sufficient evidence is a normal successful stop, not an interruption.
- Event and byte limits must state whether they stop observation or only stop retention.
- Dropped, unavailable, and unobserved data must not be represented as known zero.
- Tree deltas must not be applied across an unaccounted gap.
- Large bodies, screenshots, and snapshots should be referencable without forcing them into every event envelope.
- Schema and storage choices must permit independent evolution of artifact families.
- CAS-294 defines types and invariants only. Runtime scheduling, browser adapters, and compression implementation remain future work.

## Vocabulary

### Capture session

A potentially long-lived runtime relationship with a browser or HTTP provider. It may span multiple agent turns and contain several bounded observations. A session is not itself an immutable receipt.

### Observation window

A bounded interval with declared policy, start, end, elapsed duration, and terminal cause.

### Interaction epoch

An interval beginning with navigation or an agent action. It groups observations that may be consequences of that action without claiming strict causality.

### Observation stream

One typed source of observations, scoped to a browser context and document epoch where applicable.

### Document epoch

A capture-local identity for one document lifetime. Navigation creates a new document epoch so late events from an earlier document cannot be mistaken for current state.

### Signal

A timestamped fact derived from observations, such as first paint or satisfaction of a declared quiet-period policy. A signal may later be superseded or invalidated.

### Checkpoint

An immutable projection of what is known through a cursor. It does not imply that capture has terminated or that no later event will change the projection.

### Gap

An explicit range or quantity of observations that was not retained or could not be observed.

## Option A: terminal snapshot only

Store configured bounds, final snapshots, and one termination outcome. Do not retain an observation journal.

```rust
pub struct BoundedCapture {
    pub window: ObservationWindow,
    pub artifacts: Vec<WebArtifactRef>,
    pub termination: CaptureTermination,
}
```

### Optimizes for

- the smallest type surface;
- straightforward JSON serialization;
- consumers interested only in final representations;
- low storage overhead.

### Problems

- cannot explain how a discovered recipe became valid;
- cannot expose incremental evidence across agent turns;
- loses transitions such as a candidate appearing and disappearing;
- weak support for debugging timing-dependent extraction;
- forces providers to collapse loss and in-flight activity into final summaries.

### Likely failure mode

The final snapshot becomes overloaded with provider-specific lifecycle flags, while discovery needs an unmodeled side channel for everything that happened before it.

## Option B: one universal event enum

Represent all future observations as variants in one closed enum.

```rust
pub enum WebObservationEvent {
    NetworkRequestStarted(NetworkRequestStarted),
    NetworkRequestFinished(NetworkRequestFinished),
    DomMutation(DomMutation),
    AccessibilityChanged(AccessibilityChanged),
    FirstPaint(FirstPaint),
    AgentAction(AgentAction),
}
```

### Optimizes for

- exhaustive Rust matching;
- obvious event ordering;
- simple in-memory streaming;
- one wire union for consumers.

### Problems

- every artifact-family addition changes the central enum;
- network, tree, visual, and action payloads evolve at different rates;
- unknown variants may be discarded by generated codecs;
- large snapshots and small lifecycle events share an awkward envelope;
- a single enum suggests stronger total ordering than providers can guarantee.

### Likely failure mode

The enum grows into a provider protocol mirror and makes every consumer recompile for unrelated artifact changes.

## Option C: typed multiplexed streams with snapshots and patches

Use a stable observation envelope whose payload is associated with an independently versioned stream schema.

```rust
pub struct StreamId {
    pub browsing_context: BrowsingContextId,
    pub document_epoch: DocumentEpoch,
    pub kind: CaptureStreamKind,
}

pub struct ObservationEvent {
    pub log_sequence: LogSequence,
    pub stream: StreamId,
    pub source_sequence: Observation<SourceSequence>,
    pub observed_at: CaptureOffset,
    pub source_timestamp: Observation<SourceTimestamp>,
    pub interaction_epoch: InteractionEpoch,
    pub payload: EncodedEventPayload,
}

pub struct EncodedEventPayload {
    pub schema: SchemaIdentity,
    pub bytes: Vec<u8>,
}
```

`EncodedEventPayload` illustrates an evolution boundary, not a recommendation that ordinary domain APIs expose untyped bytes. A decoding layer can produce family-specific Rust enums after checking `schema`.

### Optimizes for

- independent artifact-family evolution;
- preserving unknown payloads;
- live streaming and durable replay using the same envelope;
- filtering by stream before decoding payloads;
- binary framing and compression.

### Problems

- payload decoding can fail independently from envelope decoding;
- exhaustive matching moves from compile time to schema dispatch;
- more identities and validation rules are required;
- JSON representations become less natural if payload bytes are exposed directly.

### Likely failure mode

The opaque payload boundary becomes an excuse for arbitrary maps or undocumented provider blobs. Stable semantic stream schemas and typed decoding remain required.

## Option D: checkpoints and changes without a raw event log

Record periodic typed checkpoints and only the changes necessary to derive the next checkpoint.

```rust
pub enum StreamRecord<TSnapshot, TPatch> {
    Snapshot(TSnapshot),
    Patch(TPatch),
    Gap(StreamGap),
}

pub struct TreePatch {
    pub base_revision: StreamRevision,
    pub revision: StreamRevision,
    pub operations: Vec<TreePatchOperation>,
}
```

### Optimizes for

- reconstructing state at useful boundaries;
- avoiding noisy low-level provider events;
- compact tree and representation history;
- direct consumption by discovery agents.

### Problems

- projection and coalescing semantics become part of capture truth;
- raw evidence needed to debug a bad patch may be absent;
- not every stream has a meaningful snapshot;
- deriving patches may be more expensive than recording source events.

### Likely failure mode

A buggy or lossy projector creates authoritative-looking checkpoints that cannot be audited against retained observations.

## Recommended direction: layered hybrid of Options C and D

Use typed multiplexed observation streams as the durable temporal foundation, then derive checkpoints for agent consumption. Individual streams select their natural representation:

| Stream | Candidate representation |
| --- | --- |
| Network | Request lifecycle events plus optional body artifact references |
| DOM | Initial snapshot followed by ordered mutation batches or semantic patches |
| Accessibility | Snapshot plus diffs when stable node identity is available; otherwise repeated snapshots |
| Rendering | Lifecycle signals and references to visual frame artifacts |
| Source content | One-shot artifact observation |
| Agent actions | Immutable action markers and outcomes |
| Lifecycle | Small timestamped signals |

The log remains evidence. A checkpoint is a projection and identifies exactly which sequence range and stream revisions it covers.

## Time model

Record configured bounds, wall-clock correlation, and monotonic duration separately:

```rust
pub struct ObservationWindow {
    pub configured: ObservationBounds,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub elapsed: CaptureDuration,
}

pub struct ObservationBounds {
    pub maximum_elapsed: Observation<CaptureDuration>,
    pub maximum_events: Observation<EventCount>,
    pub maximum_bytes: Observation<ByteCount>,
}

pub struct CaptureOffset(u64); // Illustrative integer duration unit.
```

The eventual representation should document its unit in the type and wire schema, for example nanoseconds or microseconds. Avoid serializing floating-point seconds.

Important invariants:

```text
finished_at >= started_at
0 <= event.observed_at <= window.elapsed
configured bounds remain present even when not reached
elapsed comes from a monotonic clock, not wall-clock subtraction alone
```

A five-second and ten-second policy remain distinguishable through `configured.maximum_elapsed` even if each stops after one second.

## Ordering model

A single coordinator can assign ingestion sequence numbers, but ingestion order is not browser causality.

```rust
pub struct EventOrder {
    pub log_sequence: LogSequence,
    pub source_sequence: Observation<SourceSequence>,
    pub observed_at: CaptureOffset,
    pub source_timestamp: Observation<SourceTimestamp>,
}
```

The model can safely claim:

- total order of admission to this capture log;
- per-source ordering when supplied or reconstructed;
- association with an interaction epoch;
- observed temporal offsets.

It should not claim:

- that a DOM mutation with the next log sequence was caused by the preceding network event;
- that clocks from separate processes are exactly synchronized;
- that protocol arrival order equals browser execution order;
- that observations after an action were necessarily caused by that action.

If exact cross-process ordering becomes necessary, it needs explicit source identities, source-local sequence numbers, clock-correlation evidence, and uncertainty—not only a merged timestamp.

## Snapshot, patch, and gap model

Trees and other large stateful representations need revisions:

```rust
pub struct TreeSnapshot {
    pub revision: StreamRevision,
    pub root: TreeNode,
}

pub struct TreePatch {
    pub base_revision: StreamRevision,
    pub revision: StreamRevision,
    pub operations: Vec<TreePatchOperation>,
}

pub struct StreamGap {
    pub stream: StreamId,
    pub after_sequence: Observation<SourceSequence>,
    pub dropped_events: MeasuredCount<EventCount>,
    pub dropped_bytes: MeasuredCount<ByteCount>,
    pub reason: ReasonCode,
}

pub enum MeasuredCount<T> {
    Known(T),
    Unavailable { reason: ReasonCode },
}
```

A gap invalidates incremental reconstruction until the stream supplies a new complete snapshot. Unknown loss must not be serialized as `Known(0)`.

```text
snapshot revision 1
→ patch 1→2
→ patch 2→3
→ gap
→ patch 3→4       invalid: base is no longer trusted
→ snapshot 8      reconstruction becomes valid again
→ patch 8→9
```

## Signals are observations, not permanent states

Lifecycle and readiness signals can be modeled as timestamped records:

```rust
pub enum LifecycleSignal {
    FirstResponse,
    FirstPaint,
    DomContentLoaded,
    LoadEvent,
    QuietPeriodSatisfied(QuietPeriodEvidence),
    QuietPeriodInvalidated(QuietPeriodInvalidation),
    CandidateFieldObserved(CandidateFieldSignal),
}

pub struct QuietPeriodEvidence {
    pub policy: SettlementPolicyIdentity,
    pub quiet_since: CaptureOffset,
    pub satisfied_at: CaptureOffset,
    pub relevant_in_flight: ActivityCount,
}
```

A quiet-period signal can be true at one moment and invalidated by later activity. The model should say only that its declared condition was satisfied at `satisfied_at`.

A settlement policy must expose enough semantic parameters to validate its evidence. An opaque policy name alone is insufficient:

```rust
pub struct QuietPeriodPolicy {
    pub identity: SettlementPolicyIdentity,
    pub required_quiet: CaptureDuration,
    pub observed_signals: NonEmpty<SettlementSignalKind>,
    pub maximum_relevant_in_flight: ActivityCount,
    pub classification: ActivityClassificationIdentity,
}
```

The exact `NonEmpty` representation should remain concrete and dependency-free unless repeated need justifies an abstraction.

## Controller decisions and successful stopping

A future controller may choose among actions without mutating captured facts:

```rust
pub enum ObservationDirective {
    ObserveMore(AdditionalObservationBounds),
    CreateCheckpoint(CheckpointRequest),
    Interact(InteractionRequest),
    Finish(ControllerStopReason),
}

pub enum ControllerStopReason {
    GoalSatisfied,
    NoFurtherUsefulAction,
    PolicyDecision,
}
```

This reveals a possible missing CAS-294 outcome: the controller obtaining sufficient evidence is neither settlement nor interruption. Candidate terminal shapes follow.

### Termination Option 1: retain the ticket's five variants

```rust
pub enum CaptureTermination {
    Settled(SettlementEvidence),
    DeadlineReached(DeadlineEvidence),
    EventLimitReached(EventLimitEvidence),
    ByteLimitReached(ByteLimitEvidence),
    Interrupted(InterruptionEvidence),
}
```

Advantages:

- exactly follows the current ticket;
- small closed enum;
- sufficient for a collector whose only successful completion rule is settlement.

Problem:

- normal controller-directed completion has no truthful variant;
- treating it as `Interrupted` makes successful discovery look abnormal;
- treating it as `Settled` invents evidence.

### Termination Option 2: add controller completion (recommended)

```rust
pub enum CaptureTermination {
    ConditionSatisfied(ConditionSatisfiedEvidence),
    ControllerStopped(ControllerStopEvidence),
    DeadlineReached(DeadlineEvidence),
    EventLimitReached(EventLimitEvidence),
    ByteLimitReached(ByteLimitEvidence),
    Interrupted(InterruptionEvidence),
}

pub enum CompletionCondition {
    QuietPeriod(QuietPeriodEvidence),
    ContractSatisfied(ContractSatisfactionEvidence),
    Named(DeclaredConditionEvidence),
}
```

Advantages:

- separates an observed condition from the decision to stop;
- supports quiet-period completion without privileging it forever;
- represents successful multi-turn discovery honestly.

Risk:

- `Named` conditions can become an unvalidated extension escape hatch. If retained, they need stable identity, declared parameters, producer identity, and inspectable evidence.

### Termination Option 3: orthogonal stop initiator and stop trigger

```rust
pub struct CaptureTermination {
    pub initiator: TerminationInitiator,
    pub trigger: TerminationTrigger,
    pub completion: CompletionClassification,
}
```

Advantages:

- distinguishes who stopped from what was observed;
- can represent a controller stopping after a quiet signal or before settlement;
- avoids a growing cross-product enum.

Problems:

- permits contradictory combinations unless construction is carefully validated;
- pushes more invariants into runtime checks;
- less direct to pattern-match and explain.

Recommendation: begin with Option 2's closed semantic variants. Revisit orthogonal facets only after real outcomes demonstrate an unmanageable cross-product.

## Terminal accounting

Every terminal outcome should share a snapshot of activity and loss:

```rust
pub struct TerminalObservationState {
    pub observed_through: CaptureOffset,
    pub admitted_events: EventCount,
    pub retained_events: EventCount,
    pub dropped_events: MeasuredCount<EventCount>,
    pub retained_bytes: ByteCount,
    pub dropped_bytes: MeasuredCount<ByteCount>,
    pub in_flight: Vec<InFlightActivitySummary>,
    pub last_log_sequence: Observation<LogSequence>,
}
```

`in_flight` should distinguish total activity from settlement-relevant activity. Long-lived WebSockets, EventSource connections, polling, background frames, and service workers may be irrelevant to one quiet policy but remain real observed activity.

Limit outcomes carry the configured limit they reached. A generic reason code alone is not enough:

```rust
pub struct EventLimitEvidence {
    pub configured_limit: EventCount,
    pub terminal: TerminalObservationState,
}
```

## Does a limit stop observation or retention?

This requires an explicit policy decision.

### Option A: stop observation immediately (recommended initial behavior)

When a limit is reached, stop admission, finalize accounting, and terminate the window.

Advantages:

- simple bounded resource behavior;
- terminal cause is unambiguous;
- no false claim about later settlement;
- easiest invariants for the first schema.

### Option B: stop retaining but continue observing summaries

The provider continues counting or projecting activity without retaining individual events.

Advantages:

- may still detect quiet or contract satisfaction;
- can preserve low-cost aggregate evidence after detailed storage is exhausted.

Problems:

- "observed" and "retained" become different capability levels;
- settlement may rely on events unavailable for audit;
- requires separate resource bounds for summary observation;
- provider loss accounting may be incomplete.

If later required, model this as an explicit retention mode rather than silently changing event-limit semantics.

## Live checkpoints across turns

A checkpoint is a cursor-addressed projection:

```rust
pub struct ObservationCheckpoint {
    pub cursor: CaptureCursor,
    pub observed_through: CaptureOffset,
    pub interaction_epoch: InteractionEpoch,
    pub stream_revisions: Vec<StreamRevisionSummary>,
    pub lifecycle_signals: Vec<LifecycleSignalRef>,
    pub relevant_activity: ActivitySummary,
    pub requested_fields: Vec<FieldObservation>,
    pub loss: LossSummary,
}
```

Illustrative wire view:

```json
{
  "cursor": { "log_sequence": 923 },
  "observed_through_us": 840000,
  "interaction_epoch": 1,
  "signals": ["first_paint"],
  "requested_fields": {
    "advertisement_token": { "state": "candidate_observed" },
    "advertisement_url": { "state": "candidate_observed" }
  },
  "activity": {
    "relevant_in_flight": 0,
    "background_in_flight": 12
  },
  "loss": {
    "dropped_events": { "state": "known", "value": 0 }
  }
}
```

The next agent turn asks for observations after cursor `923`. The browser session and capture writer may remain active while checkpoints are created.

A checkpoint must never silently imply:

- that all streams are current to the same provider timestamp;
- that no later event will invalidate a candidate;
- that absent fields were observed to be absent;
- that capture has terminated.

## Interaction epochs

Agent actions should be part of the observation history:

```rust
pub struct InteractionEpochStarted {
    pub epoch: InteractionEpoch,
    pub action: AgentActionRef,
    pub started_at: CaptureOffset,
}

pub struct AgentActionResult {
    pub action: AgentActionRef,
    pub finished_at: CaptureOffset,
    pub outcome: AgentActionOutcome,
}
```

An epoch provides a useful grouping boundary:

```text
epoch 0: initial navigation
epoch 1: consent button clicked
epoch 2: advertisement scrolled into view
```

"Observed after" is not the same as "caused by." The model should use causal language only when the provider supplies evidence for it.

## Logical schema versus physical encoding

The Rust domain model, public JSON form, and efficient binary storage do not need to be identical.

### Option A: JSON events

Advantages:

- inspectable with ordinary tools;
- Serde support is direct;
- easiest golden fixtures and debugging.

Problems:

- repeated field names and string values are expensive;
- framing and append recovery need an additional convention;
- binary payloads require externalization or text encoding;
- parsing large logs allocates heavily.

JSON remains useful for manifests, terminal receipts, fixtures, and debugging views.

### Option B: CBOR or MessagePack frames

Advantages:

- mostly self-describing;
- maps naturally from Serde models;
- smaller than JSON;
- relatively easy implementation.

Problems:

- schema evolution rules remain project-defined;
- generic maps can weaken domain boundaries;
- not necessarily optimal for repetitive event streams.

Useful as a prototype if the first priority is validating the logical event model.

### Option C: versioned Protobuf-style frames plus Zstandard (recommended first benchmark)

Advantages:

- compact integer and enum representation;
- length-delimited framing is well understood;
- independent payload schemas can evolve;
- Zstandard should compress repeated URLs, names, and event shapes well;
- usable for both live transport and durable chunks.

Problems:

- generated code introduces tooling and dependency policy work;
- unknown fields are not automatically preserved by every implementation;
- canonical byte identity needs separate rules;
- direct domain types may need conversion to generated wire types.

Use a stable envelope with opaque payload bytes if preserving unknown event schemas is required. Do not assume a generated decoder will retain every unknown field.

### Option D: custom columnar or zero-copy format

Advantages:

- potentially best scan and compression performance;
- efficient source/time filtering;
- may avoid decoding unrelated payload columns.

Problems:

- substantial specification and maintenance burden;
- premature without representative captures and queries;
- awkward for heterogeneous event unions and live tailing;
- schema evolution and corruption recovery become wholly project-owned.

Defer until benchmarks show framed records are insufficient. Columnar projections can be derived later from the durable log for analytics.

## Candidate package layout

One possible durable package:

```text
capture/
  manifest.json
  events/
    000001.chunk.zst
    000002.chunk.zst
    000003.chunk.zst
  blobs/
    sha256-2f...
    sha256-b8...
  terminal.json
```

The manifest identifies the capture, schemas, environment, configured capabilities, time origin, and chunk set. Large response bodies, screenshots, and complete tree snapshots can be content-addressed blobs referenced by events.

Each independently decodable chunk can carry:

```rust
pub struct EventChunkHeader {
    pub format_version: EventLogFormatVersion,
    pub first_sequence: LogSequence,
    pub last_sequence: LogSequence,
    pub first_offset: CaptureOffset,
    pub last_offset: CaptureOffset,
    pub streams: Vec<StreamId>,
    pub uncompressed_bytes: ByteCount,
    pub checksum: ContentDigest,
}
```

Chunks provide:

- bounded writer memory;
- incremental upload and live tailing;
- corruption isolation;
- time/source indexes;
- recovery of committed prefixes after interruption;
- independent compression.

Exact chunk sizes and flush intervals are runtime and benchmarking decisions, not domain constants.

## Crash and interruption behavior

An interrupted process may leave valid committed chunks without a terminal footer. The package reader should distinguish:

```text
complete package with terminal receipt
incomplete package with explicit interrupted receipt
recoverable committed prefix without a receipt
corrupt or unverifiable chunk
```

A recovery tool may create a new provenance-bearing recovery artifact. It must not silently invent the missing original terminal facts.

## Backpressure and loss policy

A future runtime is likely to use bounded channels, but channel behavior must not define artifact semantics accidentally.

Candidate priorities:

- action, lifecycle, gap, and terminal records are never silently dropped;
- DOM mutations may be batched at browser-delivered batch boundaries;
- replaceable projections may be coalesced only under a declared policy;
- large bytes become artifact references;
- bulk observations may be dropped only when a gap and loss accounting are emitted;
- stopping admission and draining already-admitted events use an explicit bounded finalization phase.

If several terminal triggers are ready together, the domain needs deterministic precedence. `tokio::select!` polling order must not become the undocumented wire contract.

One candidate precedence is:

```text
corruption/provider failure
→ explicit controller cancellation
→ byte/event resource exhaustion
→ hard deadline
→ selected successful completion condition
```

This ordering is only a discussion point. Boundary tests must fix the selected semantics before runtime implementation.

## Proposed type boundaries for CAS-294

CAS-294 should stay narrower than the entire future event model. Candidate types for the ticket itself:

```text
CaptureDuration
CaptureOffset
ObservationBounds
ObservationWindow
QuietPeriodPolicy / SettlementPolicyIdentity
SettlementEvidence
MeasuredCount<T>
TerminalObservationState
CaptureTermination
CaptureTerminationError
```

Possible future tickets can own:

```text
stream and browsing-context identities
event envelope and schema registry
document/interaction epochs
network event payloads
DOM snapshot and patch payloads
accessibility snapshot and patch payloads
rendering and visual payloads
checkpoint projections
binary framing and compression
runtime coordinator and provider adapters
discovery recipe representation
```

CAS-294 should avoid adding placeholder payload enums for domains that have not yet been typed. It should define temporal and terminal primitives that those domains can compose later.

## Validation ideas

### Time and bounds

- zero-duration windows are either deliberately valid or rejected consistently;
- end before start is rejected;
- event offsets after terminal elapsed time are rejected;
- five-second and ten-second configured windows serialize differently;
- wall-clock duration disagreement does not overwrite monotonic elapsed duration;
- integer duration overflow is rejected.

### Settlement evidence

- quiet evidence shorter than the declared quiet period is rejected;
- relevant in-flight activity above the policy threshold rejects settlement;
- policy identity and evidence policy must agree;
- an invalidation after quiet satisfaction can exist if capture continued;
- settlement never implies absence of ignored background activity.

### Termination

- every terminal variant requires its variant-specific evidence;
- event-limit termination carries the reached event limit;
- byte-limit termination carries the reached byte limit;
- deadline termination carries the configured deadline;
- controller completion is not encoded as interruption;
- interrupted termination carries a secret-safe reason and initiator;
- unrelated limit fields do not imply that those limits were reached.

### Accounting

- retained events cannot exceed admitted events;
- known dropped counts participate in checked arithmetic;
- unavailable dropped counts remain distinct from zero;
- in-flight activity may be nonzero at deadline or interruption;
- loss affecting completion cannot be omitted;
- tree patches following a gap require a replacement snapshot.

### Serialization

- every outcome has a golden fixture;
- unknown fields follow the project's documented version policy;
- relative timestamps use one explicit integer unit;
- large counters round-trip without floating-point conversion;
- incomplete and complete package states remain distinguishable;
- binary corruption in one chunk does not validate as a complete capture.

## Decisions proposed for discussion

1. Treat global settlement as an optional observed condition, not the definition of usefulness.
2. Let an LLM or deterministic controller decide when available evidence satisfies a discovery goal.
3. Keep a capture session live across turns while returning immutable cursor-based checkpoints.
4. Model navigation and agent actions as interaction-epoch boundaries.
5. Use independently typed streams under a stable temporal envelope.
6. Use snapshots plus validated patches for stateful trees and explicit gaps after loss.
7. Record monotonic elapsed time and relative event offsets independently from UTC correlation timestamps.
8. Add a successful controller-directed terminal outcome rather than calling it settlement or interruption.
9. Initially let event and byte limits stop observation; defer lossy continued observation.
10. Keep the logical model independent of its wire encoding.
11. Prototype or benchmark framed binary records with per-chunk Zstandard before designing a custom format.
12. Externalize large bodies and visual artifacts as content-addressed blobs.

## Open questions

- Should CAS-294 add `ControllerStopped`, or should that belong to a later session/orchestration receipt?
- Is `Settled` retained as a dedicated outcome, or generalized to `ConditionSatisfied` with typed quiet-period evidence?
- Which clock and integer unit should `CaptureOffset` use on the wire?
- Does the initial model need per-stream in-flight accounting or only aggregate classified counts?
- Are DOM and accessibility changes stored as provider events, semantic patches, repeated snapshots, or a combination?
- What stable identities are available for DOM and accessibility nodes across revisions?
- Can one capture session contain multiple `CaptureReceipt`s, or does each bounded segment receive a fresh `CaptureId`?
- Does creating a checkpoint produce an artifact, an ephemeral API value, or both?
- Which observations must survive every retention policy?
- What is the first representative capture corpus for measuring event rate, compression ratio, patch cost, and agent query patterns?
- Should contract satisfaction become a general activity outcome, a capture termination condition, or recipe-layer evidence?

## Recommended next design experiment

Before implementing a collector or selecting a permanent binary dependency:

1. hand-author one small logical event sequence containing navigation, network activity, first paint, DOM and accessibility changes, an agent action, a quiet signal, and controller completion;
2. include one dropped-event gap and recovery snapshot;
3. represent two agent checkpoints over the sequence;
4. encode the same fixture as JSON, CBOR, and framed Protobuf-style records;
5. compress each representation with Zstandard;
6. compare uncompressed size, compressed size, decode allocations, partial-tail recovery, and ease of inspecting unknown payloads;
7. use the fixture to test whether the proposed CAS-294 terminal types can describe the sequence without depending on event payload internals.

The experiment is reversible and will expose missing semantics before a runtime architecture hardens them.

## Research precedents

The following systems solve useful parts of the problem but do not define Yosoi's contract:

- [Chrome DevTools Protocol Network domain](https://chromedevtools.github.io/devtools-protocol/tot/Network/) exposes request lifecycle events, monotonic timestamps, resource types, long-lived connections, and encoded byte counts.
- [Chrome DevTools Protocol Tracing domain](https://chromedevtools.github.io/devtools-protocol/tot/Tracing/) exposes buffer usage and reports whether trace data was lost.
- [WARC 1.1](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/) records explicit `length`, `time`, `disconnect`, and `unspecified` truncation reasons while retaining actual stored length.
- [HAR](https://w3c.github.io/web-performance/specs/HAR/Overview.html) combines absolute start timestamps with relative elapsed timings and explicit unavailable timing values.
- [OpenTelemetry trace protocol](https://github.com/open-telemetry/opentelemetry-proto/blob/main/opentelemetry/proto/trace/v1/trace.proto) records timestamped events and dropped-event counts.
- [libpcap capture statistics](https://www.tcpdump.org/manpages/pcap_stats.3pcap.html) distinguish capture-buffer and interface drops while warning that platform support and zero values can be ambiguous.
- [ReactiveX debounce](https://reactivex.io/documentation/operators/debounce.html) demonstrates quiet-period semantics that can be postponed forever by continued activity.
- [Tokio `select!`](https://tokio.rs/tokio/tutorial/select) and [`timeout`](https://docs.rs/tokio/latest/tokio/time/fn.timeout.html) are plausible future runtime tools, but their cancellation and polling behavior must not implicitly define serialized outcomes.

These precedents support a bounded append-only log, explicit loss, relative timing, typed terminal causes, and separation between runtime control and durable evidence. They do not answer the product-level question of when an agent has enough evidence; that decision belongs to discovery or recipe execution above the capture model.
