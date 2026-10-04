//! Anti-detection / stealth configuration for browser sessions.

use serde::{Deserialize, Serialize};

/// Explicit automation-disclosure policy for JavaScript's
/// `navigator.webdriver` signal.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NavigatorWebdriverPolicy {
    /// Preserve the value and native property descriptor reported by Chrome.
    /// The supported non-zero debugging port makes that value `false`; an
    /// `BrowserDebugPortPolicy::ChromeAssigned` makes Chrome report `true`.
    BrowserReported,
}

/// Supported browser identity-coherence policy.
///
/// This configuration does not install page-world spoofing, bypass CSP, or
/// disguise `navigator.webdriver`. Callers can still install an explicit init
/// script through `Page::add_init_script`, but that detectable mutation is not
/// a VoidCrawl stealth preset.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StealthConfig {
    /// Automation-disclosure contract. The supported default is truthful.
    pub navigator_webdriver: NavigatorWebdriverPolicy,
    /// Viewport width in pixels.
    pub viewport_width: u32,
    /// Viewport height in pixels.
    pub viewport_height: u32,
    /// Accept-Language header value.
    pub locale: String,
}

impl Default for StealthConfig {
    fn default() -> Self {
        Self::chrome_like()
    }
}

impl StealthConfig {
    /// Preset that mimics a real desktop Chrome session.
    ///
    /// This relies on a small set of operational Chrome launch flags rather
    /// than unsupported anti-automation switches or heavy JS injection. The
    /// UA override derives from the exact browser product and removes only the
    /// headless qualifier. Chromiumoxide's broad built-in stealth mode is not
    /// used because it fires multiple page-world patches that sophisticated
    /// detectors can fingerprint.
    ///
    /// No JS is injected at all. In particular, VoidCrawl does not disguise
    /// Chromium's `navigator.webdriver` automation signal. The old
    /// force-open-shadow-DOM patch is also gone because it broke Cloudflare
    /// Turnstile's closed-shadow tamper check. UA / platform / Client-Hints
    /// consistency is applied via CDP `setUserAgentOverride`, not page-world
    /// JavaScript.
    pub fn chrome_like() -> Self {
        Self {
            navigator_webdriver: NavigatorWebdriverPolicy::BrowserReported,
            viewport_width: 1920,
            viewport_height: 1080,
            // CDP's `acceptLanguage` value also feeds navigator.languages.
            // Quality weights belong in an HTTP header, not the JavaScript
            // language list; Chrome adds the header weights itself.
            locale: "en-US,en".into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{NavigatorWebdriverPolicy, StealthConfig};

    #[test]
    fn default_policy_is_truthful_and_has_javascript_safe_languages() {
        let config = StealthConfig::default();
        assert_eq!(
            config.navigator_webdriver,
            NavigatorWebdriverPolicy::BrowserReported
        );
        assert_eq!(config.locale, "en-US,en");
        assert!(!config.locale.contains(";q="));
    }
}
