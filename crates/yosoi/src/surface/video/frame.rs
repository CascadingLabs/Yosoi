//! Lazy decoder materialization and checked pixel provenance.
use super::{
    DecodedFrame, FrameInfo, VideoError, VideoSurface, process, time::seconds_us, timeline,
};
use crate::{
    documents::{FileLimits, FileMetadata, ImageDocument},
    request::CancellationToken,
    surface::{
        PixelRect,
        model::{self, AddressToken},
        pixels::{
            PixelArtifact, PixelCoordinateKind, PixelCoordinateSpace, PixelOperation,
            PixelOrientation, PixelSource,
        },
    },
};
use image::{ImageFormat, ImageReader};
use sha2::{Digest, Sha256};
use std::io::Cursor;
use tokio::process::Command;

impl VideoSurface {
    /// Materializes one frame or previously addressed crop. At most four full frames are cached.
    /// The measured PTS is retained separately from the requested position.
    pub async fn frame(&self, reference: &model::Reference) -> Result<DecodedFrame, VideoError> {
        self.frame_cancellable(reference, &CancellationToken::new())
            .await
    }
    /// Materializes pixels with cancellation and awaited owned-process cleanup.
    pub async fn frame_cancellable(
        &self,
        reference: &model::Reference,
        cancellation: &CancellationToken,
    ) -> Result<DecodedFrame, VideoError> {
        if cancellation.is_cancelled() {
            return Err(VideoError::Cancelled);
        }
        let address = self.address(reference)?;
        let (position, region) = match address {
            timeline::Address::Frame(position) => (position, None),
            timeline::Address::Region(position, rect) => (position, Some(rect)),
            timeline::Address::Interval(..) => {
                return Err(VideoError::Invalid(
                    "request a frame address before materializing pixels".into(),
                ));
            }
        };
        let mut cache = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(VideoError::Cancelled),
            cache = self.data.cache.lock() => cache,
        };
        let full = if let Some((_, frame)) = cache.iter().find(|(time, _)| *time == position) {
            frame.clone()
        } else {
            let frame = self.decode(position, cancellation).await?;
            if cache.len() >= 4 {
                cache.pop_front();
            }
            cache.push_back((position, frame.clone()));
            frame
        };
        drop(cache);
        if let Some(rect) = region {
            self.crop_pixels(full, rect, reference.clone())
        } else {
            Ok(full)
        }
    }
    /// Crops full decoded-frame pixels; nested crop coordinates are rejected as ambiguous.
    pub async fn crop(
        &self,
        reference: &model::Reference,
        rect: PixelRect,
    ) -> Result<DecodedFrame, VideoError> {
        self.crop_cancellable(reference, rect, &CancellationToken::new())
            .await
    }
    /// Crops a full-frame address with cancellation and awaited decoder cleanup.
    pub async fn crop_cancellable(
        &self,
        reference: &model::Reference,
        rect: PixelRect,
        cancellation: &CancellationToken,
    ) -> Result<DecodedFrame, VideoError> {
        let timeline::Address::Frame(position) = self.address(reference)? else {
            return Err(VideoError::Invalid(
                "crop requires a full-frame reference".into(),
            ));
        };
        let full = self.frame_cancellable(reference, cancellation).await?;
        let reference = model::Reference {
            observation: self.data.observation.id.clone(),
            address: AddressToken::new(format!(
                "r:{position}:{}:{}:{}:{}",
                rect.x, rect.y, rect.width, rect.height
            ))?,
        };
        self.crop_pixels(full, rect, reference)
    }
    fn crop_pixels(
        &self,
        full: DecodedFrame,
        rect: PixelRect,
        reference: model::Reference,
    ) -> Result<DecodedFrame, VideoError> {
        if rect.width == 0
            || rect.height == 0
            || rect
                .x
                .checked_add(rect.width)
                .is_none_or(|v| v > full.info.width)
            || rect
                .y
                .checked_add(rect.height)
                .is_none_or(|v| v > full.info.height)
        {
            return Err(VideoError::Invalid(
                "crop is outside decoded-frame pixels".into(),
            ));
        }
        let mut reader = ImageReader::new(Cursor::new(&full.png)).with_guessed_format()?;
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(self.data.policy.frame_max_side);
        limits.max_image_height = Some(self.data.policy.frame_max_side);
        limits.max_alloc = Some(128 * 1024 * 1024);
        reader.limits(limits);
        let pixels = reader
            .decode()
            .map_err(|e| VideoError::Invalid(e.to_string()))?
            .crop_imm(rect.x, rect.y, rect.width, rect.height);
        let mut png = Cursor::new(Vec::new());
        pixels
            .write_to(&mut png, ImageFormat::Png)
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        let png = png.into_inner();
        if png.len() > self.data.policy.max_frame_bytes {
            return Err(VideoError::Limit("crop PNG bytes"));
        }
        let parent_artifact = full.pixel_artifact()?;
        let mut info = full.info;
        info.pixel_artifact = None;
        info.reference = reference;
        info.width = rect.width;
        info.height = rect.height;
        info.region = Some(rect);
        info.png_sha256 = format!("{:x}", Sha256::digest(&png));
        info.png_bytes = png.len();
        let mut frame = DecodedFrame {
            info,
            png,
            pixels: None,
        };
        if let Some(parent) = parent_artifact {
            let artifact = PixelArtifact::crop_from(&parent, frame.image_document()?, rect)?;
            frame.info.pixel_artifact = Some(artifact.info().clone());
            frame.pixels = Some(artifact);
        }
        Ok(frame)
    }
    async fn decode(
        &self,
        position: u64,
        cancellation: &CancellationToken,
    ) -> Result<DecodedFrame, VideoError> {
        let mut version = Command::new(&self.data.ffmpeg);
        version.arg("-version");
        let version = process::run(
            version,
            64 * 1024,
            self.data.policy.tool_timeout_ms,
            cancellation,
            self.data.snapshot.clone(),
        )
        .await?;
        let decoder = String::from_utf8_lossy(&version.stdout)
            .lines()
            .next()
            .unwrap_or_default()
            .chars()
            .take(256)
            .collect::<String>();
        if decoder != self.data.metadata.decoder {
            return Err(VideoError::Invalid(
                "decoder identity changed; create a new observation before decoding".into(),
            ));
        }
        let mut command = Command::new(&self.data.ffmpeg);
        let side = self.data.policy.frame_max_side;
        // A single PNG has no output timeline; measure source PTS before encoding.
        // Avoid version-specific fps_mode/vsync options on supported FFmpeg releases.
        command.args(["-hide_banner","-nostdin","-loglevel","info","-threads","1","-filter_threads","1","-format_whitelist","mov,matroska,webm,avi,mpegts,ogg","-protocol_whitelist","file,pipe","-ss"]).arg(format!("{}.{:06}",position/1_000_000,position%1_000_000)).arg("-copyts").arg("-i").arg(&self.data.path).args(["-map","0:v:0","-an","-vf"]).arg(format!("scale=w='min(iw,{side})':h='min(ih,{side})':force_original_aspect_ratio=decrease,showinfo")).args(["-frames:v","1","-c:v","png","-threads:v","1","-f","image2pipe","pipe:1"]);
        let output = process::run(
            command,
            self.data.policy.max_frame_bytes,
            self.data.policy.tool_timeout_ms,
            cancellation,
            self.data.snapshot.clone(),
        )
        .await?;
        let pts = String::from_utf8_lossy(&output.stderr)
            .lines()
            .filter(|line| line.contains("showinfo") && line.contains("pts_time:"))
            .flat_map(str::split_whitespace)
            .find_map(|token| token.strip_prefix("pts_time:"))
            .map(seconds_us)
            .transpose()?
            .ok_or(VideoError::NoFrameAtOrAfter {
                requested_us: position,
            })?;
        let (width, height) = ImageReader::new(Cursor::new(&output.stdout))
            .with_guessed_format()?
            .into_dimensions()
            .map_err(|e| VideoError::Invalid(e.to_string()))?;
        if width == 0 || height == 0 || width > side || height > side {
            return Err(VideoError::Limit("decoded frame dimensions"));
        }
        let relative = pts
            .checked_sub(self.data.metadata.stream_start_us)
            .and_then(|v| u64::try_from(v).ok());
        let reference = self.at(position)?;
        let info = FrameInfo {
            reference,
            requested_us: position,
            source_pts_us: pts,
            position_us: relative,
            canvas_width: width,
            canvas_height: height,
            width,
            height,
            region: None,
            png_sha256: format!("{:x}", Sha256::digest(&output.stdout)),
            png_bytes: output.stdout.len(),
            pixel_artifact: None,
        };
        let source = if let Some(document) = self.source_document() {
            PixelSource::VideoFrame {
                source_document_id: document.id().to_string(),
                source_sha256: document.sha256().to_owned(),
                observation: info.reference.observation.as_str().to_owned(),
                reference: info.reference.address.as_str().to_owned(),
                requested_us: info.requested_us,
                source_pts_us: info.source_pts_us,
            }
        } else {
            PixelSource::LegacyVideoFrame {
                source_sha256: Some(self.data.metadata.source_sha256.clone()),
                observation: info.reference.observation.as_str().to_owned(),
                reference: info.reference.address.as_str().to_owned(),
                requested_us: info.requested_us,
                source_pts_us: info.source_pts_us,
            }
        };
        let mut frame = DecodedFrame {
            info,
            png: output.stdout,
            pixels: None,
        };
        let artifact = PixelArtifact::from_raster_document(
            frame.image_document()?,
            source,
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DecodedCanvas,
                width,
                height,
                orientation: PixelOrientation::DecoderApplied,
            },
        )?;
        frame.info.pixel_artifact = Some(artifact.info().clone());
        frame.pixels = Some(artifact);
        Ok(frame)
    }
}

impl DecodedFrame {
    fn image_document(&self) -> Result<ImageDocument, VideoError> {
        ImageDocument::from_bytes_with_metadata(
            format!("video-pixels-{}", self.info.png_sha256),
            self.png.clone(),
            FileMetadata::new()
                .with_filename("frame.png")
                .map_err(|error| VideoError::Invalid(error.to_string()))?,
            FileLimits {
                max_bytes: 32 * 1024 * 1024,
            },
        )
        .map_err(|error| VideoError::Invalid(error.to_string()))
    }
    /// Restores checked shared image provenance; legacy frames may lack it.
    pub fn pixel_artifact(&self) -> Result<Option<PixelArtifact>, VideoError> {
        self.info
            .pixel_artifact
            .as_ref()
            .map(|info| {
                let artifact = if let Some(artifact) = self.pixels.as_ref() {
                    if artifact.info() != info || artifact.bytes() != self.png.as_slice() {
                        return Err(VideoError::Invalid(
                            "frame and retained pixels differ".into(),
                        ));
                    }
                    artifact.clone()
                } else {
                    PixelArtifact::from_archived_parts(self.image_document()?, info.clone())?
                };
                if info.width != self.info.width
                    || info.height != self.info.height
                    || info.sha256 != self.info.png_sha256
                    || artifact.bytes().len() != self.info.png_bytes
                    || info.source_space.kind != PixelCoordinateKind::DecodedCanvas
                    || info.source_space.width != self.info.canvas_width
                    || info.source_space.height != self.info.canvas_height
                {
                    return Err(VideoError::Invalid(
                        "frame and shared pixel metadata differ".into(),
                    ));
                }
                let (PixelSource::VideoFrame {
                    observation,
                    reference,
                    requested_us,
                    source_pts_us,
                    ..
                }
                | PixelSource::LegacyVideoFrame {
                    observation,
                    reference,
                    requested_us,
                    source_pts_us,
                    ..
                }) = &info.source
                else {
                    return Err(VideoError::Invalid(
                        "frame pixels lack video provenance".into(),
                    ));
                };
                let expected_frame_address = format!("f:{}", self.info.requested_us);
                let expected_address = self.info.region.map_or(expected_frame_address, |rect| {
                    format!(
                        "r:{}:{}:{}:{}:{}",
                        self.info.requested_us, rect.x, rect.y, rect.width, rect.height
                    )
                });
                if observation != self.info.reference.observation.as_str()
                    || reference != &format!("f:{}", self.info.requested_us)
                    || *requested_us != self.info.requested_us
                    || *source_pts_us != self.info.source_pts_us
                    || self.info.reference.address.as_str() != expected_address
                {
                    return Err(VideoError::Invalid(
                        "frame time and pixel provenance differ".into(),
                    ));
                }
                match (self.info.region, &info.transform.operation) {
                    (None, PixelOperation::Source) => {}
                    (Some(rect), PixelOperation::Crop { rect: recorded }) if rect == *recorded => {}
                    _ => {
                        return Err(VideoError::Invalid(
                            "frame crop and pixel transform differ".into(),
                        ));
                    }
                }
                Ok(artifact)
            })
            .transpose()
    }
}

#[cfg(test)]
mod tests {
    use super::{DecodedFrame, FrameInfo, VideoError};
    use crate::{
        documents::ImageDocument,
        surface::{
            PixelCoordinateKind, PixelCoordinateSpace, PixelOrientation, PixelRect, PixelSource,
            model::{AddressToken, ObservationId, Reference},
            pixels::PixelArtifact,
        },
    };
    use image::{ImageFormat, Rgba, RgbaImage};
    use std::io::Cursor;

    fn image_document(id: &str, width: u32, height: u32) -> Result<ImageDocument, VideoError> {
        let image = RgbaImage::from_pixel(width, height, Rgba([10, 20, 30, 255]));
        let mut encoded = Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(image)
            .write_to(&mut encoded, ImageFormat::Png)
            .map_err(|error| VideoError::Invalid(error.to_string()))?;
        ImageDocument::from_bytes(id, encoded.into_inner())
            .map_err(|error| VideoError::Invalid(error.to_string()))
    }

    fn frame_info(
        address: String,
        region: Option<PixelRect>,
        artifact: &PixelArtifact,
    ) -> Result<FrameInfo, VideoError> {
        Ok(FrameInfo {
            reference: Reference {
                observation: ObservationId::new("video-observation")?,
                address: AddressToken::new(address)?,
            },
            requested_us: 10,
            source_pts_us: 15,
            position_us: Some(15),
            canvas_width: 2,
            canvas_height: 2,
            width: artifact.info().width,
            height: artifact.info().height,
            region,
            png_sha256: artifact.info().sha256.clone(),
            png_bytes: artifact.bytes().len(),
            pixel_artifact: Some(artifact.info().clone()),
        })
    }

    fn source_artifact() -> Result<PixelArtifact, VideoError> {
        let document = image_document("video-frame-source", 2, 2)?;
        PixelArtifact::from_raster_document(
            document,
            PixelSource::VideoFrame {
                source_document_id: "video-document".into(),
                source_sha256: "0".repeat(64),
                observation: "video-observation".into(),
                reference: "f:10".into(),
                requested_us: 10,
                source_pts_us: 15,
            },
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DecodedCanvas,
                width: 2,
                height: 2,
                orientation: PixelOrientation::DecoderApplied,
            },
        )
        .map_err(VideoError::from)
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions verify that altered frame addresses reject otherwise valid pixel provenance."
    )]
    fn typed_frame_pixels_require_the_exact_frame_address() -> Result<(), VideoError> {
        let artifact = source_artifact()?;
        let png = artifact.bytes().to_vec();
        let mut frame = DecodedFrame {
            info: frame_info("f:10".into(), None, &artifact)?,
            png,
            pixels: Some(artifact),
        };
        assert!(frame.pixel_artifact()?.is_some());

        frame.info.reference.address = AddressToken::new("f:11")?;
        assert!(frame.pixel_artifact().is_err());
        Ok(())
    }

    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions verify that altered crop addresses reject otherwise valid pixel provenance."
    )]
    fn typed_crop_pixels_require_the_exact_crop_address() -> Result<(), VideoError> {
        let parent = source_artifact()?;
        let rect = PixelRect {
            x: 1,
            y: 0,
            width: 1,
            height: 2,
        };
        let crop =
            PixelArtifact::crop_from(&parent, image_document("video-frame-crop", 1, 2)?, rect)?;
        let png = crop.bytes().to_vec();
        let mut frame = DecodedFrame {
            info: frame_info("r:10:1:0:1:2".into(), Some(rect), &crop)?,
            png,
            pixels: Some(crop),
        };
        assert!(frame.pixel_artifact()?.is_some());

        frame.info.reference.address = AddressToken::new("r:10:0:0:1:2")?;
        assert!(frame.pixel_artifact().is_err());
        Ok(())
    }
}
