// Assertions fail the harness; Result is used for setup and serializer errors.
#![allow(clippy::panic_in_result_fn)]

use std::io;

use crate::browser::BrowserEngine;
use crate::internal::policy::{
    Policy, PolicyError, PolicySnapshot,
    policy::{
        AddressableByteLimit, EvidenceFailurePolicy, ObservePolicy, RecordingMode, RecordingRule,
        ScreenshotScope, Search,
    },
};
use crate::policy::observe::MAX_RECORDING_DURATION_MS;
use serde_json::{Value, json};

use super::common::{DEFAULT_POLICY_JSON, TestResult};

const OBSERVE_POLICY_JSON: &str = include_str!("fixtures/observe-policy.json");
const DEFAULT_POLICY_IDENTITY_V7_SHA256: &str =
    "65f808531d392ce5ea96509219dfd62a3e0440c0c2c0a8e657bc420a89a6d7d2";

fn recording_rule(mode: RecordingMode, include_audio: bool) -> Result<RecordingRule, PolicyError> {
    Ok(RecordingRule {
        mode,
        max_bytes: AddressableByteLimit::try_from(8_000_000_u64)?,
        max_duration_ms: 15_000,
        include_audio,
    })
}

fn policy_value() -> Result<Value, serde_json::Error> {
    serde_json::from_str(DEFAULT_POLICY_JSON)
}

fn set_observe(value: &mut Value, observe: Value) -> Result<(), io::Error> {
    let object = value.as_object_mut().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "default policy is not an object",
        )
    })?;
    object.insert("observe".to_owned(), observe);
    Ok(())
}

#[test]
fn absent_observe_preserves_legacy_policy_json_and_identity() -> TestResult {
    let decoded: Policy = serde_json::from_str(DEFAULT_POLICY_JSON)?;
    assert_eq!(decoded.observe, ObservePolicy::default());
    assert_eq!(decoded.to_canonical_json()?, DEFAULT_POLICY_JSON.trim());
    assert_eq!(decoded.effective_identity()?.version(), 7);
    assert_eq!(
        decoded.effective_identity()?.digest().to_string(),
        DEFAULT_POLICY_IDENTITY_V7_SHA256
    );
    assert_eq!(decoded.archived_v6_identity()?.version(), 6);
    assert_eq!(decoded.archived_v5_identity()?.version(), 5);
    Ok(())
}

#[test]
fn default_observe_is_omitted_and_has_bounded_safe_defaults() -> TestResult {
    let policy = Policy::default();
    let serialized: Value = serde_json::from_str(&policy.to_canonical_json()?)?;
    assert!(serialized.get("observe").is_none());
    assert!(!policy.observe.enabled);
    assert!(!policy.observe.native_tab_capture);
    assert_eq!(policy.observe.failure, EvidenceFailurePolicy::Continue);
    assert_eq!(policy.observe.screenshots.before, None);
    assert_eq!(policy.observe.screenshots.after, None);
    assert_eq!(policy.observe.screenshots.failure, None);
    assert!(policy.observe.recordings.is_empty());
    assert_eq!(policy.observe.limits.max_sources, 33);
    assert_eq!(policy.observe.limits.max_recordings, 5);
    assert_eq!(policy.observe.limits.max_buffer_bytes.get(), 16_000_000);
    assert_eq!(policy.observe.limits.max_retained_bytes.get(), 64_000_000);
    let default_rule = RecordingRule::default();
    assert_eq!(default_rule.mode, RecordingMode::BrowserVisible);
    assert_eq!(default_rule.max_bytes.get(), 64_000_000);
    assert_eq!(default_rule.max_duration_ms, 60_000);
    assert!(!default_rule.include_audio);
    Ok(())
}

#[test]
fn enabled_observe_roundtrips_typed_screenshots_and_additive_recordings() -> TestResult {
    let mut policy = Policy::default();
    policy.observe.enabled = true;
    policy.observe.native_tab_capture = true;
    policy.observe.screenshots.before = Some(ScreenshotScope::Target);
    policy.observe.screenshots.after = Some(ScreenshotScope::Viewport);
    policy.observe.screenshots.failure = Some(ScreenshotScope::Target);
    policy.observe.failure = EvidenceFailurePolicy::Require;
    policy.observe.recordings = vec![
        recording_rule(RecordingMode::BrowserVisible, false)?,
        recording_rule(RecordingMode::EachTab, false)?,
        recording_rule(RecordingMode::EachTab, true)?,
    ];
    policy.observe.limits.max_recordings = 3;

    let encoded = policy.to_canonical_json()?;
    let value: Value = serde_json::from_str(&encoded)?;
    let expected_observe: Value = serde_json::from_str(OBSERVE_POLICY_JSON)?;
    assert_eq!(value["observe"], expected_observe);
    assert_eq!(value["observe"]["enabled"], true);
    assert_eq!(value["observe"]["native_tab_capture"], true);
    assert_eq!(value["observe"]["failure"], "require");
    assert_eq!(value["observe"]["screenshots"]["before"], "target");
    assert_eq!(value["observe"]["screenshots"]["after"], "viewport");
    assert_eq!(value["observe"]["screenshots"]["failure"], "target");
    assert_eq!(value["observe"]["recordings"][0]["mode"], "browser_visible");
    assert_eq!(value["observe"]["recordings"][1]["mode"], "each_tab");
    assert_eq!(
        value["observe"]["recordings"].as_array().map(Vec::len),
        Some(3)
    );
    assert_eq!(value["observe"]["recordings"][2]["include_audio"], true);

    let reopened: Policy = serde_json::from_str(&encoded)?;
    assert_eq!(reopened, policy);
    let snapshot = PolicySnapshot::from_policy(&policy)?;
    assert_eq!(snapshot.effective_policy().observe, policy.observe);
    assert_eq!(snapshot.identity().version(), 9);
    assert_eq!(snapshot.identity(), reopened.effective_identity()?);
    Ok(())
}

#[test]
fn observe_changes_identity_without_rewriting_legacy_disabled_identity() -> TestResult {
    let baseline = Policy::default();
    let mut enabled = baseline.clone();
    enabled.observe.enabled = true;

    assert_eq!(baseline.effective_identity()?.version(), 7);
    assert_eq!(
        baseline.effective_identity()?.digest().to_string(),
        DEFAULT_POLICY_IDENTITY_V7_SHA256
    );
    assert_eq!(enabled.effective_identity()?.version(), 9);
    assert_ne!(
        enabled.effective_identity()?.digest(),
        baseline.effective_identity()?.digest()
    );
    assert_eq!(
        enabled.archived_v6_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );
    assert_eq!(
        enabled.archived_v5_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );

    let legacy = Policy {
        search: Search::disabled(),
        ..Policy::default()
    };
    let observed_legacy = Policy {
        observe: enabled.observe,
        ..legacy
    };
    assert_eq!(
        observed_legacy.archived_v2_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );
    assert_eq!(
        observed_legacy.archived_v3_map_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );
    assert_eq!(
        observed_legacy.archived_v3_map_pre_robots_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );
    assert_eq!(
        observed_legacy
            .effective_policy()?
            .archived_v4_search_pre_robots_identity(),
        Err(PolicyError::LegacyIdentityCannotIncludeObserve)
    );
    Ok(())
}

#[test]
fn default_observe_preserves_the_browser_identity_and_active_observe_uses_v9() -> TestResult {
    let browser = Policy {
        browser: crate::browser::BrowserConfig {
            engine: BrowserEngine::Firefox,
            ..crate::browser::BrowserConfig::default()
        },
        ..Policy::default()
    };
    assert_eq!(browser.effective_identity()?.version(), 8);

    let observed_browser = Policy {
        observe: ObservePolicy {
            enabled: true,
            ..ObservePolicy::default()
        },
        ..browser
    };
    assert_eq!(observed_browser.effective_identity()?.version(), 9);
    Ok(())
}

#[test]
fn native_tab_permission_alone_does_not_enable_automatic_observation() -> TestResult {
    let mut policy = Policy::default();
    policy.observe.native_tab_capture = true;

    assert!(!policy.observe.enabled);
    assert!(policy.observe.recordings.is_empty());
    assert!(policy.validate().is_ok());
    assert_eq!(policy.effective_identity()?.version(), 9);
    Ok(())
}

#[test]
fn observe_rejects_zero_or_conflicting_source_output_buffer_and_rule_bounds() -> TestResult {
    let mut value = policy_value()?;
    set_observe(&mut value, json!({"limits":{"max_sources":0}}))?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(&mut value, json!({"limits":{"max_recordings":0}}))?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(&mut value, json!({"limits":{"max_buffer_bytes":0}}))?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(&mut value, json!({"limits":{"max_retained_bytes":0}}))?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let rule = json!({
        "mode":"browser_visible",
        "max_bytes":1,
        "max_duration_ms":1,
        "include_audio":false
    });
    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"enabled":true,"limits":{"max_recordings":1},"recordings":[rule.clone(),rule.clone()]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"recordings":[{"mode":"browser_visible","max_bytes":0,"max_duration_ms":1}]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"recordings":[{"mode":"browser_visible","max_bytes":1,"max_duration_ms":0}]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"recordings":[{"mode":"browser_visible","max_bytes":1,"max_duration_ms":u64::MAX}]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());
    Ok(())
}

#[test]
fn recording_duration_accepts_minutes_and_one_day_but_rejects_more() -> TestResult {
    for duration_ms in [300_000, MAX_RECORDING_DURATION_MS] {
        let mut policy = Policy::default();
        policy.observe.native_tab_capture = true;
        let mut rule = recording_rule(RecordingMode::EachTab, false)?;
        rule.max_duration_ms = duration_ms;
        policy.observe.recordings.push(rule);
        assert!(policy.validate().is_ok());
    }

    let mut policy = Policy::default();
    policy.observe.native_tab_capture = true;
    let mut rule = recording_rule(RecordingMode::EachTab, false)?;
    rule.max_duration_ms = MAX_RECORDING_DURATION_MS
        .checked_add(1)
        .ok_or_else(|| io::Error::other("recording duration test bound overflowed"))?;
    policy.observe.recordings.push(rule);
    assert_eq!(
        policy.validate(),
        Err(PolicyError::InvalidObservationRecordingDuration)
    );
    Ok(())
}

#[test]
fn observe_rejects_unsupported_audio_and_missing_tab_capture_permission() -> TestResult {
    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"recordings":[{"mode":"browser_visible","max_bytes":1,"max_duration_ms":1,"include_audio":true}]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut policy = Policy::default();
    policy
        .observe
        .recordings
        .push(recording_rule(RecordingMode::EachTab, false)?);
    assert_eq!(
        policy.validate(),
        Err(PolicyError::NativeTabCaptureNotPermitted)
    );

    policy.observe.native_tab_capture = true;
    assert!(policy.validate().is_ok());
    Ok(())
}

#[test]
fn observe_rejects_unknown_fields_in_policy_and_nested_rules() -> TestResult {
    let mut value = policy_value()?;
    set_observe(&mut value, json!({"unexpected":true}))?;
    assert!(serde_json::from_value::<Policy>(value).is_err());

    let mut value = policy_value()?;
    set_observe(
        &mut value,
        json!({"recordings":[{"mode":"browser_visible","max_bytes":1,"max_duration_ms":1,"unexpected":true}]}),
    )?;
    assert!(serde_json::from_value::<Policy>(value).is_err());
    Ok(())
}
