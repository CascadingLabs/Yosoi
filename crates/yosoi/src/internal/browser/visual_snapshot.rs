//! Provider-native layout metrics and visual capture metadata.

use std::{
    fmt,
    result::Result as StdResult,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use crate::internal::types::{ByteCount, Viewport};
use serde::Serialize;

use crate::internal::browser::{
    Bbox, BrowserByteDomain, BrowserByteReport, BrowserByteReportError, BrowserTargetKind,
    DocumentScope,
};

/// Layout viewport metrics in CSS pixels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct LayoutViewportMetrics {
    pub page_x: i64,
    pub page_y: i64,
    pub client_width: i64,
    pub client_height: i64,
}

/// Visual viewport metrics in CSS pixels.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct VisualViewportMetrics {
    pub offset_x: f64,
    pub offset_y: f64,
    pub page_x: f64,
    pub page_y: f64,
    pub client_width: f64,
    pub client_height: f64,
    pub scale: f64,
    pub zoom: Option<f64>,
}

/// Scrollable document bounds in CSS pixels.
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct ContentSizeMetrics {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// Point-in-time layout metrics for a document epoch.
#[derive(Debug, Clone, PartialEq)]
pub struct LayoutSnapshot {
    pub scope: DocumentScope,
    pub generated_at_unix_ms: Option<u64>,
    pub layout_viewport: LayoutViewportMetrics,
    pub visual_viewport: VisualViewportMetrics,
    pub content_size: ContentSizeMetrics,
    pub device_scale_factor: Option<f64>,
}

/// Raster format produced by a visual snapshot.
///
/// This provider-native snake-case wire value remains distinct from the
/// durable visual-evidence vocabulary owned by Web Capture.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VisualFormat {
    Png,
}

/// Requested visual capture region.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum VisualCaptureRegion {
    FullPage,
    Viewport,
    BoundingBox { bbox: Bbox },
    BrowserTarget { target_kind: BrowserTargetKind },
}

/// Sequential layout and raster observations from one document epoch.
/// This does not guarantee simultaneous or atomic measurement.
#[derive(Debug, Clone, PartialEq)]
pub struct PairedLayoutVisualSnapshot {
    pub layout: LayoutSnapshot,
    pub visual: VisualSnapshot,
}

/// PNG bytes plus the facts needed to interpret their coordinate space.
#[derive(Clone, PartialEq)]
pub struct VisualSnapshot {
    pub scope: DocumentScope,
    pub generated_at_unix_ms: Option<u64>,
    pub format: VisualFormat,
    pub region: VisualCaptureRegion,
    pub image_width_pixels: u32,
    pub image_height_pixels: u32,
    pub capture_viewport: Viewport,
    pub device_scale_factor: f64,
    pub retained_bytes: usize,
    /// One-shot screenshots are either returned in full or fail without a
    /// `VisualSnapshot`; this explicit fact keeps artifact mapping honest.
    pub complete: bool,
    payload: Arc<[u8]>,
}

impl VisualSnapshot {
    pub fn bytes(&self) -> &[u8] {
        &self.payload
    }

    /// Complete, unbounded accounting for the PNG payload.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::ScreenshotPng,
            None,
            ByteCount::try_from_usize(self.retained_bytes)?,
            ByteCount::try_from_usize(self.retained_bytes)?,
        )
    }
}

impl fmt::Debug for VisualSnapshot {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VisualSnapshot")
            .field("scope", &self.scope)
            .field("generated_at_unix_ms", &self.generated_at_unix_ms)
            .field("format", &self.format)
            .field("region", &self.region)
            .field("image_width_pixels", &self.image_width_pixels)
            .field("image_height_pixels", &self.image_height_pixels)
            .field("capture_viewport", &self.capture_viewport)
            .field("device_scale_factor", &self.device_scale_factor)
            .field("retained_bytes", &self.retained_bytes)
            .field("complete", &self.complete)
            .finish_non_exhaustive()
    }
}

pub(in crate::internal::browser) fn visual_snapshot(
    bytes: Vec<u8>,
    scope: DocumentScope,
    region: VisualCaptureRegion,
    capture_viewport: Viewport,
    device_scale_factor: f64,
) -> Option<VisualSnapshot> {
    let (image_width_pixels, image_height_pixels) = png_dimensions(&bytes)?;
    Some(VisualSnapshot {
        scope,
        generated_at_unix_ms: unix_millis(),
        format: VisualFormat::Png,
        region,
        image_width_pixels,
        image_height_pixels,
        capture_viewport,
        device_scale_factor,
        retained_bytes: bytes.len(),
        complete: true,
        payload: Arc::from(bytes),
    })
}

fn png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    const SIGNATURE: &[u8; 8] = b"\x89PNG\r\n\x1a\n";
    if bytes.get(..8)? != SIGNATURE
        || bytes.get(8..12)? != [0, 0, 0, 13]
        || bytes.get(12..16)? != b"IHDR"
    {
        return None;
    }
    let width = bytes.get(16..20)?.try_into().ok().map(u32::from_be_bytes)?;
    let height = bytes.get(20..24)?.try_into().ok().map(u32::from_be_bytes)?;
    (width > 0 && height > 0).then_some((width, height))
}

fn unix_millis() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

#[cfg(test)]
mod tests {
    use super::png_dimensions;

    #[test]
    fn png_dimensions_reject_short_payloads() {
        assert_eq!(png_dimensions(&[]), None);
    }

    #[test]
    fn png_dimensions_require_signature_ihdr_and_nonzero_dimensions() {
        let mut valid = vec![0_u8; 24];
        valid[..8].copy_from_slice(b"\x89PNG\r\n\x1a\n");
        valid[8..12].copy_from_slice(&13_u32.to_be_bytes());
        valid[12..16].copy_from_slice(b"IHDR");
        valid[16..20].copy_from_slice(&2_u32.to_be_bytes());
        valid[20..24].copy_from_slice(&3_u32.to_be_bytes());
        assert_eq!(png_dimensions(&valid), Some((2, 3)));
        valid[0] = 0;
        assert_eq!(png_dimensions(&valid), None);
    }
}
