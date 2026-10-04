//! Dependency-light browser vocabulary shared by acquisition engines and captures.

use std::num::NonZeroU32;

use crate::ReasonCode;
use serde::{Deserialize, Serialize};

/// An environment value whose absence has an explicit meaning.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum EnvironmentValue<T, U = ReasonCode, O = U> {
    Known { value: T },
    Unavailable { reason: U },
    Omitted { reason: O },
}

impl<T> EnvironmentValue<T> {
    pub const fn known(value: T) -> Self {
        Self::Known { value }
    }

    pub const fn unavailable(reason: ReasonCode) -> Self {
        Self::Unavailable { reason }
    }

    pub const fn omitted(reason: ReasonCode) -> Self {
        Self::Omitted { reason }
    }
}

impl<T, U, O> EnvironmentValue<T, U, O> {
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
    Headless,
    Headful,
}

/// Effective or requested `prefers-color-scheme` setting.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorScheme {
    Light,
    Dark,
    NoPreference,
}

/// Effective or requested `prefers-reduced-motion` setting.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReducedMotion {
    Reduce,
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
    pub const fn new(width_css_pixels: NonZeroU32, height_css_pixels: NonZeroU32) -> Self {
        Self {
            width_css_pixels,
            height_css_pixels,
        }
    }

    pub const fn width_css_pixels(self) -> NonZeroU32 {
        self.width_css_pixels
    }

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
    #[error("viewport width must be greater than zero")]
    ZeroWidth,
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
            crate::ReasonCode::new("browser.environment.unavailable").unwrap(),
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
            serde_json::to_string(&crate::ByteCount::new(10)).unwrap(),
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
            let count = crate::ByteCount::new(value);
            let encoded = serde_json::to_string(&count).unwrap();
            let decoded: crate::ByteCount = serde_json::from_str(&encoded).unwrap();
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
