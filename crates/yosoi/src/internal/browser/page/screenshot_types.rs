use std::path::PathBuf;

use crate::internal::browser::selector::BrowserTarget;
use crate::internal::browser::viewport::{ScrollTarget, Viewport};

/// Rectangular crop in CSS pixels for [`ScreenshotOptions::bbox`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub struct Bbox {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

/// Options for [`crate::internal::browser::page::Page::screenshot`].
#[derive(Debug, Clone)]
pub struct ScreenshotOptions {
    /// Write PNG to this path instead of returning bytes.
    pub path: Option<PathBuf>,
    /// Crop to this CSS-pixel region. Takes precedence over `full_page`.
    /// With `scroll` set, coordinates are relative to wherever that scroll
    /// lands rather than the top of the document.
    pub bbox: Option<Bbox>,
    /// Crop to a VoidCrawl browser target's resolved rectangle instead of an
    /// explicit `bbox`. Mutually exclusive with `bbox`: setting both is an
    /// error.
    /// A non-[`Resolved`](crate::internal::browser::selector::TargetResolution::Resolved)
    /// outcome (nothing matched, hidden/zero-area target, ambiguous match,
    /// or a non-visual kind like `jsonld`/`regex`) becomes an actionable
    /// `Err` here — see [`crate::internal::browser::page::Page::resolve_target`] for a version that
    /// returns the typed outcome instead of erroring.
    pub selector: Option<BrowserTarget>,
    /// Apply this viewport/device override for just this capture, then
    /// restore whatever was active before (even on error). See
    /// [`crate::internal::browser::page::Page::set_viewport`] for a persistent version.
    pub viewport: Option<Viewport>,
    /// Scroll to this position before capturing, then restore the original
    /// scroll position after (even on error). Combine with `bbox` to crop a
    /// specific on-screen region after paging down a fixed viewport, or use
    /// alone with `full_page: false` to capture whatever's scrolled into
    /// view without cropping.
    pub scroll: Option<ScrollTarget>,
    /// Capture the full scrollable page (default `true`) vs just what's
    /// currently visible in the viewport. Ignored when `bbox` is set — a
    /// crop always wins. Set `false` via [`ScreenshotOptions::viewport_only`]
    /// to capture only the visible fold: cheaper, and the right choice when
    /// "screenshot this page" really means "what does a visitor see first,"
    /// not the whole scroll history.
    pub full_page: bool,
}

impl Default for ScreenshotOptions {
    fn default() -> Self {
        Self {
            path: None,
            bbox: None,
            selector: None,
            viewport: None,
            scroll: None,
            full_page: true,
        }
    }
}

impl ScreenshotOptions {
    pub fn with_path(mut self, path: impl Into<PathBuf>) -> Self {
        self.path = Some(path.into());
        self
    }

    pub const fn with_bbox(mut self, bbox: Bbox) -> Self {
        self.bbox = Some(bbox);
        self
    }

    pub fn with_selector(mut self, selector: BrowserTarget) -> Self {
        self.selector = Some(selector);
        self
    }

    pub fn with_viewport(mut self, viewport: Viewport) -> Self {
        self.viewport = Some(viewport);
        self
    }

    pub const fn with_scroll(mut self, scroll: ScrollTarget) -> Self {
        self.scroll = Some(scroll);
        self
    }

    /// Capture only the currently visible viewport instead of the full
    /// scrollable page.
    pub const fn viewport_only(mut self) -> Self {
        self.full_page = false;
        self
    }
}

/// Return type of [`crate::internal::browser::page::Page::screenshot`].
#[derive(Debug)]
pub enum ScreenshotOutput {
    /// PNG bytes held in memory (no path supplied).
    Bytes(Vec<u8>),
    /// Path the PNG was written to.
    Path(PathBuf),
}
