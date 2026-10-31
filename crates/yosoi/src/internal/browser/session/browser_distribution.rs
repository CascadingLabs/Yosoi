use std::{path::Path, path::PathBuf, result::Result as StdResult, time::Duration};

use crate::internal::browser::vendor::chromiumoxide::detection::{
    DetectionOptions, default_executable,
};
use tokio::{process::Command, time};

use crate::internal::browser::error::{Result, VoidCrawlError};

const BROWSER_IDENTITY_TIMEOUT: Duration = Duration::from_secs(5);

pub async fn supported_chrome_executable(explicit: Option<&str>) -> Result<PathBuf> {
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
    let identity = browser_identity(executable).await?;
    supported_version(&identity)?;
    Ok(())
}

pub(super) async fn browser_identity(executable: &Path) -> Result<String> {
    let output = time::timeout(
        BROWSER_IDENTITY_TIMEOUT,
        Command::new(executable)
            .kill_on_drop(true)
            .arg("--version")
            .output(),
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
    Ok(version)
}

// Launch admission is independent of the exact browser/CDP certification tuple.
const MINIMUM_CHROME_MILESTONE: u32 = 153;

pub(super) fn supported_version(identity: &str) -> Result<&str> {
    if identity.contains("Chrome for Testing") {
        return Err(VoidCrawlError::LaunchFailed(
            "testing-only browser distributions are prohibited".into(),
        ));
    }
    let version = identity
        .trim()
        .strip_prefix("Google Chrome ")
        .or_else(|| identity.trim().strip_prefix("Chromium "))
        .and_then(|value| value.split_whitespace().next())
        .ok_or_else(|| VoidCrawlError::LaunchFailed("unrecognized browser distribution".into()))?;
    let suffix = identity
        .trim()
        .strip_prefix("Google Chrome ")
        .or_else(|| identity.trim().strip_prefix("Chromium "))
        .and_then(|value| value.strip_prefix(version))
        .unwrap_or_default()
        .trim();
    if !matches!(
        suffix,
        "" | "Arch Linux"
            | "built on Debian GNU/Linux 12 (bookworm)"
            | "built on Debian GNU/Linux 13 (trixie)"
    ) {
        return Err(VoidCrawlError::LaunchFailed(
            "non-Stable browser distribution".into(),
        ));
    }
    let components = version
        .split('.')
        .map(str::parse::<u32>)
        .collect::<StdResult<Vec<_>, _>>()
        .map_err(|_| VoidCrawlError::LaunchFailed("invalid browser version".into()))?;
    let [milestone, _, _, _] = components.as_slice() else {
        return Err(VoidCrawlError::LaunchFailed(
            "invalid browser version".into(),
        ));
    };
    if *milestone < MINIMUM_CHROME_MILESTONE {
        return Err(VoidCrawlError::LaunchFailed(
            "regular Chrome/Chromium 153 or newer is required".into(),
        ));
    }
    Ok(version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regular_chrome_from_milestone_153_is_admitted() {
        for identity in [
            "Google Chrome 153.0.0.0",
            "Google Chrome 153.0.8010.52",
            "Chromium 154.0.8037.97 Arch Linux",
            "Google Chrome 155.0.8059.39",
            "Chromium 155.0.8059.39 Arch Linux",
            "Google Chrome 156.0.8078.47",
            "Chromium 156.0.8078.47 Arch Linux",
            "Google Chrome 155.0.8059.84",
            "Chromium 155.0.8059.79 built on Debian GNU/Linux 13 (trixie)",
            "Chromium 154.0.8037.97 built on Debian GNU/Linux 12 (bookworm)",
            "Google Chrome 200.0.9999.1",
            "Chromium 200.1.2.3",
        ] {
            assert!(supported_version(identity).is_ok(), "{identity}");
        }
    }

    #[test]
    fn old_non_stable_and_malformed_browsers_are_rejected() {
        for identity in [
            "Google Chrome 152.999.999.999",
            "Google Chrome 152.0.7977.82",
            "Chromium 152.0.7977.82 Arch Linux",
            "Google Chrome 154.0.8037.97 beta",
            "Google Chrome Canary 154.0.8037.97",
            "Google Chrome for Testing 154.0.8037.97",
            "Not Chrome 154.0.8037.97",
            "Google Chrome 153",
            "Google Chrome 153.0.0",
            "Google Chrome 153.0.0.0.1",
            "Google Chrome 153.0.x.1",
            "Google Chrome 153..0.1",
            "Google Chrome 4294967296.0.0.1",
            "Google Chrome ",
        ] {
            assert!(supported_version(identity).is_err(), "{identity}");
        }
    }
}
