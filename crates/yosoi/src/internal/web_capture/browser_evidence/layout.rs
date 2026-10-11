use super::{BrowserDocumentScope, CaptureOffset};
use serde::Serialize;

/// Integer micro-CSS-pixel geometry avoids nonfinite floating-point values.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
#[allow(
    clippy::struct_field_names,
    reason = "coordinate field names preserve explicit units and wire compatibility"
)]
pub struct BrowserLayoutRect {
    pub x_micro_css: i64,
    pub y_micro_css: i64,
    pub width_micro_css: u64,
    pub height_micro_css: u64,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserLayoutFact {
    pub scope: BrowserDocumentScope,
    pub at: CaptureOffset,
    pub layout_viewport: BrowserLayoutRect,
    pub visual_viewport: BrowserLayoutRect,
    pub content: BrowserLayoutRect,
    pub device_scale_micro: Option<u64>,
}
