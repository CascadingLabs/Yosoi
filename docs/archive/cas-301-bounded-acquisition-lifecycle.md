# CAS-301 bounded acquisition lifecycle

`AcquisitionLifecycle` is a synchronous, provider-independent linearization boundary for one resolved Direct HTTP attempt. The caller injects wall-clock timestamps, monotonic capture offsets, producer events, and final evidence. It performs no HTTP, async scheduling, persistence, or publication.

## State and admission

A lifecycle is either running or terminal. While running, offsets must be monotonic. A `LifecycleEvent` separately declares bytes admitted from the producer, bytes retained as evidence, and whether the event itself was retained. Construction rejects retained bytes greater than admitted bytes.

Admission updates four independent checked counters: admitted events, retained events, admitted bytes, and retained bytes. An event that crosses the byte bound atomically admits only the remaining bounded byte extent; its retained extent is capped to that admitted portion. The returned `AdmittedEvent` exposes these exact facts through `admitted_bytes()`, `retained_bytes()`, and `is_event_retained()` while keeping its representation private. Counters never exceed a configured bound.

Bounds are inclusive: equality terminates the attempt. If an admission simultaneously reaches the event bound and byte bound, `EventLimitReached` has deterministic precedence. A deadline-offset event is not admitted and returns `NotAdmittedAndStopped(DeadlineReached)`. Once terminal, all clock, admission, and explicit-stop operations return `AlreadyStopped`.

## Offsets and terminal precedence

Deadline comparison precedes event accounting. Deadline stops are linearized exactly at `maximum_elapsed`, even when the offered clock is later. Every finalization terminal offset must equal the lifecycle's linearized stop offset: exactly the deadline for deadline termination, and exactly the explicit/event/byte stop offset for all other reasons. A terminal offset behind the observed offset is diagnosed separately.

## Final accounting

Finalization constructs `EventAccounting` and `ByteAccounting` from the independently tracked admitted and retained totals plus the caller's dropped counts. `Known(0)` is distinct from unavailable loss. Known loss must exactly satisfy `retained + dropped == admitted`; overflow and mismatches remain typed nested accounting errors. `Unavailable` preserves its reason without inventing a count.

## Finalization chain

Finalization consumes the lifecycle. Before building output it verifies that `manifest.requests` exactly equals the resolved specification. When source artifacts are produced, at least one must use the declared base representation schema; additional source-family artifacts may use the declared Unicode schema when Unicode retention is enabled. Every produced network artifact must use the declared network schema. Explicit unavailable or otherwise absent-family results do not invent receipt outputs.

After these checks, the lifecycle validates the observation snapshot, derives receipt outputs from the manifest, validates the activity receipt, capture receipt, acquisition record, complete `WebCapture` aggregate (identity, resolution, environment, capabilities, relationships, and output set), and finally the payload `CaptureBundle`. Source capture identity, producer, operation, and observation policy are preserved from the resolved spec. Payload attachment is deliberately the last construction step, and publication occurs only after the bundle validates the complete chain.

## Errors and publication

Malformed events, manifest/spec mismatch, output-schema mismatch, accounting disagreement, invalid wall clocks, invalid acquisition or aggregate facts, and nested bundle failures are explicit `LifecycleError` variants with their typed sources preserved. Bundle validation rejects missing, wrong-size, wrong-digest, foreign, orphaned, discarded, or unavailable payloads. Because finalization consumes staged state and returns a bundle only after exhaustive validation, no partial capture or payload collection is published on error.
