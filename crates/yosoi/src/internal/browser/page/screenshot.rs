use crate::internal::types as yosoi_types;

use super::Bbox;
use super::Page;
use super::ScreenshotOptions;
use super::ScreenshotOutput;
use crate::internal::browser::environment::EnvironmentObservation;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::selector::TargetResolution;
use crate::internal::browser::viewport::ScrollTarget;
use chromiumoxide::cdp::browser_protocol::page::CaptureScreenshotFormat;
use chromiumoxide::cdp::browser_protocol::page::PrintToPdfParams;
use chromiumoxide::cdp::browser_protocol::page::Viewport as CdpClipViewport;
use chromiumoxide::page::ScreenshotParams;
use std::fs;
use std::time::Duration;
use tokio::time;

impl Page {
    /// Capture a full-page PNG screenshot, returned as raw bytes.
    ///
    /// Backward-compatible shim around [`Page::screenshot`] with no
    /// options (full page, no crop, bytes in memory).
    pub async fn screenshot_png(&self) -> Result<Vec<u8>> {
        match self.screenshot(ScreenshotOptions::default()).await? {
            ScreenshotOutput::Bytes(b) => Ok(b),
            ScreenshotOutput::Path(_) => Err(VoidCrawlError::ScreenshotError(
                "screenshot unexpectedly wrote to disk".into(),
            ))?,
        }
    }

    /// Capture a PNG screenshot with optional cropping, viewport override,
    /// scrolling, and/or writing to disk.
    ///
    /// * No `path` → returns bytes in memory.
    /// * `path` set → writes PNG to disk and returns that path.
    /// * `bbox` crops to a pixel region (CSS pixels, pre-DPR); with `scroll`
    ///   set, `bbox.x`/`bbox.y` are relative to wherever that scroll lands
    ///   rather than the top of the document.
    /// * `viewport` swaps in a device/dimension override (see
    ///   [`Page::set_viewport`]) for just this capture and restores whatever
    ///   was active before, even on error.
    /// * `scroll` moves the page before capturing (see [`ScrollTarget`]) and
    ///   restores the original scroll position after, even on error.
    pub async fn screenshot(&self, opts: ScreenshotOptions) -> Result<ScreenshotOutput> {
        if opts.bbox.is_some() && opts.selector.is_some() {
            return Err(VoidCrawlError::Other(
                "ScreenshotOptions: `bbox` and `selector` are mutually exclusive".into(),
            ));
        }

        // One-shot viewport override for just this capture — snapshot
        // whatever's already in effect so it's restored exactly, even on
        // error, so a temporary device identity never leaks to the next
        // call on this page.
        let restore_viewport = if let Some(ref viewport) = opts.viewport {
            let prev = self.current_viewport();
            self.set_viewport(viewport.clone()).await?;
            Some(prev)
        } else {
            None
        };

        let result = self.screenshot_inner(&opts).await;

        if let Some(prev) = restore_viewport {
            let restored = match prev {
                Some(v) => self.set_viewport(v).await,
                None => self.clear_viewport().await,
            };
            let _ = restored;
        }

        result
    }

    async fn screenshot_inner(&self, opts: &ScreenshotOptions) -> Result<ScreenshotOutput> {
        // Scroll before cropping — lets a fixed viewport (e.g. a 4K
        // desktop) be paged through and a specific on-screen region cropped
        // from wherever it lands, the way a human scrolling and
        // screenshotting would. Restored after capture for the same
        // leak-proofing reason as the viewport override above.
        let restore_scroll = match opts.scroll {
            Some(_) => Some(self.scroll_position().await?),
            None => None,
        };
        let bbox_shift = if let Some(target) = opts.scroll {
            self.scroll_to(target).await?;
            self.scroll_position().await?
        } else {
            (0.0, 0.0)
        };

        // A `selector` resolves to viewport-relative coordinates *as of
        // right now* (after any scroll above), so unlike a caller-supplied
        // numeric `bbox` — specified relative to the page and shifted by
        // `bbox_shift` below — it needs no shift: `getBoundingClientRect`
        // already reflects wherever the page is currently scrolled to.
        let effective_bbox: Option<(Bbox, bool)> = if let Some(bbox) = opts.bbox {
            Some((bbox, true))
        } else if let Some(entry) = &opts.selector {
            if !entry.supports_geometry() {
                return Err(VoidCrawlError::UnsupportedVisualTarget);
            }
            match self.resolve_target(entry).await? {
                TargetResolution::Resolved { bbox } => Some((bbox, false)),
                TargetResolution::Empty { reason } => {
                    return Err(VoidCrawlError::ElementNotVisible(reason));
                }
                TargetResolution::Ambiguous { reason, .. } => {
                    return Err(VoidCrawlError::AmbiguousSelector(reason));
                }
            }
        } else {
            None
        };

        let mut builder = ScreenshotParams::builder().format(CaptureScreenshotFormat::Png);
        if let Some((bbox, apply_shift)) = effective_bbox {
            let (shift_x, shift_y) = if apply_shift { bbox_shift } else { (0.0, 0.0) };
            builder = builder
                .clip(CdpClipViewport {
                    x: f64::from(bbox.x) + shift_x,
                    y: f64::from(bbox.y) + shift_y,
                    width: f64::from(bbox.width),
                    height: f64::from(bbox.height),
                    scale: 1.0,
                })
                // A region can legitimately sit outside the layout viewport
                // (e.g. paging through a fixed viewport via `scroll`), so
                // always allow capture beyond it rather than silently
                // clamping to whatever's currently on screen.
                .capture_beyond_viewport(true);
        } else if opts.full_page {
            builder = builder.full_page(true);
        } else if let Some(vp) = self.current_viewport() {
            // Viewport-only: an explicit clip at the tracked viewport's exact
            // size, rather than relying on Chrome's ambient "currently
            // visible" state. A prior full-page/capture-beyond-viewport
            // capture on this same page can leave that ambient state stale,
            // so an explicit size makes this mode order-independent.
            builder = builder.clip(CdpClipViewport {
                x: 0.0,
                y: 0.0,
                width: f64::from(vp.width),
                height: f64::from(vp.height),
                scale: 1.0,
            });
        }
        // else: no tracked viewport (e.g. a page adopted through an attached session
        // that skipped apply_stealth) — leave unset and take whatever
        // Chrome currently considers the visible viewport.

        // Headless Chrome only reliably composites a frame for the
        // foregrounded tab. With several tabs sharing one browser process,
        // an un-guarded capture on a backgrounded
        // tab can fail with CDP -32000 ("Unable to capture screenshot").
        // Headful Chromium already composites its visible target and can stall
        // indefinitely while acknowledging Target.activateTarget, so do not
        // issue that headless workaround in known headful mode. Attached mode
        // remains conservative because its visibility is unknown.
        let capture_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: yosoi_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .activate()
                .await
                .map_err(|e| VoidCrawlError::ScreenshotError(e.to_string()))?;
        }
        let bytes = self
            .inner
            .screenshot(builder.build())
            .await
            .map_err(|e| VoidCrawlError::ScreenshotError(e.to_string()))?;
        drop(capture_guard);

        if let Some((x, y)) = restore_scroll {
            let _ = self
                .evaluate_js(&format!("window.scrollTo({x}, {y})"))
                .await;
        }

        if let Some(path) = opts.path.clone() {
            fs::write(&path, &bytes).map_err(|e| {
                VoidCrawlError::ScreenshotError(format!("write {}: {e}", path.display()))
            })?;
            Ok(ScreenshotOutput::Path(path))
        } else {
            Ok(ScreenshotOutput::Bytes(bytes))
        }
    }

    /// Current `window.scrollX`/`scrollY`, in CSS pixels.
    pub(in crate::internal::browser) async fn scroll_position(&self) -> Result<(f64, f64)> {
        let value = self.evaluate_js("[window.scrollX, window.scrollY]").await?;
        let arr = value.as_array().ok_or_else(|| {
            VoidCrawlError::JsEvalError("scroll position: expected a [x, y] array".into())
        })?;
        let x = arr
            .first()
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0);
        let y = arr
            .get(1)
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0);
        Ok((x, y))
    }

    /// Scroll to `target` (see [`ScrollTarget`]) and wait for the resulting
    /// layout to actually paint — two animation frames — before the caller
    /// captures, rather than a blind sleep.
    pub(in crate::internal::browser) async fn scroll_to(&self, target: ScrollTarget) -> Result<()> {
        let y = match target {
            ScrollTarget::Pixels(y) => {
                serde_json::Number::from(y)
                    .as_f64()
                    .ok_or(VoidCrawlError::InvalidInput {
                        operation: "scroll_to",
                        reason: "pixel offset could not be represented as a number",
                    })?
            }
            ScrollTarget::Viewports(n) => {
                let height = self
                    .evaluate_js("window.innerHeight")
                    .await?
                    .as_f64()
                    .unwrap_or(0.0);
                height * n
            }
        };
        self.evaluate_js(&format!("window.scrollTo(0, {y})"))
            .await?;
        self.wait_for_repaint().await
    }

    /// Wait for two animation frames — a layout-affecting CDP command
    /// (device-metrics override, scroll) doesn't always reflect in
    /// `window.innerWidth`/`scrollY`/etc. synchronously once the CDP
    /// response returns; this settles it before the caller reads or
    /// captures, without a blind sleep.
    ///
    /// Bounded: `requestAnimationFrame` never fires on a backgrounded tab in
    /// headless Chrome (the same reason `screenshot()` brings a tab to
    /// front before capturing — see `capture_lock`), and this is called
    /// from `set_viewport`/`clear_viewport`, which can run on tabs that are
    /// *not* guaranteed to be foregrounded. An unbounded wait there
    /// would hang the caller forever instead of just being
    /// occasionally stale. Best-effort: on timeout the caller's JS-visible
    /// state may lag by a frame until the tab is next foregrounded or
    /// navigated, which is an acceptable trade for "never hangs."
    pub(super) async fn wait_for_repaint(&self) -> Result<()> {
        let _ = time::timeout(
            Duration::from_millis(500),
            self.evaluate_js(
                "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))",
            ),
        )
        .await;
        Ok(())
    }

    /// Generate a PDF of the page, returned as raw bytes.
    pub async fn pdf_bytes(&self) -> Result<Vec<u8>> {
        let params = PrintToPdfParams::default();
        self.inner
            .pdf(params)
            .await
            .map_err(|e| VoidCrawlError::PdfError(e.to_string()))
    }
}
