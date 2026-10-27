---
title: Surfaces
description: Explore documents and video in bounded views, then let an agent act through the CLI.
---

# Surfaces

A Surface gives an agent a small view of a larger source. The agent starts with an overview, zooms into a region, and reads exact evidence when it needs detail. Preparing the index needs no field contract, selector, model, or task description.

A document offers structure and text. A video offers a timeline and requested pixels. Both return references tied to the exact observation being read. A reference identifies evidence; taking action requires a live adapter and separate control authority.

## Example: inspect the lamp

Use the [0.4.0 release](../releases/0-4-0.md) or its source checkout. The earlier 0.3.0 packages do not expose these Surface APIs.

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
