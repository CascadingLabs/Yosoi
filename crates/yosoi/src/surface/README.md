# Web and video surfaces

Web and video share a bounded evidence protocol; source-specific capabilities remain explicit.
`surface::model` defines the shared evidence DTOs and `SurfaceRead` boundary.
`surface::web::WebSurface` wraps an immutable captured web document.
`surface::video::VideoSurface` owns a frozen local video and lazily materializes frames.
No TV, game, drone, live-camera, or general plugin implementation is included.

## Shared contract

Both readers implement `SurfaceRead` and use the same:

- Source, surface and observation identities.
- Opaque, observation-bound references and continuations.
- `ReadRequest`, `ReadResult`, routing pages and inspection chunks.
- Whole-result byte and item budgets; inspection chunks may need concatenation.
- Descriptor with `controllable: bool` and advertised read/control capabilities.
- Normal Archive documents and AutomationRecords for retained evidence.

The immutable web reader is not itself controllable. The live web CLI binds a
browser owner and reports `controllable: true`; archived evidence and video
report false. This flag describes provider availability and never grants authority.
Web actions still require attachment, hot ownership, exact current evidence and
live eligibility. Video seeking changes only the read cursor; it requires no hot
capability and does not modify the recording.

```rust
use yosoi::surface::model::SurfaceRead;
// `web` and `video` are independently prepared readers.
let readers: [&dyn SurfaceRead; 2] = [&web, &video];
for reader in readers {
    let description = reader.descriptor();
    let result = reader.read(&request)?;
}
```

`SourceId` identifies the source, `SurfaceId` its continuing representation, and
`ObservationId` one immutable interpretation. A reference's address remains
producer-owned; callers do not convert media positions into DOM coordinates.
Web view identities include their source binding. Video observation identities
bind the frozen bytes, metadata, decoder header, frame scale and timeline profile.

## Python SDK

`import yosoi as ys; ys.surface` uses the same Rust index, shared web reader,
video provider, image crops, sessions and one-action leases. Results are typed
immutable Pydantic models. Source, surface and observation IDs are distinct
Rust-validated string types; serialized evidence never restores live authority.

The immutable `WebSurface` is a reader, not a browser controller. The live CLI
adapter adds browser authority and target eligibility separately. Video methods
are asynchronous, own a frozen source snapshot, and bound native processing by
policy. Python cancellation can leave Rust finishing bounded cleanup.

See `python/examples/surface_read.py`, `surface_video.py` and
`surface_video_replay.py`, plus the paired public guides under `docs/public`.

## CLI

Build the local binary with `cargo build -p yosoi --features cli --bin yosoi -j 1`.
The standalone Rust video API needs `--features surface-video`; it does not need
a browser. FFmpeg and FFprobe must be installed to prepare/decode new videos.
`YOSOI_FFMPEG` and `YOSOI_FFPROBE` select those local executables.

```sh
yosoi surface web --url https://cascadinglabs.com/yosoi/getting-started/what-is-yosoi/ --headless
yosoi surface video --file recording.mp4 --output .local/video --archive .local/video-archive
```

`surface drive` remains an alias for `surface web` so existing saved web workflows
continue to work. Both processes use the same persistent JSON-lines command loop:

```json
{"op":"describe"}
{"op":"read","request":{"operation":{"kind":"overview"},"budget":{"bytes":3072,"items":3}}}
{"op":"read","request":{"operation":{"kind":"expand","reference":{"observation":"COPY_OBSERVATION","address":"COPY_ADDRESS"}}}}
{"op":"read","request":{"operation":{"kind":"inspect","reference":{"observation":"COPY_OBSERVATION","address":"COPY_ADDRESS"}}}}
```

Copy references and continuation tokens intact. Supported operations are advertised;
a video does not pretend to support literal text search or a universal parent.
Use the returned continuation in `request.continuation` for the same read.
The outer CLI budget still bounds the complete reply; inner read budgets may be
reduced to reserve the transport envelope. The default reply limit is 4,096 bytes.

Video-specific **read** capabilities:

```json
{"op":"seek","position_us":3500000}
{"op":"frame","reference":{"observation":"COPY_OBSERVATION","address":"COPY_FOCUS_ADDRESS"}}
{"op":"crop","reference":{"observation":"COPY_OBSERVATION","address":"COPY_FULL_FRAME_ADDRESS"},"rect":{"x":1580,"y":50,"width":320,"height":300}}
{"op":"close"}
```

`frame` and `crop` return actual PNG artifact paths plus `FrameInfo`, rather than
silently embedding binary bytes in a text reply. Crop coordinates are in the full
**decoded frame**: source dimensions, decoded canvas dimensions and output crop
size remain separate. Frame scaling never upscales smaller source videos.
Requests seek the first decoded frame at or after the requested position. Returned
metadata retains both the requested position and the **measured source PTS** and
stream-relative position. Nonzero stream start timestamps are not wall-clock time.
The final-frame tail may have no later frame, which returns `NoFrameAtOrAfter`
instead of inventing pixels or copying the requested time into observed metadata.

The web CLI keeps its existing action DTOs for persisted-record compatibility.
`focus_evidence` converts a shared reference through the owning web adapter and
returns the existing `cursor.position.focus` action target. No client parses an
opaque address to construct a DOM locator. Web `describe` advertises the live
control domain. Video rejects browser actions and `hot` without changing its mode.

## Resource and evidence boundaries

The initial adapter accepts self-contained MOV/MP4, Matroska/WebM, AVI, MPEG-TS
and Ogg containers. Playlist/bundle demuxers are rejected so an immutable snapshot
cannot silently depend on mutable external media files.

Video opens a local regular file and copies at most 32 MiB by default into a
private immutable snapshot. Subsequent original-file changes do not retarget refs.
Policy can raise this limit up to 128 MiB. Default maximum duration is six hours;
source raster area is limited to 16,777,216 pixels. The default decoded frame side
is 1,920, PNG output is capped at 8 MiB, native tools have 30-second timeouts, and
only four full frames are cached. Decode processes use one codec/filter worker.
Timeout and output-limit failures kill and reap the decoder process.

Timeline overview/expansion produces at most eight temporal children at a time;
it does not scan or retain every frame. Frame decoding is a separately requested
read capability. Text budgets and pixel-processing budgets are deliberately separate.

Coverage is explicitly partial: the representation covers visual timeline metadata
and requested pixels. It does not observe audio, transcribe speech, run OCR,
identify scenes, or semantically search the contents of a video. Audio stream
counts are metadata only. Container duration is marked estimated when the primary
stream has no duration; such an extent can include a tail without a decodable frame.

FFmpeg timestamp preservation and measured frame timestamps are based on its
[`copyts` behavior](https://ffmpeg.org/ffmpeg.html) and
[`showinfo` output](https://ffmpeg.org/ffmpeg-filters.html#showinfo), with actual
nonzero-origin media exercised by the Rust integration tests.

## Archive and replay

`--archive DIR` records the full source snapshot and actual requested PNG frames
using versioned JSON binary envelopes in ordinary Archive Documents. Their
references and metadata are retained in a normal AutomationRecord; the existing
Archive and AutomationRecord formats are unchanged. This costs base64 storage
overhead and is a prototype bridge, not a new general binary artifact format.

```sh
yosoi surface replay --record .local/video/record.json --repeat 3 --output .local/video-offline
```

This reconstructs the timeline and verifies/reopens saved PNG evidence without
the original file, a browser, FFprobe or FFmpeg. It never re-executes source control.
Re-decoding a new frame from archived source bytes is a separate operation that
requires the compatible recorded decoder profile. Archived pixels remain usable
when that decoder is unavailable. Video recordings cannot use the live web-click
`surface repeat` path because they are not controllable.

## Design boundaries

The common read contract should work without forcing a timeline into a DOM tree.
Differences stay explicit: web can advertise control; video has media time, sparse
pixel observations, and decoder limits. Existing web authority, recording, offline
replay, and live repetition must keep working. The experiment deliberately leaves
live streaming, audio, OCR, scene detection, richer cross-view synchronization and
a universal session runtime unresolved.
