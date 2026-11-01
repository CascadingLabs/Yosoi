//! Stateful, read-only exploration of one typed image document.

use super::{
    ArchivePolicy, ArchivedSource, Budget, ExecutionError, ImageSurface, Outcome, PixelArtifact,
    PixelLimits, SurfaceConnection, SurfacePolicy,
    connection::{AgentSurface, Connection, Operation, Request, Result, Trace, connection},
    model::{self, ReadOperation, ReadRequest, SurfaceRead},
};
use crate::{
    Archive,
    archive::PixelArtifactArchiveRef,
    automation_record::OperationStatus,
    documents::{FileDocument, FileLimits, ImageDocument, read_file},
};
use serde_json::{Value, json};
use std::{
    error::Error,
    fmt::{self, Debug, Formatter},
    fs,
    future::{Future, ready},
    io,
    path::{Path, PathBuf},
    result::Result as StdResult,
};

struct ImageDriver {
    surface: ImageSurface,
    focus: model::Reference,
    trace: Trace,
    output: PathBuf,
    pixel_limits: PixelLimits,
    tile_side: u32,
    retained_artifacts: usize,
    source_archive_ref: Option<PixelArtifactArchiveRef>,
    archive: Option<Archive>,
    outcome: Option<Outcome>,
    attached: bool,
}

impl Debug for ImageDriver {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ImageDriver")
            .field("surface", &self.surface.descriptor())
            .field("retained_artifacts", &self.retained_artifacts)
            .finish_non_exhaustive()
    }
}

impl ImageDriver {
    fn describe(&self) -> Value {
        json!({
            "descriptor": self.surface.descriptor(),
            "observation": self.surface.observation(),
            "root": self.surface.root_reference(),
            "source": {
                "document_id": self.surface.source_document().id(),
                "sha256": self.surface.source_document().sha256(),
                "bytes": self.surface.source_document().byte_len(),
            },
            "source_pixel_artifact": self.surface.source_artifact().info(),
            "source_archive_ref": self.source_archive_ref,
        })
    }

    fn status(&self) -> Value {
        json!({
            "descriptor": self.surface.descriptor(),
            "observation": self.surface.observation(),
            "source": {
                "document_id": self.surface.source_document().id(),
                "sha256": self.surface.source_document().sha256(),
                "bytes": self.surface.source_document().byte_len(),
            },
            "source_pixel_artifact": self.surface.source_artifact().info(),
            "root": self.surface.root_reference(),
            "cursor": {
                "attached": self.attached,
                "mode": "reader",
                "focus": self.focus,
            },
            "pixel_limits": self.pixel_limits,
            "retained_artifacts": self.retained_artifacts,
            "source_archive_ref": self.source_archive_ref,
            "archive": self.archive.as_ref().map(Archive::root),
        })
    }

    fn validate(&self, reference: &model::Reference) -> Result<()> {
        self.surface.read(&ReadRequest {
            operation: ReadOperation::Inspect {
                reference: reference.clone(),
            },
            budget: Budget::default(),
            continuation: None,
        })?;
        Ok(())
    }

    async fn pixels(&mut self, artifact: PixelArtifact) -> Result<Value> {
        if self.retained_artifacts >= self.pixel_limits.max_retained_artifacts {
            return Err(io::Error::other("retained image artifact limit exhausted").into());
        }
        let extension = match artifact.info().media_type.as_str() {
            "image/png" => "png",
            "image/jpeg" => "jpg",
            _ => return Err(io::Error::other("unsupported artifact media type").into()),
        };
        let path = self
            .output
            .join(format!("image-{}.{}", artifact.info().sha256, extension));
        if let Some(outcome) = &mut self.outcome {
            let source = ArchivedSource::new_pixel_artifact(
                artifact.info().identity.clone(),
                &artifact,
                self.tile_side,
                Some(self.surface.index()),
            );
            match outcome.clone().with_source(source) {
                Ok(updated) => *outcome = updated,
                Err(error) => {
                    outcome.complete = false;
                    return Err(error.into());
                }
            }
        }
        self.retained_artifacts = self
            .retained_artifacts
            .checked_add(1)
            .ok_or_else(|| io::Error::other("retained image artifact counter exhausted"))?;
        // Reserve the attempt before persistence: partial I/O failures must not
        // permit unbounded retries that each create an immutable Archive record.
        let persisted: Result<Option<PixelArtifactArchiveRef>> = async {
            fs::write(&path, artifact.bytes())?;
            let archive_ref =
                if artifact.info().identity == self.surface.source_artifact().info().identity {
                    self.source_archive_ref.clone()
                } else if let Some(archive) = &self.archive {
                    Some(archive.write(&artifact).await?)
                } else {
                    None
                };
            Ok(archive_ref)
        }
        .await;
        let archive_ref = match persisted {
            Ok(reference) => reference,
            Err(error) => {
                if let Some(outcome) = &mut self.outcome {
                    outcome.complete = false;
                }
                return Err(error);
            }
        };
        Ok(json!({
            "artifact": {
                "path": path,
                "info": artifact.info(),
                "archive_ref": archive_ref,
            }
        }))
    }

    async fn close(mut self) -> (Option<Outcome>, Result<()>) {
        let result = if let Some(outcome) = &mut self.outcome {
            outcome.sealed = true;
            outcome.receipt(
                "surface.closed",
                OperationStatus::Observed,
                json!({"resources_released":true,"browser_started":false}),
            );
            if let Some(archive) = &self.archive {
                match archive.write(outcome).await {
                    Ok(reference) => match archive
                        .export_file(&reference, self.output.join("surface.yosoi"))
                        .await
                    {
                        Ok(()) => match archive.read(&reference).await {
                            Ok(restored) => {
                                *outcome = restored;
                                Ok(())
                            }
                            Err(error) => Err(error.into()),
                        },
                        Err(error) => Err(error.into()),
                    },
                    Err(error) => Err(error.into()),
                }
            } else {
                Ok(())
            }
        } else {
            Ok(())
        };
        (self.outcome, result)
    }
}

impl AgentSurface for ImageDriver {
    fn ready(&mut self) -> Result<Value> {
        let page = self.surface.read(&ReadRequest {
            operation: ReadOperation::Overview,
            budget: Budget::default(),
            continuation: None,
        })?;
        self.trace.read("surface.open", &page)?;
        Ok(json!({
            "event": "ready",
            "sdk": "ys::surface",
            "representation": self.surface.descriptor().representation,
            "state": self.status(),
            "initial_read": page,
            "protocol": "JSON lines; describe/read/focus_evidence use the shared reader; image/crop/overview_image/resize_image return bounded pixel artifacts; no control authority",
        }))
    }

    async fn command(&mut self, request: &Request) -> Result<Value> {
        match &request.operation {
            Operation::Describe => Ok(self.describe()),
            Operation::Status => Ok(self.status()),
            Operation::Attach => {
                self.attached = true;
                Ok(self.status())
            }
            Operation::Detach => {
                self.attached = false;
                Ok(self.status())
            }
            Operation::Read { request: read } => {
                let mut read = read.clone();
                read.budget.bytes = read.budget.bytes.min(request.budget.saturating_sub(256));
                Ok(serde_json::to_value(self.surface.read(&read)?)?)
            }
            Operation::FocusEvidence { reference } => {
                self.validate(reference)?;
                self.focus.clone_from(reference);
                Ok(self.status())
            }
            Operation::ImageDirect => {
                let artifact = self.surface.direct_image()?;
                self.pixels(artifact).await
            }
            Operation::OverviewImage { max_side } => {
                let artifact = self.surface.overview_image(*max_side)?;
                self.pixels(artifact).await
            }
            Operation::ResizeImage { width, height } => {
                let artifact = self.surface.resize_image(*width, *height)?;
                self.pixels(artifact).await
            }
            Operation::CropImage { rect } => {
                let crop = self.surface.crop_rect(*rect, self.pixel_limits.max_output_bytes)?;
                self.focus = self.surface.reference(&crop.reference)?;
                self.pixels(crop.artifact).await
            }
            Operation::Crop { reference, rect } => {
                if reference != &self.surface.root_reference() {
                    return Err(io::Error::other(
                        "image coordinate crops require the exact root image reference; nested crops are unsupported",
                    )
                    .into());
                }
                let crop = self
                    .surface
                    .crop_rect(*rect, self.pixel_limits.max_output_bytes)?;
                self.focus = self.surface.reference(&crop.reference)?;
                self.pixels(crop.artifact).await
            }
            Operation::Close => Ok(json!({"closing": true})),
            _ => Err(io::Error::other(
                "capability unavailable on read-only image; use describe and the shared read protocol",
            )
            .into()),
        }
    }

    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()> {
        match result {
            Ok(value) => {
                if matches!(operation, Operation::Read { .. }) {
                    self.trace.read_bytes = self
                        .trace
                        .read_bytes
                        .saturating_add(serde_json::to_vec(value)?.len());
                }
                self.trace.event("cli.reply", value.clone());
            }
            Err(error) => self.trace.event(
                "cli.error",
                json!({"error":error.to_string().chars().take(512).collect::<String>()}),
            ),
        }
        Ok(())
    }

    fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> impl Future<Output = Result<Value>> + Send {
        if let Some(outcome) = &mut self.outcome {
            let (status, result_value) = match &result {
                Ok(value) => {
                    let mut portable = value.clone();
                    if let Some(artifact) =
                        portable.get_mut("artifact").and_then(Value::as_object_mut)
                    {
                        artifact.remove("path");
                        artifact.remove("archive_ref");
                    }
                    (OperationStatus::Observed, portable)
                }
                Err(error) => (
                    OperationStatus::Rejected,
                    json!({"error":error.to_string().chars().take(512).collect::<String>()}),
                ),
            };
            outcome.receipt(
                "surface.image.command",
                status,
                json!({"command":operation,"outcome":result_value}),
            );
        }
        ready(result)
    }

    fn trace(&mut self) -> &mut Trace {
        &mut self.trace
    }

    fn outcome(&self) -> Option<Outcome> {
        self.outcome.clone()
    }

    async fn close(self) -> (Option<Outcome>, Result<()>) {
        Self::close(self).await
    }
}

/// Read-only image connection using the shared JSON-lines Surface protocol.
pub struct ImageSession {
    inner: Connection<ImageDriver>,
}

impl ImageSession {
    /// Opens one PNG/JPEG file and owns a typed source snapshot for its lifetime.
    pub async fn open(
        path: impl AsRef<Path> + Send + Sync,
        policy: SurfacePolicy,
        tile_side: u32,
        limits: super::Limits,
        pixel_limits: PixelLimits,
    ) -> StdResult<Self, ExecutionError> {
        let result = async {
            policy.archive_limits.validate()?;
            let pixel_limits = pixel_limits.validate()?;
            let temporary = tempfile::tempdir()?;
            let output = policy
                .output
                .clone()
                .unwrap_or_else(|| temporary.path().join("artifacts"));
            fs::create_dir_all(&output)?;
            let root = (policy.archive == ArchivePolicy::Enabled).then(|| {
                policy
                    .archive_root
                    .clone()
                    .unwrap_or_else(|| temporary.path().join("archive"))
            });
            let max_bytes = u64::try_from(limits.input_bytes)
                .map_err(|_| io::Error::other("image source limit does not fit u64"))?;
            let file_limits = FileLimits::new(max_bytes)?;
            let file = read_file("image-surface", path.as_ref(), file_limits).await?;
            let document: ImageDocument = match file {
                FileDocument::Image(document) => document,
                _ => {
                    return Err(
                        io::Error::other("image Surface requires PNG or JPEG file bytes").into(),
                    );
                }
            };
            let surface =
                ImageSurface::from_image_document(&document, tile_side, limits, pixel_limits)?;
            let outcome = if policy.archive == ArchivePolicy::Enabled {
                Some(
                    Outcome::new(
                        format!("image-{}", uuid::Uuid::new_v4()),
                        policy.archive_limits,
                    )?
                    .with_source(ArchivedSource::new_pixel_artifact(
                        surface.source_artifact().info().identity.clone(),
                        surface.source_artifact(),
                        tile_side,
                        Some(surface.index()),
                    ))?,
                )
            } else {
                None
            };
            let archive = match root {
                Some(root) => Some(Archive::open(root).await?),
                None => None,
            };
            let source_archive_ref = match &archive {
                Some(archive) => Some(archive.write(surface.source_artifact()).await?),
                None => None,
            };
            let focus = surface.root_reference();
            let driver = ImageDriver {
                surface,
                focus,
                trace: Trace::new(&output),
                output: output.clone(),
                pixel_limits,
                tile_side,
                retained_artifacts: 0,
                source_archive_ref,
                archive,
                outcome,
                attached: false,
            };
            Ok::<_, Box<dyn Error + Send + Sync>>(Self {
                inner: Connection::new(driver, output, temporary),
            })
        }
        .await;
        result.map_err(ExecutionError::Operation)
    }

    /// Opens a saved root PixelArtifact without a source file, browser, or video decoder.
    pub async fn open_pixel_artifact(
        reference: &PixelArtifactArchiveRef,
        archive_root: impl AsRef<Path> + Send + Sync,
        policy: SurfacePolicy,
        tile_side: u32,
        limits: super::Limits,
        pixel_limits: PixelLimits,
    ) -> StdResult<Self, ExecutionError> {
        let result = async {
            policy.archive_limits.validate()?;
            let pixel_limits = pixel_limits.validate()?;
            let temporary = tempfile::tempdir()?;
            let output = policy
                .output
                .clone()
                .unwrap_or_else(|| temporary.path().join("artifacts"));
            fs::create_dir_all(&output)?;
            let archive = Archive::open(archive_root).await?;
            let artifact = PixelArtifact::read_from(&archive, reference).await?;
            let surface =
                ImageSurface::from_pixel_artifact(&artifact, tile_side, limits, pixel_limits)?;
            let retained_archive = (policy.archive == ArchivePolicy::Enabled).then_some(archive);
            let outcome = if policy.archive == ArchivePolicy::Enabled {
                Some(
                    Outcome::new(
                        format!("image-{}", uuid::Uuid::new_v4()),
                        policy.archive_limits,
                    )?
                    .with_source(ArchivedSource::new_pixel_artifact(
                        surface.source_artifact().info().identity.clone(),
                        surface.source_artifact(),
                        tile_side,
                        Some(surface.index()),
                    ))?,
                )
            } else {
                None
            };
            let focus = surface.root_reference();
            let driver = ImageDriver {
                surface,
                focus,
                trace: Trace::new(&output),
                output: output.clone(),
                pixel_limits,
                tile_side,
                retained_artifacts: 0,
                source_archive_ref: Some(reference.clone()),
                archive: retained_archive,
                outcome,
                attached: false,
            };
            Ok::<_, Box<dyn Error + Send + Sync>>(Self {
                inner: Connection::new(driver, output, temporary),
            })
        }
        .await;
        result.map_err(ExecutionError::Operation)
    }
}

connection!(ImageSession);

#[cfg(test)]
mod tests {
    use super::*;
    use crate::surface::{ArchiveLimits, Limits};
    use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
    use std::io::Cursor;

    fn surface() -> Result<ImageSurface> {
        let mut encoded = Cursor::new(Vec::new());
        DynamicImage::ImageRgba8(RgbaImage::from_pixel(64, 64, Rgba([1, 2, 3, 255])))
            .write_to(&mut encoded, ImageFormat::Png)?;
        let document = ImageDocument::from_bytes("retention-fixture", encoded.into_inner())?;
        Ok(ImageSurface::from_image_document(
            &document,
            32,
            Limits::default(),
            PixelLimits::default(),
        )?)
    }

    fn files(root: &Path) -> io::Result<usize> {
        let mut total = 0_usize;
        for entry in fs::read_dir(root)? {
            let entry = entry?;
            let count = if entry.file_type()?.is_dir() {
                files(&entry.path())?
            } else {
                1
            };
            total = total
                .checked_add(count)
                .ok_or_else(|| io::Error::other("file count overflow"))?;
        }
        Ok(total)
    }

    #[tokio::test]
    async fn rejected_outcome_retention_never_persists_artifacts() -> Result<()> {
        let root = tempfile::tempdir()?;
        let output = root.path().join("output");
        fs::create_dir(&output)?;
        let archive = Archive::open(root.path().join("archive")).await?;
        let surface = surface()?;
        let original = ArchivedSource::new_pixel_artifact(
            "original",
            surface.source_artifact(),
            32,
            Some(surface.index()),
        );
        let outcome = Outcome::new(
            "retention",
            ArchiveLimits {
                observations: 1,
                ..ArchiveLimits::default()
            },
        )?
        .with_source(original)?;
        let source_archive_ref = Some(archive.write(surface.source_artifact()).await?);
        let before = files(archive.root())?;
        let mut driver = ImageDriver {
            focus: surface.root_reference(),
            surface,
            trace: Trace::new(&output),
            output: output.clone(),
            pixel_limits: PixelLimits {
                max_retained_artifacts: 2,
                ..PixelLimits::default()
            },
            tile_side: 32,
            retained_artifacts: 0,
            source_archive_ref,
            archive: Some(archive),
            outcome: Some(outcome),
            attached: false,
        };
        for width in 8..18 {
            let artifact = driver
                .surface
                .crop_rect(
                    super::super::PixelRect {
                        x: 0,
                        y: 0,
                        width,
                        height: 8,
                    },
                    1_048_576,
                )?
                .artifact;
            if driver.pixels(artifact).await.is_ok() {
                return Err("over-limit crop was retained".into());
            }
        }
        let archive = driver.archive.as_ref().ok_or("archive missing")?;
        if files(&output)? != 0
            || files(archive.root())? != before
            || driver.retained_artifacts != 0
        {
            return Err("rejected retention wrote persistent image evidence".into());
        }
        Ok(())
    }

    #[tokio::test]
    async fn failed_persistence_consumes_reserved_retention_capacity() -> Result<()> {
        let root = tempfile::tempdir()?;
        let output = root.path().join("not-a-directory");
        fs::write(&output, b"block image output")?;
        let surface = surface()?;
        let artifact = surface.direct_image()?;
        let mut driver = ImageDriver {
            focus: surface.root_reference(),
            surface,
            trace: Trace::new(&output),
            output,
            pixel_limits: PixelLimits {
                max_retained_artifacts: 2,
                ..PixelLimits::default()
            },
            tile_side: 32,
            retained_artifacts: 0,
            source_archive_ref: None,
            archive: None,
            outcome: None,
            attached: false,
        };
        for _ in 0..2 {
            if driver.pixels(artifact.clone()).await.is_ok() {
                return Err("invalid output unexpectedly succeeded".into());
            }
        }
        let error = driver
            .pixels(artifact)
            .await
            .err()
            .ok_or("capacity failure missing")?;
        if driver.retained_artifacts != 2
            || !error.to_string().contains("retained image artifact limit")
        {
            return Err("failed writes bypassed retention capacity".into());
        }
        Ok(())
    }
}
