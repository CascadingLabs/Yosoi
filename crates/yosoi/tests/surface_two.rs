//! Independent behavior checks across web documents and actual decoded videos.
#![cfg(feature = "surface-video")]
use serde_json::json;
use std::{error::Error, io, path::Path, process::Stdio};
use tokio::{fs, process::Command};
use yosoi::{
    Archive,
    documents::Document,
    surface::{
        Budget, PixelRect, Surface,
        browser::WebSurface,
        model::{
            AddressToken, ObservationId, ReadOperation, ReadRequest, ReadResult,
            Reference as EvidenceReference, SourceId, SurfaceRead,
        },
        video::{DecodedFrame, VideoPolicy, VideoSurface},
    },
};
type TestResult = Result<(), Box<dyn Error + Send + Sync>>;
async fn fixture(path: &Path) -> TestResult {
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
            "color=c=red:s=320x180:r=2:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=2:d=2",
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
const fn request(operation: ReadOperation, bytes: usize) -> ReadRequest {
    ReadRequest {
        operation,
        budget: Budget { bytes, items: 20 },
        continuation: None,
    }
}
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify externally visible evidence and failure boundaries."
)]
async fn both_readers_share_protocol_budgets_and_reference_isolation() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("clock.mp4");
    fixture(&path).await?;
    let video = VideoSurface::open(&path, VideoPolicy::default()).await?;
    let web = WebSurface::new(
        Surface::new(&Document::html(
            "web",
            b"<main><button>Latest</button><a href='/old'>v0.1.0</a></main>".to_vec(),
        )?)?,
        SourceId::new("web:test")?,
    )?;
    let relabeled = WebSurface::new(
        Surface::new(&Document::html(
            "web",
            b"<main><button>Latest</button><a href='/old'>v0.1.0</a></main>".to_vec(),
        )?)?,
        SourceId::new("web:other")?,
    )?;
    assert!(
        relabeled
            .read(&request(
                ReadOperation::Inspect {
                    reference: web.root_reference()
                },
                4096
            ))
            .is_err()
    );
    let readers: [&dyn SurfaceRead; 2] = [&web, &video];
    for reader in readers {
        let mut query = request(ReadOperation::Overview, 1024);
        let mut seen = 0_usize;
        loop {
            let result = reader.read(&query)?;
            assert!(serde_json::to_vec(&result)?.len() <= 1024);
            let ReadResult::Page(page) = result else {
                return Err(io::Error::other("overview did not produce a page").into());
            };
            seen = seen.saturating_add(page.entries.len());
            for entry in &page.entries {
                assert_eq!(entry.reference.observation, reader.observation().id);
            }
            if let Some(next) = page.next {
                query.continuation = Some(next);
            } else {
                assert_eq!(seen, page.total);
                break;
            }
        }
        assert!(
            !reader.descriptor().controllable,
            "immutable reader must not manufacture live authority"
        );
    }
    assert!(
        video
            .read(&request(
                ReadOperation::Inspect {
                    reference: web.root_reference()
                },
                4096
            ))
            .is_err()
    );
    assert!(
        web.read(&request(
            ReadOperation::Inspect {
                reference: video.root_reference()
            },
            4096
        ))
        .is_err()
    );
    assert!(
        video
            .read(&request(
                ReadOperation::Search {
                    query: "Latest".into()
                },
                4096
            ))
            .is_err()
    );
    let result = video.read(&request(ReadOperation::Overview, 1024))?;
    let ReadResult::Page(page) = result else {
        return Err(io::Error::other("overview absent").into());
    };
    let mut wrong = request(
        ReadOperation::Expand {
            reference: video.root_reference(),
        },
        1024,
    );
    wrong.continuation = page.next;
    assert!(
        video.read(&wrong).is_err(),
        "a continuation cannot change operation or scope"
    );
    Ok(())
}
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions compare measured timestamps and actual decoded pixels."
)]
async fn frames_measure_media_time_and_crops_use_decoded_pixels() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("clock.mp4");
    fixture(&path).await?;
    let video = VideoSurface::open(&path, VideoPolicy::default()).await?;
    assert_eq!(video.metadata().stream_start_us, 5_000_000);
    assert_eq!(video.metadata().duration_us, 4_000_000);
    let early = video.frame(&video.at(1_250_000)?).await?;
    assert_eq!(early.info.position_us, Some(1_500_000));
    assert_eq!(early.info.source_pts_us, 6_500_000);
    assert_eq!(early.info.width, 320);
    assert_eq!(early.info.height, 180);
    let red = image::load_from_memory(&early.png)?.to_rgb8();
    assert!(red.get_pixel(20, 20).0.first() > red.get_pixel(20, 20).0.get(2));
    let reference = video.at(2_250_000)?;
    let late = video.frame(&reference).await?;
    assert_eq!(late.info.position_us, Some(2_500_000));
    assert_eq!(late.info.source_pts_us, 7_500_000);
    let blue = image::load_from_memory(&late.png)?.to_rgb8();
    assert!(blue.get_pixel(20, 20).0.get(2) > blue.get_pixel(20, 20).0.first());
    let crop = video
        .crop(
            &reference,
            PixelRect {
                x: 30,
                y: 40,
                width: 100,
                height: 60,
            },
        )
        .await?;
    assert_eq!((crop.info.width, crop.info.height), (100, 60));
    assert_eq!(
        (crop.info.canvas_width, crop.info.canvas_height),
        (320, 180)
    );
    let restored = video.frame(&crop.info.reference).await?;
    assert_eq!(restored.png, crop.png);
    assert!(
        video
            .crop(
                &reference,
                PixelRect {
                    x: 319,
                    y: 0,
                    width: 2,
                    height: 1
                }
            )
            .await
            .is_err()
    );
    assert!(video.at(4_000_000).is_err());
    assert!(
        video.frame(&video.at(3_750_000)?).await.is_err(),
        "at-or-after sampling must not invent a frame in the final-frame tail"
    );
    Ok(())
}
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions check snapshot and Archive immutability, not decoder implementation details."
)]
async fn frozen_sources_and_archived_pixels_survive_original_file_changes() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("snapshot.mp4");
    fixture(&path).await?;
    let video = VideoSurface::open(&path, VideoPolicy::default()).await?;
    fs::write(&path, b"original file replaced after surface preparation").await?;
    let reference = video.at(2_250_000)?;
    let frame = video.frame(&reference).await?;
    let archive = Archive::open(directory.path().join("archive")).await?;
    let saved = video.write_to(&archive).await?;
    let pixels = frame.write_to(&archive).await?;
    fs::remove_file(path).await?;
    drop(video);
    let restored = VideoSurface::read_from(&archive, &saved).await?;
    assert_eq!(restored.observation().id, reference.observation);
    let restored_pixels = DecodedFrame::read_from(&archive, &pixels).await?;
    assert_eq!(restored_pixels.png, frame.png);
    assert_eq!(restored_pixels.info.position_us, Some(2_500_000));
    let mut wrong = saved.clone();
    wrong.observation = ObservationId::new("wrong")?;
    assert!(VideoSurface::read_from(&archive, &wrong).await.is_err());
    let mut malformed = reference;
    malformed.address = AddressToken::new("f:999999999999999")?;
    assert!(restored.frame(&malformed).await.is_err());
    Ok(())
}
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions check explicit resource and media failure behavior."
)]
async fn malformed_sources_and_processing_limits_fail_explicitly() -> TestResult {
    let directory = tempfile::tempdir()?;
    let invalid = directory.path().join("invalid.mp4");
    fs::write(&invalid, b"not a movie").await?;
    assert!(
        VideoSurface::open(&invalid, VideoPolicy::default())
            .await
            .is_err()
    );
    let path = directory.path().join("valid.mp4");
    fixture(&path).await?;
    assert!(
        VideoSurface::open(
            &path,
            VideoPolicy {
                max_source_bytes: 16,
                ..VideoPolicy::default()
            }
        )
        .await
        .is_err()
    );
    let playlist = directory.path().join("playlist.ffconcat");
    fs::write(&playlist, b"ffconcat version 1.0\nfile 'valid.mp4'\n").await?;
    assert!(
        VideoSurface::open(&playlist, VideoPolicy::default())
            .await
            .is_err(),
        "a single-file snapshot must not silently depend on external playlist files"
    );
    let tiny = VideoSurface::open(
        &path,
        VideoPolicy {
            max_frame_bytes: 8,
            ..VideoPolicy::default()
        },
    )
    .await?;
    assert!(tiny.frame(&tiny.at(0)?).await.is_err());
    let normal = VideoSurface::open(&path, VideoPolicy::default()).await?;
    let small = VideoSurface::open(
        &path,
        VideoPolicy {
            frame_max_side: 160,
            ..VideoPolicy::default()
        },
    )
    .await?;
    assert_ne!(normal.observation().id, small.observation().id);
    assert_eq!(normal.descriptor().source, small.descriptor().source);
    assert!(small.frame(&normal.at(0)?).await.is_err());
    let frame = small.frame(&small.at(0)?).await?;
    assert_eq!((frame.info.width, frame.info.height), (160, 90));
    assert!(
        serde_json::from_value::<EvidenceReference>(json!({"observation":"ok","address":""}))
            .is_err()
    );
    Ok(())
}

#[cfg(feature = "surface-connections")]
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify runtime authority and lifecycle."
)]
async fn runtime_executes_without_terminal_and_closes_idempotently() -> TestResult {
    use yosoi::surface::{SurfaceConnection, SurfacePolicy, video::VideoSession};
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("source.mp4");
    fixture(&path).await?;
    let output = directory.path().join("output");
    let mut runtime = VideoSession::open(
        &path,
        SurfacePolicy {
            output: Some(output.clone()),
            ..SurfacePolicy::default()
        },
        160,
    )
    .await?;
    let ready = runtime.ready()?;
    assert_eq!(ready["representation"], "yosoi.video.timeline.v1");
    let description = runtime.execute(json!({"op":"describe"})).await?;
    assert_eq!(description["descriptor"]["controllable"], false);
    assert!(runtime.execute(json!({"op":"hot"})).await.is_err());
    assert!(
        runtime
            .execute(json!({"op":"attach","budget":1}))
            .await
            .is_err()
    );
    let before = runtime.execute(json!({"op":"status"})).await?;
    assert_eq!(before["cursor"]["mode"], "detached");
    runtime.execute(json!({"op":"attach"})).await?;
    let read = runtime
        .execute(json!({"op":"read","request":{"operation":{"kind":"overview"}}}))
        .await?;
    assert_eq!(read["kind"], "page");
    assert!(output.join("trace.json").is_file());
    runtime.close().await?;
    runtime.close().await?;
    assert!(runtime.ready().is_err());
    assert!(runtime.execute(json!({"op":"status"})).await.is_err());
    Ok(())
}
