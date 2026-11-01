//! Decode the supplied shared synthetic clip and emit actual Python parity fixtures.

use serde_json::{Value, json};
use std::{
    env,
    error::Error,
    io::{self, Write},
    path::{Path, PathBuf},
};
use yosoi::{
    Archive, CancellationToken,
    surface::{
        Budget, PixelRect,
        model::{ObservationId, ReadOperation, ReadRequest, SurfaceRead},
        video::{DecodedFrame, VideoPolicy, VideoSurface},
    },
};
#[path = "support/video_conformance.rs"]
mod support;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let path = PathBuf::from(
        env::args()
            .nth(1)
            .ok_or_else(|| io::Error::other("expected shared clip path"))?,
    );
    let policy = VideoPolicy {
        frame_max_side: 64,
        min_interval_us: 125_000,
        ..VideoPolicy::default()
    };
    let video = VideoSurface::open(&path, policy.clone()).await?;
    let mut cases = source_cases(&video, &path, &policy).await?;
    cases.extend(navigation_cases(&video).await?);
    let root = video.root_reference();
    let reference = video.at(125_000)?;
    let rect = PixelRect {
        x: 8,
        y: 4,
        width: 16,
        height: 8,
    };
    let cropped = video.crop(&reference, rect).await?;
    cases.push(support::case(
        "crop",
        "yosoi::VideoSurface::crop",
        json!({"self":root,"reference":reference,"rect":rect}),
        support::frame(&cropped)?,
    ));
    cases.extend(archive_cases(&video, &cropped).await?);
    let errors = error_cases(&video, &cropped, rect).await?;
    let output = json!({"schemaVersion":1,"kind":"yosoi-video-conformance-fixtures","input":{"policy":policy,"filename":path.file_name().and_then(|name|name.to_str())},"cases":cases,"errorCases":errors});
    let mut writer = io::stdout().lock();
    serde_json::to_writer(&mut writer, &output)?;
    writer.write_all(b"\n")?;
    Ok(())
}

async fn source_cases(
    video: &VideoSurface,
    path: &Path,
    policy: &VideoPolicy,
) -> Result<Vec<Value>, Box<dyn Error>> {
    let mut cases = vec![support::case(
        "open",
        "yosoi::VideoSurface::open",
        json!({"path":path,"policy":policy}),
        support::video(video),
    )];
    let document = video
        .source_document()
        .ok_or_else(|| io::Error::other("fixture source lacks VideoDocument"))?;
    let from_document = VideoSurface::from_document(document, policy.clone()).await?;
    cases.push(support::case(
        "from-document",
        "yosoi::VideoSurface::from_document",
        json!({"document":{"id":document.id(),"sha256":document.sha256()},"policy":policy}),
        support::video(&from_document),
    ));
    Ok(cases)
}

async fn navigation_cases(video: &VideoSurface) -> Result<Vec<Value>, Box<dyn Error>> {
    let root = video.root_reference();
    let mut cases = Vec::new();
    for (name, operation) in [
        ("overview", ReadOperation::Overview),
        (
            "expand",
            ReadOperation::Expand {
                reference: root.clone(),
            },
        ),
    ] {
        let request = ReadRequest {
            operation,
            budget: Budget {
                bytes: 4096,
                items: 3,
            },
            continuation: None,
        };
        cases.push(support::case(
            name,
            "yosoi::VideoSurface::read",
            json!({"self":root,"request":request}),
            serde_json::to_value(video.read(&request)?)?,
        ));
    }
    for (name, position) in [
        ("frame-zero", 0),
        ("frame-next", 125_000),
        ("frame-half", 500_000),
    ] {
        let reference = video.at(position)?;
        let value = video.frame(&reference).await?;
        cases.push(support::case(
            name,
            "yosoi::VideoSurface::frame",
            json!({"self":root,"reference":reference}),
            support::frame(&value)?,
        ));
    }
    Ok(cases)
}

async fn archive_cases(
    video: &VideoSurface,
    cropped: &DecodedFrame,
) -> Result<Vec<Value>, Box<dyn Error>> {
    let mut cases = Vec::new();
    let temporary = tempfile::tempdir()?;
    let archive = Archive::open(temporary.path().join("archive")).await?;
    let frame_ref = cropped.write_to(&archive).await?;
    let restored_frame = DecodedFrame::read_from(&archive, &frame_ref).await?;
    let frame_value = support::frame(&restored_frame)?;
    cases.push(support::case("archive-frame","yosoi::DecodedFrame::read_from",json!({"archive":"archive","reference":{"kind":"FrameArchiveRef","selected_value":frame_value},"observed_storage_reference":frame_ref}),frame_value));
    let video_ref = video.write_to(&archive).await?;
    let restored_video = VideoSurface::read_from(&archive, &video_ref).await?;
    let video_value = support::video(&restored_video);
    cases.push(support::case("archive-video","yosoi::VideoSurface::read_from",json!({"archive":"archive","reference":{"kind":"VideoArchiveRef","selected_value":video_value},"observed_storage_reference":video_ref}),video_value));
    Ok(cases)
}

async fn error_cases(
    video: &VideoSurface,
    cropped: &DecodedFrame,
    rect: PixelRect,
) -> Result<Vec<Value>, Box<dyn Error>> {
    let root = video.root_reference();
    let reference = video.at(125_000)?;
    let token = CancellationToken::new();
    token.cancel();
    let mut errors = vec![support::error(
        "cancelled-frame",
        "yosoi::VideoSurface::frame_cancellable",
        json!({"self":root,"reference":reference,"cancellation":{"cancelled":token.is_cancelled()}}),
        "Cancelled",
        video
            .frame_cancellable(&reference, &token)
            .await
            .map(|_| ()),
    )?];
    let mut foreign = reference.clone();
    foreign.observation = ObservationId::new("foreign-video")?;
    errors.push(support::error(
        "foreign-reference",
        "yosoi::VideoSurface::frame",
        json!({"self":root,"reference":foreign}),
        "Surface",
        video.frame(&foreign).await.map(|_| ()),
    )?);
    errors.push(support::error(
        "nested-crop",
        "yosoi::VideoSurface::crop",
        json!({"self":root,"reference":cropped.info.reference,"rect":rect}),
        "Invalid",
        video.crop(&cropped.info.reference, rect).await.map(|_| ()),
    )?);
    let outside = PixelRect {
        x: 63,
        y: 0,
        width: 2,
        height: 2,
    };
    errors.push(support::error(
        "crop-outside",
        "yosoi::VideoSurface::crop",
        json!({"self":root,"reference":reference,"rect":outside}),
        "Invalid",
        video.crop(&reference, outside).await.map(|_| ()),
    )?);
    let tail = video.at(875_000)?;
    errors.push(support::error(
        "tail-no-frame",
        "yosoi::VideoSurface::frame",
        json!({"self":root,"reference":tail}),
        "NoFrameAtOrAfter",
        video.frame(&tail).await.map(|_| ()),
    )?);
    errors.push(support::error(
        "at-end",
        "yosoi::VideoSurface::at",
        json!({"self":root,"position_us":video.metadata().duration_us}),
        "Invalid",
        video.at(video.metadata().duration_us).map(|_| ()),
    )?);
    Ok(errors)
}
