// Test assertions fail the harness; Result is used for fixture setup errors.
#![allow(clippy::panic_in_result_fn)]

mod common;

use std::io;

use serde_json::Value;
use yosoi_policy::{
    Policy,
    policy::{
        AccessibilityNodeLimit, Acquisition, AddressableByteLimit, CountLimit, DocumentRequest,
        EventLimit, MaximumElapsed, RedirectHopLimit, ResourceLimit, StepLimit,
    },
};
use yosoi_types::BrowserMode;

use common::{TestResult, default_policy_json_value, set_json_value};

const POLICY_MANIFEST: &str = include_str!("../Cargo.toml");

fn first_u64_not_addressable_as_usize() -> Option<u64> {
    u64::try_from(usize::MAX).ok()?.checked_add(1)
}

fn first_u32_not_addressable_as_usize() -> Option<u32> {
    u32::try_from(usize::MAX).ok()?.checked_add(1)
}

fn first_u64_after_u32_max() -> Result<u64, io::Error> {
    u64::from(u32::MAX).checked_add(1).ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "u64 cannot represent u32::MAX + 1",
        )
    })
}

fn insert_json_field(
    document: &mut Value,
    pointer: &str,
    name: &str,
    value: Value,
) -> Result<(), io::Error> {
    let object = document
        .pointer_mut(pointer)
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                format!("the default policy fixture has no object at {pointer}"),
            )
        })?;
    object.insert(name.to_owned(), value);
    Ok(())
}

#[test]
#[allow(clippy::cognitive_complexity)] // One table-style test covers every numeric wrapper.
fn checked_limit_types_reject_zero_and_unaddressable_values() -> TestResult {
    assert!(AddressableByteLimit::try_from(0_u64).is_err());
    assert!(AddressableByteLimit::try_from(1_u64).is_ok());
    assert!(EventLimit::try_from(0_u64).is_err());
    assert!(EventLimit::try_from(1_u64).is_ok());
    assert!(CountLimit::try_from(0_u64).is_err());
    assert!(CountLimit::try_from(1_u64).is_ok());
    assert!(StepLimit::try_from(0_u32).is_err());
    assert!(StepLimit::try_from(1_u32).is_ok());
    assert!(ResourceLimit::try_from(0_u32).is_err());
    assert!(ResourceLimit::try_from(1_u32).is_ok());
    assert!(AccessibilityNodeLimit::try_from(0_u32).is_err());
    assert!(AccessibilityNodeLimit::try_from(1_u32).is_ok());
    assert!(MaximumElapsed::try_from(0_u64).is_err());
    assert_eq!(
        MaximumElapsed::try_from(u64::MAX)?.as_microseconds(),
        u64::MAX
    );
    assert_eq!(
        MaximumElapsed::try_from(10_000_000_u64)?
            .to_capture_deadline()?
            .as_microseconds(),
        10_000_000
    );
    assert!(RedirectHopLimit::try_from(0_u32).is_err());
    assert!(RedirectHopLimit::try_from(1_u32).is_ok());
    assert!(RedirectHopLimit::try_from(u32::MAX).is_ok());

    if let Some(first_unaddressable) = first_u64_not_addressable_as_usize() {
        assert!(AddressableByteLimit::try_from(first_unaddressable).is_err());
        assert!(EventLimit::try_from(first_unaddressable).is_err());

        for pointer in [
            "/request/source/content_coded_bytes",
            "/request/source/representation_bytes",
            "/request/source/unicode_utf8_bytes",
            "/request/browser/dom_utf8_bytes",
            "/request/browser/ax_json_utf8_bytes",
            "/request/browser/max_events",
            "/documents/max_input_bytes",
            "/locators/max_query_bytes",
            "/locators/max_output_bytes",
            "/search/max_in_flight",
            "/search/max_browser_in_flight",
            "/search/max_retained_content_bytes",
        ] {
            let mut document = default_policy_json_value()?;
            set_json_value(&mut document, pointer, Value::from(first_unaddressable))?;
            assert!(
                serde_json::from_value::<Policy>(document).is_err(),
                "{pointer} must reject a value larger than usize"
            );
        }
    }
    if let Some(first_unaddressable) = first_u32_not_addressable_as_usize() {
        assert!(ResourceLimit::try_from(first_unaddressable).is_err());
        assert!(AccessibilityNodeLimit::try_from(first_unaddressable).is_err());
        for pointer in [
            "/request/browser/max_resources",
            "/request/browser/max_accessibility_nodes",
        ] {
            let mut document = default_policy_json_value()?;
            set_json_value(&mut document, pointer, Value::from(first_unaddressable))?;
            assert!(
                serde_json::from_value::<Policy>(document).is_err(),
                "{pointer} must reject a value larger than usize"
            );
        }
    }
    Ok(())
}

#[test]
fn serde_rejects_zero_bounds_in_every_numeric_policy_domain() -> TestResult {
    for pointer in [
        "/request/maximum_elapsed",
        "/request/source/content_coded_bytes",
        "/request/source/representation_bytes",
        "/request/source/unicode_utf8_bytes",
        "/request/browser/dom_utf8_bytes",
        "/request/browser/ax_json_utf8_bytes",
        "/request/browser/max_events",
        "/request/browser/max_resources",
        "/request/browser/max_accessibility_nodes",
        "/request/direct_http_redirects/max_hops",
        "/documents/max_input_bytes",
        "/documents/max_nodes",
        "/documents/max_depth",
        "/locators/max_selector_visits",
        "/locators/max_query_bytes",
        "/locators/max_query_steps",
        "/locators/max_regions",
        "/locators/max_matches",
        "/locators/max_captures",
        "/locators/max_output_bytes",
        "/search/max_in_flight",
        "/search/max_browser_in_flight",
        "/search/max_results_per_provider",
        "/search/max_total_results",
        "/search/max_retained_content_bytes",
        "/search/maximum_elapsed",
    ] {
        let mut document = default_policy_json_value()?;
        set_json_value(&mut document, pointer, Value::from(0_u64))?;
        assert!(
            serde_json::from_value::<Policy>(document).is_err(),
            "{pointer} must reject zero"
        );
    }

    let mut document = default_policy_json_value()?;
    set_json_value(
        &mut document,
        "/request/maximum_elapsed",
        Value::from(u64::MAX),
    )?;
    let maximum_deadline: Policy = serde_json::from_value(document)?;
    assert_eq!(
        maximum_deadline.request.maximum_elapsed.as_microseconds(),
        u64::MAX
    );
    Ok(())
}

#[test]
fn direct_policy_json_rejects_unknown_fields_and_malformed_values() -> TestResult {
    let legacy_envelope = serde_json::json!({
        "schema_version": 2,
        "policy": default_policy_json_value()?,
    });
    assert!(serde_json::from_value::<Policy>(legacy_envelope).is_err());

    let mut document = default_policy_json_value()?;
    insert_json_field(&mut document, "", "schema_version", Value::from(2_u64))?;
    assert!(serde_json::from_value::<Policy>(document).is_err());

    let mut document = default_policy_json_value()?;
    let fields = document.as_object_mut().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "policy fixture is not an object",
        )
    })?;
    fields.remove("page");
    assert!(serde_json::from_value::<Policy>(document).is_err());

    let mut document = default_policy_json_value()?;
    insert_json_field(&mut document, "", "future_field", Value::Null)?;
    assert!(serde_json::from_value::<Policy>(document).is_err());

    let mut document = default_policy_json_value()?;
    insert_json_field(&mut document, "/page", "future_field", Value::Null)?;
    assert!(serde_json::from_value::<Policy>(document).is_err());

    let mut document = default_policy_json_value()?;
    insert_json_field(&mut document, "/request", "future_field", Value::Null)?;
    assert!(serde_json::from_value::<Policy>(document).is_err());

    for (pointer, unknown) in [
        ("/page/acquisitions/0/kind", "future_acquisition"),
        (
            "/page/acquisitions/0/documents/kind",
            "future_document_selection",
        ),
        ("/request/direct_http_redirects/kind", "future_redirects"),
    ] {
        let mut document = default_policy_json_value()?;
        set_json_value(&mut document, pointer, Value::from(unknown))?;
        assert!(serde_json::from_value::<Policy>(document).is_err());
    }

    let mut document = default_policy_json_value()?;
    set_json_value(
        &mut document,
        "/request/direct_http_redirects/targets",
        Value::from("future_targets"),
    )?;
    assert!(serde_json::from_value::<Policy>(document).is_err());

    for pointer in [
        "/request/direct_http_redirects/max_hops",
        "/request/browser/max_resources",
        "/request/browser/max_accessibility_nodes",
    ] {
        let mut document = default_policy_json_value()?;
        set_json_value(
            &mut document,
            pointer,
            Value::from(first_u64_after_u32_max()?),
        )?;
        assert!(serde_json::from_value::<Policy>(document).is_err());
    }
    Ok(())
}

#[test]
fn rejected_secret_bearing_unknown_input_does_not_echo_its_value() -> TestResult {
    let sentinel = "policy-secret-sentinel-92b7";
    let mut document = default_policy_json_value()?;
    insert_json_field(
        &mut document,
        "",
        "url",
        Value::from(format!("https://user:{sentinel}@example.test")),
    )?;
    let input = serde_json::to_string(&document)?;
    let error = match serde_json::from_str::<Policy>(&input) {
        Ok(_) => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "policy input unexpectedly accepted a URL and credential",
            )
            .into());
        }
        Err(error) => error.to_string(),
    };

    assert!(!error.contains(sentinel));
    Ok(())
}

#[test]
fn public_document_requests_and_lightweight_dependency_boundary_hold() {
    let requested_documents = [
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::NetworkTree,
    ];
    let mut policy = Policy::default();
    policy
        .page
        .acquisitions
        .push(Acquisition::Browser(BrowserMode::Headless).documents(requested_documents));
    assert!(policy.validate().is_ok());

    let manifest = POLICY_MANIFEST.to_ascii_lowercase();
    for forbidden in [
        "void_crawl_core",
        "chromiumoxide",
        "headless_chrome",
        "fantoccini",
        "thirtyfour",
        "playwright",
        "scraper",
        "html5ever",
        "kuchiki",
        "quick-xml",
        "xmltree",
        "lol_html",
    ] {
        assert!(
            !manifest.contains(forbidden),
            "policy crate must not depend on {forbidden}"
        );
    }
}
