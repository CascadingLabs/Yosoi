use std::{path::Path, path::PathBuf, time::Duration};

use chromiumoxide::detection::{DetectionOptions, default_executable};
use tokio::{process::Command, time};

use crate::error::{Result, VoidCrawlError};

const BROWSER_IDENTITY_TIMEOUT: Duration = Duration::from_secs(5);

pub(super) async fn supported_chrome_executable(explicit: Option<&str>) -> Result<PathBuf> {
    let executable = explicit.map_or_else(
        || {
            default_executable(DetectionOptions::default()).map_err(|_| {
                VoidCrawlError::LaunchFailed("browser executable could not be resolved".into())
            })
        },
        |value| Ok(PathBuf::from(value)),
    )?;
    verify_supported_browser_distribution(&executable).await?;
    Ok(executable)
}

pub(super) async fn verify_supported_browser_distribution(executable: &Path) -> Result<()> {
    let output = time::timeout(
        BROWSER_IDENTITY_TIMEOUT,
        Command::new(executable).arg("--version").output(),
    )
    .await
    .map_err(|_| VoidCrawlError::LaunchFailed("browser identity check timed out".into()))?
    .map_err(|_| VoidCrawlError::LaunchFailed("browser identity check failed".into()))?;
    if !output.status.success() {
        return Err(VoidCrawlError::LaunchFailed(
            "browser identity check failed".into(),
        ));
    }
    let version = String::from_utf8(output.stdout)
        .map_err(|_| VoidCrawlError::LaunchFailed("browser identity was not UTF-8".into()))?;
    if version.contains("Chrome for Testing") {
        return Err(VoidCrawlError::LaunchFailed(
            "testing-only browser distributions are prohibited".into(),
        ));
    }
    Ok(())
}
