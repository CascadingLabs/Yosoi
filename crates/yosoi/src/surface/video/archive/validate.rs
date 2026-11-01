//! Bounded validation of measured PNG frame evidence.
use super::{DecodedFrame, VideoError};
use image::{ImageFormat, ImageReader};
use sha2::{Digest, Sha256};
use std::io::Cursor;

pub(super) fn validate_pixels(frame: &DecodedFrame) -> Result<(), VideoError> {
    let info = &frame.info;
    if info.width == 0
        || info.height == 0
        || info.canvas_width == 0
        || info.canvas_height == 0
        || info.width > 4096
        || info.height > 4096
        || info.canvas_width > 4096
        || info.canvas_height > 4096
        || frame.png.len() > 32 * 1024 * 1024
        || frame.png.len() != info.png_bytes
        || format!("{:x}", Sha256::digest(&frame.png)) != info.png_sha256
    {
        return Err(VideoError::Invalid(
            "invalid frame pixel metadata or digest".into(),
        ));
    }
    if let Some(rect) = info.region {
        if rect.width != info.width
            || rect.height != info.height
            || rect
                .x
                .checked_add(rect.width)
                .is_none_or(|right| right > info.canvas_width)
            || rect
                .y
                .checked_add(rect.height)
                .is_none_or(|bottom| bottom > info.canvas_height)
        {
            return Err(VideoError::Invalid(
                "crop metadata is outside its decoded canvas".into(),
            ));
        }
    } else if info.width != info.canvas_width || info.height != info.canvas_height {
        return Err(VideoError::Invalid(
            "full frame dimensions differ from canvas".into(),
        ));
    }
    let mut reader = ImageReader::new(Cursor::new(&frame.png)).with_guessed_format()?;
    if reader.format() != Some(ImageFormat::Png) {
        return Err(VideoError::Invalid("frame evidence must be PNG".into()));
    }
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(4096);
    limits.max_image_height = Some(4096);
    limits.max_alloc = Some(64 * 1024 * 1024);
    reader.limits(limits);
    let pixels = reader
        .decode()
        .map_err(|error| VideoError::Invalid(error.to_string()))?;
    let dimensions = (pixels.width(), pixels.height());
    if dimensions != (info.width, info.height) {
        return Err(VideoError::Invalid(
            "frame pixel dimensions differ from metadata".into(),
        ));
    }
    Ok(())
}
