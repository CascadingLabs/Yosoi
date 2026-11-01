//! A status indicator investigation survives moving the complete evidence to a fresh process.
#![cfg(all(unix, feature = "surface-video", feature = "cli"))]

use serde_json::Value;
use std::{error::Error, io, path::Path, process::Stdio};
use tokio::{fs, process::Command};
use yosoi::{
    Archive,
    archive::DocumentArchiveRef,
    automation_record::{OperationReceipt, OperationStatus},
    surface::{
        ArchiveLimits, ArchivedSource, Outcome, PixelRect,
        video::{DecodedFrame, VideoPolicy, VideoSurface},
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
