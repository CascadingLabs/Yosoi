---
title: Surfaces
description: Explore documents, images, and video in bounded views, then let an agent act through the CLI.
---

# Surfaces

A Surface gives an agent a small view of a larger source. The agent starts with an overview, zooms into a region, and reads exact evidence when it needs detail. Preparing the index needs no field contract, selector, model, or task description.

A document offers structure and text. An image offers original pixels, bounded overviews, and crops. A video offers a timeline and requested pixels. Their references are tied to the exact observation being read. A reference identifies evidence; taking action requires a live adapter and separate control authority.

## Example: inspect the lamp

Use the [0.4.0 release](../releases/0-4-0.md) for the document and video examples, or use its source checkout. The typed image reader in this page is available in this source revision; the 0.4.0 package does not include it.

Start with a small product document. These programs search for the same lamp and print the evidence behind the returned reference.

### Rust

```rust
use std::error::Error;
use yosoi as ys;

fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "lamp", b"<main><h1>Arc desk lamp</h1><p>Stock: 12</p></main>".to_vec(),
    )?;
    let surface = ys::Surface::new(&document)?;
    let page = surface.find("Arc desk lamp", None, ys::SurfaceBudget::default())?;
    for entry in page.entries {
        let evidence = surface.inspect(
            &entry.reference, None, ys::SurfaceBudget::default(),
        )?;
        println!("{}", evidence.content);
    }
    Ok(())
}
```

`find` performs literal search. `inspect` follows an exact reference into this prepared document. Use `overview` and `expand` when you need to discover structure before choosing a query.

### Python

```python
import yosoi as ys

document = ys.Document.html(
    "lamp", "<main><h1>Arc desk lamp</h1><p>Stock: 12</p></main>"
)
surface = ys.Surface(document)
page = surface.find("Arc desk lamp")
for entry in page.entries:
    evidence = surface.inspect(entry.reference)
    print(evidence.content)
```

`ys.Surface` owns a Rust index. Parsing, reduction, reference validation and budget enforcement run in Rust. Python returns typed immutable results rather than building another index.

## Keep the conversation small

HTML, XML, JSON, text, rendered DOM and accessibility snapshots share overview, expand, find and inspect operations. Repeated siblings can appear as one group with a count and exemplar. Expanding the group reveals its members.

The default response budget is 4,096 serialized UTF-8 bytes and 20 entries. A `next` continuation means evidence remains in that same operation. Pass it back unchanged with the original query and reference. Rust rejects a continuation from another capture, query or scope.

An inspection can split JSON across UTF-8-aligned chunks. Join every chunk before parsing the complete value. A byte limit bounds transport size; token counts depend on the model's tokenizer. Source coverage is separate: a fully paged result can still describe incomplete captured evidence.

## Example: read a dense image

Place a PNG or JPEG dashboard screenshot at `dashboard.png`. This example assumes the file fits the default 8 MiB source and output byte limits and is at least 592 by 190 pixels. An `ImageDocument` keeps those exact encoded bytes. A small image can go straight to `PixelArtifact::decode_image_document` or `PixelArtifact.from_image_document`; that bounded decode returns original pixels without building a region tree. `ImageSurface.read` uses the same bounded overview and expand protocol as other Surface readers when the caller needs to route through a larger raster. Pixel bytes travel separately as a `PixelArtifact`.

### Rust

```rust
use std::{error::Error, fs, io, time::Instant};
use yosoi::{
    Archive,
    documents::{FileDocument, FileLimits, read_file},
    surface::{
        Budget, ImageSurface, Limits, PixelArtifact, PixelLimits, PixelRect,
        model::{ReadOperation, ReadRequest, ReadResult, SurfaceRead},
    },
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let file = read_file("dashboard", "dashboard.png", FileLimits::default()).await?;
    let image = match file {
        FileDocument::Image(image) => image,
        _ => return Err(io::Error::other("dashboard.png is not a PNG or JPEG").into()),
    };
    let started = Instant::now();
    let direct = PixelArtifact::decode_image_document(image.clone(), PixelLimits::default())?;
    let direct_time = started.elapsed();
    let started = Instant::now();
    let surface = ImageSurface::from_image_document(
        &image, 256, Limits::default(), PixelLimits::default(),
    )?;
    let index_time = started.elapsed();
    let routing = surface.read(&ReadRequest {
        operation: ReadOperation::Overview,
        budget: Budget::default(),
        continuation: None,
    })?;
    let ReadResult::Page(page) = routing else {
        return Err(io::Error::other("image overview did not return a page").into());
    };
    println!("Image regions: {}", page.entries.len());

    let started = Instant::now();
    let overview = surface.overview_image(640)?;
    let overview_time = started.elapsed();
    fs::write("dashboard-overview.png", overview.bytes())?;

    // This rectangle is selected in the returned overview's pixel coordinates.
    let detail_in_overview = PixelRect { x: 512, y: 140, width: 80, height: 50 };
    let detail_in_source = overview.map_rect_to_source(detail_in_overview)?;
    let started = Instant::now();
    let crop = surface.crop_rect(detail_in_source, PixelLimits::default().max_output_bytes)?;
    let crop_time = started.elapsed();
    fs::write("dashboard-detail.png", crop.png())?;

    println!(
        "direct: {} bytes, {} pixels, {:?}; index: {:?}; overview: {} bytes, {} pixels, {:?}; crop: {} bytes, {} pixels, {:?}",
        direct.bytes().len(), direct.info().width * direct.info().height, direct_time,
        index_time,
        overview.bytes().len(), overview.info().width * overview.info().height, overview_time,
        crop.png().len(), crop.artifact.info().width * crop.artifact.info().height, crop_time,
    );
    let archive = Archive::open("dashboard-evidence").await?;
    let reference = archive.write(&crop.artifact).await?;
    let restored: PixelArtifact = archive.read(&reference).await?;
    println!("Archived crop SHA-256: {}", restored.info().sha256);
    Ok(())
}
```

`PixelArtifact::decode_image_document` and `PixelArtifact.from_image_document` return the original encoded raster without building a region index. `ImageSurface.direct_image` returns those pixels after an index exists. `overview_image` resizes explicitly with the triangle filter. `map_rect_to_source` turns a region selected from the overview back into source-raster pixel edges, then `crop_rect` returns those original-resolution pixels. The crop retains its parent identity, operation, dimensions, digest, and coordinate mapping. Archive stores the artifact bytes as an `ImageDocument` payload with a separate provenance record.

A root `PixelArtifact` from a video frame or browser screenshot can also become an `ImageSurface`. This keeps its original `VideoFrame` or screenshot source, decoded-canvas coordinates, orientation declaration, and identity while the reader indexes its regions. A derived artifact cannot become a new root; map its selected rectangle back and crop from the validated source instead.

### Python

```python
import asyncio
from pathlib import Path
from time import perf_counter

import yosoi as ys
from yosoi.documents import read_file
from yosoi.surface import Overview, ReadRequest


async def main() -> None:
    image = await read_file("dashboard", "dashboard.png")
    if not isinstance(image, ys.ImageDocument):
        raise TypeError("dashboard.png is not a PNG or JPEG")
    started = perf_counter()
    direct = ys.PixelArtifact.from_image_document(image)
    direct_time = perf_counter() - started
    started = perf_counter()
    surface = ys.ImageSurface(image, tile_side=256)
    index_time = perf_counter() - started
    page = surface.read(ReadRequest(operation=Overview()))
    if page.kind != "page":
        raise RuntimeError("image overview did not return a page")
    print("Image regions:", len(page.data.entries))

    started = perf_counter()
    overview = surface.overview_image(640)
    overview_time = perf_counter() - started
    Path("dashboard-overview.png").write_bytes(overview.bytes)

    # This rectangle is selected in the returned overview's pixel coordinates.
    detail_in_overview = ys.PixelRect(x=512, y=140, width=80, height=50)
    detail_in_source = overview.map_rect_to_source(detail_in_overview)
    started = perf_counter()
    crop = surface.crop_rect(detail_in_source)
    crop_time = perf_counter() - started
    Path("dashboard-detail.png").write_bytes(crop.png)

    print(
        f"direct: {len(direct.bytes)} bytes, {direct.info.width * direct.info.height} pixels, {direct_time:.4f}s; "
        f"index: {index_time:.4f}s; "
        f"overview: {len(overview.bytes)} bytes, {overview.info.width * overview.info.height} pixels, {overview_time:.4f}s; "
        f"crop: {len(crop.png)} bytes, {crop.artifact.info.width * crop.artifact.info.height} pixels, {crop_time:.4f}s"
    )
    archive = await ys.Archive.open("dashboard-evidence")
    reference = await archive.write(crop.artifact)
    restored = await archive.read(reference)
    print("Archived crop SHA-256:", restored.info.sha256)


asyncio.run(main())
```

Both programs print encoded bytes, returned pixels, and local processing time for the exact values they produced. Those measurements describe this image and machine; they do not predict model-token savings. The small red marker in a dense screenshot can disappear in a resized overview, so callers can map an overview region back to the original pixels and crop that detail.

The known-pixel Rust fixtures also compare a tiny raster with a dense dashboard. These are one local run with millisecond timing resolution; index construction is included in the overview-plus-crop path. The tiny fixture encodes a pixel-drawn `λ` label. The dashboard contains a 2×2 red marker.

| Fixture and delivery                      | Encoded bytes | Pixels sent |                     Measured processing |
| ----------------------------------------- | ------------: | ----------: | --------------------------------------: |
| Tiny raster, direct decode                |           374 |         256 |                                    0 ms |
| Tiny raster, overview only                |           285 |          64 |                             0 ms resize |
| Tiny raster, overview plus exact crop     |           643 |         208 |   0 ms including index, resize and crop |
| Dense dashboard, direct decode            |        42,799 |   2,073,600 |                                   53 ms |
| Dense dashboard, overview only            |         1,621 |      57,600 |                           327 ms resize |
| Dense dashboard, overview plus exact crop |         1,815 |      57,924 | 380 ms including index, resize and crop |

The tiny raster is cheaper to send directly than to send its overview and crop; its crop still reproduces the pixel label exactly. In the dense dashboard, resizing loses the exact marker pixel, while the mapped source crop recovers it. The combined overview and crop use fewer bytes and pixels than the original raster in that fixture. The timings are local measurements, not performance guarantees or model-token estimates.

## Example: zoom into a recording

A video Surface freezes a local file and probes its timeline. It decodes a frame only when requested. Place a recording longer than four seconds at `recording.mp4`; these programs save the first frame at or after 3.5 seconds, then restore its PNG through Archive.

Rust requires `surface-video` and Tokio. Python's wheel needs video support. Opening and decoding use local FFmpeg and FFprobe, selected from PATH or `YOSOI_FFMPEG` and `YOSOI_FFPROBE`. The local Archive backend requires Unix.

### Rust

```rust
use std::{error::Error, fs};
use yosoi as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let video = ys::VideoSurface::open("recording.mp4", ys::VideoPolicy::default()).await?;
    let frame = video.frame(&video.at(3_500_000)?).await?;
    fs::write("frame.png", &frame.png)?;
    println!("Source timestamp: {}", frame.info.source_pts_us);

    let archive = ys::Archive::open("video-evidence").await?;
    let reference = frame.write_to(&archive).await?;
    let restored = ys::DecodedFrame::read_from(&archive, &reference).await?;
    println!("Restored PNG bytes: {}", restored.png.len());
    Ok(())
}
```

`at` addresses this frozen interpretation. `frame` reports a measured source timestamp, which can differ from the requested time. PNG bytes have their own processing limits, separate from text response budgets.

### Python

```python
import asyncio
from pathlib import Path
import yosoi as ys

async def main() -> None:
    video = await ys.VideoSurface.open("recording.mp4")
    frame = await video.frame(video.at(3_500_000))
    Path("frame.png").write_bytes(frame.png)
    print("Source timestamp:", frame.info.source_pts_us)

    archive = await ys.Archive.open("video-evidence")
    reference = await frame.write_to(archive)
    restored = await ys.DecodedFrame.read_from(archive, reference)
    print("Restored PNG bytes:", len(restored.png))

asyncio.run(main())
```

The async calls use the same Rust provider. The copied source keeps later decoding independent of the original path. Restoring a saved frame needs neither the original video nor FFmpeg.

## Read capabilities before choosing an action

Video overview and expansion subdivide time lazily. A frame request can return an explicit error when no frame exists at or after the selected time. Crops use `ys.PixelRect` in the returned decoded canvas, which can be smaller than the source raster. Processing bounds cover source bytes, duration, decoded pixels, PNG bytes, tool runtime and cached frames.

Video is read-only. It does not play a stream, transcribe audio, perform OCR or search visible words. An immutable `ys.WebSurface` is also a reader. The CLI's live web adapter adds actions; its descriptive `controllable` flag does not grant permission to act.

## Let a coding agent add the lamp to a cart

Use [QScrape's Arc desk lamp page](https://qscrape.dev/eshop/html/product/obj-001/). This is a synthetic shop. The task is to add one lamp and verify the site's confirmation, without checkout or payment.

Give your coding agent this task:

> Use the Yosoi Surface CLI to open the QScrape Arc desk lamp product page.
> Read the product and locate its Add to cart control through the index.
> Inspect the current reference and check that exactly one matching button is eligible.
> Attach as a live reader, acquire hot control, and add the lamp once.
> Require the visible confirmation "Added Arc desk lamp to cart.".
> Report the action receipt and close the browser. Do not check out or pay.

The agent can keep a CLI process alive while choosing its next command:

This live Surface adapter requires ChromeDriver and regular Chrome or Chromium. Install compatible versions and put them on PATH, or select their paths with `CHROMEDRIVER` and `CHROME`. It uses an isolated, sandboxed profile. Firefox and Moli selection in Requests and Sessions does not change this separate Surface transport.

```sh
yosoi surface web \
  --url https://qscrape.dev/eshop/html/product/obj-001/ \
  --headless --output lamp-run
```

The ready reply contains an initial capture and a detached cursor. `describe` reports capabilities. `attach` makes the reader live; `hot` acquires the single action slot. The agent searches with `find`, follows references with `inspect` and `parent`, and calls `eligibility` before clicking. It sends the chosen current reference in `click`, together with a text postcondition for the confirmation above.

The following small driver makes that agent loop concrete. It talks only to the CLI and selects from returned evidence; it contains no CSS or XPath selectors. Run it with Python while `yosoi` is on PATH.

```python
import json
import subprocess

process = subprocess.Popen(
    ["yosoi", "surface", "web", "--headless", "--output", "lamp-run",
     "--url", "https://qscrape.dev/eshop/html/product/obj-001/"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
)

def send(command):
    process.stdin.write(json.dumps(command) + "\n")
    process.stdin.flush()
    reply = json.loads(process.stdout.readline())
    if not reply["ok"]:
        raise RuntimeError(reply["error"])
    return reply["result"]

def inspect(reference):
    detail = send({"op": "inspect", "reference": reference})
    content = detail["content"]
    while detail["next"]:
        detail = send({"op": "inspect", "reference": reference,
                       "continuation": detail["next"]})
        content += detail["content"]
    return json.loads(content)

try:
    ready = json.loads(process.stdout.readline())
    if not ready["ok"]:
        raise RuntimeError(ready["error"])
    send({"op": "attach"})
    send({"op": "hot"})
    page = send({"op": "find", "query": "Add to cart"})
    if page["next"]:
        raise RuntimeError("Search is incomplete; narrow the query before acting")
    buttons = {}
    for entry in page["entries"]:
        reference = entry["reference"]
        for _ in range(8):
            if reference is None:
                break
            if inspect(reference).get("tag_name") == "button":
                if send({"op": "eligibility", "reference": reference})["eligible"]:
                    buttons[json.dumps(reference, sort_keys=True)] = reference
                break
            reference = send({"op": "parent", "reference": reference})
    if len(buttons) != 1:
        raise RuntimeError(f"Expected one eligible button, found {len(buttons)}")
    reference = next(iter(buttons.values()))
    result = send({"op": "click", "reference": reference,
                   "target": {"query": "Add to cart", "tag": "button"},
                   "expect": {"kind": "text", "present": True,
                              "text": "Added Arc desk lamp to cart."}})
    if result["receipt"]["status"] != "Confirmed":
        raise RuntimeError("The cart postcondition was not confirmed")
    print(json.dumps(result["receipt"], indent=2))
finally:
    if process.poll() is None:
        try:
            send({"op": "close"})
        finally:
            process.stdin.close()
    if process.wait(timeout=30) != 0:
        raise RuntimeError("Surface CLI cleanup failed")
```

The live adapter checks current-document binding, visibility, enabled state and hit testing, then revalidates the action lease. After dispatch it attempts a fresh capture. `Confirmed` means the declared postcondition was observed; transport success alone is insufficient. If evidence changes or two buttons match, the agent must inspect and locate again rather than guess. An unconfirmed effect should be investigated before retrying, because another click could add a second lamp.

## Keep evidence and authority separate

Use a Surface session when readers need independent positions, subscriptions and explicit hot ownership. Rust uses `ys::SurfaceSession`; Python uses `ys.SurfaceSession`. Detaching revokes hot ownership. An external adapter owns observation and effects; attaching a session does not install a DOM observer by itself.

Video source and frame references can be retained through normal Archive Documents. Saved evidence does not restore live browser memory or permission to click. Continue with [Keeping the evidence](keeping-the-evidence.md), the [Surface SDK guide](../sdk/surfaces.md), or the [CLI command guide](../cli/surface.md).

## Example: inspect native network events

This fragment assumes `surface` is bound to a managed native Chrome Session. Start the subscription before the application action that may issue requests. Run that action through the normal Surface control flow, then wait for an event and freeze its window. A timeout means no new event arrived before the deadline; it does not prove the page made no request.

### Rust

```rust
use std::error::Error;
use yosoi as ys;

async fn inspect_network(
    surface: &mut ys::surface::browser::BrowserSurface,
) -> Result<(), Box<dyn Error + Send + Sync>> {
    let subscription = surface.subscribe_network(Some(true)).await?;
    println!("CDP subscription {}", subscription.subscription_id);

    let waited = surface.wait_network_event(0, 5_000).await?;
    let (observation, window) = surface.observe_network().await?;
    println!(
        "Window {} has {} events; complete: {}",
        window.window_id,
        window.events.len(),
        window.coverage.complete,
    );
    println!("Wait result: {waited}");

    if let Some(reference) = window.payloads.iter().find(|payload|
        matches!(payload.state, ys::surface::NetworkPayloadState::Retained
            | ys::surface::NetworkPayloadState::Truncated)
    ) {
        let body = surface.network_payload(reference, 8_192).await?;
        println!("Retained response bytes: {}", body.bytes().len());
    }

    println!("Observation: {}", observation.observation.id.as_str());
    surface.cancel_network().await?;
    Ok(())
}
```

`subscribe_network` opts into response bodies here; pass `None` to use the policy setting, which defaults off. `observe_network` reads the resulting `NetworkWindow` through the shared bounded inspection protocol. Body links point to separate existing HTML/JSON `Document`s or `FileDocument`s. CDP returns browser-decoded response bytes, not a lossless wire copy. Truncation, unsupported projection, provider errors, event loss and requests still in flight stay explicit.

For a non-base64 CDP body, the bytes are the browser's Unicode text encoded as UTF-8. The payload reference marks this with `text_utf8_normalized`; `declared_media_type` preserves the observed Content-Type header, while `browser_effective_charset` records CDP's interpretation separately. Yosoi does not decode CDP text a second time. Base64 responses keep decoded entity bytes and their content-encoding declaration separately.

### Python

```python
import yosoi as ys

async def inspect_network(surface: ys.BrowserSurface) -> None:
    subscription = await surface.subscribe_network(retain_bodies=True)
    print("CDP subscription:", subscription.subscription_id)

    waited = await surface.wait_network_event(after_sequence=0, timeout_ms=5_000)
    observation, window = await surface.observe_network()
    print(
        f"Window {window.window_id} has {len(window.events)} events; "
        f"complete: {window.coverage.complete}"
    )
    print("Wait result:", waited)

    reference = next(
        (payload for payload in window.payloads
         if payload.state in {"retained", "truncated"}),
        None,
    )
    if reference is not None:
        payload = await surface.network_payload(reference, chunk_bytes=8_192)
        body = payload.value.data if isinstance(payload.value, ys.Document) else payload.value.bytes
        print("Retained response bytes:", len(body))

    print("Observation:", observation.observation.id)
    await surface.cancel_network()
```

## Keep network coverage explicit

Both SDKs use the same Rust event producer and typed window contract. Network evidence is available only for a consumed native Chrome Session. BiDi and the isolated ChromeDriver provider do not advertise it. URLs keep only their origin by default, header retention is empty, credentials and cookie headers are always excluded, and response bodies stay off unless requested. Coverage remains partial because CDP events are scoped to one page target rather than the whole browser. A response body appears in a window only after the provider reports request completion; unfinished responses remain in the in-flight list and can appear with their body link in a later frozen window.
