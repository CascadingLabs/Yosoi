use serde::{Deserialize, Serialize};

/// Pixel rectangle in an exact captured raster, with an exclusive right/bottom edge.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct PixelRect {
    /// Left pixel coordinate.
    pub x: u32,
    /// Top pixel coordinate.
    pub y: u32,
    /// Positive region width.
    pub width: u32,
    /// Positive region height.
    pub height: u32,
}

#[cfg(any(feature = "browser", feature = "surface-images"))]
mod enabled {
    use super::PixelRect;
    use crate::surface::{
        Coordinate, Coverage, Data, Limits, Node, Payload, Reference, Surface, SurfaceError,
        prepare,
    };
    use image::{DynamicImage, ImageFormat, ImageReader};
    use sha2::{Digest, Sha256};
    use std::{collections::BTreeMap, io::Cursor, sync::Arc};

    #[derive(Debug)]
    pub struct ImageData {
        pub(super) pixels: DynamicImage,
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

    /// Actual PNG pixel evidence for an indexed image region; not OCR or a semantic prediction.
    #[derive(Clone, Debug)]
    pub struct ImageCrop {
        /// Exact captured region from which these pixels were cropped.
        pub reference: Reference,
        /// Crop bounds in the original image coordinate system.
        pub rect: PixelRect,
        /// Encoded PNG bytes; the crop's byte limit applies to these bytes.
        pub png: Vec<u8>,
    }

    impl Surface {
        /// Decodes PNG/JPEG evidence and indexes a bounded quadtree of pixel regions.
        /// `tile_side` controls the smallest automatic regions; no OCR/model is invoked.
        /// Decode is limited to 8,192 pixels per side and 64 MiB of pixel allocation.
        /// Coordinates follow the decoded raster; EXIF orientation is not applied.
        pub fn from_image(
            bytes: &[u8],
            tile_side: u32,
            limits: Limits,
        ) -> Result<Self, SurfaceError> {
            if bytes.len() > limits.input_bytes {
                return Err(SurfaceError::Limit("image input bytes"));
            }
            if !(32..=4096).contains(&tile_side) {
                return Err(SurfaceError::Invalid(
                    "image tile side must be 32..=4096".into(),
                ));
            }
            let mut reader = ImageReader::new(Cursor::new(bytes))
                .with_guessed_format()
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            if !matches!(reader.format(), Some(ImageFormat::Png | ImageFormat::Jpeg)) {
                return Err(SurfaceError::Invalid(
                    "image evidence supports PNG and JPEG".into(),
                ));
            }
            let mut decode_limits = image::Limits::default();
            decode_limits.max_image_width = Some(8192);
            decode_limits.max_image_height = Some(8192);
            decode_limits.max_alloc = Some(64 * 1024 * 1024);
            reader.limits(decode_limits);
            let pixels = reader
                .decode()
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            let rect = PixelRect {
                x: 0,
                y: 0,
                width: pixels.width(),
                height: pixels.height(),
            };
            let mut digest = Sha256::new();
            digest.update(b"yosoi-image-index-v1");
            digest.update(tile_side.to_le_bytes());
            digest.update(bytes);
            let identity = format!("image-v1:{:x}", digest.finalize());
            let mut nodes = Vec::new();
            region(rect, None, 0, tile_side, limits, &mut nodes)?;
            let mut data = Data {
                identity,
                source: String::new(),
                input_bytes: bytes.len(),
                representation: "image/png-or-jpeg; pixel-space=original".into(),
                nodes,
                coverage: Coverage {
                    complete: true,
                    reason: None,
                },
                overview: Vec::new(),
                repeated: BTreeMap::new(),
                json: None,
                views: Vec::new(),
                image: Some(Arc::new(ImageData { pixels })),
            };
            prepare::reduce(&mut data, limits.overview_depth)?;
            Ok(Self {
                data: Arc::new(data),
            })
        }

        /// Returns actual PNG pixels from an image reference, rejecting foreign or non-image nodes.
        /// The binary PNG payload must fit `max_png_bytes`; text response budgets are separate.
        pub fn crop(
            &self,
            reference: &Reference,
            max_png_bytes: usize,
        ) -> Result<ImageCrop, SurfaceError> {
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
            let mut output = Cursor::new(Vec::new());
            crop.write_to(&mut output, ImageFormat::Png)
                .map_err(|e| SurfaceError::Parse(e.to_string()))?;
            let png = output.into_inner();
            if png.len() > max_png_bytes {
                return Err(SurfaceError::Limit("crop PNG bytes"));
            }
            Ok(ImageCrop {
                reference: reference.clone(),
                rect,
                png,
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
                value: serde_json::to_string(&rect)
                    .map_err(|e| SurfaceError::Parse(e.to_string()))?,
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
}

#[cfg(any(feature = "browser", feature = "surface-images"))]
pub use enabled::ImageCrop;
#[cfg(any(feature = "browser", feature = "surface-images"))]
pub(super) use enabled::ImageData;
#[cfg(any(feature = "browser", feature = "surface-images"))]
pub(super) use enabled::region_digest;
