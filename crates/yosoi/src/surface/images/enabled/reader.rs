use super::{ImageCrop, PixelRect};
use crate::documents::ImageDocument;
use crate::surface::{
    Budget, Continuation, Limits, PixelArtifact, PixelLimits, Reference, Surface, SurfaceError,
    model::{
        self, Access, AddressToken, Capability, ContinuationToken, Descriptor, Observation,
        ObservationId, ReadOperation, ReadRequest, ReadResult, SourceId, SurfaceId, SurfaceRead,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Read-only shared navigation over one typed image's bounded region index.
#[derive(Clone, Debug)]
pub struct ImageSurface {
    index: Surface,
    document: ImageDocument,
    source_artifact: PixelArtifact,
    descriptor: Descriptor,
    observation: Observation,
    root: model::Reference,
}

impl ImageSurface {
    /// Decodes a typed ImageDocument and binds its source identity to the shared reader model.
    pub fn from_image_document(
        document: &ImageDocument,
        tile_side: u32,
        limits: Limits,
        pixel_limits: PixelLimits,
    ) -> Result<Self, SurfaceError> {
        let index = Surface::from_image_document_with_pixel_limits(
            document,
            tile_side,
            limits,
            pixel_limits,
        )?;
        let artifact = index.prepared_image_artifact()?.clone();
        let source_identity = artifact.source_identity()?;
        Self::from_index(index, document.clone(), artifact, source_identity)
    }

    /// Opens a root PixelArtifact while preserving its existing source identity and coordinates.
    /// A derived artifact cannot become a new coordinate root.
    pub fn from_pixel_artifact(
        artifact: &PixelArtifact,
        tile_side: u32,
        limits: Limits,
        pixel_limits: PixelLimits,
    ) -> Result<Self, SurfaceError> {
        let index = Surface::from_pixel_artifact_with_pixel_limits(
            artifact,
            tile_side,
            limits,
            pixel_limits,
        )?;
        let source_identity = artifact.source_identity()?;
        Self::from_index(
            index,
            artifact.document().clone(),
            artifact.clone(),
            source_identity,
        )
    }

    fn from_index(
        index: Surface,
        document: ImageDocument,
        source_artifact: PixelArtifact,
        source_identity: String,
    ) -> Result<Self, SurfaceError> {
        let source = SourceId::new(source_identity)?;
        let id = SurfaceId::new(format!("image:{}", source.as_str()))?;
        let capabilities = [
            "overview",
            "expand",
            "inspect",
            "parent",
            "direct",
            "overview_pixels",
            "resize",
            "crop",
        ]
        .into_iter()
        .map(|name| Capability {
            id: format!("image.{name}@1"),
            access: Access::Read,
            control_domain: None,
            input_schema: if name == "overview_pixels" {
                "yosoi.surface.pixel.overview.v1".into()
            } else if name == "resize" {
                "yosoi.surface.pixel.resize.v1".into()
            } else if name == "crop" {
                "yosoi.surface.pixel.crop.v1".into()
            } else if name == "direct" {
                "yosoi.surface.pixel.direct.v1".into()
            } else {
                format!("yosoi.surface.read.{name}.v1")
            },
        })
        .collect();
        let descriptor = Descriptor {
            id: id.clone(),
            source: source.clone(),
            representation: "yosoi.image.raster.v1".into(),
            controllable: false,
            capabilities,
        };
        let mut digest = Sha256::new();
        digest.update(b"yosoi-image-observation-v1");
        digest.update(index.identity().as_bytes());
        digest.update(source.as_str().as_bytes());
        let observation = Observation {
            id: ObservationId::new(format!("image-v1:{:x}", digest.finalize()))?,
            surface: id,
            coverage: index.coverage().clone(),
        };
        let root = model::Reference {
            observation: observation.id.clone(),
            address: AddressToken::new(format!("n:{}", index.root().node))?,
        };
        Ok(Self {
            index,
            document: document.clone(),
            source_artifact,
            descriptor,
            observation,
            root,
        })
    }

    /// Returns the exact underlying image index.
    pub const fn index(&self) -> &Surface {
        &self.index
    }

    /// Returns the encoded image payload indexed by this reader.
    pub const fn source_document(&self) -> &ImageDocument {
        &self.document
    }

    /// Returns the root PixelArtifact with its original source and coordinate provenance.
    pub const fn source_artifact(&self) -> &PixelArtifact {
        &self.source_artifact
    }

    /// Converts an index reference into a source-bound common reader address.
    pub fn reference(&self, reference: &Reference) -> Result<model::Reference, SurfaceError> {
        self.index.validate(reference)?;
        Ok(model::Reference {
            observation: self.observation.id.clone(),
            address: AddressToken::new(format!("n:{}", reference.node))?,
        })
    }

    /// Resolves and validates a common reader address for this exact observation.
    pub fn native_reference(
        &self,
        reference: &model::Reference,
    ) -> Result<Reference, SurfaceError> {
        if reference.observation != self.observation.id {
            return Err(SurfaceError::WrongCapture);
        }
        let value = reference
            .address
            .as_str()
            .strip_prefix("n:")
            .ok_or_else(|| SurfaceError::Invalid("not an image address".into()))?;
        let node = value
            .parse::<usize>()
            .map_err(|_| SurfaceError::Invalid("invalid image address".into()))?;
        if node.to_string() != value {
            return Err(SurfaceError::Invalid("noncanonical image address".into()));
        }
        let native = Reference {
            capture: self.index.identity().into(),
            node,
        };
        self.index.validate(&native)?;
        Ok(native)
    }

    /// Returns the original encoded image without routing through region navigation.
    pub fn direct_image(&self) -> Result<PixelArtifact, SurfaceError> {
        self.index.direct_image()
    }

    /// Materializes an explicit overview under the image Surface's output bounds.
    pub fn overview_image(&self, max_side: u32) -> Result<PixelArtifact, SurfaceError> {
        self.index.overview_image(max_side)
    }

    /// Materializes an explicitly sized resize under the image Surface's output bounds.
    pub fn resize_image(&self, width: u32, height: u32) -> Result<PixelArtifact, SurfaceError> {
        self.index.resize_image(width, height)
    }

    /// Crops a region reference in the original image coordinate space.
    pub fn crop(
        &self,
        reference: &model::Reference,
        max_png_bytes: usize,
    ) -> Result<ImageCrop, SurfaceError> {
        self.index
            .crop(&self.native_reference(reference)?, max_png_bytes)
    }

    /// Crops explicit source-raster bounds under the image output budget.
    pub fn crop_rect(
        &self,
        rect: PixelRect,
        max_png_bytes: usize,
    ) -> Result<ImageCrop, SurfaceError> {
        self.index.crop_image(rect, max_png_bytes)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ImageCursor {
    observation: ObservationId,
    native: Continuation,
}

fn encode_cursor(
    token: Continuation,
    observation: &ObservationId,
) -> Result<ContinuationToken, SurfaceError> {
    ContinuationToken::new(
        serde_json::to_string(&ImageCursor {
            observation: observation.clone(),
            native: token,
        })
        .map_err(|error| SurfaceError::Parse(error.to_string()))?,
    )
}

fn decode_cursor(
    token: &ContinuationToken,
    observation: &ObservationId,
) -> Result<Continuation, SurfaceError> {
    let cursor: ImageCursor = serde_json::from_str(token.as_str())
        .map_err(|error| SurfaceError::Parse(error.to_string()))?;
    if &cursor.observation != observation {
        return Err(SurfaceError::WrongCapture);
    }
    Ok(cursor.native)
}

impl SurfaceRead for ImageSurface {
    fn descriptor(&self) -> &Descriptor {
        &self.descriptor
    }

    fn observation(&self) -> &Observation {
        &self.observation
    }

    fn root_reference(&self) -> model::Reference {
        self.root.clone()
    }

    fn read(&self, request: &ReadRequest) -> Result<ReadResult, SurfaceError> {
        if request.budget.bytes < 512 || request.budget.bytes > 65536 {
            return Err(SurfaceError::Invalid(
                "read budget must be 512..65536 bytes".into(),
            ));
        }
        let token = request
            .continuation
            .as_ref()
            .map(|token| decode_cursor(token, &self.observation.id))
            .transpose()?;
        if matches!(request.operation, ReadOperation::Parent { .. })
            && request.continuation.is_some()
        {
            return Err(SurfaceError::Invalid(
                "parent does not accept a continuation".into(),
            ));
        }
        let mut items = request.budget.items.clamp(1, 100);
        loop {
            let budget = Budget {
                bytes: request.budget.bytes.saturating_sub(256),
                items,
            };
            let result = match &request.operation {
                ReadOperation::Parent { reference } => ReadResult::Parent(
                    self.index
                        .parent(&self.native_reference(reference)?)?
                        .map(|value| self.reference(&value))
                        .transpose()?,
                ),
                ReadOperation::Inspect { reference } => {
                    let detail = self.index.inspect(
                        &self.native_reference(reference)?,
                        token.as_ref(),
                        budget,
                    )?;
                    ReadResult::Inspection(model::Inspection {
                        reference: reference.clone(),
                        media_type: detail.media_type,
                        total_bytes: detail.total_bytes,
                        offset: detail.offset,
                        content: detail.content,
                        next: detail
                            .next
                            .map(|value| encode_cursor(value, &self.observation.id))
                            .transpose()?,
                        coverage: detail.coverage,
                    })
                }
                ReadOperation::Overview | ReadOperation::Expand { .. } => {
                    let page = match &request.operation {
                        ReadOperation::Overview => self.index.overview(token.as_ref(), budget)?,
                        ReadOperation::Expand { reference } => self.index.expand(
                            &self.native_reference(reference)?,
                            token.as_ref(),
                            budget,
                        )?,
                        _ => {
                            return Err(SurfaceError::Invalid("unsupported image read".into()));
                        }
                    };
                    let entries = page
                        .entries
                        .into_iter()
                        .map(|entry| {
                            Ok(model::Entry {
                                reference: self.reference(&entry.reference)?,
                                kind: entry.kind,
                                label: entry.label,
                                preview: entry.preview,
                                members: entry.members,
                            })
                        })
                        .collect::<Result<Vec<_>, SurfaceError>>()?;
                    ReadResult::Page(model::Page {
                        observation: self.observation.id.clone(),
                        total: page.total,
                        offset: page.offset,
                        entries,
                        next: page
                            .next
                            .map(|value| encode_cursor(value, &self.observation.id))
                            .transpose()?,
                        coverage: page.coverage,
                    })
                }
                ReadOperation::Search { .. } => {
                    return Err(SurfaceError::Invalid(
                        "image does not advertise text search; no OCR was performed".into(),
                    ));
                }
            };
            if serde_json::to_vec(&result)
                .map_err(|error| SurfaceError::Parse(error.to_string()))?
                .len()
                <= request.budget.bytes
            {
                return Ok(result);
            }
            if items <= 1 {
                return Err(SurfaceError::BudgetTooSmall);
            }
            items = items.saturating_sub(1);
        }
    }
}
