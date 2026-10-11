//! `CdpMode` init-chain contract (CAS-217).
//!
//! These assert on the exact CDP method sequence each mode emits, because that
//! sequence *is* the anti-bot surface: every extra eager domain enable is a
//! tell. They also pin the trade-off in the other direction — Minimal must not
//! silently drop `Security.setIgnoreCertificateErrors`, and Normal must keep
//! enabling the domains that network capture and frame-scoped eval depend on.
//!
//! No browser required: `CommandChain` is polled directly.

use std::time::{Duration, Instant};

use chromiumoxide::{
    CdpMode,
    cmd::CommandChain,
    handler::{frame::FrameManager, network::NetworkManager},
};
use futures::task::Poll;

/// Drain a `CommandChain` into the CDP method names it would send, in order.
fn collect_methods(mut cmds: CommandChain) -> Result<Vec<String>, String> {
    let mut out = Vec::new();
    loop {
        match cmds.poll(Instant::now()) {
            Poll::Ready(Some(Ok((method, _params)))) => {
                let method_name = method.as_ref().to_string();
                if !cmds.received_response(&method_name) {
                    return Err(format!("command chain rejected response for {method_name}"));
                }
                out.push(method_name);
            }
            Poll::Ready(None) => return Ok(out),
            other => return Err(format!("unexpected command poll: {other:?}")),
        }
    }
}

fn require_methods(actual: &[String], expected: &[&str]) -> Result<(), String> {
    if actual == expected {
        Ok(())
    } else {
        Err(format!(
            "unexpected CDP methods: expected {expected:?}, got {actual:?}"
        ))
    }
}

/// `Runtime.enable` is the single most-cited CDP automation tell. Minimal must
/// not send it; Normal must, or per-frame execution-context tracking breaks.
#[test]
fn minimal_frame_init_skips_runtime_enable() -> Result<(), String> {
    let actual = collect_methods(FrameManager::init_commands(
        Duration::from_secs(1),
        CdpMode::Minimal,
    ))?;
    require_methods(
        &actual,
        &[
            "Page.enable",
            "Page.getFrameTree",
            "Page.setLifecycleEventsEnabled",
        ],
    )?;

    let actual = collect_methods(FrameManager::init_commands(
        Duration::from_secs(1),
        CdpMode::Normal,
    ))?;
    require_methods(
        &actual,
        &[
            "Page.enable",
            "Page.getFrameTree",
            "Page.setLifecycleEventsEnabled",
            "Runtime.enable",
        ],
    )?;
    Ok(())
}

/// Minimal skips `Network.enable` — that is the point — but must still honor
/// `ignore_https_errors`. `Security.setIgnoreCertificateErrors` is not a
/// network subscription, and dropping it silently changed bad-TLS behavior.
#[test]
fn minimal_network_init_preserves_ignore_https_without_network_enable() -> Result<(), String> {
    let timeout = Duration::from_secs(1);

    let actual =
        collect_methods(NetworkManager::new(true, timeout).init_commands(CdpMode::Minimal))?;
    require_methods(&actual, &["Security.setIgnoreCertificateErrors"])?;

    let minimal =
        collect_methods(NetworkManager::new(false, timeout).init_commands(CdpMode::Minimal))?;
    if !minimal.is_empty() {
        return Err(format!(
            "minimal mode with HTTPS checks enabled sent {minimal:?}"
        ));
    }

    let actual =
        collect_methods(NetworkManager::new(true, timeout).init_commands(CdpMode::Normal))?;
    require_methods(
        &actual,
        &["Network.enable", "Security.setIgnoreCertificateErrors"],
    )?;
    Ok(())
}

/// The default must stay `Normal`. Flipping it would silently disable
/// `network_capture_arm`/`wait`, CDP request-header capture, and
/// `wait_for_network_idle` for every existing caller.
#[test]
fn default_mode_is_normal() {
    assert_eq!(CdpMode::default(), CdpMode::Normal);
}
