//! Dependency-light browser vocabulary shared by acquisition engines and captures.

#[cfg(test)]
use crate::internal::types as yosoi_types;

use std::num::NonZeroU32;

use crate::internal::types::ReasonCode;
use serde::{Deserialize, Serialize};

/// An environment value whose absence has an explicit meaning.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum EnvironmentValue<T, U = ReasonCode, O = U> {
    /// A value was observed or explicitly supplied and retained.
    Known {
        /// Retained value in its declared domain and units.
        value: T,
    },
    /// Required environment evidence could not be obtained.
    Unavailable {
        /// Typed explanation of unavailable evidence.
        reason: U,
    },
    /// Evidence was intentionally not retained or requested.
    Omitted {
        /// Typed omission explanation, distinct from evidence being unavailable.
        reason: O,
    },
}

impl<T> EnvironmentValue<T> {
    /// Wraps owned environment evidence without independently verifying its truth.
    pub const fn known(value: T) -> Self {
        Self::Known { value }
    }

    /// Retains a reason why environment evidence could not be obtained.
    pub const fn unavailable(reason: ReasonCode) -> Self {
        Self::Unavailable { reason }
    }

    /// Retains a reason why environment evidence was intentionally omitted.
    pub const fn omitted(reason: ReasonCode) -> Self {
        Self::Omitted { reason }
    }
}

impl<T, U, O> EnvironmentValue<T, U, O> {
    /// Borrows retained known evidence, or `None` without collapsing its typed absence reason.
    pub const fn as_known(&self) -> Option<&T> {
        match self {
            Self::Known { value } => Some(value),
            Self::Unavailable { .. } | Self::Omitted { .. } => None,
        }
    }
}

/// Browser windowing mode that can influence rendering behavior.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserMode {
    /// Run without a visible browser window; rendering behavior still depends on browser identity.
    Headless,
    /// Run with visible windowing, without an independent browser certification claim.
    Headful,
}

/// Effective or requested `prefers-color-scheme` setting.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorScheme {
    /// Effective or requested light color preference.
    Light,
    /// Effective or requested dark color preference.
    Dark,
    /// No authored or observed light/dark preference claim.
    NoPreference,
}

/// Effective or requested `prefers-reduced-motion` setting.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReducedMotion {
    /// Effective or requested reduced-motion preference.
    Reduce,
    /// No reduced-motion preference claim.
    NoPreference,
}

/// Effective CSS viewport dimensions.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Viewport {
    width_css_pixels: NonZeroU32,
    height_css_pixels: NonZeroU32,
}

impl Viewport {
    /// Owns positive CSS-pixel dimensions without querying a live browser.
    pub const fn new(width_css_pixels: NonZeroU32, height_css_pixels: NonZeroU32) -> Self {
        Self {
            width_css_pixels,
            height_css_pixels,
        }
    }

    /// Returns positive viewport width in CSS pixels, not device pixels.
    pub const fn width_css_pixels(self) -> NonZeroU32 {
        self.width_css_pixels
    }

    /// Returns positive viewport height in CSS pixels, not device pixels.
    pub const fn height_css_pixels(self) -> NonZeroU32 {
        self.height_css_pixels
    }

    /// Validates raw browser-reported dimensions before they become shared evidence.
    pub fn try_from_pixels(
        width_css_pixels: u32,
        height_css_pixels: u32,
    ) -> Result<Self, ViewportError> {
        let width_css_pixels = NonZeroU32::new(width_css_pixels).ok_or(ViewportError::ZeroWidth)?;
        let height_css_pixels =
            NonZeroU32::new(height_css_pixels).ok_or(ViewportError::ZeroHeight)?;
        Ok(Self::new(width_css_pixels, height_css_pixels))
    }
}

/// A browser viewport dimension was zero.
#[derive(Clone, Copy, Debug, Eq, thiserror::Error, PartialEq)]
pub enum ViewportError {
    /// Reported CSS viewport width is zero.
    #[error("viewport width must be greater than zero")]
    ZeroWidth,
    /// Reported CSS viewport height is zero.
    #[error("viewport height must be greater than zero")]
    ZeroHeight,
}

/// Capture-local browser resource identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct BrowserResourceId(pub u64);

/// Capture-local browser frame identity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct BrowserFrameId(pub u64);

/// Capture-local browser document generation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct BrowserDocumentEpoch(pub u64);

/// Terminal state of one observed browser resource.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum BrowserResourceOutcome {
    Pending,
    ResponseReceived,
    Redirected,
    Complete,
    Failed { cancelled: bool, blocked: bool },
}

/// Schema of a browser accessibility payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum BrowserAccessibilitySchema {
    ChromiumCdpAxNodeJson,
}

/// Scope used when acquiring a browser accessibility tree.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum BrowserAccessibilityCaptureMode {
    FullTree,
    DepthLimited,
}

/// Treatment of ignored nodes in a browser accessibility tree.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum BrowserAccessibilityIgnoredNodes {
    Included,
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::yosoi_types;
    use super::{
        BrowserAccessibilityCaptureMode, BrowserAccessibilityIgnoredNodes,
        BrowserAccessibilitySchema, BrowserDocumentEpoch, BrowserFrameId, BrowserMode,
        BrowserResourceId, BrowserResourceOutcome, ColorScheme, EnvironmentValue, ReducedMotion,
        Viewport,
    };
    use proptest::prelude::*;

    #[test]
    fn environment_primitives_preserve_snake_case_wire_values() {
        assert_eq!(
            serde_json::to_string(&BrowserMode::Headless).unwrap(),
            r#""headless""#
        );
        assert_eq!(
            serde_json::to_string(&ColorScheme::NoPreference).unwrap(),
            r#""no_preference""#
        );
        assert_eq!(
            serde_json::to_string(&ReducedMotion::Reduce).unwrap(),
            r#""reduce""#
        );
        let unavailable = EnvironmentValue::<u8>::unavailable(
            yosoi_types::ReasonCode::new("browser.environment.unavailable").unwrap(),
        );
        assert_eq!(
            serde_json::to_string(&unavailable).unwrap(),
            r#"{"status":"unavailable","reason":"browser.environment.unavailable"}"#
        );
    }

    #[test]
    fn resource_primitives_preserve_existing_web_capture_wire_values() {
        assert_eq!(serde_json::to_string(&BrowserResourceId(7)).unwrap(), "7");
        assert_eq!(serde_json::to_string(&BrowserFrameId(8)).unwrap(), "8");
        assert_eq!(
            serde_json::to_string(&BrowserDocumentEpoch(9)).unwrap(),
            "9"
        );
        assert_eq!(
            serde_json::to_string(&yosoi_types::ByteCount::new(10)).unwrap(),
            "10"
        );
        assert_eq!(
            serde_json::to_string(&BrowserResourceOutcome::Failed {
                cancelled: true,
                blocked: false,
            })
            .unwrap(),
            r#"{"Failed":{"cancelled":true,"blocked":false}}"#
        );
    }

    #[test]
    fn accessibility_primitives_preserve_existing_wire_values() {
        assert_eq!(
            serde_json::to_string(&BrowserAccessibilitySchema::ChromiumCdpAxNodeJson).unwrap(),
            r#""ChromiumCdpAxNodeJson""#
        );
        assert_eq!(
            serde_json::to_string(&BrowserAccessibilityCaptureMode::DepthLimited).unwrap(),
            r#""DepthLimited""#
        );
        assert_eq!(
            serde_json::to_string(&BrowserAccessibilityIgnoredNodes::Included).unwrap(),
            r#""Included""#
        );
    }

    #[test]
    fn viewport_rejects_zero_dimensions() {
        assert!(Viewport::try_from_pixels(0, 1).is_err());
        assert!(Viewport::try_from_pixels(1, 0).is_err());
        let viewport = Viewport::try_from_pixels(1280, 720).unwrap();
        assert_eq!(
            serde_json::to_string(&viewport).unwrap(),
            r#"{"width_css_pixels":1280,"height_css_pixels":720}"#
        );
    }

    proptest! {
        #[test]
        fn browser_byte_count_json_round_trips(value in any::<u64>()) {
            let count = yosoi_types::ByteCount::new(value);
            let encoded = serde_json::to_string(&count).unwrap();
            let decoded: yosoi_types::ByteCount = serde_json::from_str(&encoded).unwrap();
            prop_assert_eq!(decoded, count);
            prop_assert_eq!(decoded.get(), value);
        }

        #[test]
        fn known_environment_values_round_trip(value in any::<u64>()) {
            let observed = EnvironmentValue::<u64>::known(value);
            let encoded = serde_json::to_string(&observed).unwrap();
            let decoded: EnvironmentValue<u64> = serde_json::from_str(&encoded).unwrap();
            prop_assert_eq!(decoded, observed);
        }
    }
}

/// Content-free reason a browser capture could not complete.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserFailureReason {
    /// Browser process could not launch under the required execution environment.
    Launch,
    /// Controller connection to the selected browser could not be established or maintained.
    Connection,
    /// Requested browser navigation failed before usable capture evidence.
    Navigation,
    /// A browser acquisition or controller deadline expired.
    Timeout,
    /// Requested visible windowing cannot use a suitable display environment.
    DisplayUnavailable,
    /// Observed browser environment disagrees with requested capture constraints.
    EnvironmentMismatch,
    /// Requested browser profile cannot be acquired.
    ProfileUnavailable,
    /// Browser acquisition is unavailable without a more specific retained reason.
    Unavailable,
    /// Browser or tab admission exhausted configured capacity.
    CapacityExhausted,
    /// Owning browser authority closed before the requested work could proceed.
    Closed,
    /// Renderer process crashed, preventing reliable current-page evidence.
    RendererCrashed,
    /// Selected browser settings or capabilities are unsupported by this implementation.
    UnsupportedConfiguration,
}
