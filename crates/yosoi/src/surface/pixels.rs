//! Checked pixel artifacts shared by image, browser screenshot, and video readers.
//!
//! Coordinates use pixel edges. Derived images map output edges back to an exact
//! parent coordinate plane with checked integer ratios.

#[cfg(any(feature = "browser", feature = "surface-images"))]
mod artifact;
#[cfg(any(feature = "browser", feature = "surface-images"))]
mod identity;
mod limits;
mod model;
#[cfg(any(feature = "browser", feature = "surface-images"))]
mod transform;
#[cfg(any(feature = "browser", feature = "surface-images"))]
mod validation;

#[cfg(any(feature = "browser", feature = "surface-images"))]
pub use identity::{image_source_identity, pixel_source_identity};
pub use limits::PixelLimits;
pub use model::PixelArtifact;
pub use model::{
    PixelArtifactArchiveRef, PixelArtifactInfo, PixelCoordinateKind, PixelCoordinateSpace,
    PixelEdgeTransform, PixelOperation, PixelOrientation, PixelSource, PixelTransform,
};
#[cfg(any(feature = "browser", feature = "surface-images"))]
pub use transform::resize_transform;
