//! Capture a caller-authored download Flow on the same native browser Work.
//! Usage: media_download <page-url> <trigger-flow.json> <archive-root>
#![cfg(feature = "browser")]
use std::{env, error::Error, io};
use tokio::fs;
use yosoi::{
    Archive,
    automation_record::OperationStatus,
    flow::Flow,
    session::{self, DownloadOptions},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let url = args
        .next()
        .ok_or_else(|| io::Error::other("missing page URL"))?;
    let trigger_path = args
        .next()
        .ok_or_else(|| io::Error::other("missing trigger Flow file"))?;
    let root = args
        .next()
        .ok_or_else(|| io::Error::other("missing Archive root"))?;
    let trigger: Flow = serde_json::from_slice(&fs::read(trigger_path).await?)?;
    let browser = session::new().acquire().await?;
    let result = async {
        let file = {
            let work = browser.work().await?;
            let receipt = work.navigate(&url).await?;
            if receipt.status != OperationStatus::Observed {
                return Err(io::Error::other("page navigation was not confirmed").into());
            }
            let file = {
                let capture = work.expect_download(DownloadOptions::default()).await?;
                let outcome = match trigger.with_lease(&work).invoke().await {
                    Ok(outcome) => outcome,
                    Err(error) => {
                        capture.cancel().await?;
                        return Err(error.into());
                    }
                };
                if let Err(error) = outcome.require_completed() {
                    capture.cancel().await?;
                    return Err(error.into());
                }
                capture.wait().await?
            };
            drop(work);
            file
        };
        Ok::<_, Box<dyn Error>>(file)
    }
    .await;
    let cleanup = browser.close().await;
    drop(browser);
    let file = result?;
    cleanup?;
    let archive = Archive::open(root).await?;
    let reference = archive.write(&file).await?;
    println!(
        "Downloaded {} bytes; sha256 {}; reference {reference}",
        file.byte_len(),
        file.sha256()
    );
    Ok(())
}
