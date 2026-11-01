use crate::{
    archive::{Archive, ArchiveError},
    documents::ImageDocument,
    surface::{PixelRect, SurfaceError},
};

use super::{
    identity::{artifact_identity, image_media_type, pixel_source_identity, verify_dimensions},
    model::{
        PixelArtifact, PixelArtifactArchiveRef, PixelArtifactInfo, PixelCoordinateKind,
        PixelCoordinateSpace, PixelEdgeTransform, PixelOperation, PixelOrientation, PixelSource,
        PixelTransform,
    },
    transform::resize_transform,
};

impl PixelArtifact {
    /// Creates a source artifact from a typed image document and validated dimensions.
    /// ImageDocument coordinates are its encoded raster; pass `ExifUnapplied`.
    pub fn from_image_document(
        document: ImageDocument,
        width: u32,
        height: u32,
        orientation: PixelOrientation,
    ) -> Result<Self, SurfaceError> {
        verify_dimensions(&document, width, height)?;
        let space = PixelCoordinateSpace {
            kind: PixelCoordinateKind::OriginalRaster,
            width,
            height,
            orientation,
        };
        let source = PixelSource::ImageDocument {
            document_id: document.id().to_string(),
            sha256: document.sha256().to_owned(),
        };
        Self::from_raster_document(document, source, space)
    }

    /// Creates a root raster artifact from an image-producing source such as a video frame.
    pub fn from_raster_document(
        document: ImageDocument,
        source: PixelSource,
        coordinate_space: PixelCoordinateSpace,
    ) -> Result<Self, SurfaceError> {
        verify_dimensions(&document, coordinate_space.width, coordinate_space.height)?;
        let media_type = image_media_type(&document)?;
        let mut artifact = Self {
            document,
            info: PixelArtifactInfo {
                version: 1,
                identity: String::new(),
                sha256: String::new(),
                media_type,
                width: coordinate_space.width,
                height: coordinate_space.height,
                source,
                coordinate_space,
                source_space: coordinate_space,
                transform: PixelTransform {
                    version: 1,
                    operation: PixelOperation::Source,
                    parent_identity: None,
                    parent_sha256: None,
                    parent_media_type: None,
                    parent_space: None,
                    output_to_parent: None,
                },
            },
        };
        artifact.refresh_identity()?;
        artifact.validate()?;
        Ok(artifact)
    }

    /// Crops only a root source artifact; nested artifact crops are rejected.
    pub fn crop_from(
        parent: &Self,
        document: ImageDocument,
        rect: PixelRect,
    ) -> Result<Self, SurfaceError> {
        parent.validate()?;
        if !matches!(&parent.info.transform.operation, PixelOperation::Source) {
            return Err(SurfaceError::Invalid(
                "nested pixel artifact transforms are unsupported".into(),
            ));
        }
        let right = rect
            .x
            .checked_add(rect.width)
            .ok_or(SurfaceError::Limit("pixel crop coordinates"))?;
        let bottom = rect
            .y
            .checked_add(rect.height)
            .ok_or(SurfaceError::Limit("pixel crop coordinates"))?;
        if rect.width == 0
            || rect.height == 0
            || right > parent.info.width
            || bottom > parent.info.height
        {
            return Err(SurfaceError::Invalid(
                "pixel crop is empty or outside its parent".into(),
            ));
        }
        let transform = PixelTransform {
            version: 1,
            operation: PixelOperation::Crop { rect },
            parent_identity: Some(parent.info.identity.clone()),
            parent_sha256: Some(parent.info.sha256.clone()),
            parent_media_type: Some(parent.info.media_type.clone()),
            parent_space: Some(parent.info.coordinate_space),
            output_to_parent: Some(PixelEdgeTransform {
                scale_x_numerator: 1,
                scale_x_denominator: 1,
                scale_y_numerator: 1,
                scale_y_denominator: 1,
                translate_x: rect.x,
                translate_y: rect.y,
            }),
        };
        Self::derived_internal(
            parent,
            document,
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DerivedCanvas,
                width: rect.width,
                height: rect.height,
                orientation: parent.info.coordinate_space.orientation,
            },
            transform,
        )
    }

    /// Resizes only a root source artifact using explicit dimensions and parameters.
    pub fn resize_from(
        parent: &Self,
        document: ImageDocument,
        operation: PixelOperation,
        width: u32,
        height: u32,
    ) -> Result<Self, SurfaceError> {
        parent.validate()?;
        if !matches!(&parent.info.transform.operation, PixelOperation::Source) {
            return Err(SurfaceError::Invalid(
                "nested pixel artifact transforms are unsupported".into(),
            ));
        }
        let transform = resize_transform(parent, operation, width, height)?;
        Self::derived_internal(
            parent,
            document,
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DerivedCanvas,
                width,
                height,
                orientation: parent.info.coordinate_space.orientation,
            },
            transform,
        )
    }

    fn derived_internal(
        parent: &Self,
        document: ImageDocument,
        coordinate_space: PixelCoordinateSpace,
        transform: PixelTransform,
    ) -> Result<Self, SurfaceError> {
        verify_dimensions(&document, coordinate_space.width, coordinate_space.height)?;
        let media_type = image_media_type(&document)?;
        let mut artifact = Self {
            info: PixelArtifactInfo {
                version: 1,
                identity: String::new(),
                sha256: String::new(),
                media_type,
                width: coordinate_space.width,
                height: coordinate_space.height,
                source: parent.info.source.clone(),
                coordinate_space,
                source_space: parent.info.source_space,
                transform,
            },
            document,
        };
        artifact.refresh_identity()?;
        artifact.validate()?;
        Ok(artifact)
    }

    /// Reconstructs a checked artifact from an Archive record.
    pub(crate) fn from_archived_parts(
        document: ImageDocument,
        info: PixelArtifactInfo,
    ) -> Result<Self, SurfaceError> {
        let artifact = Self { document, info };
        artifact.validate()?;
        Ok(artifact)
    }

    /// Returns the typed payload and its exact encoded bytes.
    pub const fn document(&self) -> &ImageDocument {
        &self.document
    }

    /// Returns the checked source, dimension, digest and coordinate provenance.
    pub const fn info(&self) -> &PixelArtifactInfo {
        &self.info
    }

    /// Returns the stable identity of the root pixel source, independent of derived operations.
    pub fn source_identity(&self) -> Result<String, SurfaceError> {
        pixel_source_identity(&self.info.source)
    }

    /// Maps an output-space rectangle to the root source pixel edges.
    /// Derived artifacts have only one validated parent transform; nested maps are rejected.
    pub fn map_rect_to_source(&self, rect: PixelRect) -> Result<PixelRect, SurfaceError> {
        self.validate()?;
        let right = rect
            .x
            .checked_add(rect.width)
            .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        let bottom = rect
            .y
            .checked_add(rect.height)
            .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        if rect.width == 0
            || rect.height == 0
            || right > self.info.width
            || bottom > self.info.height
        {
            return Err(SurfaceError::Invalid(
                "pixel rectangle is empty or outside artifact coordinates".into(),
            ));
        }
        if matches!(&self.info.transform.operation, PixelOperation::Source) {
            return Ok(rect);
        }
        let parent = self.info.transform.parent_space.ok_or_else(|| {
            SurfaceError::Invalid("artifact lacks parent coordinates".into())
        })?;
        if parent.kind == PixelCoordinateKind::DerivedCanvas || parent != self.info.source_space {
            return Err(SurfaceError::Invalid(
                "nested pixel coordinate transforms are unsupported".into(),
            ));
        }
        let transform = self.info.transform.output_to_parent.ok_or_else(|| {
            SurfaceError::Invalid("artifact lacks a coordinate transform".into())
        })?;
        let x0 = edge_floor(
            rect.x,
            transform.scale_x_numerator,
            transform.scale_x_denominator,
        )?
        .checked_add(transform.translate_x)
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        let y0 = edge_floor(
            rect.y,
            transform.scale_y_numerator,
            transform.scale_y_denominator,
        )?
        .checked_add(transform.translate_y)
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        let x1 = edge_ceil(
            right,
            transform.scale_x_numerator,
            transform.scale_x_denominator,
        )?
        .checked_add(transform.translate_x)
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        let y1 = edge_ceil(
            bottom,
            transform.scale_y_numerator,
            transform.scale_y_denominator,
        )?
        .checked_add(transform.translate_y)
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
        if x1 > parent.width || y1 > parent.height || x1 <= x0 || y1 <= y0 {
            return Err(SurfaceError::Invalid(
                "mapped pixel rectangle is outside source coordinates".into(),
            ));
        }
        Ok(PixelRect {
            x: x0,
            y: y0,
            width: x1.checked_sub(x0).ok_or(SurfaceError::Limit("pixel coordinate map"))?,
            height: y1
                .checked_sub(y0)
                .ok_or(SurfaceError::Limit("pixel coordinate map"))?,
        })
    }

    /// Returns the exact encoded artifact bytes.
    pub fn bytes(&self) -> &[u8] {
        self.document.bytes()
    }
}

fn edge_floor(value: u32, numerator: u32, denominator: u32) -> Result<u32, SurfaceError> {
    if denominator == 0 {
        return Err(SurfaceError::Invalid(
            "pixel coordinate denominator is zero".into(),
        ));
    }
    let mapped = u64::from(value)
        .checked_mul(u64::from(numerator))
        .and_then(|result| result.checked_div(u64::from(denominator)))
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
    u32::try_from(mapped).map_err(|_| SurfaceError::Limit("pixel coordinate map"))
}

fn edge_ceil(value: u32, numerator: u32, denominator: u32) -> Result<u32, SurfaceError> {
    if denominator == 0 {
        return Err(SurfaceError::Invalid(
            "pixel coordinate denominator is zero".into(),
        ));
    }
    let divisor = u64::from(denominator);
    let mapped = u64::from(value)
        .checked_mul(u64::from(numerator))
        .and_then(|result| result.checked_add(divisor.saturating_sub(1)))
        .and_then(|result| result.checked_div(divisor))
        .ok_or(SurfaceError::Limit("pixel coordinate map"))?;
    u32::try_from(mapped).map_err(|_| SurfaceError::Limit("pixel coordinate map"))
}

impl PixelArtifact {
    /// Stores metadata through the existing Archive and pixels in its typed image payload store.
    pub async fn write_to(
        &self,
        archive: &Archive,
    ) -> Result<PixelArtifactArchiveRef, ArchiveError> {
        archive.write(self).await
    }

    /// Restores exact pixels and checked provenance without a source file or decoder.
    pub async fn read_from(
        archive: &Archive,
        reference: &PixelArtifactArchiveRef,
    ) -> Result<Self, ArchiveError> {
        archive.read(reference).await
    }

    fn refresh_identity(&mut self) -> Result<(), SurfaceError> {
        self.info.sha256 = self.document.sha256().to_owned();
        self.info.identity = artifact_identity(&self.info)?;
        Ok(())
    }
}
