//! Image index, shared reader, and derived pixel operations.

use super::PixelRect;

mod index;
mod operations;
mod reader;

pub(super) use index::{ImageData, region_digest};
pub use operations::ImageCrop;
pub use reader::ImageSurface;
