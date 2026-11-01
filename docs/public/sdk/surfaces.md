---
title: Surfaces
description: Reference scopes, image pixels, budgets, cursor ownership, and provider capabilities in Rust and Python.
---

# Surfaces

Use `ys::Surface` in Rust (`use yosoi as ys`) and `ys.Surface` in Python (`import yosoi as ys`). Both use the Rust index and providers. `ImageSurface` applies the shared bounded read contract to a typed image. Start with [Surfaces](../concepts/surfaces.md) for documents, images, video and an agent-driven CLI task.

`ImageSurface` and `PixelArtifact` are available in this source revision. The published 0.4.0 package does not include the typed image reader yet.

Browser, image and video adapters own their source behavior. Stateful connections share `SurfaceConnection` for ready, execute, outcome and close. The `surface-connections` feature enables `BrowserSurface` and `VideoSession`; the CLI also enables typed image sessions. Browser display mode, image pixel bounds, and video frame bounds remain source-specific rather than generic Surface policy fields.

## Choose the reader

| Reader       | Input                                    | Supported operations                                                             |
| ------------ | ---------------------------------------- | -------------------------------------------------------------------------------- |
| Surface      | Any of the six Document classes          | Overview, expand, literal find, inspect, parent, coordinates                     |
| ImageSurface | Typed PNG/JPEG ImageDocument             | Shared overview, expand, inspect and parent, plus direct, overview, resize, crop |
| WebSurface   | Any of the six prepared Document classes | Shared describe/read protocol: overview, expand, search, inspect, parent         |
| VideoSurface | Frozen regular local video file          | Shared timeline reads, temporal addresses, frame and crop                        |

`BrowserSurface`, `ImageSession`, and `VideoSession` own their source-specific execution. Rust shares the `SurfaceConnection` trait; Python shares the `SurfaceConnection` base class for web and video connections. Send bounded JSON commands and await `close` for cleanup and retained evidence. `SurfacePolicy` selects archive retention and output locations. Browser display mode, image pixel limits, and video frame size belong to their respective open factories. `Outcome.rerun` executes a supported confirmed procedure against fresh sources; saved evidence never restores action authority.

WebSurface preserves each Document's native meaning while exposing the same
five read operations:

| Document profile   | Shared representation   | Preserved meaning                                      |
| ------------------ | ----------------------- | ------------------------------------------------------ |
| Source HTML        | `yosoi.web.document.v1` | HTML5 normalization                                    |
| Source XML         | `yosoi.web.xml.v1`      | Namespace-aware names and exact source ranges          |
| Source JSON        | `yosoi.web.json.v1`     | JSON scalar types; duplicate keys are rejected         |
| Source text        | `yosoi.web.text.v1`     | Exact UTF-8 source ranges                              |
| Rendered DOM       | `yosoi.web.document.v1` | Snapshot-local node identities and document epoch      |
| Accessibility tree | `yosoi.web.ax.v1`       | Snapshot-local identities, epoch and declared coverage |
| Network window     | `yosoi.web.network.v1`  | Bounded event window with incomplete coverage          |

All immutable readers advertise only read capabilities and set `controllable`
to false. A live browser binding may add actions to its own descriptor after it
owns the browser Work. An archived or source-file WebSurface never becomes a
browser action target.

## Images and pixel artifacts

`ImageDocument` owns the exact encoded PNG/JPEG bytes and source metadata.
`Surface::from_image_document` in Rust and `Surface.from_image(ImageDocument)`
in Python prepare bounded region metadata. `ImageSurface::from_image_document`
in Rust and `ys.ImageSurface(image)` in Python also bind that index to the
shared `model::SurfaceRead` contract. Its source identity uses the document ID
and exact payload SHA-256, independent of tile size or other preparation
options.

For direct delivery without an index, use
`PixelArtifact::decode_image_document(document, limits)` in Rust or
`PixelArtifact.from_image_document(image, limits=...)` in Python. Both fully
decode under PixelLimits to verify dimensions and allocation, then retain the
original encoded bytes.

`Surface::from_image` and `Surface.from_image(bytes)` remain legacy byte-entry
points. New code should pass a typed `ImageDocument`; archived legacy image
envelopes continue to restore through their stored image interpretation.

PNG/JPEG decoding keeps the original encoded bytes. Image coordinates refer to
the encoded raster before EXIF rotation; orientation is recorded as
`exif_unapplied`. No OCR, inferred labels or text search runs. The reader
advertises no search capability.

`ImageSurface.read` returns bounded routing metadata through the same overview,
expand, inspect, parent and continuation types as web and video readers. Pixel
bytes use explicit `direct_image`, `overview_image`, `resize_image` and
`crop_rect` calls. `direct_image` returns exact source bytes. Overview and resize
encode PNG using the versioned triangle filter. A crop takes original-raster
coordinates, even when its rectangle was selected from a resized overview.

`PixelArtifactInfo` records the exact encoded digest and MIME type, output
dimensions, root source identity and coordinate space, orientation handling,
parent artifact identity/digest/dimensions, operation version and parameters,
and a rational output-edge-to-parent-edge transform.
`PixelArtifact.map_rect_to_source` maps a rectangle from an overview back to the
root source pixel plane. Crop and resize APIs reject nested derived artifacts
so an ambiguous transform cannot be silently composed.

Pass a root video-frame or browser-screenshot artifact to
`ImageSurface::from_pixel_artifact` in Rust or
`ImageSurface.from_pixel_artifact` in Python to inspect its regions offline.
This retains its native source identity and decoded-canvas coordinates. Derived
crops and overviews cannot be re-rooted; map their region to the original source
first.

Legacy frame envelopes that lack a typed video source ID retain an explicit
partial `LegacyVideoFrame` identity with the observation, frame reference,
requested time, measured PTS, and source digest only when recorded. They do not
invent a VideoDocument identity.

`PixelLimits` separately bounds decoded side length, decoder allocation, output
pixels, output bytes and a reader's retained artifact count. `Surface`
response-byte and text-page budgets do not count binary pixels. `Archive.write(&pixel)`
stores an `ImageDocument` in the existing raw media payload store and a small
provenance record. `Archive.read` verifies both and returns the same artifact
without a source path or video decoder.

Rust video requires `surface-video`; images require `surface-images` or
`browser`. Standard Python builds enable browser and video support. FFmpeg and
FFprobe remain external requirements for opening and decoding video. Immutable
image and document reads need neither browser nor video decoder.

## Bind an existing native browser

Use `surface::consume_session(browser.clone(), policy)` in Rust or
`await surface.consume_session(browser, policy)` in Python to observe the initial
tab of an acquired native browser Session. The browser-specific constructor is
`BrowserSurface::consume_session` / `BrowserSurface.consume_session`. These calls
acquire that tab's native Work lease and retain its existing Session owner;
they do not launch ChromeDriver or another browser.

The browser facade exposes the same function as
`browser::surface::consume_session` in Rust and `browser.surface.consume_session`
in Python. All spellings use the same native adapter.

If Work is already held, transfer it with `BrowserSurface::consume_work` /
`BrowserSurface.consume_work`. Rust can select an existing `Tab` with
`BrowserSurface::consume_tab(&tab, policy)` or transfer `tab.work().await?`.
Python currently exposes consumption of its initial-tab Work, not explicit tab
creation. A transferred Work cannot be used by its previous owner.

Native policy, per-tab control, shared execution capacity and cancellation remain
authoritative. Event-driven Surface waits retain tab control and can yield the
worker permit when `yield_on_wait` is enabled. Surface cursors still require
attach and hot ownership before effects; cooling or detaching a cursor does not
release the binding's physical Work lease.

Close the Surface to release Work. The Session and tab remain caller-owned, so
keep the browser owner open during use and close it explicitly afterward.
Observation records retain the native Session/tab/document identity. Surface's
positive capture sequence is a separate clock from the native document epoch,
which can be zero before the first navigation. A native binding's
release receipt reports Work release rather than claiming browser shutdown.
Offline evidence replay remains available. Generic fresh-browser rerun rejects
native bindings because it cannot recreate the caller's native Session policy;
acquire a fresh native Session explicitly when executing the workflow again.

This consumed backend supports regular native Chrome with DOM, AX and opt-in
network observation, plus native input, navigation and screenshots. Its
descriptor advertises `network` only for the qualified Chrome CDP provider.
BiDi and the isolated `open(url, ...)` provider do not expose network event
subscriptions; the isolated provider remains DOM-only.

## Capture a network window

Call `BrowserSurface.subscribe_network` on a consumed native Session before the
page action whose requests you want to inspect. `observe_network` freezes the
events received since the prior window and returns both its shared observation
address and typed `NetworkWindow`. Read the event metadata with the same
overview, expand, search and inspect protocol used by other `WebSurface`
documents. Window references remain bound to their own session, tab and
observation; a body link can refer to a response in an earlier window.

`SurfacePolicy.network_observation` bounds subscription lifetime, journal
events and bytes, provider queues, frozen window history, response body count
and body bytes independently. Defaults allow 2,048 retained events in a
five-minute subscription, a 256-event listener queue, 2 MiB of event metadata,
32 frozen windows, up to 16 response bodies at 1 MiB each and 8 MiB total, and
no body retention. The Page-level CDP provider buffers are shared by all
Requests and Surface users and remain capped at 8 MiB per resource and 8 MiB
aggregate, even when this subscription does not retain bodies. The window
records those provider caps separately from the caller's body-retention limits.
The initial body count and total byte limits also cap retained bodies across
the Surface session. Rearming a subscription does not reset these caps.
Cancelling preserves bodies linked by kept windows. Evicting their last window
or closing the Surface invalidates those live references. Retention receipts
report the fixed session caps separately from each subscription's limits.
Network document capture uses the separate `documents.network` policy; its
default retained input is 8 MiB and a shared read response defaults to 65,536
bytes.

The default URL policy keeps the origin and removes path, query and fragment.
Set `retain_url_path` or `retain_url_query` to include those parts. The header
allowlist defaults empty; authorization, proxy-authorization, cookie, set-cookie
and API token headers are always excluded. Exact origin and method filters are
available in `allowed_origins` and `allowed_methods`. Content-Type and
content-encoding are recorded separately as response media provenance; they do
not admit other headers into the window.

Response bodies require explicit opt-in through `subscribe_network` or
`network_observation.retain_bodies`. Each retained `NetworkPayloadRef` links
one response event to a separate existing `Document` for HTML/JSON or
`FileDocument` for other bytes. It records the observed raw `Content-Type`
header (including parameters), CDP's browser-effective MIME and charset, the
detected media type, explicit `projection_basis`, content encoding, CDP
base64 transport, retained byte count and SHA-256 as separate facts. Projection
reuses Requests' source
classification from the raw header and bounded body sniffing; CDP's effective
MIME is not relabeled as a declaration. CDP supplies
the browser-decoded response body, not a lossless wire copy. Missing,
unsupported and truncated bodies remain explicit in the reference. After
Archive retention, `Outcome.source_document` and
`Outcome.source_file_document` restore a linked body without a browser;
Python uses `Outcome.network_payload` to return the matching typed value.
Typed payload reads require the exact reference retained in one of that
Outcome's network windows, including its request, redirect hop and response
sequence. A matching body digest alone does not establish that relationship.
When CDP returns text rather than base64, the body is its Unicode text view
encoded as UTF-8; `text_utf8_normalized` records that fact while
`browser_effective_charset`
records the CDP-reported effective charset separately from the raw header
retained in `declared_media_type`. Yosoi does not decode that text a second
time. Base64 responses retain decoded entity bytes, not wire bytes, and keep
any declared content encoding as separate provenance.

Network evidence is page-target scoped and never claims browser-wide complete
traffic. A window records listener order and provider clock separately, plus
in-flight requests, start-boundary uncertainty, gaps, late events, filtering,
overflow, disconnect and subscription expiry. Enabling the subscription turns
on bounded CDP Network instrumentation for that Page. Cancel and close release
the owned listeners and task; the Page-level Network domain remains enabled for
the Page lifetime. Coverage distinguishes instrumentation newly enabled by
this subscription from Network instrumentation already active on that Page. A
fresh tab starts with its own instrumentation state.

An ordinary `Document::json` stays ordinary JSON even if its values contain a
`schema` field resembling `yosoi.network.v1`. Only a `NetworkWindow`-created
Document with the `yosoi_network_observation_v1` profile has network semantics.

## Keep reference types distinct

| Meaning                         | Rust                                | Python                      |
| ------------------------------- | ----------------------------------- | --------------------------- |
| Document-index address          | `surface::Reference`                | `surface.NativeReference`   |
| Shared observation/address pair | `surface::model::Reference`         | `surface.Reference`         |
| Native index continuation       | `surface::Continuation`             | `surface.Continuation`      |
| Shared opaque continuation      | `surface::model::ContinuationToken` | `surface.ContinuationToken` |
| Pixel artifact transform        | `surface::PixelArtifactInfo`        | `surface.PixelArtifactInfo` |

Native references bind a capture and node. Shared references bind an ObservationId and producer-issued address. WebSurface converts between its own native and shared references; it rejects references belonging to another observation or source binding. Do not parse address spelling, manufacture a replacement ID, or treat an old reference as a durable entity identifier.

SourceId, SurfaceId, ObservationId, AddressToken, and ContinuationToken validate through Rust in both SDKs. They allow 1 through 1,024 UTF-8 bytes without control characters. Python represents diagnostic CursorId and WatchId values as checked integer aliases; the integers carry no owned cursor or action permit.

## Bound preparation and replies

Limits controls input bytes, node count, tree depth, and automatic overview depth. Budget controls the complete serialized result's UTF-8 bytes and routing entry count. The defaults are 8 MiB of document input, 200,000 nodes, depth 96, overview depth 6, and 4,096 reply bytes with 20 entries.

The shared read protocol accepts byte budgets from 512 through 65,536. The CLI separately reserves its outer transport envelope and supports reply budgets from 1,024 through 16,384. A useful item that cannot fit produces an explicit error.

Copy continuations into the same operation with the same reference and query. Inspection chunks are UTF-8 aligned; assemble every chunk before parsing complete JSON. Coverage describes retained source evidence, while `next` describes pagination. Byte bounds do not establish a tokenizer-independent token count.

## Select browser evidence and per-type limits

`SurfacePolicy.documents` holds independent `DocumentPolicy` values for `dom`,
`ax`, `html`, `xml`, `json`, `text` and `network`. Python calls the ordinary JSON
field `json_document`; its serialized name remains `json`. Each policy selects
`max_bytes`, `max_depth`, `max_nodes`, `overview_depth` and `response_bytes`.
Root depth is zero. Overview depth is capped to the selected tree depth.

Capture/preparation limits and read-response limits are independent. Oversized
supplied documents and DOM captures fail explicitly; they are not silently
truncated. AX uses Chrome's native depth-limited capture and retains partial
coverage. `max_bytes` bounds retained serialized documents, not the browser's
internal allocations or the raw provider response before normalization.

Use `Surface::with_policy` or `Surface.with_policy` for immutable documents.
The declared document profile chooses the matching preparation policy. Use
`WebSurface::with_policy` or the Python `WebSurface` constructor's `policy`
argument to limit shared read responses independently of caller budgets.

Rust and Python WebSurface accept all six Document classes. The CLI's offline
`ys surface document` command accepts the same profiles and uses the same
`describe` and `read` requests. Its local input remains immutable and
non-controllable. The live CLI browser adapter continues to own its separate
Work and action capabilities.

Consumed native Sessions support `BrowserSurface.observe` for DOM and AX,
plus network windows after an explicit subscription.
`read` explores a captured view under its policy. The isolated `open` provider
currently supports DOM only. BiDi does not advertise network capture. A local
network-shaped JSON Document remains ordinary JSON; its shape alone does not
grant network semantics.

Views are sequential captures. Replacing a view rejects its previous references.
AX references remain read-only and never become DOM action targets. DOM
observation refreshes the live capture and invalidates older action targets.

## Coordinate a cursor

Session is a coordinator for an external capture/control adapter. It does not open a browser, start an observer, or dispatch a click. The [Surface CLI](../cli/surface.md) supplies a live browser adapter; immutable WebSurface and VideoSurface readers remain non-controllable.

Enable `archive` in the session policy to retain sources and receipts separately from live history. `outcome()` snapshots retained evidence; `close()` revokes logical authority and returns its final outcome. Pass that value to the existing Archive write callable, then export it as a portable file. Policy is off by default. [Archiving a surface](../concepts/archiving-a-surface.md) explains save, reload, incomplete outcomes and fresh execution.

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

Archive the original Document to reconstruct a document index after the source closes. PixelArtifact, VideoSurface and DecodedFrame use the existing Archive backend. A pixel artifact stores its exact PNG/JPEG bytes in the raw ImageDocument payload store and a separate provenance record. A saved video restores its timeline without probing; decoding a new frame still needs a compatible decoder. A saved frame restores actual verified PNG bytes without the source or decoder.

Video timestamps use microseconds relative to primary stream start. FrameInfo retains the requested position and measured source PTS separately. PixelRect uses the full decoded canvas, which may have been downscaled. Video coverage remains partial because this provider does not observe audio, OCR, transcription, or every frame eagerly.

Python document navigation, image indexing and shared read calls release the GIL. Async video and Archive methods execute on the native runtime; cancelled Python awaits can leave Rust completing bounded cleanup. Keep live-source lifecycle in the owning adapter and preserve uncertainty when execution is interrupted.
