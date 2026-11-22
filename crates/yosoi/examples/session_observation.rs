//! Capture a screenshot, with optional native tab recording, through one retained Session.
use std::{env, error::Error, io, result::Result as StdResult};
use yosoi::{
    Archive,
    automation_record::OperationStatus,
    policy::{Acquisition, BrowserMode, Policy},
    session::{self, RecordingOptions, ScreenshotOptions, SessionPolicy},
};

type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut args = env::args().skip(1);
    let url = args
        .next()
        .ok_or_else(|| io::Error::other("usage: session_observation URL [--record]"))?;
    let record = match args.next().as_deref() {
        None => false,
        Some("--record") => true,
        _ => return Err(io::Error::other("expected --record or no option").into()),
    };
    if args.next().is_some() {
        return Err(io::Error::other("unexpected extra argument").into());
    }
    let mode = if record {
        BrowserMode::Headful
    } else {
        BrowserMode::Headless
    };
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![Acquisition::Browser(mode)];
    policy.observe.native_tab_capture = record;
    let browser = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            mode,
            execution_concurrency: 1,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let result = Box::pin(capture(&browser, &url, record)).await;
    let closed = browser.close().await;
    drop(browser);
    result?;
    closed?;
    Ok(())
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "The owned Work lease stays alive until its consuming async release completes, including error paths"
)]
async fn capture(browser: &session::Session, url: &str, record: bool) -> Result<()> {
    let work = browser.work().await?;
    let result = Box::pin(async {
        let navigation = work.navigate(url).await?;
        if navigation.status != OperationStatus::Observed {
            return Err(io::Error::other(format!(
                "navigation not observed: {:?}",
                navigation.status
            ))
            .into());
        }
        let recording = if record {
            Some(work.start_recording(RecordingOptions::default()).await?)
        } else {
            None
        };
        let image = work.screenshot_with(ScreenshotOptions::default()).await;
        // Finalize an optional interval even when screenshot materialization failed.
        let recording = match recording {
            Some(handle) => Some(handle.stop().await?),
            None => None,
        };
        let image = image?;
        let archive = Archive::open(".generated/session-observation-example").await?;
        let image_ref = archive.write(&image.document).await?;
        println!(
            "screenshot={} complete={}",
            image_ref, image.metadata.complete
        );
        println!("capture={}", serde_json::to_string(&image.metadata)?);
        if let Some(output) = recording {
            let reference = output.write_to(&archive).await?;
            println!(
                "recording={} complete={} segments={} gaps={}",
                reference,
                output.complete,
                output.segments.len(),
                output.gaps.len()
            );
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    })
    .await;
    let released = work.release().await;
    result?;
    released?;
    Ok(())
}
