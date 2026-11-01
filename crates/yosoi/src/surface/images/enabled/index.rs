use super::PixelRect;
use crate::documents::{FileLimits, ImageDocument};
use crate::surface::{
    Coordinate, Coverage, Data, Limits, Node, Original, Payload, PixelArtifact, PixelLimits,
    PixelOrientation, Reference, Surface, SurfaceError, image_source_identity, prepare,
};
use image::{DynamicImage, ImageFormat, ImageReader};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Cursor, sync::Arc};

#[derive(Debug)]
pub struct ImageData {
    pub(super) pixels: DynamicImage,
    pub(super) artifact: PixelArtifact,
    pub(super) limits: PixelLimits,
}
pub fn region_digest(image: &ImageData, rect: PixelRect) -> Result<Vec<u8>, SurfaceError> {
    if rect
        .x
        .checked_add(rect.width)
        .is_none_or(|right| right > image.pixels.width())
        || rect
            .y
            .checked_add(rect.height)
            .is_none_or(|bottom| bottom > image.pixels.height())
    {
        return Err(SurfaceError::Invalid("image digest outside raster".into()));
    }
    let pixels = image
        .pixels
        .crop_imm(rect.x, rect.y, rect.width, rect.height)
        .to_rgba8();
    let mut digest = Sha256::new();
    digest.update(rect.width.to_le_bytes());
    digest.update(rect.height.to_le_bytes());
    digest.update(pixels.as_raw());
    Ok(digest.finalize().to_vec())
}

impl Surface {
    /// Decodes PNG/JPEG evidence and indexes a bounded quadtree of pixel regions.
    /// `tile_side` controls the smallest automatic regions; no OCR/model is invoked.
    /// Decode is limited to 8,192 pixels per side and 64 MiB of pixel allocation.
    /// Coordinates follow the decoded raster; EXIF orientation is not applied.
    pub fn from_image(bytes: &[u8], tile_side: u32, limits: Limits) -> Result<Self, SurfaceError> {
        let digest = Sha256::digest(bytes);
        let id = format!("surface-image-legacy-{:x}", digest);
        let max_bytes = u64::try_from(limits.input_bytes)
            .map_err(|_| SurfaceError::Limit("image input bytes"))?;
        let document = ImageDocument::from_bytes_with_limits(
            id,
            bytes.to_vec(),
            FileLimits::new(max_bytes).map_err(|error| SurfaceError::Invalid(error.to_string()))?,
        )
        .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
        Self::from_image_document_inner(document, tile_side, limits, PixelLimits::default(), true)
    }

    /// Prepares a typed image under the shared Surface reader contract.
    /// The image source identity is independent of `tile_side` and other preparation options.
    pub fn from_image_document(
        document: &ImageDocument,
        tile_side: u32,
        limits: Limits,
    ) -> Result<Self, SurfaceError> {
        Self::from_image_document_with_pixel_limits(
            document,
            tile_side,
            limits,
            PixelLimits::default(),
        )
    }

    /// Prepares a typed image with explicit decoded and output-pixel bounds.
    pub fn from_image_document_with_pixel_limits(
        document: &ImageDocument,
        tile_side: u32,
        limits: Limits,
        pixel_limits: PixelLimits,
    ) -> Result<Self, SurfaceError> {
        Self::from_image_document_inner(document.clone(), tile_side, limits, pixel_limits, false)
    }

    fn from_image_document_inner(
        document: ImageDocument,
        tile_side: u32,
        limits: Limits,
        pixel_limits: PixelLimits,
        legacy: bool,
    ) -> Result<Self, SurfaceError> {
        let bytes = document.bytes();
        if bytes.len() > limits.input_bytes {
            return Err(SurfaceError::Limit("image input bytes"));
        }
        if !(32..=4096).contains(&tile_side) {
            return Err(SurfaceError::Invalid(
                "image tile side must be 32..=4096".into(),
            ));
        }
        let pixel_limits = pixel_limits.validate()?;
        let detected = document.metadata().detected_media_type();
        if !matches!(detected, Some("image/png" | "image/jpeg")) {
            return Err(SurfaceError::Invalid(
                "image Surface supports PNG and JPEG ImageDocuments".into(),
            ));
        }
        let detected = match detected {
            Some(value) => value.to_owned(),
            None => "image/png-or-jpeg".to_owned(),
        };
        let mut reader = ImageReader::new(Cursor::new(bytes))
            .with_guessed_format()
            .map_err(|e| SurfaceError::Parse(e.to_string()))?;
        if !matches!(reader.format(), Some(ImageFormat::Png | ImageFormat::Jpeg)) {
            return Err(SurfaceError::Invalid(
                "image evidence supports PNG and JPEG".into(),
            ));
        }
        let mut decode_limits = image::Limits::default();
        decode_limits.max_image_width = Some(pixel_limits.max_side);
        decode_limits.max_image_height = Some(pixel_limits.max_side);
        decode_limits.max_alloc = Some(
            u64::try_from(pixel_limits.max_decoded_bytes)
                .map_err(|_| SurfaceError::Limit("decoded image allocation"))?,
        );
        reader.limits(decode_limits);
        let pixels = reader
            .decode()
            .map_err(|e| SurfaceError::Parse(e.to_string()))?;
        pixel_limits.check_pixels(pixels.width(), pixels.height())?;
        let artifact = PixelArtifact::from_image_document(
            document.clone(),
            pixels.width(),
            pixels.height(),
            PixelOrientation::ExifUnapplied,
        )?;
        let rect = PixelRect {
            x: 0,
            y: 0,
            width: pixels.width(),
            height: pixels.height(),
        };
        let identity = if legacy {
            let mut digest = Sha256::new();
            digest.update(b"yosoi-image-index-v1");
            digest.update(tile_side.to_le_bytes());
            digest.update(bytes);
            format!("image-v1:{:x}", digest.finalize())
        } else {
            let mut digest = Sha256::new();
            digest.update(b"yosoi-image-index-v2");
            digest.update(image_source_identity(&document)?.as_bytes());
            digest.update(tile_side.to_le_bytes());
            format!("image-v2:{:x}", digest.finalize())
        };
        let input_bytes = bytes.len();
        let representation = format!(
            "{detected}; pixel-space=original-raster; exif=unapplied; source={}",
            artifact.source_identity()?
        );
        let original = if legacy {
            Original::Image {
                bytes: bytes.to_vec(),
                tile_side,
            }
        } else {
            Original::TypedImage {
                document,
                tile_side,
            }
        };
        let mut nodes = Vec::new();
        region(rect, None, 0, tile_side, limits, &mut nodes)?;
        let mut data = Data {
            original: Some(original),
            identity,
            source: String::new(),
            input_bytes,
            representation,
            nodes,
            coverage: Coverage {
                complete: true,
                reason: None,
            },
            overview: Vec::new(),
            repeated: BTreeMap::new(),
            json: None,
            views: Vec::new(),
            image: Some(Arc::new(ImageData {
                pixels,
                artifact,
                limits: pixel_limits,
            })),
        };
        prepare::reduce(&mut data, limits.overview_depth)?;
        Ok(Self {
            data: Arc::new(data),
        })
    }
}

fn region(
    rect: PixelRect,
    parent: Option<usize>,
    depth: usize,
    tile: u32,
    limits: Limits,
    nodes: &mut Vec<Node>,
) -> Result<usize, SurfaceError> {
    if nodes.len() >= limits.nodes || depth > limits.depth {
        return Err(SurfaceError::Limit("image region tree"));
    }
    let id = nodes.len();
    nodes.push(Node {
        kind: "image-region".into(),
        name: if parent.is_none() {
            "image".into()
        } else {
            "tile".into()
        },
        text: format!(
            "{}×{} pixels at {},{}; no semantic labels inferred",
            rect.width, rect.height, rect.x, rect.y
        ),
        attrs: BTreeMap::new(),
        children: Vec::new(),
        parent,
        coordinate: Coordinate {
            kind: "image_rect".into(),
            value: serde_json::to_string(&rect).map_err(|e| SurfaceError::Parse(e.to_string()))?,
        },
        payload: Payload::Image(rect),
    });
    if let Some(parent) = parent {
        nodes
            .get_mut(parent)
            .ok_or(SurfaceError::Unknown)?
            .children
            .push(id);
    }
    if rect.width > tile || rect.height > tile {
        let widths = if rect.width > tile {
            let left = rect
                .width
                .checked_div(2)
                .ok_or(SurfaceError::Limit("image split"))?;
            vec![left, rect.width.saturating_sub(left)]
        } else {
            vec![rect.width]
        };
        let heights = if rect.height > tile {
            let top = rect
                .height
                .checked_div(2)
                .ok_or(SurfaceError::Limit("image split"))?;
            vec![top, rect.height.saturating_sub(top)]
        } else {
            vec![rect.height]
        };
        let mut y = rect.y;
        for height in heights {
            let mut x = rect.x;
            for width in &widths {
                region(
                    PixelRect {
                        x,
                        y,
                        width: *width,
                        height,
                    },
                    Some(id),
                    depth
                        .checked_add(1)
                        .ok_or(SurfaceError::Limit("image depth"))?,
                    tile,
                    limits,
                    nodes,
                )?;
                x = x
                    .checked_add(*width)
                    .ok_or(SurfaceError::Limit("image x"))?;
            }
            y = y
                .checked_add(height)
                .ok_or(SurfaceError::Limit("image y"))?;
        }
    }
    Ok(id)
}
