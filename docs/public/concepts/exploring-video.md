---
title: Exploring video evidence
description: Zoom through a frozen video timeline and retain exact frames and crops.
---

# Exploring video evidence

A video Surface begins with a frozen local file. Opening it copies and probes that file; it does not decode every frame. The agent reads a small timeline, narrows an interval, and requests pixels only when needed.

This adapter is read-only. It does not subscribe to live streams, play a video, transcribe audio, or search visible words. Timeline coverage says so explicitly.

## Requirements

Rust needs Yosoi's `surface-video` feature, Tokio, and Serde JSON for saving reference files. Python needs a wheel built with video support. Both use local FFmpeg and FFprobe, selected from PATH or `YOSOI_FFMPEG` and `YOSOI_FFPROBE`.

## Example: keep one frame

Place a video longer than four seconds at `recording.mp4`. These programs request the first frame at or after 3.5 seconds and retain its PNG evidence in the normal Archive backend. The local Archive backend requires Unix.

### Rust

```rust
use std::error::Error;
use yosoi::{Archive, surface::video::{DecodedFrame, VideoPolicy, VideoSurface}};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let video = VideoSurface::open("recording.mp4", VideoPolicy::default()).await?;
    let frame = video.frame(&video.at(3_500_000)?).await?;
    std::fs::write("frame.png", &frame.png)?;
    println!("Source timestamp: {}", frame.info.source_pts_us);

    let archive = Archive::open("video-evidence").await?;
    let reference = frame.write_to(&archive).await?;
    let restored = DecodedFrame::read_from(&archive, &reference).await?;
    println!("Restored PNG bytes: {}", restored.png.len());
    Ok(())
}
```

`at` creates an exact address within this frozen interpretation. `frame` measures the decoded source timestamp; it does not report the requested time as though it had been observed. Frame PNG bytes are separate from bounded text responses.

### Python

```python
import asyncio
from pathlib import Path
import yosoi as ys
from yosoi import surface as sf


async def main():
    video = await sf.VideoSurface.open("recording.mp4")
    frame = await video.frame(video.at(3_500_000))
    Path("frame.png").write_bytes(frame.png)
    print("Source timestamp:", frame.info.source_pts_us)

    archive = await ys.Archive.open("video-evidence")
    reference = await frame.write_to(archive)
    restored = await sf.DecodedFrame.read_from(archive, reference)
    print("Restored PNG bytes:", len(restored.png))


asyncio.run(main())
```

The async methods execute the same Rust provider. Opening the video owns its copied source, so later decoding does not depend on the original path. Saved FrameInfo and PNG bytes are checked when restored.

## Zoom in time and pixels

The shared `ReadRequest` protocol returns timeline intervals from overview and expand. It subdivides lazily, with eight children per interval and a default minimum interval of 250,000 microseconds. A frame request decodes the first frame at or after the selected time. A request in the final frame's tail can have no qualifying frame and returns an explicit error.

`crop` takes a full-frame reference and PixelRect in the decoded frame's coordinate space. The default maximum decoded side is 1,920 pixels, with no upscaling. Use the returned canvas dimensions to choose the rectangle; source-video dimensions may be larger.

The provider bounds source bytes, duration, decoded pixels, PNG bytes, decoder runtime, and cached frames. The default source limit is 32 MiB and the default tool timeout is 30 seconds. Cancelling a Python await can leave Rust finishing bounded cleanup in the background.

## Archive once, inspect later

`video.write_to` retains the entire frozen source and interpretation profile as a normal Archive Document. `VideoSurface.read_from` restores its timeline without probing or requiring the original file. Decoding a new frame still needs a compatible decoder.

`frame.write_to` retains the actual PNG and FrameInfo. `DecodedFrame.read_from` needs neither the source file nor FFmpeg. It verifies the saved pixels and their metadata. Neither restoration grants live control.

Run `python/examples/surface_video.py FILE OUTPUT` for a complete frame, crop, and source archival example. The [Surface CLI](../cli/surface.md) exposes the same timeline and pixel operations through JSON lines.

Then run `python/examples/surface_video_replay.py OUTPUT` in a fresh Python process. It writes `restored-crop.png` from Archive and reads the retained timeline without a decoder or the original video path.
