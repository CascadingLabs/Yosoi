---
title: Media documents and downloads
description: Retain image, video, audio and opaque files through the same Archive lifecycle.
draft: false
---

# Media documents and downloads

An `ImageDocument`, `VideoDocument` or `AudioDocument` owns immutable source bytes with a recognized file format. `BinaryDocument` retains other files, including files whose format is unknown. These types do not decode pixels or audio, extract video frames, or prove that every part of a file is valid media. Those operations belong to later interpretation APIs.

The existing `Document` remains the reader for HTML, XML, JSON, text, rendered DOM and accessibility snapshots. A media document does not acquire text locators or browser action authority merely because it can be archived.

## Choose a source

Use `documents.read_file` for an existing file, `Attempt.file_document` for a complete retained HTTP response, or arm a download on existing browser Work before triggering its normal action. All three paths use the same native classification and Archive implementation.

File limits default to 64 MiB. The maximum is 256 MiB. HTTP acquisition also has its existing content-coded and representation limits; raising a file limit does not raise those acquisition limits. An incomplete HTTP response cannot be converted to a complete file document.

Classification uses byte signatures. Detected MIME is separate from a server's declared Content-Type and suggested filename. A `.jpg` name does not make PNG bytes a JPEG. Unknown and non-media formats remain retainable as binary documents. Recognition does not promise that a decoder supports the file's codecs or that a recording contains particular tracks.

Source provenance keeps the exact URL or source value up to 1 MiB of UTF-8 bytes. Filename metadata is limited to 1 KiB, and declared MIME and other provenance fields are limited to 4 KiB. Values are rejected at their limits, not shortened.

## Example: retain a local file

### Rust

```rust
use yosoi::{Archive, documents::{FileLimits, read_file}};

# async fn example() -> Result<(), Box<dyn std::error::Error>> {
let file = read_file("recording", "recording.mp4", FileLimits::default()).await?;
let archive = Archive::open(".yosoi").await?;
let reference = archive.write(&file).await?;
let restored = archive.read(&reference).await?;
println!("{} bytes; sha256 {}", restored.byte_len(), restored.sha256());
# Ok(())
# }
```

The runtime `FileDocument` enum contains a concrete image, video, audio or binary document. Its reference restores the same variant. The original path is not required after the Archive write completes.

### Python

```python
import yosoi as ys
from yosoi.documents import read_file


async def example():
    file = await read_file("recording", "recording.mp4")
    archive = await ys.Archive.open(".yosoi")
    reference = await archive.write(file)
    restored = await archive.read(reference)
    print(restored.byte_len, restored.sha256)
```

The factory returns the concrete Python document class. Payload bytes are omitted from normal representations and metadata serialization; retrieve them explicitly when needed.

## Example: retain an HTTP response

### Rust

```rust
use yosoi::{Archive, documents::FileLimits, request};

# async fn example(url: &str) -> Result<(), Box<dyn std::error::Error>> {
let response = request::new(url).send().await?;
let attempt = response.attempts().next().ok_or("no acquisition attempt")?;
if !attempt.status().is_some_and(|status| (200..300).contains(&status)) {
    return Err("HTTP response was not successful".into());
}
let file = attempt.file_document(FileLimits::default())?;
let archive = Archive::open(".yosoi").await?;
let reference = archive.write(&file).await?;
println!("{reference}");
# Ok(())
# }
```

File conversion shares the complete native response payload. It does not make another HTTP request or character-decode the body. An HTTP error can also have a complete body, which is why this example checks status separately.

### Python

```python
import yosoi as ys


async def example(url):
    response = await ys.request.new(url).send()
    attempt = response.attempts[0]
    if attempt.http_status is None or not 200 <= attempt.http_status < 300:
        raise RuntimeError("HTTP response was not successful")
    file = attempt.file_document()
    archive = await ys.Archive.open(".yosoi")
    reference = await archive.write(file)
    print(reference)
```

Missing, incomplete and unretained bodies produce an explicit conversion failure. The original Request document outcomes and response-body API remain available.

## Example: capture a browser download

Download capture watches the existing browser Work. It does not choose or dispatch a click. Navigate to the page first, arm capture on that Work, then run the caller-supplied Flow. The Session and Work stay owned by the caller. Leaving the Python context without consuming the result cancels the provider capture and waits for cleanup.

### Rust

```rust
use std::{error::Error, io};
use yosoi::{
    automation_record::OperationStatus,
    documents::FileDocument,
    flow::{Flow, FlowOutcome},
    session::{DownloadOptions, Work},
};

async fn capture_download(
    work: &Work,
    page_url: &str,
    trigger: &Flow,
) -> Result<(FlowOutcome, FileDocument), Box<dyn Error>> {
    let navigation = work.navigate(page_url).await?;
    if navigation.status != OperationStatus::Observed {
        return Err(io::Error::other("page navigation was not confirmed").into());
    }

    let capture = work.expect_download(DownloadOptions::default()).await?;
    let outcome = match trigger.with_lease(work).invoke().await {
        Ok(outcome) => outcome,
        Err(error) => {
            capture.cancel().await?;
            return Err(error.into());
        }
    };
    if let Err(error) = outcome.require_completed() {
        capture.cancel().await?;
        return Err(error.into());
    }
    let file = capture.wait().await?;
    Ok((outcome, file))
}
```

The `trigger` Flow belongs to the calling application. The helper reports its captured outcome and only returns a file after the Flow's receipts and cleanup are confirmed. If execution is rejected, unknown, or incomplete, it attempts to cancel capture before returning the original outcome error. Cleanup failures remain visible. The `media_download` Rust example accepts a caller-authored Flow file and uses this sequence.

### Python

```python
import yosoi as ys


async def capture_download(
    page_url: str,
    trigger: ys.Flow,
) -> tuple[ys.FlowOutcome, ys.FileDocument]:
    async with ys.session() as session:
        async with session.work() as work:
            navigation = await work.run(ys.flow([ys.navigate(page_url)]))
            navigation.require_completed()
            async with work.expect_download() as expected:
                outcome = await work.run(trigger)
                outcome.require_completed()
                file = await expected.wait()
            return outcome, file
```

The `trigger` Flow is supplied by the application and runs on the same Work as navigation and download capture. Python's context manager cancels and awaits cleanup if the Flow raises, fails its completion check, or the caller cancels while waiting. `DownloadError` preserves the native failure variant and any recovery-directory path through `rust_error_details`.

## Example: reopen a saved file reference

Keep the typed Archive reference when saving a file. A fresh Python process can restore an unknown file kind from its JSON using the public file-reference union. The kind-specific prefix is validated by Rust.

### Rust

```rust
use std::error::Error;
use yosoi::{Archive, archive::FileDocumentArchiveRef};

async fn reopen(reference: &str, archive_root: &str) -> Result<(), Box<dyn Error>> {
    let reference: FileDocumentArchiveRef = reference.parse()?;
    let archive = Archive::open(archive_root).await?;
    let restored = archive.read(&reference).await?;
    println!("{} bytes; sha256 {}", restored.byte_len(), restored.sha256());
    Ok(())
}
```

The executable example supports `media_documents --read REFERENCE ARCHIVE_ROOT` for a fresh-process read.

### Python

```python
from pydantic import TypeAdapter
from yosoi import Archive
from yosoi.archive import FileDocumentArchiveRef


async def reopen(reference_json, archive_root):
    reference = TypeAdapter(FileDocumentArchiveRef).validate_json(reference_json)
    archive = await Archive.open(archive_root)
    restored = await archive.read(reference)
    print(type(restored).__name__, restored.byte_len, restored.sha256)
```

The union selects the concrete Python reference from its validated prefix. Neither example requires the original input or a media decoder.

## Capture failures and recovery

Only one capture can own a browser context at a time. Unrelated downloads from another context are ignored. If a sibling tab in the same context starts a download, capture returns an explicit `UnrelatedDownload` error and preserves the files in the reported recovery directory. A failed context reset also preserves its destination and prevents further actions in that context. Close the owning Session before acquiring fresh browser resources.

Cancellation waits for native transfer cancellation and context restoration. An uncertain click or capture failure is not a reason to repeat the triggering action automatically. Inspect its receipt and retained evidence first.

Source URLs are retained exactly up to 1 MiB of UTF-8 bytes; larger source declarations fail explicitly. Filename and other metadata fields have their own smaller bounds. These limits are independent of the payload size limit.

## Archive representation

Archive stores file metadata in versioned records and original bytes in its existing binary payload storage. Media does not need a JSON/base64 wrapper. Reads verify payload length and SHA-256, plus a separate digest binding the saved identity and interpretation metadata. Restoring a file requires no browser, network connection or media decoder.

Distinct typed references select image, video, audio and binary documents. Existing text-document records and historical Surface media envelopes remain readable through their original APIs; this foundation does not reinterpret or rewrite them.

For executable local-file and HTTP examples, see `crates/yosoi/examples/media_documents.rs` and `python/examples/media_documents.py`. The paired browser examples are `crates/yosoi/examples/media_download.rs` and the Python browser mode in `python/examples/media_documents.py`.

## Commands

Set `YOSOI_DOWNLOAD_URL`, `YOSOI_ARCHIVE_ROOT`, and the caller-authored `YOSOI_TRIGGER_FLOW_JSON` before running either example. The Flow file contains the application's existing download action.

### Cargo

```sh
cargo run -p yosoi --example media_download --features browser -- \
  "$YOSOI_DOWNLOAD_URL" "$YOSOI_TRIGGER_FLOW_JSON" "$YOSOI_ARCHIVE_ROOT"
```

The `browser` feature enables native Chrome download capture. The example opens one Session, retains one Work, runs the supplied Flow, closes the Session, then archives the resulting file.

### uv

```sh
uv run python python/examples/media_documents.py browser \
  "$YOSOI_DOWNLOAD_URL" --id downloaded-file \
  --trigger-flow "$YOSOI_TRIGGER_FLOW_JSON" \
  --archive-root "$YOSOI_ARCHIVE_ROOT"
```

The Python example reads the existing Flow from the caller-authored JSON file. It does not create or guess a selector. It arms capture before the Flow, writes the resulting file to Archive, reopens the typed reference and prints media metadata, byte length, and digest without printing the payload.
