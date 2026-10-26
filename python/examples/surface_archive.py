"""Capture once, then reload the same portable evidence in any later process."""

import argparse
import asyncio
import json
from pathlib import Path

import yosoi as ys
from yosoi import Archive, Document


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["capture", "reload"])
    parser.add_argument("file", type=Path)
    parser.add_argument("store", type=Path)
    args = parser.parse_args()
    archive = await Archive.open(args.store)
    if args.mode == "capture":
        document = Document.html(
            "versions", "<main><h1>Documentation</h1><button>v0.1.0</button></main>"
        )
        session = ys.SurfaceSession(
            ys.Surface(document), ys.SurfaceSessionPolicy(archive="enabled")
        )
        with session.cursor() as cursor:
            page = cursor.find("v0.1.0")
            if not page.entries:
                raise RuntimeError("version missing")
            cursor.inspect(page.entries[0].reference)
        outcome = session.close()
        if outcome is None:
            raise RuntimeError("archive policy is off")
        reference = await archive.write(outcome)
        await archive.export_file(reference, args.file)
    else:
        reference = await archive.import_file(args.file)
    saved = await archive.read(reference)
    if not saved.sources:
        raise RuntimeError("source missing")
    restored = saved.surface(saved.sources[0].key)
    print(
        json.dumps(
            {
                "file": str(args.file),
                "capture": restored.identity,
                "sealed": saved.sealed,
                "complete": saved.complete,
                "operations": len(saved.record.operations),
                "matches": restored.find("v0.1.0").model_dump(mode="json"),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
