//! Emit actual image pixels and public SDK observations for installed-wheel parity.
//!
//! Run with the `surface-images` feature. Python consumes these authored inputs,
//! executes its public API, and binds comparisons to a fresh compiler inventory.

use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, Write},
};
use yosoi::{
    Archive,
    documents::ImageDocument,
    surface::{
        ArchiveLimits, ArchivedSource, Budget, ImageSurface, Limits, Outcome, PixelArtifact,
        PixelCoordinateKind, PixelCoordinateSpace, PixelLimits, PixelOrientation, PixelRect,
        PixelSource,
        model::{ReadOperation, ReadRequest, SurfaceRead},
    },
};

#[path = "support/image_surface_conformance.rs"]
mod support;
use support::{artifact, case, error, reader};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut encoded = io::Cursor::new(Vec::new());
    // Four quadrants make crop/resize mistakes observable in the actual payload.
    let pixels = RgbaImage::from_fn(8, 4, |x, y| match (x < 4, y < 2) {
        (true, true) => Rgba([255, 0, 0, 255]),
        (false, true) => Rgba([0, 255, 0, 255]),
        (true, false) => Rgba([0, 0, 255, 255]),
        (false, false) => Rgba([255, 255, 0, 255]),
    });
    let image = DynamicImage::ImageRgba8(pixels);
    image.write_to(&mut encoded, ImageFormat::Png)?;
    let document = ImageDocument::from_bytes("image-parity", encoded.into_inner())?;
    let limits = Limits::default();
    let pixel_limits = PixelLimits::default();
    let tile_side = 32;
    let surface = ImageSurface::from_image_document(&document, tile_side, limits, pixel_limits)?;
    let direct = PixelArtifact::decode_image_document(document.clone(), pixel_limits)?;
    let root = surface.root_reference();
    let rect = PixelRect {
        x: 0,
        y: 0,
        width: 4,
        height: 2,
    };
    let map_rect = PixelRect {
        x: 0,
        y: 0,
        width: 2,
        height: 1,
    };
    let overview = surface.overview_image(4)?;
    let resized = surface.resize_image(3, 2)?;
    let crop = surface.crop_rect(rect, pixel_limits.max_output_bytes)?;
    let crop_ref = surface.crop(&root, pixel_limits.max_output_bytes)?;
    let native = surface.native_reference(&root)?;
    let mut cases = vec![
        case(
            "decode-direct",
            "PixelArtifact::decode_image_document",
            json!({"document": document.id(), "limits": pixel_limits}),
            artifact(&direct)?,
        ),
        case(
            "image-reader",
            "ImageSurface::from_image_document",
            json!({"document": document.id(), "tile_side": tile_side, "limits": limits, "pixel_limits": pixel_limits}),
            reader(&surface)?,
        ),
        case(
            "direct",
            "ImageSurface::direct_image",
            json!({"self": root}),
            artifact(&surface.direct_image()?)?,
        ),
        case(
            "overview",
            "ImageSurface::overview_image",
            json!({"self": root, "max_side": 4}),
            artifact(&overview)?,
        ),
        case(
            "overview-fits",
            "ImageSurface::overview_image",
            json!({"self": root, "max_side": 8}),
            artifact(&surface.overview_image(8)?)?,
        ),
        case(
            "resize",
            "ImageSurface::resize_image",
            json!({"self": root, "width": 3, "height": 2}),
            artifact(&resized)?,
        ),
        case(
            "crop-rect",
            "ImageSurface::crop_rect",
            json!({"self": root, "rect": rect, "max_png_bytes": pixel_limits.max_output_bytes}),
            json!({"reference": crop.reference, "rect": crop.rect, "artifact": artifact(&crop.artifact)?, "png": crop.png()}),
        ),
        case(
            "crop-reference",
            "ImageSurface::crop",
            json!({"self": root, "reference": root, "max_png_bytes": pixel_limits.max_output_bytes}),
            json!({"reference": crop_ref.reference, "rect": crop_ref.rect, "artifact": artifact(&crop_ref.artifact)?, "png": crop_ref.png()}),
        ),
        case(
            "coordinate-map",
            "PixelArtifact::map_rect_to_source",
            json!({"self": overview.info(), "rect": map_rect}),
            serde_json::to_value(overview.map_rect_to_source(map_rect)?)?,
        ),
        case(
            "native-reference",
            "ImageSurface::native_reference",
            json!({"self": root, "reference": root}),
            serde_json::to_value(&native)?,
        ),
        case(
            "shared-reference",
            "ImageSurface::reference",
            json!({"self": root, "reference": native}),
            serde_json::to_value(surface.reference(&native)?)?,
        ),
        case(
            "root-artifact",
            "ImageSurface::from_pixel_artifact",
            json!({"artifact": direct.info(), "tile_side": tile_side, "limits": limits, "pixel_limits": pixel_limits}),
            reader(&ImageSurface::from_pixel_artifact(
                &direct,
                tile_side,
                limits,
                pixel_limits,
            )?)?,
        ),
    ];
    let mut jpeg_bytes = io::Cursor::new(Vec::new());
    DynamicImage::ImageRgb8(image.to_rgb8()).write_to(&mut jpeg_bytes, ImageFormat::Jpeg)?;
    let jpeg = ImageDocument::from_bytes("jpeg-parity", jpeg_bytes.into_inner())?;
    let jpeg_artifact = PixelArtifact::decode_image_document(jpeg.clone(), pixel_limits)?;
    let jpeg_surface = ImageSurface::from_image_document(&jpeg, tile_side, limits, pixel_limits)?;
    for (name, method, arguments, observed) in [
        (
            "jpeg-decode-direct",
            "PixelArtifact::decode_image_document",
            json!({"document": jpeg.id(), "limits": pixel_limits}),
            artifact(&jpeg_artifact)?,
        ),
        (
            "jpeg-reader",
            "ImageSurface::from_image_document",
            json!({"document": jpeg.id(), "tile_side": tile_side, "limits": limits, "pixel_limits": pixel_limits}),
            reader(&jpeg_surface)?,
        ),
        (
            "jpeg-direct",
            "ImageSurface::direct_image",
            json!({"self": jpeg_surface.root_reference()}),
            artifact(&jpeg_surface.direct_image()?)?,
        ),
        (
            "jpeg-overview",
            "ImageSurface::overview_image",
            json!({"self": jpeg_surface.root_reference(), "max_side": 4}),
            artifact(&jpeg_surface.overview_image(4)?)?,
        ),
        (
            "jpeg-crop",
            "ImageSurface::crop_rect",
            json!({"self": jpeg_surface.root_reference(), "rect": rect, "max_png_bytes": pixel_limits.max_output_bytes}),
            {
                let value = jpeg_surface.crop_rect(rect, pixel_limits.max_output_bytes)?;
                json!({"reference": value.reference, "rect": value.rect, "artifact": artifact(&value.artifact)?, "png": value.png()})
            },
        ),
    ] {
        cases.push(case(name, method, arguments, observed));
    }
    for (name, operation) in [
        ("read-overview", ReadOperation::Overview),
        (
            "read-expand",
            ReadOperation::Expand {
                reference: root.clone(),
            },
        ),
        (
            "read-inspect",
            ReadOperation::Inspect {
                reference: root.clone(),
            },
        ),
        (
            "read-parent",
            ReadOperation::Parent {
                reference: root.clone(),
            },
        ),
    ] {
        let request = ReadRequest {
            operation,
            budget: Budget::default(),
            continuation: None,
        };
        cases.push(case(
            name,
            "SurfaceRead::read",
            json!({"self": root, "request": request}),
            serde_json::to_value(surface.read(&request)?)?,
        ));
    }
    // Rust is the producer for these portable provenance envelopes. Python must
    // restore them through ArchivedSource, never manufacture a native handle.
    for (name, source, orientation) in [
        (
            "screenshot-root",
            PixelSource::BrowserScreenshot {
                identity: "screenshot:parity".into(),
            },
            PixelOrientation::NotApplicable,
        ),
        (
            "video-frame-root",
            PixelSource::VideoFrame {
                source_document_id: "video-parity".into(),
                source_sha256: "a".repeat(64),
                observation: "video-observation".into(),
                reference: "frame:125000".into(),
                requested_us: 125_000,
                source_pts_us: 124_000,
            },
            PixelOrientation::DecoderApplied,
        ),
    ] {
        let root_artifact = PixelArtifact::from_raster_document(
            document.clone(),
            source,
            PixelCoordinateSpace {
                kind: PixelCoordinateKind::DecodedCanvas,
                width: 8,
                height: 4,
                orientation,
            },
        )?;
        let retained = ArchivedSource::new_pixel_artifact(name, &root_artifact, tile_side, None);
        let opened =
            ImageSurface::from_pixel_artifact(&root_artifact, tile_side, limits, pixel_limits)?;
        cases.push(case(name, "ImageSurface::from_pixel_artifact", json!({"source_envelope": retained, "artifact": root_artifact.info(), "tile_side": tile_side, "limits": limits, "pixel_limits": pixel_limits}), json!({"reader": reader(&opened)?, "direct": artifact(&opened.direct_image()?)?, "crop": artifact(&opened.crop_rect(rect, pixel_limits.max_output_bytes)?.artifact)?})));
    }
    let other_doc = ImageDocument::from_bytes("other-image", document.bytes().to_vec())?;
    let other = ImageSurface::from_image_document(&other_doc, tile_side, limits, pixel_limits)?;
    let invalid_rect = PixelRect {
        x: 7,
        y: 0,
        width: 2,
        height: 1,
    };
    let invalid_map = PixelRect {
        x: 4,
        y: 0,
        width: 1,
        height: 1,
    };
    let mut errors = vec![
        error(
            "foreign-reference",
            "ImageSurface::crop",
            json!({"reference": root}),
            other.crop(&root, pixel_limits.max_output_bytes).map(|_| ()),
        )?,
        error(
            "crop-outside",
            "ImageSurface::crop_rect",
            json!({"rect": invalid_rect}),
            surface
                .crop_rect(invalid_rect, pixel_limits.max_output_bytes)
                .map(|_| ()),
        )?,
        error(
            "crop-zero-budget",
            "ImageSurface::crop_rect",
            json!({"rect": rect, "max_png_bytes": 0}),
            surface.crop_rect(rect, 0).map(|_| ()),
        )?,
        error(
            "crop-byte-bound",
            "ImageSurface::crop_rect",
            json!({"rect": rect, "max_png_bytes": 1}),
            surface.crop_rect(rect, 1).map(|_| ()),
        )?,
        error(
            "overview-zero",
            "ImageSurface::overview_image",
            json!({"max_side": 0}),
            surface.overview_image(0).map(|_| ()),
        )?,
        error(
            "resize-zero",
            "ImageSurface::resize_image",
            json!({"width": 0, "height": 2}),
            surface.resize_image(0, 2).map(|_| ()),
        )?,
        error(
            "nested-root",
            "ImageSurface::from_pixel_artifact",
            json!({"artifact": crop.artifact.info()}),
            ImageSurface::from_pixel_artifact(&crop.artifact, tile_side, limits, pixel_limits)
                .map(|_| ()),
        )?,
        error(
            "map-outside",
            "PixelArtifact::map_rect_to_source",
            json!({"rect": invalid_map}),
            overview.map_rect_to_source(invalid_map).map(|_| ()),
        )?,
    ];
    let search = ReadRequest {
        operation: ReadOperation::Search {
            query: "red".into(),
        },
        budget: Budget::default(),
        continuation: None,
    };
    errors.push(error(
        "search-unavailable",
        "SurfaceRead::read",
        json!({"request": search}),
        surface.read(&search).map(|_| ()),
    )?);
    let tiny = PixelLimits {
        max_output_bytes: 1,
        ..pixel_limits
    };
    errors.push(error(
        "decode-byte-bound",
        "PixelArtifact::decode_image_document",
        json!({"limits": tiny}),
        PixelArtifact::decode_image_document(document.clone(), tiny).map(|_| ()),
    )?);

    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path().join("original")).await?;
    let reference = crop.artifact.write_to(&archive).await?;
    let restored = PixelArtifact::read_from(&archive, &reference).await?;
    let source =
        ArchivedSource::new_pixel_artifact("root", &direct, tile_side, Some(surface.index()));
    let derived_source =
        ArchivedSource::new_pixel_artifact("crop", &crop.artifact, tile_side, None);
    let outcome = Outcome::new("image-parity-outcome", ArchiveLimits::default())?
        .with_source(source)?
        .with_source(derived_source)?;
    let outcome_ref = archive.write(&outcome).await?;
    let portable = temporary.path().join("image.yosoi");
    archive.export_file(&outcome_ref, &portable).await?;
    let fresh = Archive::open(temporary.path().join("fresh")).await?;
    let imported = fresh.import_file(&portable).await?;
    let loaded: Outcome = fresh.read(&imported).await?;
    cases.push(case("archive-portable", "PixelArtifact::read_from", json!({"archive": archive.root().file_name().and_then(|name| name.to_str()), "reference": reference, "artifact": crop.artifact.info(), "tile_side": tile_side}), json!({
        "artifact_class": "PixelArtifact", "restored": artifact(&restored)?,
        "outcome_class": "Outcome", "record_id": loaded.record.id(),
        "root": artifact(&loaded.source_pixel_artifact("root", 8 * 1024 * 1024)?)?,
        "crop": artifact(&loaded.source_pixel_artifact("crop", 8 * 1024 * 1024)?)?,
        "restored_surface_identity": loaded.surface("root", limits)?.identity(),
        "source_count": loaded.sources.len(), "complete": loaded.complete, "sealed": loaded.sealed,
    })));
    for row in &mut errors {
        let name = row
            .get("name")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("error fixture lacks name"))?
            .to_owned();
        let arguments = row
            .get_mut("input")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| io::Error::other("error fixture lacks arguments"))?;
        if name == "decode-byte-bound" {
            arguments.insert("document".into(), json!(document.id()));
        } else if name == "nested-root" {
            arguments.insert("tile_side".into(), json!(tile_side));
            arguments.insert("limits".into(), json!(limits));
            arguments.insert("pixel_limits".into(), json!(pixel_limits));
        } else if name == "map-outside" {
            arguments.insert("self".into(), json!(overview.info()));
        } else {
            arguments.insert(
                "self".into(),
                json!(if name == "foreign-reference" {
                    other.root_reference()
                } else {
                    root.clone()
                }),
            );
            if name == "foreign-reference" || name == "crop-outside" {
                arguments.insert("max_png_bytes".into(), json!(pixel_limits.max_output_bytes));
            }
        }
    }
    let output = json!({"schemaVersion": 1, "kind": "yosoi-image-surface-conformance-fixtures", "input": {"id": document.id(), "bytes": document.bytes(), "jpeg": {"id": jpeg.id(), "bytes": jpeg.bytes()}, "tile_side": tile_side, "limits": limits, "pixel_limits": pixel_limits}, "cases": cases, "errorCases": errors});
    let mut writer = io::stdout().lock();
    serde_json::to_writer(&mut writer, &output)?;
    writer.write_all(b"\n")?;
    Ok(())
}
