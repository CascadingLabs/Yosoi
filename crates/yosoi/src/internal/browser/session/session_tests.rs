use crate::internal::types as yosoi_types;

use super::{
    BrowserDebugPortPolicy, BrowserMode, BrowserSessionBuilder, DEFAULT_CHROME_ARGS, Ipv4Addr,
    TcpListener, assemble_chrome_args, browser_mode_observation, reserve_debug_port,
    stderr_mentions_debug_port_collision,
};
use crate::internal::browser::environment::{EnvironmentObservation, EnvironmentUnavailableReason};
use chromiumoxide::error::BrowserStderr;

#[test]
fn launch_mode_observation_does_not_guess_for_attached_browsers() {
    assert_eq!(
        browser_mode_observation(&BrowserMode::Headless),
        EnvironmentObservation::Known {
            value: yosoi_types::BrowserMode::Headless
        }
    );
    assert_eq!(
        browser_mode_observation(&BrowserMode::Headful),
        EnvironmentObservation::Known {
            value: yosoi_types::BrowserMode::Headful
        }
    );
    assert_eq!(
        browser_mode_observation(&BrowserMode::RemoteDebug {
            ws_url: "ws://secret-local-handle".into(),
        }),
        EnvironmentObservation::Unavailable {
            reason: EnvironmentUnavailableReason::AttachedBrowserNotControlled,
        }
    );
}

#[test]
fn debug_port_collision_detection_is_narrow() {
    assert!(stderr_mentions_debug_port_collision(&BrowserStderr::new(
        b"bind() failed: Address already in use".to_vec()
    )));
    assert!(!stderr_mentions_debug_port_collision(&BrowserStderr::new(
        b"GPU process exited unexpectedly".to_vec()
    )));
}

#[test]
fn supported_ephemeral_debug_port_is_the_default() {
    assert_eq!(
        BrowserSessionBuilder::default().debug_port,
        BrowserDebugPortPolicy::SupportedEphemeral
    );
    assert_eq!(
        BrowserSessionBuilder::default()
            .debug_port_policy(BrowserDebugPortPolicy::ChromeAssigned)
            .debug_port,
        BrowserDebugPortPolicy::ChromeAssigned
    );
}

#[tokio::test]
#[allow(clippy::expect_used, reason = "test harness")]
async fn automatic_debug_port_is_nonzero_and_released_to_chrome() {
    let port = reserve_debug_port().await.expect("reserve debug port");
    assert_ne!(port, 0);
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, port))
        .await
        .expect("reserved port should be released before Chrome binds");
    drop(listener);
}

/// Flags are stored WITHOUT a leading `--` (chromiumoxide adds it; a `--`
/// here would become the inert `----flag`). Guards the double-dash bug.
#[test]
fn defaults_have_no_leading_double_dash() {
    for f in DEFAULT_CHROME_ARGS {
        assert!(
            !f.starts_with("--"),
            "default flag must not start with --: {f}"
        );
    }
}

/// Hardware-GPU defaults are present (so headless doesn't fall back to
/// SwiftShader), alongside the low-noise nodriver launch core. Forms are
/// un-prefixed.
#[test]
fn defaults_enable_hardware_gpu_without_unsupported_automation_switches() {
    let args = assemble_chrome_args(&[]);
    for expected in [
        "remote-allow-origins=*",
        "no-service-autorun",
        "no-pings",
        "password-store=basic",
        "use-angle=vulkan",
        "enable-gpu",
        "ignore-gpu-blocklist",
    ] {
        assert!(
            args.iter().any(|a| a == expected),
            "missing default flag: {expected}"
        );
    }
    for removed in [
        "disable-gpu-sandbox",
        "disable-site-isolation-trials",
        "disable-blink-features=AutomationControlled",
        "disable-infobars",
        "disable-background-networking",
        "disable-renderer-backgrounding",
        "disable-ipc-flooding-protection",
    ] {
        assert!(
            !args.iter().any(|a| a == removed),
            "human defaults should omit {removed}"
        );
    }
    assert!(
        !args.iter().any(|argument| {
            argument
                .strip_prefix("disable-features=")
                .is_some_and(|features| {
                    features
                        .split(',')
                        .any(|feature| matches!(feature, "IsolateOrigins" | "site-per-process"))
                })
        }),
        "human defaults must preserve Chrome site and process isolation"
    );
}

/// Novel caller `extra_args` (no matching default switch) are normalized
/// and appended.
#[test]
fn novel_extra_args_are_normalized_and_appended() {
    let extra = vec![
        "--proxy-bypass-list=*".to_string(),
        "lang=fr".to_string(),
        "--disable-gpu-sandbox".to_string(),
    ];
    let args = assemble_chrome_args(&extra);
    // Both forms (with/without `--`) land un-prefixed and last.
    assert_eq!(
        &args[args.len() - 3..],
        &[
            "proxy-bypass-list=*".to_string(),
            "lang=fr".to_string(),
            "disable-gpu-sandbox".to_string(),
        ][..]
    );
    assert_eq!(args.len(), DEFAULT_CHROME_ARGS.len() + extra.len());
}

/// The override contract: a caller value for a switch that already has a
/// default *replaces* it — exactly one occurrence, default value gone — and
/// the caller's `--` is normalized away. (Critical for `use-angle`, which
/// Chrome reads first-occurrence-wins, so a duplicate would not override.)
#[test]
fn caller_value_replaces_default_same_switch() {
    let args = assemble_chrome_args(&["--use-angle=swiftshader".to_string()]);
    let angle: Vec<&String> = args.iter().filter(|a| a.starts_with("use-angle")).collect();
    assert_eq!(angle.len(), 1, "exactly one use-angle flag");
    assert_eq!(angle[0], "use-angle=swiftshader");
    assert!(
        !args.iter().any(|a| a == "use-angle=vulkan"),
        "default value must be gone"
    );
    // Length unchanged: replacement, not addition.
    assert_eq!(args.len(), DEFAULT_CHROME_ARGS.len());
}

/// Replacement happens in place, so unrelated defaults are untouched.
#[test]
fn override_is_in_place_and_leaves_other_defaults() {
    let args = assemble_chrome_args(&["--use-angle=gl".to_string()]);
    assert!(args.iter().any(|a| a == "enable-gpu"));
    assert!(args.iter().any(|a| a == "remote-allow-origins=*"));
}

/// No `extra_args` => exactly the defaults, unchanged order.
#[test]
fn no_extra_args_is_just_defaults() {
    let args = assemble_chrome_args(&[]);
    let defaults: Vec<String> = DEFAULT_CHROME_ARGS
        .iter()
        .map(ToString::to_string)
        .collect();
    assert_eq!(args, defaults);
}
