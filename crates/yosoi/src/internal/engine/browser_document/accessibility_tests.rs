#![allow(clippy::unwrap_used)]

use crate::internal::engine as yosoi_engine;
use crate::internal::types as yosoi_types;

use crate::internal::documents::{ResourceBudget, ResourceBudgetValues};
use crate::internal::types::LossExtent;
use crate::internal::web_capture::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityEvidence,
    BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema, BrowserBudgetScope,
    BrowserByteAccounting, BrowserDocumentEpoch, BrowserDocumentScope, BrowserFrameId,
    BrowserLimitEnforcement,
};
use serde_json::{Value, json};

use super::{AccessibilityNormalizationError, normalize_accessibility};

fn node(
    id: &str,
    parent: Option<&str>,
    children: &[&str],
    role: &str,
    name: Option<&str>,
) -> Value {
    let mut node = json!({
        "nodeId": id,
        "ignored": false,
        "role": { "type": "role", "value": role },
        "childIds": children,
    });
    if let Some(parent) = parent {
        node["parentId"] = json!(parent);
    }
    if let Some(name) = name {
        node["name"] = json!({ "type": "computedString", "value": name });
    }
    node
}

fn budget(
    max_input_bytes: u64,
    max_nodes: u64,
    max_output_bytes: u64,
    max_depth: u32,
) -> ResourceBudget {
    ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes,
        max_selector_visits: 100,
        max_query_bytes: 100,
        max_query_steps: 10,
        max_regions: 10,
        max_matches: 100,
        max_captures: 100,
        max_depth,
        max_output_bytes,
    })
    .unwrap()
}

fn evidence(
    payload: Vec<u8>,
    capture_mode: BrowserAccessibilityCaptureMode,
    requested_depth: Option<i64>,
    nodes_observed: u64,
    nodes_lost: LossExtent,
    bytes_complete: bool,
    bytes_lost: LossExtent,
) -> BrowserAccessibilityEvidence {
    let retained = u64::try_from(payload.len()).unwrap();
    let observed = match bytes_lost {
        LossExtent::Known(lost) => retained.checked_add(lost).unwrap(),
        LossExtent::Unknown => retained,
    };
    let nodes_retained = u64::try_from(
        serde_json::from_slice::<Vec<Value>>(&payload)
            .unwrap()
            .len(),
    )
    .unwrap();
    BrowserAccessibilityEvidence {
        schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
        schema_version: 1,
        capture_mode,
        requested_depth,
        ignored_nodes: BrowserAccessibilityIgnoredNodes::Included,
        scope: BrowserDocumentScope {
            frame: BrowserFrameId(1),
            epoch: BrowserDocumentEpoch(7),
        },
        at: yosoi_types::CaptureOffset::from_microseconds(1),
        nodes_observed,
        nodes_retained,
        nodes_lost,
        bytes: BrowserByteAccounting {
            configured_limit: 1_000_000,
            enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            budget_scope: BrowserBudgetScope::PerPayload,
            observed,
            retained,
            lost: bytes_lost,
            complete: bytes_complete,
        },
        canonical_node_bytes: payload,
    }
}

#[allow(
    clippy::needless_pass_by_value,
    reason = "owned synthetic fixtures keep the focused test call sites readable"
)]
fn complete_evidence(nodes: Value) -> BrowserAccessibilityEvidence {
    let payload = serde_json::to_vec(&nodes).unwrap();
    let count = u64::try_from(nodes.as_array().unwrap().len()).unwrap();
    evidence(
        payload,
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        count,
        LossExtent::Known(0),
        true,
        LossExtent::Known(0),
    )
}

fn document_json(document: &yosoi_engine::Document) -> Value {
    serde_json::from_slice(document.bytes()).unwrap()
}

#[test]
fn normalizes_exact_fields_boolean_states_and_never_control_values_as_text() {
    let mut button = node("button", Some("root"), &[], "button", Some("Open"));
    button["value"] = json!({ "type": "string", "value": "private-control-value" });
    button["properties"] = json!([
        { "name": "expanded", "value": { "type": "boolean", "value": false } },
        { "name": "focused", "value": { "type": "booleanOrUndefined", "value": true } },
        { "name": "checked", "value": { "type": "boolean", "value": true } },
    ]);
    let evidence = complete_evidence(json!([
        node("root", None, &["button"], "RootWebArea", Some("Page")),
        button,
    ]));

    let document =
        normalize_accessibility("page.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap();
    let wire = document_json(&document);
    let nodes = wire.get("nodes").and_then(Value::as_array).unwrap();
    let button = nodes
        .iter()
        .find(|node| node.get("id").and_then(Value::as_str) == Some("button"))
        .unwrap();

    assert_eq!(
        wire.get("schema").and_then(Value::as_str),
        Some("yosoi.accessibility-tree.v1")
    );
    assert_eq!(wire.get("document_epoch").and_then(Value::as_u64), Some(7));
    assert_eq!(button.get("role").and_then(Value::as_str), Some("button"));
    assert_eq!(
        button.get("accessible_name").and_then(Value::as_str),
        Some("Open")
    );
    assert!(button.get("text").is_some_and(Value::is_null));
    assert_eq!(
        button
            .get("states")
            .and_then(|states| states.get("expanded"))
            .and_then(Value::as_bool),
        Some(false)
    );
    assert_eq!(
        button
            .get("states")
            .and_then(|states| states.get("focused"))
            .and_then(Value::as_bool),
        Some(true)
    );
    assert!(
        button
            .get("states")
            .and_then(|states| states.get("checked"))
            .is_none()
    );
    assert!(
        !document
            .bytes()
            .windows(b"private-control-value".len())
            .any(|window| window == b"private-control-value")
    );
}

#[test]
fn exact_duplicate_cdp_nodes_are_canonicalized_without_semantic_loss() {
    let root = node("root", None, &["button"], "RootWebArea", Some("Page"));
    let evidence = complete_evidence(json!([
        root.clone(),
        root,
        node("button", Some("root"), &[], "button", Some("Open")),
    ]));

    let document =
        normalize_accessibility("duplicate.ax", evidence, budget(100_000, 20, 100_000, 10))
            .unwrap();
    let wire = document_json(&document);
    assert_eq!(
        wire.get("nodes").and_then(Value::as_array).map(Vec::len),
        Some(2)
    );
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("complete")
    );
}

#[test]
fn conflicting_duplicate_cdp_nodes_remain_invalid() {
    let evidence = complete_evidence(json!([
        node("root", None, &[], "RootWebArea", Some("First")),
        node("root", None, &[], "RootWebArea", Some("Second")),
    ]));

    assert_eq!(
        normalize_accessibility("conflict.ax", evidence, budget(100_000, 20, 100_000, 10))
            .unwrap_err(),
        AccessibilityNormalizationError::InvalidTreeGraph
    );
}

#[test]
fn partial_prefix_prunes_dangling_edges_and_orphans_with_checked_loss() {
    let nodes = json!([
        node("root", None, &["kept", "omitted"], "RootWebArea", None),
        node("kept", Some("root"), &[], "button", Some("Keep")),
        node(
            "orphan",
            Some("missing-parent"),
            &[],
            "button",
            Some("Drop")
        ),
    ]);
    let payload = serde_json::to_vec(&nodes).unwrap();
    let evidence = evidence(
        payload,
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        4,
        LossExtent::Known(1),
        false,
        LossExtent::Known(3),
    );

    let document =
        normalize_accessibility("partial.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap();
    let wire = document_json(&document);
    let nodes = wire.get("nodes").and_then(Value::as_array).unwrap();
    let root = nodes
        .iter()
        .find(|node| node.get("id").and_then(Value::as_str) == Some("root"))
        .unwrap();

    assert_eq!(nodes.len(), 2);
    assert_eq!(
        root.get("children").and_then(Value::as_array),
        Some(&vec![json!("kept")])
    );
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("partial")
    );
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("lost_items"))
            .and_then(Value::as_u64),
        Some(2)
    );
}

#[test]
fn depth_limited_capture_is_partial_even_when_its_retained_bytes_are_complete() {
    let evidence = evidence(
        serde_json::to_vec(&json!([node("root", None, &[], "RootWebArea", None)])).unwrap(),
        BrowserAccessibilityCaptureMode::DepthLimited,
        Some(2),
        1,
        LossExtent::Known(0),
        true,
        LossExtent::Known(0),
    );
    let document =
        normalize_accessibility("depth.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap();
    let wire = document_json(&document);

    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("partial")
    );
    assert!(
        wire.get("completeness")
            .and_then(|value| value.get("lost_items"))
            .and_then(Value::as_u64)
            .is_none()
    );
}

#[test]
fn complete_capture_rejects_dangling_child_edges() {
    let evidence = complete_evidence(json!([node(
        "root",
        None,
        &["missing"],
        "RootWebArea",
        None
    )]));

    assert_eq!(
        normalize_accessibility("bad.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap_err(),
        AccessibilityNormalizationError::InvalidTreeGraph
    );
}

#[test]
fn node_loss_is_independent_of_byte_completeness() {
    let nodes = json!([node("root", None, &["omitted"], "RootWebArea", None)]);
    let evidence = evidence(
        serde_json::to_vec(&nodes).unwrap(),
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        2,
        LossExtent::Known(1),
        true,
        LossExtent::Known(0),
    );

    let document =
        normalize_accessibility("node-loss.ax", evidence, budget(100_000, 20, 100_000, 10))
            .unwrap();
    let wire = document_json(&document);
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("partial")
    );
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("lost_items"))
            .and_then(Value::as_u64),
        Some(1)
    );
}

#[test]
fn known_byte_loss_is_partial_without_inventing_a_node_count() {
    let nodes = json!([node("root", None, &[], "RootWebArea", None)]);
    let evidence = evidence(
        serde_json::to_vec(&nodes).unwrap(),
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        1,
        LossExtent::Known(0),
        false,
        LossExtent::Known(2),
    );

    let document =
        normalize_accessibility("byte-loss.ax", evidence, budget(100_000, 20, 100_000, 10))
            .unwrap();
    let wire = document_json(&document);
    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("partial")
    );
    assert!(
        wire.get("completeness")
            .and_then(|value| value.get("lost_items"))
            .and_then(Value::as_u64)
            .is_none()
    );
}

#[test]
fn does_not_fall_back_to_chrome_role() {
    let mut raw = json!({
        "nodeId": "root",
        "ignored": false,
        "chromeRole": { "type": "internalRole", "value": "RootWebArea" },
        "childIds": [],
    });
    raw["name"] = json!({ "type": "computedString", "value": "Page" });
    let evidence = complete_evidence(json!([raw]));

    assert_eq!(
        normalize_accessibility("no-fallback.ax", evidence, budget(100_000, 20, 100_000, 10))
            .unwrap_err(),
        AccessibilityNormalizationError::MissingRole
    );
}

#[test]
fn rejects_wrong_schema_epoch_and_ax_type_without_echoing_payload() {
    let mut wrong_version =
        complete_evidence(json!([node("root", None, &[], "RootWebArea", None)]));
    wrong_version.schema_version = 2;
    assert_eq!(
        normalize_accessibility("bad.ax", wrong_version, budget(100_000, 20, 100_000, 10))
            .unwrap_err(),
        AccessibilityNormalizationError::UnsupportedSchemaVersion
    );

    let mut zero_epoch = complete_evidence(json!([node("root", None, &[], "RootWebArea", None)]));
    zero_epoch.scope.epoch = BrowserDocumentEpoch(0);
    assert_eq!(
        normalize_accessibility("bad.ax", zero_epoch, budget(100_000, 20, 100_000, 10))
            .unwrap_err(),
        AccessibilityNormalizationError::InvalidEpoch
    );

    let mut wrong_role_type = node("root", None, &[], "RootWebArea", None);
    wrong_role_type["role"]["type"] = json!("computedString");
    let payload = serde_json::to_vec(&json!([wrong_role_type])).unwrap();
    let evidence = evidence(
        payload,
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        1,
        LossExtent::Known(0),
        true,
        LossExtent::Known(0),
    );
    let error =
        normalize_accessibility("bad.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap_err();
    assert_eq!(error, AccessibilityNormalizationError::InvalidRole);
    assert!(!format!("{error:?}").contains("RootWebArea"));
}

#[test]
fn enforces_input_node_output_and_depth_budgets() {
    let tree = json!([
        node("root", None, &["child"], "RootWebArea", None),
        node("child", Some("root"), &[], "button", None),
    ]);
    let raw = serde_json::to_vec(&tree).unwrap();

    assert_eq!(
        normalize_accessibility(
            "limited.ax",
            complete_evidence(tree.clone()),
            budget(1, 20, 100_000, 10),
        )
        .unwrap_err(),
        AccessibilityNormalizationError::InputLimitExceeded
    );
    assert_eq!(
        normalize_accessibility(
            "limited.ax",
            complete_evidence(tree.clone()),
            budget(100_000, 1, 100_000, 10),
        )
        .unwrap_err(),
        AccessibilityNormalizationError::NodeLimitExceeded
    );
    assert_eq!(
        normalize_accessibility(
            "limited.ax",
            complete_evidence(tree.clone()),
            budget(100_000, 20, 1, 10),
        )
        .unwrap_err(),
        AccessibilityNormalizationError::OutputLimitExceeded
    );
    assert_eq!(
        normalize_accessibility(
            "limited.ax",
            complete_evidence(tree),
            budget(u64::try_from(raw.len()).unwrap(), 20, 100_000, 1),
        )
        .unwrap_err(),
        AccessibilityNormalizationError::InvalidNormalizedDocument
    );
}

#[test]
fn unknown_loss_stays_unknown_when_partial_prefix_edges_are_pruned() {
    let nodes = json!([node("root", None, &["missing"], "RootWebArea", None),]);
    let evidence = evidence(
        serde_json::to_vec(&nodes).unwrap(),
        BrowserAccessibilityCaptureMode::FullTree,
        None,
        2,
        LossExtent::Unknown,
        false,
        LossExtent::Unknown,
    );
    let document =
        normalize_accessibility("unknown.ax", evidence, budget(100_000, 20, 100_000, 10)).unwrap();
    let wire = document_json(&document);

    assert_eq!(
        wire.get("completeness")
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str),
        Some("unknown")
    );
}
