#![allow(clippy::panic_in_result_fn)] // Contract assertions intentionally fail the test.

use std::{collections::BTreeSet, error::Error, io};

use serde_json::Value;
use yosoi::prelude as ys;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn plan_serialization_contains_no_resource_budget() -> TestResult {
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    let serialized = serde_json::to_value(plan)?;

    assert_eq!(
        budget_field(&serialized),
        None,
        "Plan serde contains a resource budget field"
    );
    Ok(())
}

#[test]
fn facade_policy_json_is_direct_and_rejects_legacy_or_unknown_fields() -> TestResult {
    let serialized = serde_json::to_value(ys::Policy::default())?;
    let fields = serialized
        .as_object()
        .ok_or_else(|| io::Error::other("serialized Policy is not an object"))?
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    assert_eq!(
        fields,
        BTreeSet::from(["documents", "locators", "map", "page", "request", "search"])
    );

    let legacy_envelope = serde_json::json!({
        "schema_version": 2,
        "policy": serialized,
    });
    assert!(serde_json::from_value::<ys::Policy>(legacy_envelope).is_err());

    let mut versioned_direct_values = serialized.clone();
    insert_field(
        &mut versioned_direct_values,
        "schema_version",
        Value::from(2_u64),
    )?;
    assert!(serde_json::from_value::<ys::Policy>(versioned_direct_values).is_err());

    let mut unknown_direct_values = serialized;
    insert_field(&mut unknown_direct_values, "future_field", Value::Null)?;
    assert!(serde_json::from_value::<ys::Policy>(unknown_direct_values).is_err());
    Ok(())
}

#[test]
fn locate_keeps_no_match_indeterminate_and_failure_distinct() -> TestResult {
    let complete_document = ys::Document::text("orders.txt", b"no orders here".to_vec())?;
    let missing_plan = ys::Plan::new([ys::output(
        "missing_order",
        ys::text_literal("absent")?.text(),
    )?])?;
    assert!(matches!(
        complete_document.locate(&missing_plan),
        ys::LocateOutcome::NoMatch { document_id }
            if document_id.as_str() == "orders.txt"
    ));

    let incomplete_ax = br#"{
        "schema":"yosoi.accessibility-tree.v1",
        "document_epoch":7,
        "root":"root",
        "completeness":{"status":"unknown","reason_code":"capture_completeness_unverified"},
        "nodes":[{"id":"root","parent":null,"children":[],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}}]
    }"#;
    let ax_document = ys::Document::accessibility_tree(
        "partial.ax",
        ys::DocumentEpoch::try_from(7)?,
        incomplete_ax.to_vec(),
    )?;
    let absent_role_plan = ys::Plan::new([ys::output("button", ys::role("button")?.node())?])?;
    assert!(matches!(
        ax_document.locate(&absent_role_plan),
        ys::LocateOutcome::Indeterminate {
            document_id,
            completeness: ys::IncompleteEvidence::Unknown { .. },
            ..
        } if document_id.as_str() == "partial.ax"
    ));

    let malformed_json = ys::Document::json("broken.json", b"{".to_vec())?;
    let json_plan = ys::Plan::new([ys::output("value", ys::json_pointer("/value")?.value())?])?;
    assert!(matches!(
        malformed_json.locate(&json_plan),
        ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::ParseFailed { .. }
        }
    ));
    Ok(())
}

fn budget_field(value: &Value) -> Option<String> {
    match value {
        Value::Object(fields) => fields.iter().find_map(|(name, nested)| {
            let normalized = name.to_ascii_lowercase();
            let is_budget = normalized.contains("budget")
                || normalized == "limits"
                || normalized.starts_with("max_")
                || normalized.ends_with("_limit");
            if is_budget {
                Some(name.clone())
            } else {
                budget_field(nested)
            }
        }),
        Value::Array(values) => values.iter().find_map(budget_field),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => None,
    }
}

fn insert_field(object: &mut Value, name: &str, value: Value) -> Result<(), io::Error> {
    let fields = object
        .as_object_mut()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "policy is not an object"))?;
    fields.insert(name.to_owned(), value);
    Ok(())
}
