use chromiumoxide::{Browser, cdp::browser_protocol::system_info::GetInfoParams};
use rustls::crypto::ring::default_provider as ring_crypto_provider;
use serde_json::Value;
use std::{path::Path, sync::Once};
use tokio::time;

use super::{browser_distribution, normalize_flag, switch_key};
use crate::error::{Result, VoidCrawlError};

pub(super) fn validate_launch_security(arguments: &[String], no_sandbox: bool) -> Result<()> {
    if no_sandbox || arguments.iter().any(|argument| weakens_security(argument)) {
        return Err(VoidCrawlError::InvalidInput {
            operation: "browser launch",
            reason: "sandbox and site/process isolation must remain enabled",
        });
    }
    Ok(())
}

fn weakens_security(argument: &str) -> bool {
    let flag = normalize_flag(argument);
    match switch_key(flag) {
        "no-sandbox"
        | "disable-setuid-sandbox"
        | "disable-gpu-sandbox"
        | "disable-seccomp-filter-sandbox"
        | "disable-namespace-sandbox"
        | "disable-site-isolation-trials"
        | "disable-web-security"
        | "single-process"
        | "no-zygote"
        | "in-process-gpu" => true,
        "disable-features" => flag.split_once('=').is_some_and(|(_, value)| {
            value.split(',').any(|feature| {
                let name = feature.trim().split(['<', ':']).next().unwrap_or(feature);
                matches!(
                    name,
                    "IsolateOrigins"
                        | "site-per-process"
                        | "SitePerProcess"
                        | "SiteIsolation"
                        | "StrictOriginIsolation"
                )
            })
        }),
        _ => false,
    }
}

pub(super) fn require_local_attachment(endpoint: &str) -> Result<()> {
    let url = reqwest::Url::parse(endpoint)
        .map_err(|_| VoidCrawlError::ConnectionFailed("invalid debug endpoint".into()))?;
    if !matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]")) {
        return Err(VoidCrawlError::ConnectionFailed(
            "attached browser distribution can only be verified on the local host".into(),
        ));
    }
    Ok(())
}

pub(super) async fn verify_attached_browser(browser: &Browser) -> Result<()> {
    time::timeout(super::ATTACHED_TARGET_WAIT_TIMEOUT, async {
        let version = browser
            .version()
            .await
            .map_err(|e| VoidCrawlError::ConnectionFailed(e.to_string()))?;
        let info = browser
            .execute(GetInfoParams::default())
            .await
            .map_err(|e| VoidCrawlError::ConnectionFailed(e.to_string()))?
            .result;
        // CDP's product does not distinguish Stable from Chrome for Testing.
        // Verify the executable reported by the local browser as well.
        let arguments: Vec<String> = info
            .command_line
            .split_whitespace()
            .skip(1)
            .map(str::to_owned)
            .collect();
        validate_launch_security(&arguments, false)?;
        let executable = command_executable(&info.command_line).ok_or_else(|| {
            VoidCrawlError::ConnectionFailed("attached browser executable is unverifiable".into())
        })?;
        let identity = browser_distribution::browser_identity(Path::new(executable)).await?;
        let local_version = browser_distribution::supported_version(&identity)?;
        let remote_version = version.product.split_once('/').map(|(_, value)| value);
        if remote_version != Some(local_version) {
            return Err(VoidCrawlError::ConnectionFailed(
                "attached browser identity mismatch".into(),
            ));
        }
        Ok(())
    })
    .await
    .map_err(|_| {
        VoidCrawlError::ConnectionFailed("attached browser identity check timed out".into())
    })?
}

fn command_executable(command: &str) -> Option<&str> {
    let executable = if let Some(quoted) = command.strip_prefix('"') {
        quoted.split_once('"')?.0
    } else {
        command.split_whitespace().next()?
    };
    Path::new(executable).is_absolute().then_some(executable)
}

/// If the user gives us `http://host:port` (Chrome's debug HTTP endpoint),
/// resolve it to the actual `ws://` URL by hitting `/json/version`.
pub(super) async fn resolve_ws_url(url: &str) -> Result<String> {
    // Already a ws:// URL — use directly
    if url.starts_with("ws://") || url.starts_with("wss://") {
        return Ok(url.to_string());
    }

    // reqwest is built with `rustls-no-provider`, so we must install a rustls
    // CryptoProvider before the first request or reqwest panics "No provider
    // set" (even for this plain-HTTP localhost fetch). Install the `ring`
    // provider exactly once; `install_default` errors if already set, so the
    // `Once` + ignored result is idempotent.
    static CRYPTO_INIT: Once = Once::new();
    CRYPTO_INIT.call_once(|| {
        let _ = ring_crypto_provider().install_default();
    });

    // Treat as an HTTP endpoint, fetch /json/version
    let version_url = format!("{}/json/version", url.trim_end_matches('/'));
    let resp: Value = reqwest::get(&version_url)
        .await
        .map_err(|e| VoidCrawlError::ConnectionFailed(format!("GET {version_url}: {e}")))?
        .json()
        .await
        .map_err(|e| VoidCrawlError::ConnectionFailed(format!("parse {version_url}: {e}")))?;

    resp.get("webSocketDebuggerUrl")
        .and_then(|v| v.as_str())
        .map(ToString::to_string)
        .ok_or_else(|| {
            VoidCrawlError::ConnectionFailed(
                "webSocketDebuggerUrl not found in /json/version response".into(),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn security_switches_are_rejected_with_or_without_prefix_and_values() {
        for flag in [
            "no-sandbox",
            "disable-setuid-sandbox",
            "disable-gpu-sandbox",
            "disable-seccomp-filter-sandbox",
            "disable-namespace-sandbox",
            "disable-site-isolation-trials",
            "disable-web-security",
            "single-process",
            "no-zygote",
            "in-process-gpu",
            "disable-features=IsolateOrigins,Other",
            "disable-features=Other,site-per-process",
            "disable-features=SitePerProcess:mode/on",
        ] {
            for arg in [flag.to_string(), format!("--{flag}")] {
                assert!(validate_launch_security(&[arg], false).is_err(), "{flag}");
            }
        }
        assert!(validate_launch_security(&[], true).is_err());
        assert!(validate_launch_security(&["--disable-features=Translate".into()], false).is_ok());
    }

    #[tokio::test]
    async fn unsafe_arguments_fail_before_executable_resolution() {
        let error = crate::BrowserSession::builder()
            .chrome_executable("/nonexistent/browser")
            .arg("--no-sandbox=false")
            .launch()
            .await;
        assert!(matches!(error, Err(VoidCrawlError::InvalidInput { .. })));
        let error = crate::BrowserSession::builder()
            .chrome_executable("/nonexistent/browser")
            .no_sandbox()
            .launch()
            .await;
        assert!(matches!(error, Err(VoidCrawlError::InvalidInput { .. })));
    }

    #[test]
    fn remote_endpoints_fail_closed_without_local_distribution_evidence() {
        assert!(require_local_attachment("ws://example.com/devtools/browser/id").is_err());
        assert!(require_local_attachment("ws://127.0.0.1:9222/devtools/browser/id").is_ok());
        assert!(require_local_attachment("http://localhost:9222").is_ok());
        assert_eq!(
            command_executable("/opt/google/chrome/chrome --headless"),
            Some("/opt/google/chrome/chrome")
        );
        assert_eq!(command_executable("chrome --headless"), None);
    }
}
