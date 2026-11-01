"""Capture a screenshot and an optional native tab interval through one Session."""

from __future__ import annotations

import argparse
import asyncio
from typing import Literal

import yosoi as ys
from yosoi.browser import RecordingOptions, ScreenshotOptions, SessionPolicy
from yosoi.policy import Acquisition, ObservePolicy, Page, Policy


async def capture(url: str, *, record: bool) -> None:
    """Retain image/video evidence without inferring business-task completion."""
    mode: Literal["headful", "headless"] = "headful" if record else "headless"
    policy = Policy(
        page=Page(acquisitions=[Acquisition.browser(mode)]),
        observe=ObservePolicy(native_tab_capture=record),
    )
    settings = SessionPolicy(mode=mode, execution_concurrency=1)
    async with ys.browser.session(policy=policy, settings=settings) as browser:
        async with browser.work() as work:
            navigation = await work.run(ys.flow([ys.navigate(url)]))
            navigation.require_completed()
            recording = (
                await work.start_recording(RecordingOptions()) if record else None
            )
            try:
                image = await work.screenshot_with(ScreenshotOptions())
            finally:
                output = await recording.stop() if recording is not None else None
            archive = await ys.Archive.open(".generated/session-observation-example")
            image_ref = await archive.write(image.document)
            print(f"screenshot={image_ref.value} complete={image.complete}")
            if output is not None:
                reference = await output.write_to(archive)
                print(
                    f"recording={reference.value} complete={output.complete} "
                    f"segments={len(output.segments)} gaps={len(output.gaps)}"
                )


def main() -> None:
    """Run with an authorized URL; static capture defaults to screenshot only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--record", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(capture(arguments.url, record=arguments.record))


if __name__ == "__main__":
    main()
