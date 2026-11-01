//! A status indicator investigation survives moving the complete evidence to a fresh process.
#![cfg(all(unix, feature = "surface-video", feature = "cli"))]

use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{error::Error, io, path::Path, process::Stdio};
use tokio::{fs, process::Command};
use yosoi::{
    Archive,
    archive::DocumentArchiveRef,
    automation_record::{OperationReceipt, OperationStatus},
    documents::Document,
    surface::{
        ArchiveLimits, ArchivedSource, Outcome, PixelRect,
        model::ObservationId,
        video::{DecodedFrame, FrameArchiveRef, VideoArchiveRef, VideoPolicy, VideoSurface},
    },
};

type Result<T = ()> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

async fn dashboard(path: &Path) -> Result {
    let green = "color=c=0x1b2330:s=320x180:r=2:d=2,drawbox=x=8:y=8:w=304:h=32:c=white:t=fill,drawbox=x=8:y=48:w=96:h=124:c=gray:t=fill,drawbox=x=112:y=48:w=200:h=124:c=white:t=fill,drawbox=x=128:y=100:w=24:h=56:c=blue:t=fill,drawbox=x=164:y=72:w=24:h=84:c=blue:t=fill,drawbox=x=288:y=16:w=16:h=16:c=0x00ff00:t=fill";
    let red = green.replace("0x00ff00", "0xff0000");
    let output = Command::new("ffmpeg")
        .args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-filter_complex_threads",
            "1",
            "-f",
            "lavfi",
            "-i",
            green,
            "-f",
            "lavfi",
            "-i",
            &red,
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-threads:v",
            "1",
            "-output_ts_offset",
            "5",
        ])
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .await?;
    if !output.status.success() {
        return Err(io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into());
    }
    Ok(())
}

async fn record(
    outcome: &mut Outcome,
    archive: &Archive,
    id: &str,
    kind: &str,
    value: Value,
) -> Result {
    let key = value
        .get("document")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("missing evidence metadata reference"))?;
    let reference: DocumentArchiveRef = key.parse()?;
    let document = archive.read_document(&reference).await?;
    outcome
        .sources
        .push(ArchivedSource::new(key, &document, None));
    outcome.record.push_operation(OperationReceipt {
        browser: None,
        id: id.into(),
        kind: kind.into(),
        status: OperationStatus::Observed,
        result: Some(value),
        observation: None,
        error: None,
    })?;
    Ok(())
}

fn indicator(frame: &DecodedFrame) -> Result<(u8, u8)> {
    let pixels = image::load_from_memory(&frame.png)?.into_rgb8();
    if pixels.width() != 16 || pixels.height() != 16 {
        return Err(io::Error::other("indicator crop has incorrect dimensions").into());
    }
    let [red, green, _] = pixels.get_pixel(8, 8).0;
    Ok((red, green))
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify real pixels and complete portable replay, not implementation details."
)]
async fn dashboard_status_pixels_and_timestamps_survive_portable_replay() -> Result {
    let root = tempfile::tempdir()?;
    let path = root.path().join("dashboard.mp4");
    dashboard(&path).await?;
    let store = root.path().join("original-store");
    let archive = Archive::open(&store).await?;
    let video = VideoSurface::open(&path, VideoPolicy::default()).await?;
    let first = video.at(0)?;
    let second = video.at(2_000_000)?;
    let rect = PixelRect {
        x: 288,
        y: 16,
        width: 16,
        height: 16,
    };
    let full_green = video.frame(&first).await?;
    let full_red = video.frame(&second).await?;
    let green = video.crop(&first, rect).await?;
    let red = video.crop(&second, rect).await?;
    assert!(matches!(indicator(&green)?, (r, g) if g > 200 && r < 64));
    assert!(matches!(indicator(&red)?, (r, g) if r > 200 && g < 64));
    assert_eq!(green.info.source_pts_us, 5_000_000);
    assert_eq!(red.info.source_pts_us, 7_000_000);
    let mut outcome = Outcome::new("dashboard-status", ArchiveLimits::default())?;
    record(
        &mut outcome,
        &archive,
        "source",
        "surface.video.source",
        serde_json::to_value(video.write_to(&archive).await?)?,
    )
    .await?;
    for (id, frame) in [
        ("green-full", full_green),
        ("red-full", full_red),
        ("green-crop", green),
        ("red-crop", red),
    ] {
        let reference = frame.write_to(&archive).await?;
        let metadata = archive.read_document(&reference.document).await?;
        let metadata: Value = serde_json::from_slice(metadata.bytes())?;
        assert_eq!(
            metadata.get("schema").and_then(Value::as_str),
            Some("yosoi.surface.video-frame.v2")
        );
        assert!(metadata.get("png_base64").is_none());
        record(
            &mut outcome,
            &archive,
            id,
            "surface.video.frame",
            serde_json::to_value(reference)?,
        )
        .await?;
    }
    outcome.sealed = true;
    let saved = archive.write(&outcome).await?;
    let portable = root.path().join("dashboard.yosoi");
    archive.export_file(&saved, &portable).await?;
    drop(video);
    drop(archive);
    fs::remove_file(path).await?;
    fs::remove_dir_all(&store).await?;
    let output = root.path().join("replayed");
    let replay = Command::new(env!("CARGO_BIN_EXE_yosoi"))
        .args(["surface", "replay", "--record"])
        .arg(&portable)
        .arg("--output")
        .arg(&output)
        .env("PATH", "")
        .env("YOSOI_FFMPEG", "/decoder-unavailable")
        .env("YOSOI_FFPROBE", "/probe-unavailable")
        .stdin(Stdio::null())
        .output()
        .await?;
    assert!(
        replay.status.success(),
        "{}",
        String::from_utf8_lossy(&replay.stderr)
    );
    let mut files = fs::read_dir(output).await?;
    let mut png_count = 0_u32;
    while let Some(entry) = files.next_entry().await? {
        if entry
            .path()
            .extension()
            .is_some_and(|extension| extension == "png")
        {
            png_count = png_count
                .checked_add(1)
                .ok_or_else(|| io::Error::other("artifact count overflow"))?;
            image::load_from_memory(&fs::read(entry.path()).await?)?;
        }
    }
    assert_eq!(png_count, 4);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify the explicit v1 video and frame envelope migration path."
)]
async fn legacy_v1_video_and_frame_envelopes_restore_without_migration_rewrites() -> Result {
    let root = tempfile::tempdir()?;
    let path = root.path().join("legacy-source.mp4");
    dashboard(&path).await?;
    let video = VideoSurface::open(&path, VideoPolicy::default()).await?;
    let frame = video.frame(&video.at(0)?).await?;
    let archive = Archive::open(root.path().join("legacy-archive")).await?;
    let metadata = video.metadata().clone();
    let policy = video.policy().clone();
    let mut digest = Sha256::new();
    digest.update(b"yosoi-video-timeline-v1");
    digest.update(metadata.source_sha256.as_bytes());
    digest.update(serde_json::to_vec(&metadata)?);
    digest.update(serde_json::to_vec(&serde_json::json!({
        "width": metadata.width,
        "height": metadata.height,
        "duration_us": metadata.duration_us,
        "start_us": metadata.stream_start_us,
        "decoder": metadata.decoder,
        "side": policy.frame_max_side,
        "interval": policy.min_interval_us,
    }))?);
    let observation = ObservationId::new(format!("video-v1:{:x}", digest.finalize()))?;
    let source_value = serde_json::json!({
        "schema": "yosoi.surface.video-source.v1",
        "metadata": metadata,
        "policy": policy,
        "content_base64": STANDARD.encode(fs::read(&path).await?),
    });
    let source_envelope =
        Document::json("legacy-video-envelope", serde_json::to_vec(&source_value)?)?;
    let source_reference = archive.write_document(&source_envelope).await?;
    let restored_video = VideoSurface::read_from(
        &archive,
        &VideoArchiveRef {
            document: source_reference,
            observation: observation.clone(),
        },
    )
    .await?;
    assert_eq!(restored_video.observation().id, observation);
    assert!(restored_video.source_document().is_none());

    let mut corrupt_source = source_value;
    let digest = corrupt_source
        .pointer_mut("/metadata/source_sha256")
        .ok_or_else(|| io::Error::other("legacy source digest is missing"))?;
    *digest = serde_json::json!("0".repeat(64));
    let corrupt_source = Document::json(
        "corrupt-legacy-video-envelope",
        serde_json::to_vec(&corrupt_source)?,
    )?;
    let corrupt_source = archive.write_document(&corrupt_source).await?;
    assert!(
        VideoSurface::read_from(
            &archive,
            &VideoArchiveRef {
                document: corrupt_source,
                observation: observation.clone(),
            },
        )
        .await
        .is_err()
    );

    let mut legacy_info = frame.info.clone();
    legacy_info.reference.observation = observation.clone();
    legacy_info.pixel_artifact = None;
    let frame_value = serde_json::json!({
        "schema": "yosoi.surface.video-frame.v1",
        "info": legacy_info,
        "png_base64": STANDARD.encode(&frame.png),
    });
    let frame_envelope =
        Document::json("legacy-frame-envelope", serde_json::to_vec(&frame_value)?)?;
    let frame_reference = archive.write_document(&frame_envelope).await?;
    let restored_frame = DecodedFrame::read_from(
        &archive,
        &FrameArchiveRef {
            document: frame_reference,
        },
    )
    .await?;
    assert_eq!(restored_frame.info.reference.observation, observation);
    assert_eq!(restored_frame.png, frame.png);
    assert!(restored_frame.pixel_artifact()?.is_none());

    let mut corrupt_frame = frame_value;
    let digest = corrupt_frame
        .pointer_mut("/info/png_sha256")
        .ok_or_else(|| io::Error::other("legacy frame digest is missing"))?;
    *digest = serde_json::json!("0".repeat(64));
    let corrupt_frame = Document::json(
        "corrupt-legacy-frame-envelope",
        serde_json::to_vec(&corrupt_frame)?,
    )?;
    let corrupt_frame = archive.write_document(&corrupt_frame).await?;
    assert!(
        DecodedFrame::read_from(
            &archive,
            &FrameArchiveRef {
                document: corrupt_frame,
            }
        )
        .await
        .is_err()
    );
    Ok(())
}
