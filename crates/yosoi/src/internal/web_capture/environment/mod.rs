//! Secret-safe capture environment and browser rendering context metadata.
//!
//! These values describe effective conditions that influenced a capture. They
//! do not contain captured page content or runtime acquisition configuration.
//! In particular, this module has no representation for profile paths, cookie
//! values, credentials, authorization headers, browser launch arguments, or
//! provider process handles.

mod browser;
mod fingerprint;
mod http;
mod scalars;
mod value;

pub use browser::{
    BrowserCaptureEnvironment, BrowserMode, BrowserRenderingContext, ColorScheme, ReducedMotion,
    Viewport,
};
pub use fingerprint::{
    BrowserEnvironmentFingerprintInputs, EnvironmentFingerprintInputs,
    HttpEnvironmentFingerprintInputs,
};
pub use http::HttpCaptureEnvironment;
pub use scalars::{
    DeviceScaleFactor, DeviceScaleFactorError, Locale, LocaleError, PreferredLanguages,
    PreferredLanguagesError, TimeZone, TimeZoneError, UserAgent, UserAgentError,
};
pub use value::EnvironmentValue;

use serde::{Deserialize, Serialize};

/// Capture environment with a shape appropriate to its execution family.
///
/// Browser-only geometry cannot be attached to a direct HTTP capture. Browser
/// execution always states the availability of the geometry needed to
/// interpret visual artifacts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "environment",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum CaptureEnvironment {
    /// A native, non-browser HTTP execution environment.
    Http(HttpCaptureEnvironment),
    /// A browser execution and rendering environment.
    Browser(Box<BrowserCaptureEnvironment>),
}

impl CaptureEnvironment {
    /// Creates a browser environment without exposing storage indirection to callers.
    pub fn browser(environment: BrowserCaptureEnvironment) -> Self {
        Self::Browser(Box::new(environment))
    }
}
