//! Inspect real video pixels and archive source, frame and crop evidence.
use std::{env, error::Error, fs, io, path::PathBuf};
use yosoi::{
    Archive,
    surface::{
        Budget, PixelRect,
        model::{ReadOperation, ReadRequest, SurfaceRead},
        video::{VideoPolicy, VideoSurface},
    },
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let file = args
        .next()
        .ok_or_else(|| io::Error::other("usage: surface_video FILE OUTPUT [POSITION_US]"))?;
    let output = PathBuf::from(
        args.next()
            .ok_or_else(|| io::Error::other("missing output directory"))?,
    );
    let position = args
        .next()
        .map(|value| value.parse::<u64>())
        .transpose()?
        .unwrap_or(3_500_000);
    fs::create_dir_all(&output)?;
    let video = VideoSurface::open(file, VideoPolicy::default()).await?;
    let reference = video.at(position)?;
    let frame = video.frame(&reference).await?;
    let top = 50.min(frame.info.height.saturating_sub(1));
    let crop = video
        .crop(
            &reference,
            PixelRect {
                x: frame.info.width.saturating_sub(340),
                y: top,
                width: 320.min(frame.info.width),
                height: 300.min(frame.info.height.saturating_sub(top)),
            },
        )
        .await?;
    fs::write(output.join("frame.png"), &frame.png)?;
    fs::write(output.join("crop.png"), &crop.png)?;
    let archive = Archive::open(output.join("archive")).await?;
    let saved = video.write_to(&archive).await?;
    let pixels = crop.write_to(&archive).await?;
    let report = serde_json::json!({
        "video":saved, "frame":pixels, "metadata":video.metadata(),
        "frame_info":frame.info, "crop_info":crop.info,
        "timeline":video.read(&ReadRequest {operation:ReadOperation::Overview, budget:Budget::default(), continuation:None})?
    });
    fs::write(
        output.join("evidence.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
