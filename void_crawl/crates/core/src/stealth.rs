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
    ///
    /// This follows the zendriver / nodriver philosophy: rely on clean
    /// Chrome launch flags rather than heavy JS injection.  We do NOT
    /// override the user-agent (avoids version mismatches with the real
    /// browser) and we do NOT use chromiumoxide's built-in stealth mode
    /// (it fires multiple `addScriptToEvaluateOnNewDocument` CDP calls
    /// that sophisticated WAFs can fingerprint).
    ///
    /// Only a minimal JS payload is injected: `navigator.webdriver`
    /// removal and forced-open shadow DOMs (needed for Cloudflare
    /// Turnstile interaction).
    pub fn chrome_like() -> Self {
        Self {
            // None = keep the browser's real UA, preventing version
            // mismatches between the UA string and the actual Chrome build.
            user_agent: None,
            viewport_width: 1920,
            viewport_height: 1080,
            locale: "en-US,en;q=0.9".into(),
            inject_js: Some(Self::default_stealth_js().into()),
            // Disabled: chromiumoxide's stealth sends detectable CDP patterns.
            use_builtin_stealth: false,
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

    /// Minimal JS payload — zendriver-philosophy.
    ///
    /// We intentionally keep this light.  Heavy JS patching (plugins,
    /// mimeTypes, WebGL, permissions) is counter-productive: each
    /// `addScriptToEvaluateOnNewDocument` CDP call is itself a
    /// fingerprint, and poorly-matched fakes (e.g. wrong GPU string)
    /// are worse than the defaults from a real Chrome install.
    ///
    /// We only patch the two things that are universally needed:
    /// 1. `navigator.webdriver` — set by Chrome when run via CDP
    /// 2. Shadow DOM mode — force open so we can interact with
    ///    Cloudflare Turnstile and similar challenge iframes.
    fn default_stealth_js() -> &'static str {
        r#"
// Remove navigator.webdriver (set to true by CDP automation).
delete Object.getPrototypeOf(navigator).webdriver;
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// Force shadow DOMs open for challenge iframe interaction.
Element.prototype._attachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function(init) {
    return this._attachShadow({ ...init, mode: 'open' });
};
"#
    }
}
