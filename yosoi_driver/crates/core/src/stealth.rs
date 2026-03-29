//! Anti-detection / stealth configuration for browser sessions.

use serde::{Deserialize, Serialize};

/// Configuration for browser stealth features that help avoid bot detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StealthConfig {
    /// User-Agent string override. `None` = use browser default.
    pub user_agent: Option<String>,
    /// Viewport width in pixels.
    pub viewport_width: u32,
    /// Viewport height in pixels.
    pub viewport_height: u32,
    /// Accept-Language header value.
    pub locale: String,
    /// JavaScript snippet injected via `Page.addScriptToEvaluateOnNewDocument`
    /// *before* every page load. Runs in the page's main world.
    pub inject_js: Option<String>,
    /// Whether to use chromiumoxide's built-in `enable_stealth_mode`.
    pub use_builtin_stealth: bool,
    /// Whether to bypass Content-Security-Policy for JS injection.
    pub bypass_csp: bool,
}

impl Default for StealthConfig {
    fn default() -> Self {
        Self::chrome_like()
    }
}

impl StealthConfig {
    /// Preset that mimics a real desktop Chrome session.
    pub fn chrome_like() -> Self {
        Self {
            user_agent: Some(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                 AppleWebKit/537.36 (KHTML, like Gecko) \
                 Chrome/131.0.0.0 Safari/537.36"
                    .into(),
            ),
            viewport_width: 1920,
            viewport_height: 1080,
            locale: "en-US,en;q=0.9".into(),
            inject_js: Some(Self::default_stealth_js().into()),
            use_builtin_stealth: true,
            bypass_csp: true,
        }
    }

    /// Minimal config — no overrides, no injection, just headless defaults.
    pub fn none() -> Self {
        Self {
            user_agent: None,
            viewport_width: 1920,
            viewport_height: 1080,
            locale: "en-US,en;q=0.9".into(),
            inject_js: None,
            use_builtin_stealth: false,
            bypass_csp: false,
        }
    }

    /// Default JS payload that patches common bot-detection signals.
    fn default_stealth_js() -> &'static str {
        r#"
// Override navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Fake plugins array
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Fake languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Spoof chrome runtime
window.chrome = { runtime: {} };

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
"#
    }
}
