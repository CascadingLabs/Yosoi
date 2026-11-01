use crate::{documents::ImageDocument, surface::SurfaceError};
use image::{ImageFormat, ImageReader};
use sha2::{Digest, Sha256};
use std::io::Cursor;

use super::{
    limits::PixelLimits,
    model::{PixelArtifactInfo, PixelSource},
};

/// Stable identity for an original image, independent of Surface options.
pub fn image_source_identity(document: &ImageDocument) -> Result<String, SurfaceError> {
    pixel_source_identity(&PixelSource::ImageDocument {
        document_id: document.id().to_string(),
        sha256: document.sha256().to_owned(),
    })
}

/// Computes a stable source key from the typed producer identity and exact source digest.
pub fn pixel_source_identity(source: &PixelSource) -> Result<String, SurfaceError> {
    let key = serde_json::to_vec(&("yosoi.pixel-source.v1", source))
        .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    Ok(format!("pixel-source-v1:{:x}", Sha256::digest(key)))
}

pub(super) fn artifact_identity(info: &PixelArtifactInfo) -> Result<String, SurfaceError> {
    let key = serde_json::to_vec(&(
        "yosoi.pixel-artifact.v1",
        &info.sha256,
        &info.media_type,
        info.width,
        info.height,
        &info.source,
        info.coordinate_space,
        info.source_space,
        &info.transform,
    ))
    .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    Ok(format!("pixel-artifact-v1:{:x}", Sha256::digest(key)))
}

pub(super) fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

pub(super) fn image_media_type(document: &ImageDocument) -> Result<String, SurfaceError> {
    match document.metadata().detected_media_type() {
        Some(media_type @ ("image/png" | "image/jpeg")) => Ok(media_type.to_owned()),
        _ => Err(SurfaceError::Invalid(
            "pixel artifacts require a PNG or JPEG ImageDocument".into(),
        )),
    }
}

pub(super) fn verify_dimensions(
    document: &ImageDocument,
    expected_width: u32,
    expected_height: u32,
) -> Result<(), SurfaceError> {
    let media_type = image_media_type(document)?;
    let mut reader = ImageReader::new(Cursor::new(document.bytes()))
        .with_guessed_format()
        .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    let expected_format = match media_type.as_str() {
        "image/png" => ImageFormat::Png,
        "image/jpeg" => ImageFormat::Jpeg,
        _ => {
            return Err(SurfaceError::Invalid(
                "unsupported pixel artifact format".into(),
            ));
        }
    };
    if reader.format() != Some(expected_format) {
        return Err(SurfaceError::Invalid(
            "pixel artifact encoded format differs from typed metadata".into(),
        ));
    }
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(PixelLimits::default().max_side);
    limits.max_image_height = Some(PixelLimits::default().max_side);
    limits.max_alloc = Some(
        u64::try_from(PixelLimits::default().max_decoded_bytes)
            .map_err(|_| SurfaceError::Limit("decoded pixel allocation"))?,
    );
    reader.limits(limits);
    let (width, height) = reader
        .into_dimensions()
        .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    PixelLimits::default().check_pixels(width, height)?;
    if width != expected_width || height != expected_height {
        return Err(SurfaceError::Invalid(
            "pixel artifact dimensions differ from encoded pixels".into(),
        ));
    }
    Ok(())
}

pub(super) fn scale_ceil(
    value: u32,
    numerator: u32,
    denominator: u32,
) -> Result<u32, SurfaceError> {
    let product = u64::from(value)
        .checked_mul(u64::from(numerator))
        .ok_or(SurfaceError::Limit("pixel coordinate transform"))?;
    let divisor = u64::from(denominator);
    let scaled = product
        .checked_add(divisor.saturating_sub(1))
        .and_then(|result| result.checked_div(divisor))
        .ok_or(SurfaceError::Limit("pixel coordinate transform"))?;
    u32::try_from(scaled).map_err(|_| SurfaceError::Limit("pixel coordinate transform"))
}
