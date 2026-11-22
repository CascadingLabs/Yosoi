"""Read local, HTTP, or caller-triggered browser download media as Rust values.

Examples::

    uv run python examples/media_documents.py local ./logo.png \
        --id local-logo --archive-root .yosoi-media
    uv run python examples/media_documents.py http \
        https://assets.example/logo.png --id http-logo \
        --archive-root .yosoi-media
    uv run python examples/media_documents.py browser \
        https://assets.example/download --id download \
        --trigger-flow "$YOSOI_TRIGGER_FLOW_JSON" --archive-root .yosoi-media

The trigger Flow is authored by the calling application. The example never
guesses which control should trigger a download.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yosoi as ys
from yosoi.errors import FileDocumentError
from yosoi.policy import Acquisition, Page, Policy


def summary(document: ys.FileDocument) -> dict[str, object]:
    """Return safe media metadata without materializing or printing the payload."""
    return {
        "kind": type(document).__name__,
        "id": str(document.id),
        "filename": document.metadata.filename,
        "declared_media_type": document.metadata.declared_media_type,
        "detected_media_type": document.metadata.detected_media_type,
        "byte_len": document.byte_len,
        "sha256": document.sha256,
    }


async def read_local(path: str, id: str) -> ys.FileDocument:
    """Read one bounded regular local file using Rust's asynchronous factory."""
    return await ys.read_file(id, Path(path))


async def read_http(url: str, id: str) -> tuple[ys.FileDocument, int | None]:
    """Convert a complete retained HTTP body without issuing a second request."""
    response = await ys.request.new(url).send()
    if not response.attempts:
        raise RuntimeError("the request returned no acquisition attempts")
    attempt = response.attempts[0]
    document = attempt.file_document()
    return document, attempt.http_status


async def read_browser_download(
    url: str,
    trigger: ys.Flow,
    id: str,
) -> tuple[ys.FileDocument, ys.FlowOutcome]:
    """Arm download capture, run the caller-supplied Flow, then await exact bytes.

    Args:
        url: Page containing the caller's download control.
        trigger: Existing application-owned Flow that triggers the download. Yosoi
            does not discover, choose, or retry its operation target.
        id: Document identity used for the page setup and the resulting capture.

    Returns:
        The Rust-classified download and the triggering Flow outcome. Inspect the
        outcome independently: the downloaded file can exist even when its click
        receipt is incomplete or uncertain.
    """
    policy = Policy(page=Page(acquisitions=[Acquisition.browser()]))
    async with ys.session(policy=policy) as session:
        async with session.work() as work:
            navigation = await work.run(ys.flow([ys.navigate(url)], timeout_ms=30_000))
            navigation.require_completed()
            async with work.expect_download() as expected:
                outcome = await work.run(trigger)
                outcome.require_completed()
                document = await expected.wait()
    return document.model_copy(update={"id": id}), outcome


async def run(arguments: argparse.Namespace) -> int:
    """Execute the selected acquisition example and print bounded metadata."""
    result: dict[str, object]
    try:
        if arguments.mode == "local":
            document = await read_local(arguments.target, arguments.id)
            result = {"document": summary(document)}
        elif arguments.mode == "http":
            document, status = await read_http(arguments.target, arguments.id)
            result = {"http_status": status, "document": summary(document)}
        else:
            if arguments.trigger_flow is None:
                raise ValueError("browser mode requires --trigger-flow")
            trigger = ys.Flow.model_validate_json(
                Path(arguments.trigger_flow).read_text(encoding="utf-8")
            )
            document, outcome = await read_browser_download(
                arguments.target, trigger, arguments.id
            )
            result = {
                "flow_termination": outcome.terminal,
                "document": summary(document),
            }
    except FileDocumentError as error:
        print(json.dumps({"file_error": str(error)}))
        return 1
    archive = await ys.Archive.open(arguments.archive_root)
    reference = await archive.write(document)
    restored = await archive.read(reference)
    result["archive_reference"] = reference.value
    result["restored_document"] = summary(restored)
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    """Parse local, HTTP, and native browser download example inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("local", "http", "browser"))
    parser.add_argument("target", help="local path or page/request URL")
    parser.add_argument("--id", default="media-example")
    parser.add_argument("--archive-root", default=".yosoi-media")
    parser.add_argument(
        "--trigger-flow",
        help="application-authored JSON Flow for browser mode's existing action",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
