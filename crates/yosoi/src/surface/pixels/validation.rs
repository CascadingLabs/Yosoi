use crate::surface::SurfaceError;

use super::{
    identity::{
        artifact_identity, image_media_type, scale_ceil, valid_sha256, verify_decoded_pixels,
    },
    limits::{PixelLimits, resized_dimensions},
    model::{
        PixelArtifact, PixelArtifactInfo, PixelCoordinateKind, PixelCoordinateSpace,
        PixelOperation, PixelOrientation, PixelSource, PixelTransform,
    },
};

impl PixelArtifact {
    /// Validates byte digest, dimensions, identity, source and transform bounds.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        self.validate_metadata()?;
        verify_decoded_pixels(
            &self.document,
            self.info.width,
            self.info.height,
            PixelLimits::default(),
        )
    }

    pub(super) fn validate_metadata(&self) -> Result<(), SurfaceError> {
        if self.info.version != 1
            || self.info.transform.version != 1
            || self.info.width == 0
            || self.info.height == 0
            || self.info.coordinate_space.width != self.info.width
            || self.info.coordinate_space.height != self.info.height
            || self.info.source_space.width == 0
            || self.info.source_space.height == 0
            || self.info.media_type != image_media_type(&self.document)?
            || self.info.sha256 != self.document.sha256()
            || (!matches!(&self.info.transform.operation, PixelOperation::Source)
                && self.document.byte_len() > 32 * 1024 * 1024)
        {
            return Err(SurfaceError::Invalid(
                "pixel artifact metadata does not match its typed image".into(),
            ));
        }
        match &self.info.transform.operation {
            PixelOperation::Source => {
                if self.info.transform.parent_identity.is_some()
                    || self.info.transform.parent_sha256.is_some()
                    || self.info.transform.parent_media_type.is_some()
                    || self.info.transform.parent_space.is_some()
                    || self.info.transform.output_to_parent.is_some()
                    || self.info.coordinate_space != self.info.source_space
                {
                    return Err(SurfaceError::Invalid(
                        "source pixel artifact has derived transform metadata".into(),
                    ));
                }
            }
            _ => {
                let parent_identity = self
                    .info
                    .transform
                    .parent_identity
                    .as_deref()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| {
                        SurfaceError::Invalid("derived artifact lacks parent identity".into())
                    })?;
                let parent_sha256 = self
                    .info
                    .transform
                    .parent_sha256
                    .as_deref()
                    .filter(|value| value.len() == 64)
                    .ok_or_else(|| {
                        SurfaceError::Invalid("derived artifact lacks parent digest".into())
                    })?;
                let parent_media_type = self
                    .info
                    .transform
                    .parent_media_type
                    .as_deref()
                    .filter(|value| matches!(*value, "image/png" | "image/jpeg"))
                    .ok_or_else(|| {
                        SurfaceError::Invalid("derived artifact lacks parent media type".into())
                    })?;
                let parent = self.info.transform.parent_space.ok_or_else(|| {
                    SurfaceError::Invalid("derived artifact lacks parent coordinates".into())
                })?;
                let map = self.info.transform.output_to_parent.ok_or_else(|| {
                    SurfaceError::Invalid("derived artifact lacks coordinate transform".into())
                })?;
                if parent_identity == self.info.identity
                    || parent.width == 0
                    || parent.height == 0
                    || parent.kind == PixelCoordinateKind::DerivedCanvas
                    || parent != self.info.source_space
                    || map.scale_x_numerator == 0
                    || map.scale_x_denominator == 0
                    || map.scale_y_numerator == 0
                    || map.scale_y_denominator == 0
                    || map
                        .translate_x
                        .checked_add(scale_ceil(
                            self.info.width,
                            map.scale_x_numerator,
                            map.scale_x_denominator,
                        )?)
                        .is_none_or(|right| right > parent.width)
                    || map
                        .translate_y
                        .checked_add(scale_ceil(
                            self.info.height,
                            map.scale_y_numerator,
                            map.scale_y_denominator,
                        )?)
                        .is_none_or(|bottom| bottom > parent.height)
                {
                    return Err(SurfaceError::Invalid(
                        "pixel artifact transform exceeds parent coordinates".into(),
                    ));
                }
                let parent_info = PixelArtifactInfo {
                    version: 1,
                    identity: String::new(),
                    sha256: parent_sha256.to_owned(),
                    media_type: parent_media_type.to_owned(),
                    width: parent.width,
                    height: parent.height,
                    source: self.info.source.clone(),
                    coordinate_space: parent,
                    source_space: parent,
                    transform: PixelTransform {
                        version: 1,
                        operation: PixelOperation::Source,
                        parent_identity: None,
                        parent_sha256: None,
                        parent_media_type: None,
                        parent_space: None,
                        output_to_parent: None,
                    },
                };
                if artifact_identity(&parent_info)? != parent_identity {
                    return Err(SurfaceError::Invalid(
                        "derived artifact parent identity is inconsistent".into(),
                    ));
                }
                match &self.info.transform.operation {
                    PixelOperation::Crop { rect } => {
                        if rect.width != self.info.width
                            || rect.height != self.info.height
                            || map.scale_x_numerator != 1
                            || map.scale_x_denominator != 1
                            || map.scale_y_numerator != 1
                            || map.scale_y_denominator != 1
                            || map.translate_x != rect.x
                            || map.translate_y != rect.y
                        {
                            return Err(SurfaceError::Invalid(
                                "crop transform does not match its parent rectangle".into(),
                            ));
                        }
                    }
                    PixelOperation::Overview { max_side, filter } => {
                        if *max_side == 0
                            || self.info.width > *max_side
                            || self.info.height > *max_side
                            || filter != "triangle"
                            || resized_dimensions(parent.width, parent.height, *max_side)?
                                != (self.info.width, self.info.height)
                            || map.scale_x_numerator != parent.width
                            || map.scale_x_denominator != self.info.width
                            || map.scale_y_numerator != parent.height
                            || map.scale_y_denominator != self.info.height
                            || map.translate_x != 0
                            || map.translate_y != 0
                        {
                            return Err(SurfaceError::Invalid(
                                "overview dimensions exceed the requested side".into(),
                            ));
                        }
                    }
                    PixelOperation::Resize {
                        width,
                        height,
                        filter,
                    } if *width != self.info.width
                        || *height != self.info.height
                        || filter != "triangle"
                        || map.scale_x_numerator != parent.width
                        || map.scale_x_denominator != self.info.width
                        || map.scale_y_numerator != parent.height
                        || map.scale_y_denominator != self.info.height
                        || map.translate_x != 0
                        || map.translate_y != 0 =>
                    {
                        return Err(SurfaceError::Invalid(
                            "resize parameters do not match artifact dimensions".into(),
                        ));
                    }
                    PixelOperation::Source => {}
                    PixelOperation::Resize { .. } => {}
                }
            }
        }
        if matches!(&self.info.transform.operation, PixelOperation::Source)
            && let PixelSource::ImageDocument {
                document_id,
                sha256,
            } = &self.info.source
            && (document_id.is_empty()
                || sha256.is_empty()
                || document_id != &self.document.id().to_string()
                || sha256 != self.document.sha256())
        {
            return Err(SurfaceError::Invalid(
                "image source identity is incomplete".into(),
            ));
        }
        match &self.info.source {
            PixelSource::ImageDocument {
                document_id,
                sha256,
            } if document_id.is_empty() || !valid_sha256(sha256) => {
                return Err(SurfaceError::Invalid(
                    "image source identity is incomplete".into(),
                ));
            }
            PixelSource::BrowserScreenshot { identity } if identity.is_empty() => {
                return Err(SurfaceError::Invalid(
                    "screenshot source identity is incomplete".into(),
                ));
            }
            PixelSource::VideoFrame {
                source_document_id,
                source_sha256,
                observation,
                reference,
                ..
            } if source_document_id.is_empty()
                || !valid_sha256(source_sha256)
                || observation.is_empty()
                || reference.is_empty() =>
            {
                return Err(SurfaceError::Invalid(
                    "video frame source identity is incomplete".into(),
                ));
            }
            PixelSource::LegacyVideoFrame {
                source_sha256,
                observation,
                reference,
                ..
            } if source_sha256
                .as_deref()
                .is_some_and(|digest| !valid_sha256(digest))
                || observation.is_empty()
                || reference.is_empty() =>
            {
                return Err(SurfaceError::Invalid(
                    "legacy video frame provenance is invalid".into(),
                ));
            }
            _ => {}
        }
        match (&self.info.source, self.info.coordinate_space) {
            (
                PixelSource::ImageDocument { .. },
                PixelCoordinateSpace {
                    kind: PixelCoordinateKind::OriginalRaster,
                    orientation: PixelOrientation::ExifUnapplied,
                    ..
                },
            ) => {}
            (
                PixelSource::VideoFrame { .. },
                PixelCoordinateSpace {
                    kind: PixelCoordinateKind::DecodedCanvas,
                    orientation: PixelOrientation::DecoderApplied,
                    ..
                },
            ) => {}
            (
                PixelSource::LegacyVideoFrame { .. },
                PixelCoordinateSpace {
                    kind: PixelCoordinateKind::DecodedCanvas,
                    orientation: PixelOrientation::DecoderApplied,
                    ..
                },
            ) => {}
            (
                PixelSource::BrowserScreenshot { .. },
                PixelCoordinateSpace {
                    kind: PixelCoordinateKind::DecodedCanvas,
                    orientation: PixelOrientation::NotApplicable,
                    ..
                },
            ) => {}
            (source, space)
                if matches!(&self.info.transform.operation, PixelOperation::Source)
                    && (space.kind == PixelCoordinateKind::DerivedCanvas
                        || match source {
                            PixelSource::ImageDocument { .. } => {
                                space.orientation != PixelOrientation::ExifUnapplied
                            }
                            PixelSource::VideoFrame { .. } => {
                                space.orientation != PixelOrientation::DecoderApplied
                            }
                            PixelSource::LegacyVideoFrame { .. } => {
                                space.orientation != PixelOrientation::DecoderApplied
                            }
                            PixelSource::BrowserScreenshot { .. } => {
                                space.orientation != PixelOrientation::NotApplicable
                            }
                        }) =>
            {
                return Err(SurfaceError::Invalid(
                    "pixel source coordinate space or orientation is unsupported".into(),
                ));
            }
            _ => {}
        }
        let expected = artifact_identity(&self.info)?;
        if self.info.identity != expected {
            return Err(SurfaceError::Invalid(
                "pixel artifact identity does not match its provenance".into(),
            ));
        }
        Ok(())
    }
}
