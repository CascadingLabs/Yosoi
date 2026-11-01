use super::PixelRect;
use crate::documents::{FileLimits, FileMetadata, ImageDocument};
use crate::surface::{
    Payload, PixelArtifact, PixelLimits, PixelOperation, Reference, Surface, SurfaceError,
};
use image::{DynamicImage, ImageFormat, imageops::FilterType};
use sha2::{Digest, Sha256};
use std::io::Cursor;

/// Actual typed PNG pixel artifact for an indexed image region.
#[derive(Clone, Debug)]
pub struct ImageCrop {
    /// Exact captured region from which these pixels were cropped.
    pub reference: Reference,
    /// Crop bounds in the original image coordinate system.
    pub rect: PixelRect,
    /// Exact encoded pixels and their source/coordinate provenance.
    pub artifact: PixelArtifact,
}

impl ImageCrop {
    /// Borrows exact encoded PNG bytes; the artifact byte limit applies to this payload.
    pub fn png(&self) -> &[u8] {
        self.artifact.bytes()
    }
}
impl Surface {
    pub(crate) fn prepared_image_artifact(&self) -> Result<&PixelArtifact, SurfaceError> {
        self.data
            .image
            .as_ref()
            .map(|image| &image.artifact)
            .ok_or(SurfaceError::Unknown)
    }

    /// Returns the original encoded image as a typed pixel artifact.
    pub fn direct_image(&self) -> Result<PixelArtifact, SurfaceError> {
        let image = self.data.image.as_ref().ok_or(SurfaceError::Unknown)?;
        image.limits.check_output(
            image.artifact.info().width,
            image.artifact.info().height,
            image.artifact.bytes().len(),
        )?;
        Ok(image.artifact.clone())
    }

    /// Returns an explicit aspect-preserving overview, or the source directly when it already fits.
    pub fn overview_image(&self, max_side: u32) -> Result<PixelArtifact, SurfaceError> {
        let image = self.data.image.as_ref().ok_or(SurfaceError::Unknown)?;
        if max_side == 0 || max_side > image.limits.max_side {
            return Err(SurfaceError::Invalid(
                "overview max_side is outside image limits".into(),
            ));
        }
        let (width, height) = resized_dimensions(
            image.artifact.info().width,
            image.artifact.info().height,
            max_side,
        )?;
        if width == image.artifact.info().width && height == image.artifact.info().height {
            return self.direct_image();
        }
        self.resize_image_with_operation(
            width,
            height,
            PixelOperation::Overview {
                max_side,
                filter: "triangle".into(),
            },
        )
    }

    /// Resizes the original raster to exact dimensions using the declared triangle filter.
    pub fn resize_image(&self, width: u32, height: u32) -> Result<PixelArtifact, SurfaceError> {
        self.resize_image_with_operation(
            width,
            height,
            PixelOperation::Resize {
                width,
                height,
                filter: "triangle".into(),
            },
        )
    }

    fn resize_image_with_operation(
        &self,
        width: u32,
        height: u32,
        operation: PixelOperation,
    ) -> Result<PixelArtifact, SurfaceError> {
        let image = self.data.image.as_ref().ok_or(SurfaceError::Unknown)?;
        image.limits.check_pixels(width, height)?;
        let output_pixels = u64::from(width)
            .checked_mul(u64::from(height))
            .ok_or(SurfaceError::Limit("output pixels"))?;
        if output_pixels > image.limits.max_output_pixels {
            return Err(SurfaceError::Limit("output pixels"));
        }
        let resized = image
            .pixels
            .resize_exact(width, height, FilterType::Triangle);
        let document = png_document(
            &resized,
            image.artifact.info().identity.as_str(),
            image.limits,
        )?;
        PixelArtifact::resize_from(&image.artifact, document, operation, width, height)
    }

    /// Returns actual PNG pixels from an image reference, rejecting foreign or non-image nodes.
    /// The binary PNG payload must fit `max_png_bytes`; text response budgets are separate.
    pub fn crop(
        &self,
        reference: &Reference,
        max_png_bytes: usize,
    ) -> Result<ImageCrop, SurfaceError> {
        if max_png_bytes == 0 {
            return Err(SurfaceError::Limit("crop PNG bytes"));
        }
        let node = self.node(reference)?;
        if let Payload::External { view, node } = node.payload {
            let (_, source) = self.data.views.get(view).ok_or(SurfaceError::Unknown)?;
            let mut crop = source.crop(&source.reference(node), max_png_bytes)?;
            crop.reference = reference.clone();
            return Ok(crop);
        }
        let Payload::Image(rect) = node.payload else {
            return Err(SurfaceError::Invalid(
                "reference is not an image region".into(),
            ));
        };
        self.crop_raster_rect(reference, rect, max_png_bytes)
    }

    /// Crops exact original-raster coordinates without selecting a tree node first.
    pub fn crop_image(
        &self,
        rect: PixelRect,
        max_png_bytes: usize,
    ) -> Result<ImageCrop, SurfaceError> {
        if max_png_bytes == 0 {
            return Err(SurfaceError::Limit("crop PNG bytes"));
        }
        self.crop_raster_rect(&self.root(), rect, max_png_bytes)
    }

    fn crop_raster_rect(
        &self,
        reference: &Reference,
        rect: PixelRect,
        max_png_bytes: usize,
    ) -> Result<ImageCrop, SurfaceError> {
        let image = self.data.image.as_ref().ok_or(SurfaceError::Unknown)?;
        let right = rect
            .x
            .checked_add(rect.width)
            .ok_or(SurfaceError::Limit("image coordinate"))?;
        let bottom = rect
            .y
            .checked_add(rect.height)
            .ok_or(SurfaceError::Limit("image coordinate"))?;
        if right > image.pixels.width()
            || bottom > image.pixels.height()
            || rect.width == 0
            || rect.height == 0
        {
            return Err(SurfaceError::Invalid("crop outside raster".into()));
        }
        let crop = image
            .pixels
            .crop_imm(rect.x, rect.y, rect.width, rect.height);
        let limits = PixelLimits {
            max_output_bytes: image.limits.max_output_bytes.min(max_png_bytes),
            ..image.limits
        };
        limits.check_output(rect.width, rect.height, 0)?;
        let document = png_document(&crop, image.artifact.info().identity.as_str(), limits)?;
        let artifact = PixelArtifact::crop_from(&image.artifact, document, rect)?;
        Ok(ImageCrop {
            reference: reference.clone(),
            rect,
            artifact,
        })
    }
}

fn resized_dimensions(width: u32, height: u32, max_side: u32) -> Result<(u32, u32), SurfaceError> {
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

fn png_document(
    image: &DynamicImage,
    parent_identity: &str,
    limits: PixelLimits,
) -> Result<ImageDocument, SurfaceError> {
    let width = image.width();
    let height = image.height();
    let pixels = limits.check_pixels(width, height)?;
    if pixels > limits.max_output_pixels {
        return Err(SurfaceError::Limit("output pixels"));
    }
    let mut output = Cursor::new(Vec::new());
    image
        .write_to(&mut output, ImageFormat::Png)
        .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    let png = output.into_inner();
    limits.check_output(width, height, png.len())?;
    let digest = Sha256::digest(&png);
    let id = format!("pixel-{digest:x}");
    let metadata = FileMetadata::new()
        .with_declared_media_type("image/png")
        .and_then(|metadata| metadata.with_source(parent_identity))
        .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
    ImageDocument::from_bytes_with_metadata(
        id,
        png,
        metadata,
        FileLimits::new(
            u64::try_from(limits.max_output_bytes)
                .map_err(|_| SurfaceError::Limit("output image bytes"))?,
        )
        .map_err(|error| SurfaceError::Invalid(error.to_string()))?,
    )
    .map_err(|error| SurfaceError::Invalid(error.to_string()))
}
