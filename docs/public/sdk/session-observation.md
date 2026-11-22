---
title: Session screenshots and recordings
description: Capture visual evidence through the same Session and Work used for browser automation.
---

# Session screenshots and recordings

Visual evidence belongs to the browser Session. A Work lease can take a screenshot or start a recording of its tab. A Session can also record its private browser display. Request, Flow and Surface consumers use this same capture layer.

A screenshot records a moment. A recording records an interval. Neither establishes that a business task succeeded. Inspect the operation receipt and the expected application state separately.

## Capture a moment

The existing `Work.screenshot` operation retains its receipt behavior. `screenshot_with` returns an immutable image document with capture metadata. Choose the visible viewport, the full page, a rectangular region or a semantic target discovered from the page.

Target capture resolves the target against the current document. It does not turn a previously discovered role or label into a durable element identity. Use `expected_document_epoch` to reject navigation races. Missing, hidden or ambiguous targets fail instead of silently becoming viewport screenshots.

A visual capture can activate its tab to obtain a fresh compositor frame. A browser-visible recording includes that switch. Capture metadata identifies the source, tab, document generation, requested region, resolved coordinate space, output dimensions and capture time. CSS coordinates and physical image pixels remain distinct.

## Example

These functions borrow an acquired Work lease and an open Archive. They save one viewport image without starting a recording or acquiring another browser.

### Rust

```rust
use yosoi as ys;

async fn save_screenshot(
    work: &ys::session::Work,
    archive: &ys::Archive,
) -> Result<ys::archive::ImageDocumentArchiveRef, Box<dyn std::error::Error + Send + Sync>> {
    let capture = work
        .screenshot_with(ys::session::ScreenshotOptions::default())
        .await?;
    Ok(archive.write(&capture.document).await?)
}
```

### Python

```python
from yosoi import Archive
from yosoi.archive import ImageDocumentArchiveRef
from yosoi.browser import ScreenshotOptions, Work


async def save_screenshot(work: Work, archive: Archive) -> ImageDocumentArchiveRef:
    capture = await work.screenshot_with(ScreenshotOptions())
    return await archive.write(capture.document)
```

## Record an interval

Each recording has an independent handle, duration and output budget. Duration defaults to 60 seconds and can be configured up to 24 hours. Stopping one handle leaves sibling recordings running. Releasing Work releases interaction authority while a recording can continue until its handle stops, its deadline expires or its owning tab or Session closes.

Browser-visible recording follows the active browser view, including browser chrome. Per-tab recording follows a selected tab even while other tabs are active. These scopes are additive: a Session can record four independent tabs and one browser overview, subject to its configured capture limits.

A logical recording can contain several video documents. Navigation can end a document-scoped capture source. The Session records the interruption and resumes into another segment where supported. Read segment timing and explicit gaps rather than assuming that one logical handle guarantees uninterrupted media. Recording action markers link settled receipt IDs to their Session publication times. They do not report browser dispatch times; `lost_action_events` makes missing markers explicit.

## Configure automatic evidence

`Policy.observe` configures the automatic consumer. Its screenshot policy selects independent before, after and failure phases. A useful choice is target evidence before an action and viewport evidence after settlement or failure.

Recording rules are additive. A browser-visible rule and a per-tab rule can run together. Source capacity, independent output capacity, in-flight buffers and retained evidence have separate limits from action-worker capacity.

Automatic observation defaults off. Explicit screenshots remain available under the Session's screenshot permission. Native tab recording requires an explicit acquisition-time self-tab capture grant. Browser-visible recording requires a headed Session provisioned with a private display at acquisition. An existing Session cannot gain those launch capabilities retroactively.

Evidence failures normally preserve the action result and report a gap. Required evidence gates later effects after the current action settles. Neither mode automatically repeats an effect whose outcome is uncertain.

## Retain and inspect

Screenshot images and recording segments use immutable media documents and the existing Archive. Save the exact documents with their metadata and receipt links. Archived media carries evidence, never browser authority.

Native tab audio is an explicit option. Browser overview audio mixing, remote viewing and takeover are separate capabilities. Capture support is specific to the selected provider and display backend.

## Commands

The repository examples open one authorized URL and save evidence into `.generated/session-observation-example`. Their default is screenshot only. Add `--record` to retain the interval while the screenshot is collected. Recording mode uses a private X11 display and requires Linux, regular Chrome or Chromium, and Xvfb. Browser overview recording additionally requires FFmpeg.

### Cargo

```sh
cargo run -p yosoi --features browser --example session_observation -- https://example.org
```

### uv

```sh
uv run python python/examples/session_observation.py https://example.org
```
