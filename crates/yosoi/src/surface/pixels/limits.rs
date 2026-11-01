use crate::surface::SurfaceError;
use serde::{Deserialize, Serialize};

/// Limits independent from text response budgets.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct PixelLimits {
    /// Maximum decoded side length for width or height.
    pub max_side: u32,
    /// Maximum decoder allocation in bytes.
    pub max_decoded_bytes: usize,
    /// Maximum pixels in a returned resized or cropped artifact.
    pub max_output_pixels: u64,
    /// Maximum encoded bytes in one returned artifact.
    pub max_output_bytes: usize,
    /// Maximum derived artifacts retained by a stateful image reader.
    pub max_retained_artifacts: usize,
}

impl Default for PixelLimits {
    fn default() -> Self {
        Self {
            max_side: 8192,
            max_decoded_bytes: 64 * 1024 * 1024,
            max_output_pixels: 16_777_216,
            max_output_bytes: 8 * 1024 * 1024,
            max_retained_artifacts: 32,
        }
    }
}

impl PixelLimits {
    /// Rejects bounds outside the supported decoder and retention envelope.
    pub fn validate(self) -> Result<Self, SurfaceError> {
        if !(1..=8192).contains(&self.max_side)
            || self.max_decoded_bytes == 0
            || self.max_decoded_bytes > 64 * 1024 * 1024
            || self.max_output_pixels == 0
            || self.max_output_pixels > 16_777_216
            || self.max_output_bytes == 0
            || self.max_output_bytes > 32 * 1024 * 1024
            || self.max_retained_artifacts == 0
            || self.max_retained_artifacts > 1024
        {
            return Err(SurfaceError::Invalid(
                "unsupported pixel resource bounds".into(),
            ));
        }
        Ok(self)
    }

    /// Checks a pixel count with overflow-safe arithmetic.
    pub fn check_pixels(self, width: u32, height: u32) -> Result<u64, SurfaceError> {
        if width == 0 || height == 0 || width > self.max_side || height > self.max_side {
            return Err(SurfaceError::Limit("pixel dimensions"));
        }
        let pixels = u64::from(width)
            .checked_mul(u64::from(height))
            .ok_or(SurfaceError::Limit("pixel allocation"))?;
        let decoded = pixels
            .checked_mul(4)
            .ok_or(SurfaceError::Limit("pixel allocation"))?;
        if decoded
            > u64::try_from(self.max_decoded_bytes)
                .map_err(|_| SurfaceError::Limit("decoded pixel allocation"))?
        {
            return Err(SurfaceError::Limit("decoded pixel allocation"));
        }
        Ok(pixels)
    }

    /// Checks returned image pixel and encoded-byte limits.
    pub fn check_output(self, width: u32, height: u32, bytes: usize) -> Result<(), SurfaceError> {
        let pixels = u64::from(width)
            .checked_mul(u64::from(height))
            .ok_or(SurfaceError::Limit("output pixels"))?;
        if width == 0 || height == 0 || pixels > self.max_output_pixels {
            return Err(SurfaceError::Limit("output pixels"));
        }
        if bytes > self.max_output_bytes {
            return Err(SurfaceError::Limit("output image bytes"));
        }
        Ok(())
    }
}

pub(super) fn resized_dimensions(
    width: u32,
    height: u32,
    max_side: u32,
) -> Result<(u32, u32), SurfaceError> {
    if width == 0 || height == 0 || max_side == 0 {
        return Err(SurfaceError::Invalid(
            "resize dimensions must be positive".into(),
        ));
    }
    if width.max(height) <= max_side {
        return Ok((width, height));
    }
    if width >= height {
        let output_height = u64::from(height)
            .checked_mul(u64::from(max_side))
            .and_then(|value| value.checked_div(u64::from(width)))
            .ok_or(SurfaceError::Limit("overview dimensions"))?;
        Ok((
            max_side,
            u32::try_from(output_height.max(1))
                .map_err(|_| SurfaceError::Limit("overview dimensions"))?,
        ))
    } else {
        let output_width = u64::from(width)
            .checked_mul(u64::from(max_side))
            .and_then(|value| value.checked_div(u64::from(height)))
            .ok_or(SurfaceError::Limit("overview dimensions"))?;
        Ok((
            u32::try_from(output_width.max(1))
                .map_err(|_| SurfaceError::Limit("overview dimensions"))?,
            max_side,
        ))
    }
}
