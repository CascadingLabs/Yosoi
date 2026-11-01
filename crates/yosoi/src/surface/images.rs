//! Typed raster ingestion and read-only image Surface adapters.

use serde::{Deserialize, Serialize};

/// Pixel rectangle in an exact captured raster, with exclusive right/bottom edges.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct PixelRect {
    /// Left pixel coordinate.
    pub x: u32,
    /// Top pixel coordinate.
    pub y: u32,
    /// Positive region width.
    pub width: u32,
    /// Positive region height.
    pub height: u32,
}

#[cfg(any(feature = "browser", feature = "surface-images"))]
mod enabled;

#[cfg(any(feature = "browser", feature = "surface-images"))]
pub use enabled::{ImageCrop, ImageSurface};
#[cfg(any(feature = "browser", feature = "surface-images"))]
pub(super) use enabled::{ImageData, region_digest};
