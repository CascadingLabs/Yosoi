use crate::internal::types::Producer;
use serde::Serialize;

use super::{
    BrowserMode, CaptureEnvironment, ColorScheme, DeviceScaleFactor, EnvironmentValue, Locale,
    PreferredLanguages, ReducedMotion, TimeZone, UserAgent, Viewport,
};

impl CaptureEnvironment {
    /// Returns an allowlisted projection suitable for later canonical hashing.
    ///
    /// The projection excludes absence reason codes because they explain
    /// knowledge or policy, not the effective representation. CAS-296 owns the
    /// canonical serialization and digest algorithm.
    pub const fn fingerprint_inputs(&self) -> EnvironmentFingerprintInputs<'_> {
        match self {
            Self::Http(environment) => {
                EnvironmentFingerprintInputs::Http(HttpEnvironmentFingerprintInputs {
                    client: environment.client(),
                    user_agent: FingerprintValue::from_environment_value(environment.user_agent()),
                    preferred_languages: FingerprintValue::from_environment_value(
                        environment.preferred_languages(),
                    ),
                })
            }
            Self::Browser(environment) => {
                let rendering = environment.rendering();
                EnvironmentFingerprintInputs::Browser(BrowserEnvironmentFingerprintInputs {
                    controller: environment.controller(),
                    renderer: environment.renderer(),
                    mode: FingerprintValue::from_environment_value(environment.mode()),
                    viewport: FingerprintValue::from_environment_value(rendering.viewport()),
                    device_scale_factor: FingerprintValue::from_environment_value(
                        rendering.device_scale_factor(),
                    ),
                    user_agent: FingerprintValue::from_environment_value(rendering.user_agent()),
                    locale: FingerprintValue::from_environment_value(rendering.locale()),
                    time_zone: FingerprintValue::from_environment_value(rendering.time_zone()),
                    color_scheme: FingerprintValue::from_environment_value(
                        rendering.color_scheme(),
                    ),
                    reduced_motion: FingerprintValue::from_environment_value(
                        rendering.reduced_motion(),
                    ),
                })
            }
        }
    }
}

/// Secret-safe inputs from which CAS-296 can later define a fingerprint.
///
/// Its current Serde representation is an inspectable projection, not a
/// canonical byte contract or digest algorithm.
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "kind", content = "inputs", rename_all = "snake_case")]
pub enum EnvironmentFingerprintInputs<'a> {
    /// Inputs affecting a direct HTTP representation.
    Http(HttpEnvironmentFingerprintInputs<'a>),
    /// Inputs affecting browser execution and rendering.
    Browser(BrowserEnvironmentFingerprintInputs<'a>),
}

/// Allowlisted direct HTTP fingerprint inputs.
#[derive(Clone, Debug, Serialize)]
pub struct HttpEnvironmentFingerprintInputs<'a> {
    client: &'a Producer,
    user_agent: FingerprintValue<'a, UserAgent>,
    preferred_languages: FingerprintValue<'a, PreferredLanguages>,
}

/// Allowlisted browser fingerprint inputs.
#[derive(Clone, Debug, Serialize)]
pub struct BrowserEnvironmentFingerprintInputs<'a> {
    controller: &'a Producer,
    renderer: &'a Producer,
    mode: FingerprintValue<'a, BrowserMode>,
    viewport: FingerprintValue<'a, Viewport>,
    device_scale_factor: FingerprintValue<'a, DeviceScaleFactor>,
    user_agent: FingerprintValue<'a, UserAgent>,
    locale: FingerprintValue<'a, Locale>,
    time_zone: FingerprintValue<'a, TimeZone>,
    color_scheme: FingerprintValue<'a, ColorScheme>,
    reduced_motion: FingerprintValue<'a, ReducedMotion>,
}

/// Environment value projected without absence reason codes.
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
enum FingerprintValue<'a, T> {
    Known(&'a T),
    Unavailable,
    Omitted,
}

impl<'a, T> FingerprintValue<'a, T> {
    const fn from_environment_value(value: &'a EnvironmentValue<T>) -> Self {
        match value {
            EnvironmentValue::Known { value } => Self::Known(value),
            EnvironmentValue::Unavailable { .. } => Self::Unavailable,
            EnvironmentValue::Omitted { .. } => Self::Omitted,
        }
    }
}
