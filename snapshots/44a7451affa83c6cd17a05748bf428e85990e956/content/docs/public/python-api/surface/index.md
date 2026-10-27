---
title: "yosoi.surface"
description: "Public declarations in yosoi.surface."
order: 0
---

`yosoi.surface`

Bounded evidence navigation over Rust-owned immutable surfaces.

Document and video readers never grant browser control. Native references and
shared references are distinct types; continuations stay bound to their original
observation and operation. Video processing requires the surface-video wheel
feature and local FFmpeg/FFprobe executables.

Shared identity and token types accept 1–1,024 UTF-8 bytes with no control
characters. Their spelling is opaque and does not establish cross-capture entity
identity or permission to act.

[Source: python/yosoi/surface.py:1](https://github.com/CascadingLabs/Yosoi/blob/44a7451affa83c6cd17a05748bf428e85990e956/python/yosoi/surface.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`ActionLease`](/yosoi/python-api/surface/types/action-lease/) | Owned one-action permit. Dropping or closing it preserves uncertain dispatch. |
| [`ActionReceipt`](/yosoi/python-api/surface/types/action-receipt/) | Adapter-reported outcome preserving dispatch uncertainty separately. |
| [`AddressToken`](/yosoi/python-api/surface/types/address-token/) | Producer-issued opaque address bound to its accompanying observation. |
| [`ArchiveLimits`](/yosoi/python-api/surface/types/archive-limits/) | Retention bounds separate from live history and response budgets. |
| [`ArchivedSource`](/yosoi/python-api/surface/types/archived-source/) | Exact source bytes and interpretation, independent of a source file path. |
| [`BrowserSurface`](/yosoi/python-api/surface/types/browser-surface/) | An isolated live browser with source-specific actions and archive support. |
| [`Budget`](/yosoi/python-api/surface/types/budget/) | Bounds on the complete Rust JSON result, before a transport envelope. |
| [`Capability`](/yosoi/python-api/surface/types/capability/) | Advertised operation with explicit read or control access. |
| [`Continuation`](/yosoi/python-api/surface/types/continuation/) | Opaque native-index continuation. Copy it unchanged into the same read. |
| [`ContinuationToken`](/yosoi/python-api/surface/types/continuation-token/) | Producer-issued opaque continuation bound to a read, scope and observation. |
| [`Coordinate`](/yosoi/python-api/surface/types/coordinate/) | Representation-specific locator coordinates retained by the index. |
| [`Coverage`](/yosoi/python-api/surface/types/coverage/) | Source completeness, independent of how many entries fit on a page. |
| [`Cursor`](/yosoi/python-api/surface/types/cursor/) | Owned navigation cursor. Close it to release watches and hot authority. |
| [`CursorState`](/yosoi/python-api/surface/types/cursor-state/) | Observable cursor status, never a transferable control capability. |
| [`DecodedFrame`](/yosoi/python-api/surface/types/decoded-frame/) | Immutable Rust-owned PNG evidence, restored without a decoder when archived. |
| [`Descriptor`](/yosoi/python-api/surface/types/descriptor/) | Continuing source representation and the operations it actually supports. |
| [`Entry`](/yosoi/python-api/surface/types/entry/) | Representation-neutral hint for choosing the next region to inspect. |
| [`Event`](/yosoi/python-api/surface/types/event/) | One retained event with optional cursor, watch and reference provenance. |
| [`EventBatch`](/yosoi/python-api/surface/types/event-batch/) | Unread bounded session history with an explicit missed-events flag. |
| [`Expand`](/yosoi/python-api/surface/types/expand/) | Request direct structural or temporal children of exact evidence. |
| [`FrameArchiveRef`](/yosoi/python-api/surface/types/frame-archive-ref/) | Normal Archive Document retaining actual PNG bytes and FrameInfo. |
| [`FrameInfo`](/yosoi/python-api/surface/types/frame-info/) | Actual PNG provenance, separating requested time from measured source PTS. |
| [`ImageCrop`](/yosoi/python-api/surface/types/image-crop/) | Actual PNG evidence cropped from an indexed immutable image region. |
| [`IndexMetadata`](/yosoi/python-api/surface/types/index-metadata/) | Preparation summary, not a current live-source status. |
| [`Inspect`](/yosoi/python-api/surface/types/inspect/) | Request source-backed text detail, possibly split across chunks. |
| [`Inspection`](/yosoi/python-api/surface/types/inspection/) | Shared source-backed text fragment; it may be incomplete serialized JSON. |
| [`InspectionResult`](/yosoi/python-api/surface/types/inspection-result/) | Tagged shared detail result. |
| [`Limits`](/yosoi/python-api/surface/types/limits/) | Task-independent document preparation bounds, enforced by Rust. |
| [`NativeEntry`](/yosoi/python-api/surface/types/native-entry/) | One structural routing hint backed by document evidence. |
| [`NativeInspection`](/yosoi/python-api/surface/types/native-inspection/) | Source-backed detail chunk; concatenate all chunks before parsing JSON. |
| [`NativePage`](/yosoi/python-api/surface/types/native-page/) | A bounded document-index window with explicit paging and coverage. |
| [`NativeReference`](/yosoi/python-api/surface/types/native-reference/) | Exact document-index address; it does not grant action permission. |
| [`Observation`](/yosoi/python-api/surface/types/observation/) | One immutable interpretation of a continuing surface. |
| [`ObservationId`](/yosoi/python-api/surface/types/observation-id/) | Rust-validated identity of one immutable interpretation. |
| [`Outcome`](/yosoi/python-api/surface/types/outcome/) | Portable evidence and receipts, without live session or action authority. |
| [`OutcomeRef`](/yosoi/python-api/surface/types/outcome-ref/) | Typed immutable reference selecting an outcome through Archive.read. |
| [`Overview`](/yosoi/python-api/surface/types/overview/) | Request a bounded set of routing regions. |
| [`Page`](/yosoi/python-api/surface/types/page/) | Shared bounded region window; coverage and pagination are independent. |
| [`PageResult`](/yosoi/python-api/surface/types/page-result/) | Tagged shared routing result. |
| [`Parent`](/yosoi/python-api/surface/types/parent/) | Request a structural parent where that relation is supported. |
| [`ParentResult`](/yosoi/python-api/surface/types/parent-result/) | Tagged parent result; a root has no parent. |
| [`PixelRect`](/yosoi/python-api/surface/types/pixel-rect/) | Crop in full decoded-frame pixels; source-video dimensions may differ. |
| [`Position`](/yosoi/python-api/surface/types/position/) | Saved navigation state without granting live access or control. |
| [`ReadRequest`](/yosoi/python-api/surface/types/read-request/) | One shared request passed unchanged to either Rust-backed reader. |
| [`Reference`](/yosoi/python-api/surface/types/reference/) | Representation-neutral evidence address, scoped to one observation. |
| [`Search`](/yosoi/python-api/surface/types/search/) | Request literal search when advertised by this representation. |
| [`Session`](/yosoi/python-api/surface/types/session/) | In-memory evidence session for an external live adapter. |
| [`SessionPolicy`](/yosoi/python-api/surface/types/session-policy/) | Bounds for in-memory readers, subscriptions, history and one hot owner. |
| [`SourceId`](/yosoi/python-api/surface/types/source-id/) | Rust-validated opaque source identity, without access or control authority. |
| [`SourceInterpretation`](/yosoi/python-api/surface/types/source-interpretation/) | Interpreter for an exact document, image or named observation bundle. |
| [`SourceReference`](/yosoi/python-api/surface/types/source-reference/) | Binding from a combined index to one original independently captured view. |
| [`Surface`](/yosoi/python-api/surface/types/surface/) | Reusable immutable index of any supported Document class. |
| [`SurfaceConnection`](/yosoi/python-api/surface/types/surface-connection/) | Shared lifecycle for a source-specific browser or video connection. |
| [`SurfaceId`](/yosoi/python-api/surface/types/surface-id/) | Rust-validated identity of a continuing representation of one source. |
| [`SurfacePolicy`](/yosoi/python-api/surface/types/surface-policy/) | Evidence retention and output bounds shared across source connections. |
| [`SurfaceRead`](/yosoi/python-api/surface/types/surface-read/) | Common pure reading contract; frame decoding and effects are capabilities. |
| [`VideoArchiveRef`](/yosoi/python-api/surface/types/video-archive-ref/) | Normal Archive Document retaining source bytes and interpretation profile. |
| [`VideoMetadata`](/yosoi/python-api/surface/types/video-metadata/) | Primary video stream metadata captured from the frozen source. |
| [`VideoPolicy`](/yosoi/python-api/surface/types/video-policy/) | Snapshot and decoder limits. Rust validates the supported combinations. |
| [`VideoSession`](/yosoi/python-api/surface/types/video-session/) | Read-only stateful exploration around a frozen VideoSurface. |
| [`VideoSurface`](/yosoi/python-api/surface/types/video-surface/) | Frozen local video with a lazy timeline and read-only frame capabilities. |
| [`WatchState`](/yosoi/python-api/surface/types/watch-state/) | One explicit subscription to captured regional evidence. |
| [`WebSurface`](/yosoi/python-api/surface/types/web-surface/) | Shared read protocol over an immutable HTML or rendered-DOM index. |

## Functions

| Name | Summary |
| --- | --- |
| [`export`](/yosoi/python-api/surface/functions/export/) | Package a saved handle into one immutable portable flat file through Rust. |
| [`replay`](/yosoi/python-api/surface/functions/replay/) | Reconstruct a saved handle or portable file without live source processes. |
| [`rerun_browser`](/yosoi/python-api/surface/functions/rerun-browser/) | Rerun a sealed browser recipe with explicit source display selection. |

## Aliases

| Name | Summary |
| --- | --- |
| [`Access`](/yosoi/python-api/surface/aliases/access/) | Whether a capability only reads evidence or may change an external source. |
| [`ActionStatus`](/yosoi/python-api/surface/aliases/action-status/) | Adapter-reported outcome, kept distinct from whether dispatch occurred. |
| [`ArchivePolicy`](/yosoi/python-api/surface/aliases/archive-policy/) | Whether a session retains a bounded portable outcome for explicit Archive saving. |
| [`CursorId`](/yosoi/python-api/surface/aliases/cursor-id/) | Session-local diagnostic integer. A copied ID never grants cursor authority. |
| [`EventKind`](/yosoi/python-api/surface/aliases/event-kind/) | Observed session transition; application memory is outside this evidence. |
| [`ExecutionError`](/yosoi/python-api/surface/aliases/execution-error/) | Shared runtime preparation, execution, retention or cleanup failure. |
| [`Freshness`](/yosoi/python-api/surface/aliases/freshness/) | Evidence status relative to the session, independent of action eligibility. |
| [`ReadOperation`](/yosoi/python-api/surface/aliases/read-operation/) | Tagged navigation operation; capabilities determine which variants are supported. |
| [`ReadResult`](/yosoi/python-api/surface/aliases/read-result/) | Tagged result of a shared read. Contains evidence, never action authority. |
| [`SurfaceError`](/yosoi/python-api/surface/aliases/surface-error/) | Rust preparation, reference, budget or authority failure with Rust metadata. |
| [`VideoError`](/yosoi/python-api/surface/aliases/video-error/) | Native video I/O, decoder, timeout, bounds or missing-frame failure. |
| [`WatchId`](/yosoi/python-api/surface/aliases/watch-id/) | Session-local subscription integer, checked against the owning Rust cursor. |
