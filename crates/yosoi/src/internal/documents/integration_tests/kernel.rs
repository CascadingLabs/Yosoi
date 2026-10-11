#![allow(clippy::absolute_paths, clippy::panic_in_result_fn)] // Conformance tests use explicit standard errors and direct assertions.

use crate::internal::documents::{
    Completeness, Document, DocumentClass, DocumentEpoch, DocumentId, DocumentProfile,
    DocumentRepresentation, DocumentSchemaProfile, DomCoordinate, DomNodeId, Finding, FindingError,
    IncompleteEvidence, JsonCoordinate, LocateFailure, LocateOutcome, LocateResult,
    LocateResultError, NativeCoordinate, NodeReference, OutputId, Plan, PlanError, ProjectedValue,
    QueryAtom, QueryResultShape, QuerySpec, RegionId, RegionLineage, ResourceBudget,
    ResourceBudgetValues, ResourceLimit, SourceFormat, css, json_pointer, output, regex,
};

#[test]
fn document_profiles_keep_axes_and_require_epochs() -> Result<(), Box<dyn std::error::Error>> {
    let epoch = DocumentEpoch::try_from(7)?;
    let dom = DocumentProfile::rendered_dom(epoch);
    assert_eq!(dom.representation(), DocumentRepresentation::RenderedDom);
    assert_eq!(dom.source_format(), SourceFormat::Json);
    assert_eq!(dom.schema(), DocumentSchemaProfile::YosoiRenderedDomV1);
    assert_eq!(dom.epoch(), Some(epoch));
    assert_eq!(dom.class()?, DocumentClass::RenderedDom);

    let invalid = DocumentProfile::try_new(
        DocumentRepresentation::RenderedDom,
        SourceFormat::Json,
        DocumentSchemaProfile::YosoiRenderedDomV1,
        None,
    );
    assert!(invalid.is_err());
    assert!(DocumentEpoch::try_from(0).is_err());
    Ok(())
}

#[test]
fn invalid_profile_cannot_enter_through_deserialization() {
    let wire = r#"{
        "representation":"source",
        "source_format":"json",
        "schema":"html5",
        "epoch":null
    }"#;
    assert!(serde_json::from_str::<DocumentProfile>(wire).is_err());
}

#[test]
fn plan_construction_derives_one_tree_document_requirement()
-> Result<(), Box<dyn std::error::Error>> {
    let products = css("article.product")?.each_as_region("product")?;
    let plan = Plan::new([
        output("authors", products.find(css(".author")?).text())?,
        output("prices", products.find(css(".price")?).text())?,
    ])?;

    let wire = serde_json::to_value(&plan)?;
    assert_eq!(
        wire.get("regions")
            .and_then(serde_json::Value::as_array)
            .map(Vec::len),
        Some(1)
    );
    assert_eq!(
        wire.get("outputs")
            .and_then(serde_json::Value::as_array)
            .map(Vec::len),
        Some(2)
    );
    assert_eq!(
        wire.pointer("/requirement/accepted_documents"),
        Some(&serde_json::json!([
            "source_html",
            "source_xml",
            "rendered_dom"
        ]))
    );
    assert!(
        wire.get("outputs")
            .and_then(serde_json::Value::as_array)
            .is_some_and(|outputs| outputs.iter().all(|output| {
                output
                    .get("parent_region")
                    .is_some_and(|region| !region.is_null())
            }))
    );

    let wire = serde_json::to_vec(&plan)?;
    let round_trip: crate::internal::documents::Plan = serde_json::from_slice(&wire)?;
    assert_eq!(plan, round_trip);
    Ok(())
}

#[test]
fn deserialization_rejects_a_forged_compiled_requirement() -> Result<(), Box<dyn std::error::Error>>
{
    let plan = Plan::new([output("title", css("title")?.text())?])?;
    let mut wire = serde_json::to_value(plan)?;
    let accepted_documents = wire
        .get_mut("requirement")
        .and_then(|requirement| requirement.get_mut("accepted_documents"))
        .ok_or("compiled requirement missing from serialized plan")?;
    *accepted_documents = serde_json::json!(["source_json"]);
    assert!(serde_json::from_value::<crate::internal::documents::Plan>(wire).is_err());
    Ok(())
}

#[test]
fn mixed_document_plan_is_rejected_during_authoring() -> Result<(), Box<dyn std::error::Error>> {
    let result = Plan::new([
        output("title", css("title")?.text())?,
        output("currency", json_pointer("/currency")?.value())?,
    ]);
    assert_eq!(result, Err(PlanError::NoCommonDocument));
    Ok(())
}

#[test]
fn atom_shape_projection_is_validated_as_one_combination() -> Result<(), Box<dyn std::error::Error>>
{
    let malformed = QuerySpec::new(
        QueryAtom::Css(".price".to_owned()),
        QueryResultShape::JsonValues,
    );
    let result = Plan::new([output("price", malformed.value())?]);
    assert!(matches!(result, Err(PlanError::InvalidCombination { .. })));
    Ok(())
}

#[test]
fn text_semantics_are_not_shared_with_tree_or_ax() -> Result<(), Box<dyn std::error::Error>> {
    let plan = Plan::new([output("orders", regex(r"Order\s+#\d+")?.text())?])?;
    assert_eq!(
        serde_json::to_value(plan)?.pointer("/requirement/accepted_documents"),
        Some(&serde_json::json!(["source_text"]))
    );
    Ok(())
}

#[test]
fn concrete_document_owns_compatibility_and_input_limit() -> Result<(), Box<dyn std::error::Error>>
{
    let json_plan = Plan::new([output("currency", json_pointer("/currency")?.value())?])?;
    let html = Document::html("page.html", b"<p>USD</p>".to_vec())?;
    assert!(matches!(
        html.locate(&json_plan),
        LocateOutcome::Failed {
            failure: LocateFailure::UnsupportedCombination {
                document: DocumentClass::SourceHtml
            }
        }
    ));

    let tiny_limits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1,
        max_nodes: 10,
        max_selector_visits: 10,
        max_query_bytes: 100,
        max_query_steps: 10,
        max_regions: 10,
        max_matches: 10,
        max_captures: 10,
        max_depth: 10,
        max_output_bytes: 100,
    })?;
    let tiny_plan = Plan::new([output("currency", json_pointer("/currency")?.value())?])?;
    let json = Document::json("page.json", br#"{"currency":"USD"}"#.to_vec())?;
    assert!(matches!(
        json.locate_with_budget(&tiny_plan, tiny_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                ..
            }
        }
    ));
    Ok(())
}

#[test]
fn every_limit_is_checked_and_conservative_values_keep_fixed_width() {
    let invalid = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1,
        max_nodes: 1,
        max_selector_visits: 1,
        max_query_bytes: 1,
        max_query_steps: 0,
        max_regions: 1,
        max_matches: 1,
        max_captures: 1,
        max_depth: 1,
        max_output_bytes: 1,
    });
    assert!(invalid.is_err_and(|error| error.limit == ResourceLimit::QuerySteps));

    let zero_selector_visits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1,
        max_nodes: 1,
        max_selector_visits: 0,
        max_query_bytes: 1,
        max_query_steps: 1,
        max_regions: 1,
        max_matches: 1,
        max_captures: 1,
        max_depth: 1,
        max_output_bytes: 1,
    });
    assert!(zero_selector_visits.is_err_and(|error| error.limit == ResourceLimit::SelectorVisits));

    let limits = ResourceBudget::conservative();
    let fixed_width_values: (u64, u64, u64, u64, u32, u32, u64, u64, u32, u64) = (
        limits.max_input_bytes(),
        limits.max_nodes(),
        limits.max_selector_visits(),
        limits.max_query_bytes(),
        limits.max_query_steps(),
        limits.max_regions(),
        limits.max_matches(),
        limits.max_captures(),
        limits.max_depth(),
        limits.max_output_bytes(),
    );
    assert_eq!(
        fixed_width_values,
        (
            67_108_864, 1_000_000, 10_000_000, 65_536, 256, 64, 100_000, 16_384, 1_024, 16_777_216,
        )
    );
}

#[test]
fn no_match_indeterminate_and_failure_are_distinct_serializable_outcomes()
-> Result<(), Box<dyn std::error::Error>> {
    let document = Document::text("orders.txt", b"no orders".to_vec())?;
    let no_match = LocateOutcome::NoMatch {
        document_id: document.id().clone(),
    };
    let indeterminate = LocateOutcome::Indeterminate {
        document_id: document.id().clone(),
        completeness: IncompleteEvidence::Partial {
            reason_code: "truncated".to_owned(),
            lost_items: None,
        },
        reason_code: "absence_not_provable".to_owned(),
    };
    let failed = LocateOutcome::Failed {
        failure: LocateFailure::ParseFailed {
            code: "invalid_utf8".to_owned(),
        },
    };

    assert_ne!(
        serde_json::to_value(no_match)?,
        serde_json::to_value(indeterminate)?
    );
    assert_ne!(
        serde_json::to_value(failed)?,
        serde_json::json!({"status":"no_match"})
    );
    Ok(())
}

#[test]
fn matched_region_membership_is_validated_and_round_trips_without_findings()
-> Result<(), Box<dyn std::error::Error>> {
    let document = DocumentId::try_new("empty-root")?;
    let region = RegionLineage::new(
        RegionId::try_new("product")?,
        0,
        NativeCoordinate::Json(JsonCoordinate::try_new("/products/0")?),
    );
    let result =
        LocateResult::try_new_with_regions(document.clone(), vec![region.clone()], Vec::new())?;
    assert_eq!(result.regions(), std::slice::from_ref(&region));
    assert_eq!(result.findings().len(), 0);
    let encoded = serde_json::to_vec(&result)?;
    assert_eq!(serde_json::from_slice::<LocateResult>(&encoded)?, result);

    assert_eq!(
        LocateResult::try_new_with_regions(
            document.clone(),
            vec![region.clone(), region.clone()],
            Vec::new(),
        ),
        Err(LocateResultError::DuplicateRegion)
    );
    let finding = Finding::try_new(
        document.clone(),
        OutputId::try_new("name")?,
        0,
        NativeCoordinate::Json(JsonCoordinate::try_new("/products/1/name")?),
        ProjectedValue::Text("Tea".into()),
        Completeness::Complete,
        Some(RegionLineage::new(
            RegionId::try_new("product")?,
            1,
            NativeCoordinate::Json(JsonCoordinate::try_new("/products/1")?),
        )),
    )?;
    assert_eq!(
        LocateResult::try_new_with_regions(document, vec![region], vec![finding]),
        Err(LocateResultError::UnknownParentRegion)
    );
    Ok(())
}

#[test]
fn serialized_coordinates_cannot_bypass_range_and_identity_checks() {
    assert!(
        serde_json::from_str::<crate::internal::documents::ByteRange>(r#"{"start":5,"end":4}"#)
            .is_err()
    );
    assert!(
        serde_json::from_str::<crate::internal::documents::ByteRange>(r#"{"start":4,"end":4}"#)
            .is_ok()
    );
    assert!(
        serde_json::from_str::<crate::internal::documents::TextRange>(r#"{"start":9,"end":2}"#)
            .is_err()
    );
    assert!(
        serde_json::from_str::<crate::internal::documents::JsonCoordinate>(r#""not-a-pointer""#)
            .is_err()
    );
    assert!(crate::internal::documents::TreeCoordinate::try_new(Vec::new(), None).is_err());
    assert!(crate::internal::documents::TreeCoordinate::try_new(vec![1, 0, 2], None).is_err());
    assert!(
        serde_json::from_str::<crate::internal::documents::TreeCoordinate>(
            r#"{"child_path":[0],"source_bytes":null}"#
        )
        .is_err()
    );
    assert!(
        serde_json::from_str::<crate::internal::documents::AccessibilityCoordinate>(
            r#"{"document_epoch":1,"node_id":"   "}"#
        )
        .is_err()
    );
}

#[test]
fn json_coordinates_validate_every_rfc_6901_escape_in_constructors_and_serde()
-> Result<(), Box<dyn std::error::Error>> {
    for pointer in ["", "/plain", "/a~1b", "/m~0n", "/~01"] {
        let coordinate = JsonCoordinate::try_new(pointer)?;
        let wire = serde_json::to_vec(&coordinate)?;
        assert_eq!(serde_json::from_slice::<JsonCoordinate>(&wire)?, coordinate);
    }

    for pointer in [
        "missing-leading-slash",
        "/dangling~",
        "/bad~2escape",
        "/bad~xescape",
    ] {
        assert!(JsonCoordinate::try_new(pointer).is_err());
        assert!(serde_json::from_value::<JsonCoordinate>(serde_json::json!(pointer)).is_err());
    }
    Ok(())
}

#[test]
fn findings_reject_projected_node_provenance_mismatches_in_constructors_and_serde()
-> Result<(), Box<dyn std::error::Error>> {
    let document_a = DocumentId::try_new("document-a")?;
    let document_b = DocumentId::try_new("document-b")?;
    let output = OutputId::try_new("node")?;
    let epoch = DocumentEpoch::try_from(1)?;
    let coordinate =
        NativeCoordinate::RenderedDom(DomCoordinate::new(epoch, DomNodeId::try_from(1)?));

    let wrong_document = Finding::try_new(
        document_a.clone(),
        output.clone(),
        0,
        coordinate.clone(),
        ProjectedValue::Node(NodeReference::new(document_b, coordinate.clone())),
        Completeness::Complete,
        None,
    );
    assert_eq!(
        wrong_document,
        Err(FindingError::ProjectedNodeDocumentMismatch)
    );

    let wrong_coordinate = Finding::try_new(
        document_a.clone(),
        output,
        0,
        coordinate.clone(),
        ProjectedValue::Node(NodeReference::new(
            document_a.clone(),
            NativeCoordinate::RenderedDom(DomCoordinate::new(epoch, DomNodeId::try_from(2)?)),
        )),
        Completeness::Complete,
        None,
    );
    assert_eq!(
        wrong_coordinate,
        Err(FindingError::ProjectedNodeCoordinateMismatch)
    );

    let hostile = serde_json::json!({
        "document_id": "document-a",
        "output_id": "node",
        "order": 0,
        "coordinate": {
            "kind": "rendered_dom",
            "coordinate": 1
        },
        "value": {
            "kind": "node",
            "value": {
                "document_id": "document-b",
                "coordinate": {
                    "kind": "rendered_dom",
                    "coordinate": 1
                }
            }
        },
        "completeness": { "status": "complete" },
        "parent_region": null
    });
    assert!(serde_json::from_value::<Finding>(hostile).is_err());

    let valid = Finding::try_new(
        document_a.clone(),
        OutputId::try_new("valid-node")?,
        0,
        coordinate.clone(),
        ProjectedValue::Node(NodeReference::new(document_a, coordinate)),
        Completeness::Complete,
        None,
    )?;
    let mut coordinate_mismatch = serde_json::to_value(&valid)?;
    assert_eq!(
        serde_json::from_value::<Finding>(coordinate_mismatch.clone())?,
        valid
    );
    let projected_coordinate = coordinate_mismatch
        .pointer_mut("/value/value/coordinate/coordinate")
        .ok_or("serialized node coordinate is missing")?;
    *projected_coordinate = serde_json::json!(2);
    assert!(serde_json::from_value::<Finding>(coordinate_mismatch).is_err());
    Ok(())
}
