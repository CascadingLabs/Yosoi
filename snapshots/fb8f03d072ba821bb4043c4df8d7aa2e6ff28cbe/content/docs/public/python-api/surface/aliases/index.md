---
title: "Aliases"
description: "Aliases declared in yosoi.surface."
order: 0
---

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
