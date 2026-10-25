---
title: Surfaces
description: Reference scopes, budgets, cursor ownership, and provider capabilities in Rust and Python.
---

# Surfaces

Use `ys::Surface` in Rust (`use yosoi as ys`) and `ys.Surface` in Python (`import yosoi as ys`). Both use the Rust index and providers. Start with [Surfaces](../concepts/surfaces.md) for documents, video and an agent-driven CLI task.

## Choose the reader

| Reader       | Input                           | Supported operations                                         |
| ------------ | ------------------------------- | ------------------------------------------------------------ |
| Surface      | Any of the six Document classes | Overview, expand, literal find, inspect, parent, coordinates |
| WebSurface   | Prepared HTML or rendered DOM   | Shared describe/read protocol, including search and parent   |
| VideoSurface | Frozen regular local video file | Shared timeline reads, temporal addresses, frame and crop    |

`Surface::from_image` in Rust and `Surface.from_image` in Python prepare PNG/JPEG pixels as a region tree. They do not perform OCR or apply EXIF rotation. `combine` joins named independently captured views without claiming an atomic observation. Keep each constituent reference when projecting between views.

Rust video requires `surface-video`; images require `surface-images` or `browser`. Standard Python builds enable browser and video support. FFmpeg and FFprobe remain external requirements for opening and decoding video. Immutable document reads need neither browser nor decoder.

## Keep reference types distinct

| Meaning                         | Rust                                | Python                      |
| ------------------------------- | ----------------------------------- | --------------------------- |
| Document-index address          | `surface::Reference`                | `surface.NativeReference`   |
| Shared observation/address pair | `surface::model::Reference`         | `surface.Reference`         |
| Native index continuation       | `surface::Continuation`             | `surface.Continuation`      |
| Shared opaque continuation      | `surface::model::ContinuationToken` | `surface.ContinuationToken` |

Native references bind a capture and node. Shared references bind an ObservationId and producer-issued address. WebSurface converts between its own native and shared references; it rejects references belonging to another observation or source binding. Do not parse address spelling, manufacture a replacement ID, or treat an old reference as a durable entity identifier.

SourceId, SurfaceId, ObservationId, AddressToken, and ContinuationToken validate through Rust in both SDKs. They allow 1 through 1,024 UTF-8 bytes without control characters. Python represents diagnostic CursorId and WatchId values as checked integer aliases; the integers carry no owned cursor or action permit.

## Bound preparation and replies

Limits controls input bytes, node count, tree depth, and automatic overview depth. Budget controls the complete serialized result's UTF-8 bytes and routing entry count. The defaults are 8 MiB of document input, 200,000 nodes, depth 96, overview depth 6, and 4,096 reply bytes with 20 entries.

The shared read protocol accepts byte budgets from 512 through 65,536. The CLI separately reserves its outer transport envelope and supports reply budgets from 1,024 through 16,384. A useful item that cannot fit produces an explicit error.

Copy continuations into the same operation with the same reference and query. Inspection chunks are UTF-8 aligned; assemble every chunk before parsing complete JSON. Coverage describes retained source evidence, while `next` describes pagination. Byte bounds do not establish a tokenizer-independent token count.

## Coordinate a cursor

Session is a coordinator for an external capture/control adapter. It does not open a browser, start an observer, or dispatch a click. The [Surface CLI](../cli/surface.md) supplies a live browser adapter; immutable WebSurface and VideoSurface readers remain non-controllable.

| State       | Meaning                                                                                                                        |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Detached    | The adapter is not attached and cannot acquire hot authority. Retained immutable evidence can still be read.                   |
| Live reader | The adapter has attached. The cursor can navigate and hold regional watches without action ownership.                          |
| Hot cursor  | One cursor owns the action slot. Its permit still needs current complete evidence and the provider's final eligibility checks. |

Create Session from an index and SessionPolicy, then allocate cursors with `cursor`. The policy defaults to one cursor, eight watches, two retained captures, and 128 events. Raising cursor capacity permits independent reader positions; it does not create multiple hot owners.

An adapter calls `attach` when it can observe its source, `invalidate` when observation is pending or uncertain, `publish` with a new immutable index, and `detach` when observation ends. Detach revokes hot authority. These calls describe actual adapter lifecycle; setting a flag is not evidence that an external subscription exists.

`subscribe` registers a logical watch on exact captured evidence. Publishing marks watches for reconciliation. `reconcile` compares a caller-selected replacement region and reports Changed, Unchanged, or Unknown. It does not locate the replacement automatically, observe arbitrary application memory, or infer that two regions are the same entity. An event batch reports `lost` when bounded history has evicted unread events.

## Finish actions explicitly

After `focus` and `promote`, `begin_action` creates one owned ActionLease. The adapter checks current visibility and eligibility, then calls `revalidate` immediately before a native effect. `mark_dispatched` records that an effect may have begun. It does not mean the task succeeded.

Finish with Confirmed only after dispatch and an observed postcondition. Rejected is allowed only before dispatch. Use Unconfirmed when dispatch or its outcome is uncertain. Dropping an unfinished lease records abandonment or uncertainty instead of inventing success.

Python supports `with` for Cursor and ActionLease. Close the lease before closing its cursor; an in-flight action prevents cursor closure and hot handoff. Rust Cursor clones share one logical position and must be closed explicitly. Serialized state and receipts cannot reconstruct owned runtime permits.

## Retain evidence

Archive the original Document to reconstruct a document index after the source closes. VideoSurface and DecodedFrame expose `write_to` and `read_from` through the existing Archive backend. A saved video restores its timeline without probing; decoding a new frame still needs a compatible decoder. A saved frame restores actual verified PNG bytes without the source or decoder.

Video timestamps use microseconds relative to primary stream start. FrameInfo retains the requested position and measured source PTS separately. PixelRect uses the full decoded canvas, which may have been downscaled. Video coverage remains partial because this provider does not observe audio, OCR, transcription, or every frame eagerly.

Python document navigation and shared read calls release the GIL. Async video and Archive methods execute on the native runtime; cancelled Python awaits can leave Rust completing bounded cleanup. Keep live-source lifecycle in the owning adapter and preserve uncertainty when execution is interrupted.
