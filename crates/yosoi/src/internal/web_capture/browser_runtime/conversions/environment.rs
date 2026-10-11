use super::accounting_scope::reason;
use crate::internal::browser as provider;
use crate::internal::types::{Producer, ProducerId, ProducerVersion};
use crate::internal::web_capture as yosoi;
use crate::internal::web_capture::VoidCrawlAdapterError;

fn controller_version(
    value: &provider::ControllerVersion,
) -> Result<Producer, VoidCrawlAdapterError> {
    if value.name != provider::VOID_CRAWL_PACKAGE_NAME
        || value.version != provider::VOID_CRAWL_VERSION
    {
        return Err(VoidCrawlAdapterError::InvalidEnvironment);
    }
    // Registry package renames must not alter persisted producer identities.
    yosoi::void_crawl_adapter_producer().map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)
}

pub(super) const fn environment_reason(
    value: provider::EnvironmentUnavailableReason,
) -> &'static str {
    match value {
        provider::EnvironmentUnavailableReason::AttachedBrowserNotControlled => {
            "voidcrawl.environment.attached-browser-not-controlled"
        }
        provider::EnvironmentUnavailableReason::BrowserDidNotReport => {
            "voidcrawl.environment.browser-did-not-report"
        }
        provider::EnvironmentUnavailableReason::InvalidBrowserValue => {
            "voidcrawl.environment.invalid-browser-value"
        }
    }
}

pub(super) const fn omission_reason(value: provider::EnvironmentOmissionReason) -> &'static str {
    match value {
        provider::EnvironmentOmissionReason::MinimizeInstrumentation => {
            "voidcrawl.environment.minimize-instrumentation"
        }
        provider::EnvironmentOmissionReason::SensitiveValue => {
            "voidcrawl.environment.sensitive-value"
        }
    }
}

pub(super) fn environment_value<T, U>(
    value: provider::EnvironmentObservation<T>,
    known: impl FnOnce(T) -> Result<U, VoidCrawlAdapterError>,
) -> Result<yosoi::EnvironmentValue<U>, VoidCrawlAdapterError> {
    match value {
        provider::EnvironmentObservation::Known { value } => {
            Ok(yosoi::EnvironmentValue::known(known(value)?))
        }
        provider::EnvironmentObservation::Unavailable { reason: value } => Ok(
            yosoi::EnvironmentValue::unavailable(reason(environment_reason(value))?),
        ),
        provider::EnvironmentObservation::Omitted { reason: value } => Ok(
            yosoi::EnvironmentValue::omitted(reason(omission_reason(value))?),
        ),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum CapabilityClass {
    Supported,
    Disabled,
    Unavailable,
    Unsupported,
}

pub(super) const fn capability_class(value: provider::CapabilityState) -> CapabilityClass {
    match value {
        provider::CapabilityState::Supported => CapabilityClass::Supported,
        provider::CapabilityState::Unavailable {
            reason: provider::CapabilityUnavailableReason::AttachedBrowserStateNotControlled,
        } => CapabilityClass::Unavailable,
        provider::CapabilityState::Disabled {
            reason: provider::CapabilityDisabledReason::MinimalCdpMode,
        } => CapabilityClass::Disabled,
        provider::CapabilityState::Unsupported {
            reason: provider::CapabilityUnsupportedReason::NotImplemented,
        } => CapabilityClass::Unsupported,
    }
}

const fn certified_class(value: &yosoi::BrowserCapabilityStatus) -> CapabilityClass {
    match value {
        yosoi::BrowserCapabilityStatus::Supported => CapabilityClass::Supported,
        yosoi::BrowserCapabilityStatus::Disabled { .. } => CapabilityClass::Disabled,
        yosoi::BrowserCapabilityStatus::Unavailable { .. } => CapabilityClass::Unavailable,
        yosoi::BrowserCapabilityStatus::Unsupported { .. } => CapabilityClass::Unsupported,
    }
}

fn verify_capabilities(
    actual: &provider::BrowserCaptureCapabilities,
    certified: &yosoi::BrowserFamilyCapabilities,
) -> Result<(), VoidCrawlAdapterError> {
    for (family, state) in [
        (yosoi::WebArtifactFamily::Source, actual.document_source),
        (yosoi::WebArtifactFamily::RenderedDom, actual.rendered_dom),
        (
            yosoi::WebArtifactFamily::AccessibilityTree,
            actual.accessibility_tree,
        ),
        (
            yosoi::WebArtifactFamily::Network,
            actual.network_resource_graph,
        ),
        (yosoi::WebArtifactFamily::Cookies, actual.cookies),
        (yosoi::WebArtifactFamily::Storage, actual.web_storage),
        (yosoi::WebArtifactFamily::Layout, actual.element_geometry),
        (yosoi::WebArtifactFamily::Visual, actual.screenshot),
        (
            yosoi::WebArtifactFamily::RuntimeDiagnostics,
            actual.runtime_diagnostics,
        ),
    ] {
        let expected = certified
            .get(family)
            .ok_or(VoidCrawlAdapterError::EnvironmentMismatch {
                field: "capabilities",
            })?;
        if capability_class(state) != certified_class(expected) {
            return Err(VoidCrawlAdapterError::EnvironmentMismatch {
                field: "capabilities",
            });
        }
    }
    Ok(())
}

fn device_scale_factor_matches(actual: f64, expected: f64) -> bool {
    let scale = actual.abs().max(expected.abs()).max(1.0);
    (actual - expected).abs() <= f64::from(f32::EPSILON) * scale
}

pub fn verify_environment(
    value: &provider::BrowserEnvironmentSnapshot,
    expected: &yosoi::BrowserAttemptEnvironment,
    certified: &yosoi::CertifiedBrowserCapabilities,
) -> Result<(), VoidCrawlAdapterError> {
    let provider::EnvironmentObservation::Known { value: mode } = &value.mode else {
        return Err(VoidCrawlAdapterError::EnvironmentMismatch { field: "mode" });
    };
    if *mode != expected.mode() {
        return Err(VoidCrawlAdapterError::EnvironmentMismatch { field: "mode" });
    }
    verify_capabilities(&value.capabilities, certified.families())?;
    let overrides = expected.overrides();
    let rendering = &value.rendering;
    if let Some(expected_viewport) = overrides.viewport {
        let provider::EnvironmentObservation::Known { value: actual } = &rendering.viewport else {
            return Err(VoidCrawlAdapterError::EnvironmentMismatch { field: "viewport" });
        };
        if actual.width_css_pixels() != expected_viewport.width_css_pixels()
            || actual.height_css_pixels() != expected_viewport.height_css_pixels()
        {
            return Err(VoidCrawlAdapterError::EnvironmentMismatch { field: "viewport" });
        }
    }
    if let Some(expected_dpr) = &overrides.device_scale_factor {
        let provider::EnvironmentObservation::Known { value: actual } =
            rendering.device_scale_factor
        else {
            return Err(VoidCrawlAdapterError::EnvironmentMismatch {
                field: "device_scale_factor",
            });
        };
        let expected_value = expected_dpr
            .as_str()
            .parse::<f64>()
            .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
        if !device_scale_factor_matches(actual, expected_value) {
            return Err(VoidCrawlAdapterError::EnvironmentNumberMismatch {
                field: "device_scale_factor",
                expected: expected_value,
                observed: actual,
            });
        }
    }
    macro_rules! require_string {
        ($field:literal, $requested:expr, $observed:expr) => {
            if let Some(requested) = $requested {
                if !matches!($observed, provider::EnvironmentObservation::Known { value } if value == requested.as_str()) {
                    return Err(VoidCrawlAdapterError::EnvironmentMismatch { field: $field });
                }
            }
        };
    }
    require_string!(
        "user_agent",
        overrides.user_agent.as_ref(),
        &rendering.user_agent
    );
    require_string!("locale", overrides.locale.as_ref(), &rendering.locale);
    require_string!(
        "time_zone",
        overrides.time_zone.as_ref(),
        &rendering.timezone
    );
    if let Some(requested) = overrides.color_scheme
        && !matches!(&rendering.color_scheme, provider::EnvironmentObservation::Known { value } if *value == requested)
    {
        return Err(VoidCrawlAdapterError::EnvironmentMismatch {
            field: "color_scheme",
        });
    }
    if let Some(requested) = overrides.reduced_motion
        && !matches!(&rendering.reduced_motion, provider::EnvironmentObservation::Known { value } if *value == requested)
    {
        return Err(VoidCrawlAdapterError::EnvironmentMismatch {
            field: "reduced_motion",
        });
    }
    Ok(())
}

pub(super) fn instrumentation_agrees(
    instrumentation: provider::InstrumentationSnapshot,
    expected: yosoi::BrowserInstrumentationMode,
) -> bool {
    match expected {
        yosoi::BrowserInstrumentationMode::Normal => {
            instrumentation.configured_mode == provider::InstrumentationMode::Normal
                && instrumentation.network_enabled
                && instrumentation.runtime_enabled
                && !instrumentation.escalated_from_minimal
        }
        yosoi::BrowserInstrumentationMode::Minimal => {
            instrumentation.configured_mode == provider::InstrumentationMode::Minimal
                && !instrumentation.network_enabled
                && !instrumentation.runtime_enabled
                && !instrumentation.escalated_from_minimal
        }
        yosoi::BrowserInstrumentationMode::MinimalNetworkEscalated => {
            instrumentation.configured_mode == provider::InstrumentationMode::Minimal
                && instrumentation.network_enabled
                && !instrumentation.runtime_enabled
                && instrumentation.escalated_from_minimal
        }
        yosoi::BrowserInstrumentationMode::MinimalRuntimeEscalated => {
            instrumentation.configured_mode == provider::InstrumentationMode::Minimal
                && !instrumentation.network_enabled
                && instrumentation.runtime_enabled
                && instrumentation.escalated_from_minimal
        }
        yosoi::BrowserInstrumentationMode::MinimalBothEscalated => {
            instrumentation.configured_mode == provider::InstrumentationMode::Minimal
                && instrumentation.network_enabled
                && instrumentation.runtime_enabled
                && instrumentation.escalated_from_minimal
        }
    }
}

pub fn environment(
    value: provider::BrowserEnvironmentSnapshot,
    expected: yosoi::BrowserInstrumentationMode,
) -> Result<yosoi::BrowserCaptureEnvironment, VoidCrawlAdapterError> {
    if !instrumentation_agrees(value.instrumentation, expected) {
        return Err(VoidCrawlAdapterError::CapabilityMismatch);
    }
    let controller = controller_version(&value.controller)?;
    let renderer = Producer::new(
        ProducerId::new("org.chromium.browser")
            .map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)?,
        ProducerVersion::new(value.renderer.product)
            .map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)?,
    );
    let mode = environment_value(value.mode, Ok)?;
    let rendering = value.rendering;
    let viewport = environment_value(rendering.viewport, Ok)?;
    let dpr = environment_value(rendering.device_scale_factor, |v| {
        if !v.is_finite() || v <= 0.0 {
            return Err(VoidCrawlAdapterError::InvalidEnvironment);
        }
        yosoi::DeviceScaleFactor::new(v.to_string())
            .map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)
    })?;
    let ua = environment_value(rendering.user_agent, |v| {
        yosoi::UserAgent::new(v).map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)
    })?;
    let locale = environment_value(rendering.locale, |v| {
        yosoi::Locale::new(v).map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)
    })?;
    let timezone = environment_value(rendering.timezone, |v| {
        yosoi::TimeZone::new(v).map_err(|_| VoidCrawlAdapterError::InvalidEnvironment)
    })?;
    let color = environment_value(rendering.color_scheme, Ok)?;
    let motion = environment_value(rendering.reduced_motion, Ok)?;
    Ok(yosoi::BrowserCaptureEnvironment::new(
        controller,
        renderer,
        mode,
        yosoi::BrowserRenderingContext::new(viewport, dpr, ua, locale, timezone, color, motion),
    ))
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::{controller_version, device_scale_factor_matches, provider};

    #[test]
    #[allow(clippy::panic_in_result_fn)]
    fn registry_package_identity_keeps_the_established_producer() -> Result<(), Box<dyn Error>> {
        let controller = controller_version(&provider::ControllerVersion {
            name: provider::VOID_CRAWL_PACKAGE_NAME.to_string(),
            version: provider::VOID_CRAWL_VERSION.to_string(),
        })?;
        assert_eq!(
            controller.id().as_str(),
            "com.cascadinglabs.void_crawl_core"
        );
        assert_eq!(controller.version().as_str(), provider::VOID_CRAWL_VERSION);
        for (name, version) in [
            ("foreign-package", provider::VOID_CRAWL_VERSION),
            (provider::VOID_CRAWL_PACKAGE_NAME, "0.0.0"),
        ] {
            assert!(
                controller_version(&provider::ControllerVersion {
                    name: name.to_string(),
                    version: version.to_string(),
                })
                .is_err()
            );
        }
        Ok(())
    }

    #[test]
    fn device_scale_factor_allows_browser_float_round_trip_only() {
        assert!(device_scale_factor_matches(1.25, 1.25));
        assert!(device_scale_factor_matches(1.250_000_018_626_451_5, 1.25));
        assert!(!device_scale_factor_matches(1.251, 1.25));
    }
}
