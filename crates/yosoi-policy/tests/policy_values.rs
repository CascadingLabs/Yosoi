// Test assertions fail the harness; Result is used for fixture setup errors.
#![allow(clippy::panic_in_result_fn)]

mod common;

use std::io;

use common::{DEFAULT_POLICY_JSON, TestResult, default_policy_json_value};
use serde_json::Value;
use yosoi_policy::{
    Policy, Tuning, TuningMode,
    policy::{Acquisition, DirectHttpRedirectTargets, DirectHttpRedirects, RedirectHopLimit},
};
use yosoi_types::BrowserMode;

const DEFAULT_POLICY_IDENTITY_SHA256: &str =
    "a340f9711e02d7c1c8218814a7d810e7dc1a1584fb659a03cc45cc202a99e924";

#[test]
fn default_policy_has_stable_canonical_json_and_identity() -> TestResult {
    let policy = Policy::default();

    let canonical_json = policy.to_canonical_json()?;
    assert_eq!(canonical_json, DEFAULT_POLICY_JSON.trim());

    let identity = policy.effective_identity()?;
    assert_eq!(identity.version(), 5);
    assert_eq!(
        identity.digest().to_string(),
        DEFAULT_POLICY_IDENTITY_SHA256
    );
    assert_eq!(identity.digest().to_string().len(), 64);
    assert!(
        identity
            .digest()
            .to_string()
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    );

    let document: Value = serde_json::from_str(&canonical_json)?;
    assert!(document.get("schema_version").is_none());
    assert!(document.get("policy").is_none());
    assert!(document.get("page").is_some());
    Ok(())
}

#[test]
fn default_policy_deserialization_roundtrips_json_and_identity() -> TestResult {
    let expected_json = DEFAULT_POLICY_JSON.trim();
    let parsed: Policy = serde_json::from_str(expected_json)?;

    assert_eq!(parsed.to_canonical_json()?, expected_json);
    assert_eq!(
        parsed.effective_identity()?.digest(),
        Policy::default().effective_identity()?.digest()
    );
    Ok(())
}

#[test]
fn explicit_default_tuning_preserves_archived_default_policy_identity() -> TestResult {
    let baseline = Policy::default();
    let tuned = Policy {
        tuning: Tuning::default(),
        ..baseline.clone()
    };
    assert_eq!(tuned.tuning.mode(), TuningMode::Default);
    assert_eq!(tuned.to_canonical_json()?, DEFAULT_POLICY_JSON.trim());
    assert_eq!(tuned.effective_identity()?, baseline.effective_identity()?);

    let mut archived: Value = serde_json::from_str(DEFAULT_POLICY_JSON)?;
    archived["tuning"] = serde_json::json!({ "mode": "default" });
    let decoded: Policy = serde_json::from_value(archived)?;
    assert_eq!(decoded, baseline);
    assert_eq!(decoded.to_canonical_json()?, DEFAULT_POLICY_JSON.trim());
    assert_eq!(
        decoded.effective_identity()?,
        baseline.effective_identity()?
    );
    Ok(())
}

#[test]
fn formatting_and_input_object_order_do_not_change_effective_identity() -> TestResult {
    let default_policy = Policy::default();
    let default_document = default_policy_json_value()?;
    let page = default_document
        .pointer("/page")
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "fixture page is missing"))?;
    let request = default_document
        .pointer("/request")
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "fixture request is missing"))?;
    let documents = default_document.pointer("/documents").ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidData, "fixture documents is missing")
    })?;
    let locators = default_document
        .pointer("/locators")
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "fixture locators is missing"))?;
    let search = default_document
        .pointer("/search")
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "fixture search is missing"))?;
    let reordered = format!(
        "{{\n  \"search\": {},\n  \"locators\": {},\n  \"request\": {},\n  \"documents\": {},\n  \"page\": {}\n}}",
        serde_json::to_string_pretty(search)?,
        serde_json::to_string_pretty(locators)?,
        serde_json::to_string_pretty(request)?,
        serde_json::to_string_pretty(documents)?,
        serde_json::to_string_pretty(page)?
    );
    let parsed: Policy = serde_json::from_str(&reordered)?;

    assert_eq!(
        parsed.effective_identity()?.digest(),
        default_policy.effective_identity()?.digest()
    );
    assert_eq!(parsed.to_canonical_json()?, DEFAULT_POLICY_JSON.trim());
    Ok(())
}

#[test]
fn semantic_policy_changes_change_effective_identity() -> TestResult {
    let default_policy = Policy::default();
    let mut redirects_disabled = Policy::default();
    redirects_disabled.request.direct_http_redirects = DirectHttpRedirects::Disabled;

    assert_ne!(
        default_policy.effective_identity()?.digest(),
        redirects_disabled.effective_identity()?.digest()
    );

    let mut browser_acquisition = Policy::default();
    browser_acquisition
        .page
        .acquisitions
        .push(Acquisition::Browser(BrowserMode::Headless));
    assert!(browser_acquisition.validate().is_ok());
    assert_ne!(
        default_policy.effective_identity()?.digest(),
        browser_acquisition.effective_identity()?.digest()
    );

    let max_hops = RedirectHopLimit::try_from(10_u32)?;
    let mut allow_http_and_https = Policy::default();
    allow_http_and_https.request.direct_http_redirects = DirectHttpRedirects::Follow {
        max_hops,
        targets: DirectHttpRedirectTargets::AllowHttpAndHttps,
    };
    let mut same_origin = Policy::default();
    same_origin.request.direct_http_redirects = DirectHttpRedirects::Follow {
        max_hops,
        targets: DirectHttpRedirectTargets::SameOrigin,
    };
    assert_ne!(
        allow_http_and_https.effective_identity()?.digest(),
        same_origin.effective_identity()?.digest()
    );

    let mut smaller_document_budget = Policy::default();
    smaller_document_budget.documents.max_nodes = yosoi_policy::CountLimit::try_from(999_999_u64)?;
    assert_ne!(
        default_policy.effective_identity()?.digest(),
        smaller_document_budget.effective_identity()?.digest()
    );

    let mut smaller_locator_budget = Policy::default();
    smaller_locator_budget.locators.max_matches = yosoi_policy::CountLimit::try_from(99_999_u64)?;
    assert_ne!(
        default_policy.effective_identity()?.digest(),
        smaller_locator_budget.effective_identity()?.digest()
    );
    Ok(())
}
