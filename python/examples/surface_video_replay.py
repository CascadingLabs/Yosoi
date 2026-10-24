"""Restore an archived video's timeline and saved crop without a decoder."""

import argparse
import asyncio
import json
from pathlib import Path

import yosoi as ys
from yosoi import surface as sf


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="Directory written by surface_video.py"
    )
    args = parser.parse_args()
    evidence = json.loads((args.output / "evidence.json").read_text())
    archive = await ys.Archive.open(args.output / "archive")
    video = await sf.VideoSurface.read_from(
        archive, sf.VideoArchiveRef.model_validate(evidence["video"])
    )
    frame = await sf.DecodedFrame.read_from(
        archive, sf.FrameArchiveRef.model_validate(evidence["frame"])
    )
    (args.output / "restored-crop.png").write_bytes(frame.png)
    report = {
        "timeline": video.read(sf.ReadRequest(operation=sf.Overview())).model_dump(),
        "frame": frame.info.model_dump(),
        "controllable": video.descriptor.controllable,
    }
    (args.output / "replay.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
