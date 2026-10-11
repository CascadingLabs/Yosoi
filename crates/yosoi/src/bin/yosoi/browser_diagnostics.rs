//! Human advice for bounded browser failure reasons from the public facade.

use yosoi::request::BrowserFailureReason;

pub const fn name(reason: BrowserFailureReason) -> &'static str {
    match reason {
        BrowserFailureReason::Launch => "browser_launch_failed",
        BrowserFailureReason::Connection => "browser_connection_failed",
        BrowserFailureReason::Navigation => "browser_navigation_failed",
        BrowserFailureReason::Timeout => "browser_timed_out",
        BrowserFailureReason::DisplayUnavailable => "browser_display_unavailable",
        BrowserFailureReason::EnvironmentMismatch => "browser_environment_mismatch",
        BrowserFailureReason::ProfileUnavailable => "browser_profile_unavailable",
        BrowserFailureReason::Unavailable => "browser_unavailable",
        BrowserFailureReason::CapacityExhausted => "browser_capacity_exhausted",
        BrowserFailureReason::Closed => "browser_closed",
        BrowserFailureReason::RendererCrashed => "browser_renderer_crashed",
        BrowserFailureReason::UnsupportedConfiguration => "browser_unsupported_configuration",
    }
}

pub fn advice(diagnostic: &str) -> Option<&'static str> {
    match diagnostic {
        "browser_launch_failed" => Some(
            "Chrome/Chromium could not start. Check that regular Stable is installed and can launch with sandboxing enabled.",
        ),
        "browser_connection_failed" => Some(
            "The CDP connection failed. Check that Chrome remains running and its local debugging connection is reachable.",
        ),
        "browser_navigation_failed" => Some(
            "The browser could not navigate to the page. Check the target URL and connectivity.",
        ),
        "browser_timed_out" => Some(
            "The browser attempt reached its deadline. Check the page load and the selected Policy's elapsed-time limit.",
        ),
        "browser_display_unavailable" => Some(
            "Headful mode needs an X11 or Wayland display. Use headless mode in a terminal without a display.",
        ),
        "browser_environment_mismatch" => Some(
            "The observed browser environment did not match the Policy. Check viewport, locale, timezone, user-agent, and rendering overrides.",
        ),
        "browser_profile_unavailable" => Some(
            "The selected browser profile is busy, missing, or expired. Release its existing owner or select an available profile.",
        ),
        "browser_unavailable" => Some(
            "The browser runtime could not be made available. Check the regular Stable installation and whether it can start.",
        ),
        "browser_capacity_exhausted" => Some(
            "Browser admission or tab capacity is exhausted. Reduce concurrent work or wait for active sessions to finish.",
        ),
        "browser_closed" => Some(
            "The browser closed before capture completed. Check for an external shutdown or browser process failure.",
        ),
        "browser_renderer_crashed" => Some(
            "The page renderer crashed. Check browser crash diagnostics and the page's resource use.",
        ),
        "browser_unsupported_configuration" => Some(
            "The browser cannot satisfy the selected Policy configuration. Check its acquisition, isolation, navigation, and artifact requirements.",
        ),
        "browser_cleanup_failed" | "browser_cancelled_cleanup_failed" => Some(
            "Browser cleanup failed. Check for remaining Chrome processes or contexts before starting more work.",
        ),
        "browser_capture_failed" => Some(
            "Browser capture failed without a more specific supported classification. The request/capture IDs can identify the failed attempt.",
        ),
        _ => None,
    }
}
