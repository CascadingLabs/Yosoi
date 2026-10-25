//! Preserve absent remote facts without weakening owned/Chrome mode validation.
#![allow(
    clippy::panic_in_result_fn,
    reason = "assertions are acceptance failures"
)]
use super::*;
use crate::browser::{BrowserEngine, BrowserExecutionIdentity, BrowserProtocol, MoliProfile};
use crate::internal::types::{Producer, ProducerId, ProducerVersion, ReasonCode};
use crate::internal::web_capture::{
    BrowserInstrumentationMode, BrowserMode, BrowserRenderingContext, EnvironmentValue,
};
use std::error as std_error;

#[test]
fn unavailable_remote_mode_is_never_promoted_to_an_owned_or_chrome_fact()
-> Result<(), Box<dyn std_error::Error>> {
    let reason = ReasonCode::new("voidcrawl.environment.attached-browser-not-controlled")?;
    let controller = Producer::new(ProducerId::new("test.bidi")?, ProducerVersion::new("1")?);
    let rendering = BrowserRenderingContext::new(
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
    );
    let backend = BrowserExecutionIdentity {
        controller_version: None,
        capability_profile: None,
        reported_headless: None,
        engine: BrowserEngine::Moli,
        protocol: BrowserProtocol::Bidi,
        reported_name: None,
        reported_version: None,
        executable_version: None,
        executable_sha256: None,
        process_owned: false,
        moli_profile: Some(MoliProfile::Dom),
        moli_resources: Some(false),
        owned_moli_private_network_blocking: None,
    };
    let environment = |backend, mode| {
        BrowserCaptureEnvironment::with_backend(
            controller.clone(),
            None,
            backend,
            mode,
            rendering.clone(),
        )
    };
    let remote = environment(
        backend.clone(),
        EnvironmentValue::unavailable(reason.clone()),
    );
    assert!(environment_mode_agrees(
        &remote,
        BrowserMode::Headless,
        BrowserInstrumentationMode::Bidi
    ));
    assert!(!environment_mode_agrees(
        &remote,
        BrowserMode::Headful,
        BrowserInstrumentationMode::Bidi
    ));
    assert!(!environment_mode_agrees(
        &remote,
        BrowserMode::Headless,
        BrowserInstrumentationMode::Normal
    ));
    assert!(remote.renderer().is_none());
    assert!(matches!(
        remote.mode(),
        EnvironmentValue::Unavailable { .. }
    ));
    let encoded = serde_json::to_string(&remote)?;
    let decoded: BrowserCaptureEnvironment = serde_json::from_str(&encoded)?;
    assert_eq!(decoded, remote);
    assert!(!encoded.contains("org.chromium"));

    let owned = environment(
        BrowserExecutionIdentity {
            process_owned: true,
            ..backend.clone()
        },
        EnvironmentValue::unavailable(reason.clone()),
    );
    assert!(!environment_mode_agrees(
        &owned,
        BrowserMode::Headless,
        BrowserInstrumentationMode::Bidi
    ));
    let chrome = environment(
        BrowserExecutionIdentity {
            engine: BrowserEngine::Chrome,
            ..backend.clone()
        },
        EnvironmentValue::unavailable(reason),
    );
    assert!(!environment_mode_agrees(
        &chrome,
        BrowserMode::Headless,
        BrowserInstrumentationMode::Bidi
    ));
    let wrong = environment(backend, EnvironmentValue::known(BrowserMode::Headful));
    assert!(!environment_mode_agrees(
        &wrong,
        BrowserMode::Headless,
        BrowserInstrumentationMode::Bidi
    ));
    Ok(())
}

#[test]
fn legacy_environment_keeps_its_known_renderer_json() -> Result<(), Box<dyn std_error::Error>> {
    let producer = Producer::new(
        ProducerId::new("test.chrome")?,
        ProducerVersion::new("156")?,
    );
    let reason = ReasonCode::new("test.unavailable")?;
    let rendering = BrowserRenderingContext::new(
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason.clone()),
        EnvironmentValue::unavailable(reason),
    );
    let legacy = BrowserCaptureEnvironment::new(
        producer.clone(),
        producer,
        EnvironmentValue::known(BrowserMode::Headless),
        rendering,
    );
    let json = serde_json::to_value(&legacy)?;
    assert!(json.get("renderer").is_some());
    assert!(json.get("backend").is_none());
    assert_eq!(
        serde_json::from_value::<BrowserCaptureEnvironment>(json)?,
        legacy
    );
    Ok(())
}
