use std::{error::Error, num::NonZeroU32};

use crate::internal::types::{Producer, ProducerId, ProducerVersion, ReasonCode};
use crate::internal::web_capture::{
    BrowserCaptureEnvironment, BrowserMode, BrowserRenderingContext, CaptureEnvironment,
    ColorScheme, DeviceScaleFactor, DeviceScaleFactorError, EnvironmentValue,
    HttpCaptureEnvironment, Locale, PreferredLanguages, ReducedMotion, TimeZone, UserAgent,
    Viewport,
};
use serde_json::{Value, json};

const DESKTOP_FIXTURE: &str = include_str!("fixtures/environment-desktop.json");
const MOBILE_FIXTURE: &str = include_str!("fixtures/environment-mobile.json");
const HTTP_FIXTURE: &str = include_str!("fixtures/environment-http.json");

#[test]
fn desktop_mobile_and_http_golden_fixtures_round_trip() {
    for fixture in [DESKTOP_FIXTURE, MOBILE_FIXTURE, HTTP_FIXTURE] {
        let expected: Value = serde_json::from_str(fixture).unwrap();
        let environment: CaptureEnvironment = serde_json::from_str(fixture).unwrap();

        assert_eq!(serde_json::to_value(environment).unwrap(), expected);
    }
}

#[test]
fn native_http_has_no_fictional_browser_geometry() {
    let environment: CaptureEnvironment = serde_json::from_str(HTTP_FIXTURE).unwrap();
    assert!(matches!(environment, CaptureEnvironment::Http(_)));

    let invalid = json!({
        "kind": "http",
        "environment": {
            "client": {
                "id": "com.cascadinglabs.yosoi.http",
                "version": "0.1.0"
            },
            "user_agent": {
                "status": "known",
                "value": "yosoi/0.1.0"
            },
            "preferred_languages": {
                "status": "known",
                "value": []
            },
            "viewport": {
                "status": "known",
                "value": {
                    "width_css_pixels": 1280,
                    "height_css_pixels": 720
                }
            }
        }
    });

    assert!(serde_json::from_value::<CaptureEnvironment>(invalid).is_err());
}

#[test]
fn browser_geometry_must_have_an_explicit_state() {
    let fixture: Value = serde_json::from_str(DESKTOP_FIXTURE).unwrap();
    let mut missing_viewport = fixture.clone();
    assert!(
        missing_viewport
            .pointer_mut("/environment/rendering")
            .and_then(Value::as_object_mut)
            .and_then(|rendering| rendering.remove("viewport"))
            .is_some()
    );
    let mut null_viewport = fixture;
    assert!(
        null_viewport
            .pointer_mut("/environment/rendering/viewport")
            .is_some()
    );
    if let Some(viewport) = null_viewport.pointer_mut("/environment/rendering/viewport") {
        *viewport = Value::Null;
    }

    assert!(serde_json::from_value::<CaptureEnvironment>(missing_viewport).is_err());
    assert!(serde_json::from_value::<CaptureEnvironment>(null_viewport).is_err());
}

#[test]
fn known_unavailable_and_omitted_are_distinct() {
    let known = EnvironmentValue::known(UserAgent::new("yosoi/0.1.0").unwrap());
    let unavailable: EnvironmentValue<UserAgent> =
        EnvironmentValue::unavailable(ReasonCode::new("capture.provider-unreported").unwrap());
    let omitted: EnvironmentValue<UserAgent> =
        EnvironmentValue::omitted(ReasonCode::new("capture.metadata-policy").unwrap());

    assert!(known.as_known().is_some());
    assert!(unavailable.as_known().is_none());
    assert!(omitted.as_known().is_none());
    assert_ne!(
        serde_json::to_value(unavailable).unwrap(),
        serde_json::to_value(omitted).unwrap()
    );
}

#[test]
fn device_scale_factor_is_exact_positive_and_canonical() {
    for valid in ["0.5", "1", "1.25", "3"] {
        let factor = DeviceScaleFactor::new(valid).unwrap();
        assert_eq!(factor.as_str(), valid);
        assert_eq!(serde_json::to_value(&factor).unwrap(), json!(valid));
        assert_eq!(
            serde_json::from_value::<DeviceScaleFactor>(json!(valid)).unwrap(),
            factor
        );
    }

    assert_eq!(
        DeviceScaleFactor::new("0"),
        Err(DeviceScaleFactorError::Zero)
    );
    for invalid in ["", "01", "1.0", "1.", ".5", "-1", "1e0", "1.2.3", "１"] {
        assert!(
            DeviceScaleFactor::new(invalid).is_err(),
            "accepted {invalid:?}"
        );
    }
    assert!(DeviceScaleFactor::new("9".repeat(33)).is_err());
    assert!(DeviceScaleFactor::new("9".repeat(32)).is_ok());
    assert!(serde_json::from_value::<DeviceScaleFactor>(json!(1.25)).is_err());
}

#[test]
fn environment_scalars_reject_unsafe_or_ambiguous_values() {
    assert!(UserAgent::new("secret\nheader").is_err());
    assert!(UserAgent::new("x".repeat(1_025)).is_err());
    assert!(Locale::new("").is_err());
    assert!(Locale::new("en_US").is_err());
    assert!(Locale::new("en--US").is_err());
    assert!(Locale::new("-en").is_err());
    assert!(TimeZone::new("../../profile").is_err());
    assert!(TimeZone::new("/tmp/profile").is_err());
    assert!(TimeZone::new("America/New York").is_err());
    assert!(TimeZone::new("America//New_York").is_err());
    assert!(PreferredLanguages::new(vec![Locale::new("en").unwrap(); 33]).is_err());

    let zero_viewport = json!({
        "width_css_pixels": 0,
        "height_css_pixels": 800
    });
    assert!(serde_json::from_value::<Viewport>(zero_viewport).is_err());
}

#[test]
fn fingerprint_inputs_are_allowlisted_and_ignore_absence_reasons() {
    let first = CaptureEnvironment::Http(HttpCaptureEnvironment::new(
        producer("com.cascadinglabs.yosoi.http", "0.1.0").unwrap(),
        EnvironmentValue::omitted(ReasonCode::new("capture.first-policy").unwrap()),
        EnvironmentValue::known(
            PreferredLanguages::new(vec![Locale::new("en-US").unwrap()]).unwrap(),
        ),
    ));
    let second = CaptureEnvironment::Http(HttpCaptureEnvironment::new(
        producer("com.cascadinglabs.yosoi.http", "0.1.0").unwrap(),
        EnvironmentValue::omitted(ReasonCode::new("capture.second-policy").unwrap()),
        EnvironmentValue::known(
            PreferredLanguages::new(vec![Locale::new("en-US").unwrap()]).unwrap(),
        ),
    ));

    let first_inputs = serde_json::to_value(first.fingerprint_inputs()).unwrap();
    let second_inputs = serde_json::to_value(second.fingerprint_inputs()).unwrap();
    assert_eq!(first_inputs, second_inputs);

    let encoded = serde_json::to_string(&first_inputs).unwrap();
    for forbidden in [
        "first-policy",
        "second-policy",
        "profile_path",
        "cookie",
        "credential",
        "authorization",
        "browser_arguments",
    ] {
        assert!(!encoded.contains(forbidden));
    }
}

#[test]
fn every_representation_fact_changes_fingerprint_inputs() {
    let desktop: Value = serde_json::from_str(DESKTOP_FIXTURE).unwrap();
    let baseline: CaptureEnvironment = serde_json::from_value(desktop.clone()).unwrap();
    let baseline_inputs = serde_json::to_value(baseline.fingerprint_inputs()).unwrap();

    for (pointer, replacement) in [
        ("/environment/controller/version", json!("1.0.1")),
        ("/environment/renderer/version", json!("143.0.1")),
        ("/environment/mode/value", json!("headful")),
        (
            "/environment/rendering/viewport/value/width_css_pixels",
            json!(1280),
        ),
        (
            "/environment/rendering/device_scale_factor/value",
            json!("2"),
        ),
        (
            "/environment/rendering/user_agent/value",
            json!("Different Browser"),
        ),
        ("/environment/rendering/locale/value", json!("fr-FR")),
        (
            "/environment/rendering/time_zone/value",
            json!("Europe/Paris"),
        ),
        ("/environment/rendering/color_scheme/value", json!("light")),
        (
            "/environment/rendering/reduced_motion/value",
            json!("reduce"),
        ),
    ] {
        let changed: CaptureEnvironment =
            serde_json::from_value(changed(&desktop, pointer, replacement)).unwrap();
        assert_ne!(
            serde_json::to_value(changed.fingerprint_inputs()).unwrap(),
            baseline_inputs,
            "fingerprint omitted {pointer}"
        );
    }

    let http: Value = serde_json::from_str(HTTP_FIXTURE).unwrap();
    let baseline: CaptureEnvironment = serde_json::from_value(http.clone()).unwrap();
    let changed: CaptureEnvironment = serde_json::from_value(changed(
        &http,
        "/environment/preferred_languages/value/0",
        json!("fr-FR"),
    ))
    .unwrap();
    assert_ne!(
        serde_json::to_value(baseline.fingerprint_inputs()).unwrap(),
        serde_json::to_value(changed.fingerprint_inputs()).unwrap()
    );
}

#[test]
fn ordinary_environment_rejects_untyped_sensitive_metadata() {
    for fixture in [HTTP_FIXTURE, DESKTOP_FIXTURE] {
        let environment: Value = serde_json::from_str(fixture).unwrap();
        for field in [
            "profile_path",
            "cookies",
            "credentials",
            "authorization_headers",
            "browser_arguments",
            "warm_up_urls",
            "extra",
        ] {
            let mut invalid = environment.clone();
            let fields = invalid
                .pointer_mut("/environment")
                .and_then(Value::as_object_mut)
                .unwrap();
            fields.insert(field.to_owned(), json!("sensitive runtime input"));
            assert!(
                serde_json::from_value::<CaptureEnvironment>(invalid).is_err(),
                "accepted forbidden field {field}"
            );
        }
    }
}

#[test]
fn browser_context_constructor_preserves_geometry_and_preferences() {
    let viewport = Viewport::new(NonZeroU32::new(390).unwrap(), NonZeroU32::new(844).unwrap());
    let rendering = BrowserRenderingContext::new(
        EnvironmentValue::known(viewport),
        EnvironmentValue::known(DeviceScaleFactor::new("3").unwrap()),
        EnvironmentValue::known(UserAgent::new("Mobile Browser").unwrap()),
        EnvironmentValue::known(Locale::new("en-US").unwrap()),
        EnvironmentValue::known(TimeZone::new("UTC").unwrap()),
        EnvironmentValue::known(ColorScheme::Dark),
        EnvironmentValue::known(ReducedMotion::Reduce),
    );
    let environment = BrowserCaptureEnvironment::new(
        producer("com.cascadinglabs.voidcrawl.cdp", "1.0.0").unwrap(),
        producer("org.chromium.chromium", "143.0.0").unwrap(),
        EnvironmentValue::known(BrowserMode::Headless),
        rendering,
    );

    assert_eq!(
        environment.rendering().viewport().as_known(),
        Some(&viewport)
    );
    assert_eq!(
        environment.rendering().color_scheme().as_known(),
        Some(&ColorScheme::Dark)
    );
}

fn changed(value: &Value, pointer: &str, replacement: Value) -> Value {
    let mut changed = value.clone();
    assert!(changed.pointer_mut(pointer).is_some());
    if let Some(target) = changed.pointer_mut(pointer) {
        *target = replacement;
    }
    changed
}

fn producer(id: &str, version: &str) -> Result<Producer, Box<dyn Error>> {
    Ok(Producer::new(
        ProducerId::new(id)?,
        ProducerVersion::new(version)?,
    ))
}
