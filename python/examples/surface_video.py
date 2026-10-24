"""Inspect a real video, save a frame and crop, and archive their exact evidence."""

import argparse
import asyncio
import json
from pathlib import Path

import yosoi as ys
from yosoi import surface as sf


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--position-us", type=int, default=3500000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    video = await sf.VideoSurface.open(args.file)
    reference = video.at(args.position_us)
    frame = await video.frame(reference)
    top = min(50, frame.info.height - 1)
    crop = await video.crop(
        reference,
        sf.PixelRect(
            x=max(0, frame.info.width - 340),
            y=top,
            width=min(320, frame.info.width),
            height=min(300, frame.info.height - top),
        ),
    )
    (args.output / "frame.png").write_bytes(frame.png)
    (args.output / "crop.png").write_bytes(crop.png)
    archive = await ys.Archive.open(args.output / "archive")
    saved = await video.write_to(archive)
    pixels = await crop.write_to(archive)
    report = {
        "video": saved.model_dump(),
        "frame": pixels.model_dump(),
        "metadata": video.metadata.model_dump(),
        "frame_info": frame.info.model_dump(),
        "crop_info": crop.info.model_dump(),
        "timeline": video.read(sf.ReadRequest(operation=sf.Overview())).model_dump(),
    }
    (args.output / "evidence.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
