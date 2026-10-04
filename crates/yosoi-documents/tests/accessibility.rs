#![allow(
    clippy::absolute_paths,
    clippy::manual_let_else,
    clippy::panic_in_result_fn
)] // Conformance tests favor explicit fixture paths and typed fallible setup.

use std::{error::Error, fs, io, path::Path};

use yosoi_documents::{
    AccessibilityCompleteness, AccessibilityCoordinate, AccessibilityParseError,
    AccessibilityStateName, Completeness, Document, DocumentClass, DocumentEpoch, DocumentProfile,
    Finding, LocateFailure, LocateOutcome, NativeCoordinate, NodeReference, OutputPlan, Plan,
    ProjectedValue, ResourceBudget, ResourceBudgetValues, ResourceLimit, accessibility_state,
    accessibility_text, accessible_name, output, role,
};

const GOLDEN_AX: &[u8] = include_bytes!(
    "../../../benchmarks/fixtures/document-locators/v1/golden/accessibility-tree.json"
);

fn document(bytes: &[u8], epoch: u64) -> Result<Document, Box<dyn Error>> {
    let epoch = DocumentEpoch::try_from(epoch)?;
    Ok(Document::accessibility_tree(
        "products.ax",
        epoch,
        bytes.to_vec(),
    )?)
}

fn outcome_for(document: &Document, value: OutputPlan) -> Result<LocateOutcome, Box<dyn Error>> {
    let plan = Plan::new([output("ax_result", value)?])?;
    Ok(document.locate(&plan))
}

fn limits_with(max_matches: u64, max_depth: u32) -> Result<ResourceBudget, Box<dyn Error>> {
    let conservative = ResourceBudget::conservative();
    limits_with_budgets(
        max_matches,
        max_depth,
        conservative.max_nodes(),
        conservative.max_selector_visits(),
    )
}

fn limits_with_budgets(
    max_matches: u64,
    max_depth: u32,
    max_nodes: u64,
    max_selector_visits: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    let conservative = ResourceBudget::conservative();
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: conservative.max_input_bytes(),
        max_nodes,
        max_selector_visits,
        max_query_bytes: conservative.max_query_bytes(),
        max_query_steps: conservative.max_query_steps(),
        max_regions: conservative.max_regions(),
        max_matches,
        max_captures: conservative.max_captures(),
        max_depth,
        max_output_bytes: conservative.max_output_bytes(),
    })?)
}

#[test]
fn parses_the_provider_neutral_v1_schema_and_retains_completeness() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let parsed = yosoi_documents::ParsedAccessibilityDocument::parse(
        &document,
        ResourceBudget::conservative(),
    )?;

    assert_eq!(document.class(), DocumentClass::AccessibilityTree);
    assert_eq!(parsed.document_epoch(), DocumentEpoch::try_from(1)?);
    assert_eq!(parsed.node_count(), 2);
    assert_eq!(parsed.max_depth(), 2);
    assert_eq!(parsed.completeness(), &AccessibilityCompleteness::Complete);
    Ok(())
}

#[test]
fn node_limits_apply_during_parse_and_locate() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let small_budget = limits_with_budgets(100, 1_024, 1, 1_000)?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(&document, small_budget,),
        Err(AccessibilityParseError::NodeCountLimitExceeded {
            maximum: 1,
            observed: 2,
        })
    ));

    let plan = Plan::new([output("missing", role("missing")?.node())?])?;
    assert!(matches!(
        document.locate_with_budget(&plan, small_budget),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum: 1,
                observed: 2,
            }
        }
    ));
    Ok(())
}

#[test]
fn selector_visit_budget_is_shared_across_accessibility_outputs() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let plan = Plan::new([
        output("first", role("missing")?.node())?,
        output("second", role("missing")?.node())?,
    ])?;

    assert!(matches!(
        document.locate_with_budget(&plan, limits_with_budgets(100, 1_024, 1_000, 2)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 2,
                observed: 3,
            }
        }
    ));
    Ok(())
}

#[test]
fn node_references_bind_document_epoch_and_stable_ax_id() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let outcome = outcome_for(&document, role("button")?.node())?;
    let LocateOutcome::Matched { result } = outcome else {
        return Err(io::Error::other("button role should match").into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| io::Error::other("matched result has no finding"))?;
    let expected_coordinate = NativeCoordinate::Accessibility(AccessibilityCoordinate::try_new(
        DocumentEpoch::try_from(1)?,
        "ax-2",
    )?);

    assert_eq!(finding.coordinate(), &expected_coordinate);
    assert_eq!(
        finding.value(),
        &ProjectedValue::Node(NodeReference::new(
            document.id().clone(),
            expected_coordinate,
        ))
    );
    let NativeCoordinate::Accessibility(coordinate) = finding.coordinate() else {
        return Err(io::Error::other("AX finding used a non-AX coordinate").into());
    };
    assert_eq!(coordinate.document_epoch(), DocumentEpoch::try_from(1)?);
    assert_eq!(coordinate.node_id(), "ax-2");
    Ok(())
}

#[test]
fn accessible_name_and_text_queries_are_distinct_exact_matches() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let name = outcome_for(&document, accessible_name("Products")?.name())?;
    let LocateOutcome::Matched { result } = name else {
        return Err(io::Error::other("exact accessible name should match").into());
    };
    let name_finding = result
        .findings()
        .first()
        .ok_or_else(|| io::Error::other("accessible-name result has no finding"))?;
    assert_eq!(
        name_finding.value(),
        &ProjectedValue::Text("Products".to_owned())
    );

    let text = outcome_for(&document, accessibility_text("Products")?.text())?;
    assert!(matches!(text, LocateOutcome::NoMatch { .. }));

    let button_text = outcome_for(&document, accessibility_text("Buy now")?.text())?;
    let LocateOutcome::Matched { result } = button_text else {
        return Err(io::Error::other("exact AX text should match").into());
    };
    let text_finding = result
        .findings()
        .first()
        .ok_or_else(|| io::Error::other("AX text result has no finding"))?;
    assert_eq!(
        text_finding.value(),
        &ProjectedValue::Text("Buy now".to_owned())
    );
    Ok(())
}

#[test]
fn state_queries_compare_only_the_supported_boolean_value() -> Result<(), Box<dyn Error>> {
    let golden_document = document(GOLDEN_AX, 1)?;
    let expanded = outcome_for(
        &golden_document,
        accessibility_state(AccessibilityStateName::Expanded, true).node(),
    )?;
    assert!(matches!(expanded, LocateOutcome::Matched { .. }));

    let collapsed = outcome_for(
        &golden_document,
        accessibility_state(AccessibilityStateName::Expanded, false).node(),
    )?;
    assert!(matches!(collapsed, LocateOutcome::NoMatch { .. }));

    let upper_case_role = outcome_for(&golden_document, role("Button")?.node())?;
    assert!(matches!(upper_case_role, LocateOutcome::NoMatch { .. }));

    let focused_payload = br#"{
        "schema":"yosoi.accessibility-tree.v1",
        "document_epoch":3,
        "root":"root",
        "completeness":{"status":"complete"},
        "nodes":[{
            "id":"root","parent":null,"children":[],"ignored":false,
            "role":"button","accessible_name":"Save","text":"Save",
            "states":{"focused":true}
        }]
    }"#;
    let focused_document = document(focused_payload, 3)?;
    let focused = outcome_for(
        &focused_document,
        accessibility_state(AccessibilityStateName::Focused, true).node(),
    )?;
    assert!(matches!(focused, LocateOutcome::Matched { .. }));
    Ok(())
}

#[test]
fn ignored_nodes_and_absent_text_are_not_silently_projected() -> Result<(), Box<dyn Error>> {
    let bytes = br#"{
        "schema":"yosoi.accessibility-tree.v1","document_epoch":4,"root":"root",
        "completeness":{"status":"complete"},"nodes":[
            {"id":"root","parent":null,"children":["hidden","visible"],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}},
            {"id":"hidden","parent":"root","children":[],"ignored":true,"role":"button","accessible_name":"Hidden","text":"Hidden","states":{}},
            {"id":"visible","parent":"root","children":[],"ignored":false,"role":"button","accessible_name":null,"text":null,"states":{}}
        ]
    }"#;
    let document = document(bytes, 4)?;
    let buttons = outcome_for(&document, role("button")?.node())?;
    let LocateOutcome::Matched { result } = buttons else {
        return Err(io::Error::other("visible button should match").into());
    };
    let ids = result
        .findings()
        .iter()
        .filter_map(|finding| match finding.coordinate() {
            NativeCoordinate::Accessibility(coordinate) => Some(coordinate.node_id()),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(ids, vec!["visible"]);

    let ignored_name = outcome_for(&document, accessible_name("Hidden")?.name())?;
    assert!(matches!(ignored_name, LocateOutcome::NoMatch { .. }));

    let absent_text = outcome_for(&document, accessibility_text("Hidden")?.text())?;
    assert!(matches!(absent_text, LocateOutcome::NoMatch { .. }));
    Ok(())
}

#[test]
fn tree_preorder_is_stable_and_match_limits_are_enforced() -> Result<(), Box<dyn Error>> {
    let bytes = br#"{
        "schema":"yosoi.accessibility-tree.v1","document_epoch":5,"root":"root",
        "completeness":{"status":"complete"},"nodes":[
            {"id":"second","parent":"root","children":[],"ignored":false,"role":"button","accessible_name":"Second","text":"Second","states":{}},
            {"id":"first","parent":"root","children":[],"ignored":false,"role":"button","accessible_name":"First","text":"First","states":{}},
            {"id":"root","parent":null,"children":["first","second"],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}}
        ]
    }"#;
    let document = document(bytes, 5)?;
    let plan = Plan::new([output("buttons", role("button")?.node())?])?;
    let outcome = document.locate(&plan);
    let LocateOutcome::Matched { result } = outcome else {
        return Err(io::Error::other("buttons should match").into());
    };
    let ids = result
        .findings()
        .iter()
        .filter_map(|finding| match finding.coordinate() {
            NativeCoordinate::Accessibility(coordinate) => Some(coordinate.node_id()),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(ids, vec!["first", "second"]);

    let limited_budget = limits_with(1, 1_024)?;
    assert!(matches!(
        document.locate_with_budget(&plan, limited_budget),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    ));
    Ok(())
}

#[test]
fn unknown_completeness_prevents_a_false_no_match_claim() -> Result<(), Box<dyn Error>> {
    let partial_bytes = br#"{
        "schema":"yosoi.accessibility-tree.v1",
        "document_epoch":2,
        "root":"root",
        "completeness":{"status":"unknown","reason_code":"capture_completeness_unverified"},
        "nodes":[{
            "id":"root","parent":null,"children":[],"ignored":false,
            "role":"document","accessible_name":null,"text":null,"states":{}
        }]
    }"#;
    let document = document(partial_bytes, 2)?;
    let outcome = outcome_for(&document, role("button")?.node())?;
    assert!(matches!(
        outcome,
        LocateOutcome::Indeterminate {
            completeness: yosoi_documents::IncompleteEvidence::Unknown { .. },
            ..
        }
    ));
    Ok(())
}

#[test]
fn parser_rejects_schema_epoch_duplicate_id_and_cycle_errors() -> Result<(), Box<dyn Error>> {
    let wrong_schema = br#"{
        "schema":"provider.raw.v1","document_epoch":1,"root":"root",
        "completeness":{"status":"complete"},"nodes":[]
    }"#;
    let wrong_schema_document = document(wrong_schema, 1)?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(
            &wrong_schema_document,
            ResourceBudget::conservative()
        ),
        Err(AccessibilityParseError::UnsupportedSchema)
    ));

    let epoch_mismatch = document(GOLDEN_AX, 2)?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(
            &epoch_mismatch,
            ResourceBudget::conservative()
        ),
        Err(AccessibilityParseError::EpochMismatch)
    ));

    let duplicate_id = br#"{
        "schema":"yosoi.accessibility-tree.v1","document_epoch":1,"root":"root",
        "completeness":{"status":"complete"},"nodes":[
            {"id":"root","parent":null,"children":[],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}},
            {"id":"root","parent":null,"children":[],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}}
        ]
    }"#;
    let duplicate_document = document(duplicate_id, 1)?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(
            &duplicate_document,
            ResourceBudget::conservative()
        ),
        Err(AccessibilityParseError::DuplicateNodeId)
    ));

    let cycle = br#"{
        "schema":"yosoi.accessibility-tree.v1","document_epoch":1,"root":"root",
        "completeness":{"status":"complete"},"nodes":[
            {"id":"root","parent":null,"children":[],"ignored":false,"role":"document","accessible_name":null,"text":null,"states":{}},
            {"id":"a","parent":"b","children":["b"],"ignored":false,"role":"generic","accessible_name":null,"text":null,"states":{}},
            {"id":"b","parent":"a","children":["a"],"ignored":false,"role":"generic","accessible_name":null,"text":null,"states":{}}
        ]
    }"#;
    let cyclic_document = document(cycle, 1)?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(
            &cyclic_document,
            ResourceBudget::conservative()
        ),
        Err(AccessibilityParseError::Cycle)
    ));
    Ok(())
}

#[test]
fn mismatched_profile_axes_cannot_claim_a_static_ax_schema() {
    assert!(
        DocumentProfile::try_new(
            yosoi_documents::DocumentRepresentation::AccessibilityTree,
            yosoi_documents::SourceFormat::Json,
            yosoi_documents::DocumentSchemaProfile::YosoiAccessibilityTreeV1,
            None,
        )
        .is_err()
    );
}

#[test]
fn parsed_tree_honors_a_lower_depth_limit() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let conservative = ResourceBudget::conservative();
    let limits = yosoi_documents::ResourceBudget::try_new(yosoi_documents::ResourceBudgetValues {
        max_input_bytes: conservative.max_input_bytes(),
        max_nodes: conservative.max_nodes(),
        max_selector_visits: conservative.max_selector_visits(),
        max_query_bytes: conservative.max_query_bytes(),
        max_query_steps: conservative.max_query_steps(),
        max_regions: conservative.max_regions(),
        max_matches: conservative.max_matches(),
        max_captures: conservative.max_captures(),
        max_depth: 1,
        max_output_bytes: conservative.max_output_bytes(),
    })?;
    assert!(matches!(
        yosoi_documents::ParsedAccessibilityDocument::parse(&document, limits),
        Err(AccessibilityParseError::DepthLimitExceeded {
            maximum: 1,
            observed: 2
        })
    ));
    Ok(())
}

#[test]
#[ignore = "opt-in: set CAS391_ADVANCED_AX_FIXTURE to a verified materialized AX v1 file"]
fn advanced_wcag_ax_locators_match_locked_matrix_oracles() -> Result<(), Box<dyn Error>> {
    let fixture_path = std::env::var_os("CAS391_ADVANCED_AX_FIXTURE")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| io::Error::other("CAS391_ADVANCED_AX_FIXTURE is required"))?;
    let fixture_bytes = fs::read(fixture_path)?;
    let epoch = DocumentEpoch::try_from(2)?;
    let document = Document::accessibility_tree("advanced-wcag.ax", epoch, fixture_bytes)?;

    let repository = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let matrix_path = repository.join("benchmarks/fixtures/document-locators/v1/matrix.json");
    let matrix: serde_json::Value = serde_json::from_slice(&fs::read(matrix_path)?)?;
    let cases = vec![
        ("ax_role", role("link")?.node()),
        (
            "ax_name",
            accessible_name("Web Content Accessibility Guidelines (WCAG) 2.2")?.name(),
        ),
        (
            "ax_text",
            accessibility_text("Web Content Accessibility Guidelines (WCAG) 2.2")?.text(),
        ),
        (
            "ax_state",
            accessibility_state(AccessibilityStateName::Focused, true).node(),
        ),
    ];

    for (case_id, value) in cases {
        let plan = Plan::new([output(case_id, value)?])?;
        let expected_case = advanced_case(&matrix, case_id)?;
        let expected = expected_case
            .get("expected")
            .ok_or_else(|| io::Error::other("advanced matrix case has no expected value"))?;
        let expected_completeness = expected
            .get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| io::Error::other("AX oracle has no completeness status"))?;
        assert_eq!(expected_completeness, "unknown");
        let expected_matches = expected
            .get("matches")
            .and_then(serde_json::Value::as_array)
            .ok_or_else(|| io::Error::other("AX oracle has no match list"))?;
        let expected_count = expected
            .get("match_count")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| io::Error::other("AX oracle has no match count"))?;
        assert_eq!(expected_count, u64::try_from(expected_matches.len())?);

        let outcome = document.locate(&plan);
        let LocateOutcome::Matched { result } = outcome else {
            return Err(io::Error::other(format!(
                "locked AX case {case_id} did not return matches"
            ))
            .into());
        };
        assert_eq!(result.findings().len(), expected_matches.len());
        for (finding, expected_match) in result.findings().iter().zip(expected_matches) {
            assert_locked_ax_finding(finding, expected_match)?;
        }
    }
    Ok(())
}

fn advanced_case<'a>(
    matrix: &'a serde_json::Value,
    case_id: &str,
) -> Result<&'a serde_json::Value, io::Error> {
    let cases = matrix
        .get("advanced_cases")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| io::Error::other("matrix has no advanced cases"))?;
    cases
        .iter()
        .find(|candidate| candidate.get("id").and_then(serde_json::Value::as_str) == Some(case_id))
        .ok_or_else(|| io::Error::other(format!("matrix has no {case_id} case")))
}

fn assert_locked_ax_finding(
    finding: &Finding,
    expected: &serde_json::Value,
) -> Result<(), Box<dyn Error>> {
    let expected_coordinate = expected
        .get("coordinate")
        .ok_or_else(|| io::Error::other("matrix match has no coordinate"))?;
    let expected_epoch = expected_coordinate
        .get("document_epoch")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| io::Error::other("matrix coordinate has no epoch"))?;
    let expected_node_id = expected_coordinate
        .get("node_id")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| io::Error::other("matrix coordinate has no node ID"))?;
    assert_eq!(
        expected_coordinate
            .get("kind")
            .and_then(serde_json::Value::as_str),
        Some("document_node")
    );

    let coordinate = match finding.coordinate() {
        NativeCoordinate::Accessibility(coordinate) => coordinate,
        _ => return Err(io::Error::other("AX oracle finding has a non-AX coordinate").into()),
    };
    assert_eq!(coordinate.document_epoch().get(), expected_epoch);
    assert_eq!(coordinate.node_id(), expected_node_id);

    let expected_value = expected
        .get("value")
        .ok_or_else(|| io::Error::other("matrix match has no projected value"))?;
    let actual_value = match finding.value() {
        ProjectedValue::Node(reference) => {
            assert_eq!(reference.document_id().as_str(), "advanced-wcag.ax");
            let NativeCoordinate::Accessibility(coordinate) = reference.coordinate() else {
                return Err(io::Error::other("AX node reference has a non-AX coordinate").into());
            };
            serde_json::json!({
                "document_epoch": coordinate.document_epoch().get(),
                "node_id": coordinate.node_id(),
            })
        }
        ProjectedValue::Text(value) => serde_json::Value::String(value.clone()),
        ProjectedValue::Attribute { .. }
        | ProjectedValue::Json(_)
        | ProjectedValue::TextWithCaptures { .. } => {
            return Err(io::Error::other("AX oracle returned an incompatible projection").into());
        }
    };
    assert_eq!(&actual_value, expected_value);
    assert!(matches!(
        finding.completeness(),
        Completeness::Unknown { reason_code }
            if reason_code == "capture_completeness_unverified"
    ));
    Ok(())
}

#[test]
fn successful_findings_preserve_tree_completeness() -> Result<(), Box<dyn Error>> {
    let document = document(GOLDEN_AX, 1)?;
    let outcome = outcome_for(&document, role("button")?.node())?;
    let LocateOutcome::Matched { result } = outcome else {
        return Err(io::Error::other("button role should match").into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| io::Error::other("matched result has no finding"))?;
    assert_eq!(finding.completeness(), &Completeness::Complete);
    Ok(())
}
