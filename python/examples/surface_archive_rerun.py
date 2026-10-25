"""Deliberately rerun a portable web procedure and archive each new outcome."""

import argparse
import asyncio
import json
from pathlib import Path

from yosoi import Archive
import yosoi as ys
from yosoi.errors import rust_error_details


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = await Archive.open(args.output / "store")
    reference = await archive.import_file(args.file)
    saved = await archive.read(reference)
    failure = None
    try:
        outcomes = await saved.rerun(
            ys.surface.SurfacePolicy(archive="enabled", output=args.output / "executions"),
            count=1,
        )
    except ys.surface.ExecutionError as error:
        details = rust_error_details(error)
        if details is None or details.variant != "Execution":
            raise
        outcomes = tuple(
            ys.surface.Outcome.model_validate(value) for value in details.details["outcomes"]
        )
        failure = error
    files = []
    for index, outcome in enumerate(outcomes):
        reference = await archive.write(outcome)
        file = args.output / f"outcome-{index}.yosoi"
        await archive.export_file(reference, file)
        files.append(str(file))
    print(
        json.dumps(
            {
                "original_run": saved.record.id,
                "runs": [outcome.record.id for outcome in outcomes],
                "files": files,
                "failed": failure is not None,
            }
        )
    )
    if failure is not None:
        raise failure


if __name__ == "__main__":
    asyncio.run(main())
