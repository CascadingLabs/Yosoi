use std::{
    path::Path,
    path::PathBuf,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use chromiumoxide::detection::{DetectionOptions, default_executable};
use tokio::{process::Command, time};

use crate::internal::browser::error::{Result, VoidCrawlError};

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

// Regular Linux Stable release history, reviewed 2026-10-10 UTC. Only the
// current and preceding milestones are eligible. The snapshot expires after
// 30 days; each superseded release has its own 30-day deadline.
// Source: https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions/all/releases
const STABLE_RELEASES: &[(&str, u64)] = &[
    ("155.0.8059.39", 1_791_590_400),
    ("154.0.8037.97", 1_791_306_547),
    ("154.0.8037.92", 1_790_902_579),
    ("154.0.8037.57", 1_790_706_629),
];
const REVIEWED_AT: u64 = 1_791_590_400; // 2026-10-10 UTC
const MAX_AGE: u64 = 30 * 24 * 60 * 60;

pub(super) fn supported_version(identity: &str) -> Result<&str> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| VoidCrawlError::LaunchFailed("invalid system clock".into()))?
        .as_secs();
    supported_version_at(identity, now)
}

fn supported_version_at(identity: &str, now: u64) -> Result<&str> {
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
    if now < REVIEWED_AT || now.saturating_sub(REVIEWED_AT) > MAX_AGE {
        return Err(VoidCrawlError::LaunchFailed(
            "Stable eligibility review is expired".into(),
        ));
    }
    if !STABLE_RELEASES.iter().any(|(release, last_served)| {
        *release == version && now.saturating_sub(*last_served) <= MAX_AGE
    }) {
        return Err(VoidCrawlError::LaunchFailed(
            "browser is outside the reviewed Stable version/age window".into(),
        ));
    }
    Ok(version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stable_identity_and_age_window_are_enforced() {
        for identity in [
            "Google Chrome 155.0.8059.39",
            "Chromium 155.0.8059.39 Arch Linux",
            "Google Chrome 154.0.8037.97",
            "Chromium 154.0.8037.97 Arch Linux",
            "Chromium 154.0.8037.92 built on Debian GNU/Linux 13 (trixie)",
        ] {
            assert!(supported_version_at(identity, REVIEWED_AT).is_ok());
        }
        for identity in [
            "Google Chrome 152.0.7977.82",
            "Google Chrome 153.0.8010.52",
            "Google Chrome 155.0.8059.26",
            "Google Chrome 154.0.8037.97 beta",
            "Google Chrome Canary 154.0.8037.97",
            "Google Chrome for Testing 154.0.8037.97",
            "Not Chrome 154.0.8037.97",
        ] {
            assert!(
                supported_version_at(identity, REVIEWED_AT).is_err(),
                "{identity}"
            );
        }
        assert!(
            supported_version_at("Google Chrome 154.0.8037.57", 1_790_706_629 + MAX_AGE + 1)
                .is_err()
        );
        assert!(
            supported_version_at("Google Chrome 155.0.8059.39", REVIEWED_AT + MAX_AGE + 1).is_err()
        );
    }
}
