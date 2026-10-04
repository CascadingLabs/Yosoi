#![allow(clippy::panic_in_result_fn)] // Conformance tests use direct assertions with fallible setup.

use std::{env, error::Error, fs, path::PathBuf};

use sha2::{Digest, Sha256};
use yosoi_documents::{
    Document, DocumentClass, JsonParseError, JsonQuerySyntaxError, LocateFailure, LocateOutcome,
    NativeCoordinate, Plan, PlanError, ProjectedValue, QueryAtom, QueryError, QueryResultShape,
    QuerySpec, ResourceBudget, ResourceBudgetValues, ResourceLimit, css, json_path, json_pointer,
    output, parse_json_document,
};

const GOLDEN_PRODUCT_JSON: &[u8] =
    include_bytes!("../../../benchmarks/fixtures/document-locators/v1/golden/product.json");

fn source_json(bytes: &[u8]) -> Result<Document, Box<dyn Error>> {
    Ok(Document::json("fixture.json", bytes.to_vec())?)
}

fn limits(
    max_input_bytes: u64,
    max_matches: u64,
    max_depth: u32,
    max_output_bytes: u64,
    max_query_steps: u32,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes: 1_000_000,
        max_selector_visits: 10_000_000,
        max_query_bytes: 65_536,
        max_query_steps,
        max_regions: 64,
        max_matches,
        max_captures: 16_384,
        max_depth,
        max_output_bytes,
    })?)
}

fn value_plan(
    id: &str,
    query: yosoi_documents::QuerySpec,
) -> Result<yosoi_documents::Plan, Box<dyn Error>> {
    Ok(Plan::new([output(id, query.value())?])?)
}

fn matched_values(
    outcome: &LocateOutcome,
) -> Result<Vec<(String, serde_json::Value)>, Box<dyn Error>> {
    let LocateOutcome::Matched { result } = outcome else {
        return Err("expected a matched JSON result".into());
    };
    result
        .findings()
        .iter()
        .map(|finding| {
            let NativeCoordinate::Json(coordinate) = finding.coordinate() else {
                return Err("expected a JSON Pointer coordinate".into());
            };
            let ProjectedValue::Json(value) = finding.value() else {
                return Err("expected a native JSON value".into());
            };
            Ok((coordinate.as_pointer().to_owned(), value.clone()))
        })
        .collect()
}

#[test]
fn tiny_golden_pointer_and_jsonpath_results_keep_native_values_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let document = source_json(GOLDEN_PRODUCT_JSON)?;
    let locator_plan = Plan::new([
        output("currency", json_pointer("/currency")?.value())?,
        output("prices", json_path("$.products[*].price")?.value())?,
    ])?;

    assert_eq!(
        matched_values(&document.locate(&locator_plan))?,
        vec![
            ("/currency".to_owned(), serde_json::json!("USD")),
            ("/products/0/price".to_owned(), serde_json::json!(12)),
            ("/products/1/price".to_owned(), serde_json::json!(18)),
        ]
    );
    Ok(())
}

#[test]
fn pointer_supports_root_empty_tokens_and_rfc_6901_escaping() -> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"a/b":{"~key":["zero",{"":null}],"~1":true}}"#)?;
    let root_plan = value_plan("root", json_pointer("")?)?;
    assert_eq!(
        matched_values(&document.locate(&root_plan))?,
        vec![(
            String::new(),
            serde_json::json!({"a/b":{"~key":["zero",{"":null}],"~1":true}}),
        )]
    );

    let escaped_plan = value_plan("empty-key", json_pointer("/a~1b/~0key/1/")?)?;
    assert_eq!(
        matched_values(&document.locate(&escaped_plan))?,
        vec![("/a~1b/~0key/1/".to_owned(), serde_json::Value::Null)]
    );

    let tilde_one_plan = value_plan("tilde-one-key", json_pointer("/a~1b/~01")?)?;
    assert_eq!(
        matched_values(&document.locate(&tilde_one_plan))?,
        vec![("/a~1b/~01".to_owned(), serde_json::json!(true))]
    );
    Ok(())
}

#[test]
fn pointer_array_indexes_are_canonical_and_missing_targets_are_complete_no_match()
-> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"items":["zero","one"]}"#)?;
    let valid = value_plan("second", json_pointer("/items/1")?)?;
    assert_eq!(
        matched_values(&document.locate(&valid))?,
        vec![("/items/1".to_owned(), serde_json::json!("one"))]
    );

    for missing in [
        "/missing",
        "/items/00",
        "/items/-",
        "/items/5",
        "/items/0/x",
    ] {
        let locator_plan = value_plan("missing", json_pointer(missing)?)?;
        assert!(matches!(
            document.locate(&locator_plan),
            LocateOutcome::NoMatch { .. }
        ));
    }
    Ok(())
}

#[test]
fn jsonpath_supports_named_children_quoted_keys_indexes_and_ordered_array_wildcards()
-> Result<(), Box<dyn Error>> {
    let document =
        source_json(br#"{"a/b":{"items":[{"price":3},{"price":4}]},"quote\"key":{"value":7}}"#)?;
    let locator_plan = Plan::new([
        output(
            "prices",
            json_path("$[\"a/b\"][\"items\"][*][\"price\"]")?.value(),
        )?,
        output(
            "indexed",
            json_path("$[\"a/b\"][\"items\"][1][\"price\"]")?.value(),
        )?,
        output(
            "quoted-key",
            json_path("$[\"quote\\\"key\"][\"value\"]")?.value(),
        )?,
    ])?;

    assert_eq!(
        matched_values(&document.locate(&locator_plan))?,
        vec![
            ("/a~1b/items/0/price".to_owned(), serde_json::json!(3)),
            ("/a~1b/items/1/price".to_owned(), serde_json::json!(4)),
            ("/a~1b/items/1/price".to_owned(), serde_json::json!(4)),
            ("/quote\"key/value".to_owned(), serde_json::json!(7)),
        ]
    );
    Ok(())
}

#[test]
fn root_jsonpath_and_json_null_are_matches_not_absence() -> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"present":null}"#)?;
    let null_plan = value_plan("null", json_pointer("/present")?)?;
    assert_eq!(
        matched_values(&document.locate(&null_plan))?,
        vec![("/present".to_owned(), serde_json::Value::Null)]
    );

    let root_plan = value_plan("root", json_path("$")?)?;
    assert_eq!(
        matched_values(&document.locate(&root_plan))?,
        vec![(String::new(), serde_json::json!({"present":null}))]
    );
    Ok(())
}

#[test]
fn unsupported_jsonpath_features_are_typed_and_rejected_during_authoring()
-> Result<(), Box<dyn Error>> {
    for expression in [
        "$..items",
        "$.items[?(@.price > 0)]",
        "$.items[0:2]",
        "$.items[0,1]",
        "$.items[*].price()",
        "$.*",
        "$.items[-1]",
    ] {
        assert!(matches!(
            json_path(expression),
            Err(QueryError::InvalidJsonQuery(
                JsonQuerySyntaxError::UnsupportedPathFeature
            ))
        ));
    }
    assert!(matches!(
        json_path("$.items["),
        Err(QueryError::InvalidJsonQuery(
            JsonQuerySyntaxError::InvalidPathSyntax
        ))
    ));
    assert!(matches!(
        json_pointer("items"),
        Err(QueryError::InvalidJsonQuery(
            JsonQuerySyntaxError::InvalidPointerSyntax
        ))
    ));
    assert!(matches!(
        json_pointer("/bad~2escape"),
        Err(QueryError::InvalidJsonQuery(
            JsonQuerySyntaxError::InvalidPointerEscape
        ))
    ));

    let manually_authored = QuerySpec::new(
        QueryAtom::JsonPath("$..items".to_owned()),
        QueryResultShape::JsonValues,
    );
    assert!(matches!(
        Plan::new([output("items", manually_authored.value())?]),
        Err(PlanError::InvalidJsonQuery(
            JsonQuerySyntaxError::UnsupportedPathFeature
        ))
    ));
    Ok(())
}

#[test]
fn non_json_locator_families_are_rejected_before_document_parsing() -> Result<(), Box<dyn Error>> {
    let document = source_json(b"{")?;
    let html_plan = Plan::new([output("text", css("p")?.text())?])?;
    assert_eq!(
        document.locate(&html_plan),
        LocateOutcome::Failed {
            failure: LocateFailure::UnsupportedCombination {
                document: DocumentClass::SourceJson,
            }
        }
    );
    Ok(())
}

#[test]
fn parser_rejects_duplicate_keys_and_distinguishes_truncated_from_malformed_json()
-> Result<(), Box<dyn Error>> {
    let duplicate = source_json(br#"{"a":1,"nested":{"a":2,"a":3}}"#)?;
    assert_eq!(
        parse_json_document(&duplicate, ResourceBudget::conservative()),
        Err(JsonParseError::DuplicateObjectKey)
    );

    let truncated = source_json(br#"{"a":[1,"#)?;
    assert_eq!(
        parse_json_document(&truncated, ResourceBudget::conservative()),
        Err(JsonParseError::TruncatedJson)
    );

    let malformed = source_json(br#"{"a": tru}"#)?;
    assert_eq!(
        parse_json_document(&malformed, ResourceBudget::conservative()),
        Err(JsonParseError::MalformedJson)
    );
    Ok(())
}

#[test]
fn parser_enforces_input_and_depth_limits_and_has_a_safe_hard_depth_ceiling()
-> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"a":{"b":1}}"#)?;
    assert!(matches!(
        parse_json_document(&document, limits(2, 10, 8, 10, 10)?),
        Err(JsonParseError::InputLimitExceeded {
            maximum: 2,
            observed: 13
        })
    ));
    assert!(matches!(
        parse_json_document(&document, limits(100, 10, 1, 10, 10)?),
        Err(JsonParseError::DepthLimitExceeded {
            maximum: 1,
            observed: 2
        })
    ));

    let too_deep = format!("{}0{}", "[".repeat(129), "]".repeat(129));
    let document = source_json(too_deep.as_bytes())?;
    assert!(matches!(
        parse_json_document(&document, ResourceBudget::conservative()),
        Err(JsonParseError::DepthLimitExceeded {
            maximum: 128,
            observed: 129
        })
    ));
    Ok(())
}

#[test]
fn query_steps_match_count_and_output_bytes_are_hard_limits() -> Result<(), Box<dyn Error>> {
    let query_steps_plan = value_plan("value", json_path("$.a.b")?)?;
    let small_steps_document = source_json(br#"{"a":{"b":1}}"#)?;
    assert!(matches!(
        small_steps_document.locate_with_budget(&query_steps_plan, limits(100, 10, 8, 100, 2)?,),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 2,
                observed: 3,
            }
        }
    ));

    let document = source_json(br#"{"items":[1,2,3]}"#)?;
    let matches_plan = value_plan("item", json_path("$.items[*]")?)?;
    assert_eq!(
        document.locate_with_budget(&matches_plan, limits(100, 2, 8, 100, 10)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 2,
                observed: 3,
            }
        }
    );

    let output_plan = value_plan("item", json_pointer("/items/0")?)?;
    assert!(matches!(
        document.locate_with_budget(&output_plan, limits(100, 10, 8, 8, 10)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 8,
                observed: 9
            }
        }
    ));
    Ok(())
}

#[test]
fn selector_visit_budget_bounds_jsonpath_candidate_values() -> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"items":[1,2]}"#)?;
    let tiny_limits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1_024,
        max_nodes: 100,
        max_selector_visits: 2,
        max_query_bytes: 128,
        max_query_steps: 8,
        max_regions: 4,
        max_matches: 100,
        max_captures: 16_384,
        max_depth: 16,
        max_output_bytes: 4_096,
    })?;
    let plan = value_plan("items", json_path("$.items[*]")?)?;

    assert_eq!(
        document.locate_with_budget(&plan, tiny_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 2,
                observed: 3,
            }
        }
    );
    Ok(())
}

#[test]
fn parsed_document_reuse_keeps_its_parse_budget_and_direct_locate_accepts_custom_budget()
-> Result<(), Box<dyn Error>> {
    let document = source_json(br#"{"a":{"b":1}}"#)?;
    let plan = value_plan("value", json_pointer("/a/b")?)?;
    let parsed = document.parse()?;
    assert_eq!(
        matched_values(&parsed.locate(&plan))?,
        vec![("/a/b".to_owned(), serde_json::json!(1))]
    );
    assert_eq!(
        document.locate_with_budget(&plan, limits(4, 10, 1, 100, 10)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: 4,
                observed: 13,
            }
        }
    );
    Ok(())
}

#[test]
#[ignore = "requires explicitly materialized advanced locator fixtures"]
fn advanced_json_oracles_match_the_rust_engine() -> Result<(), Box<dyn Error>> {
    let advanced_root = env::var_os("YOSOI_DOCUMENT_LOCATOR_ADVANCED_ROOT")
        .map_or_else(
            || {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../benchmarks/fixtures/document-locators/v1/advanced/materialized")
            },
            PathBuf::from,
        )
        .join("live");

    let nvd = source_json(&fs::read(advanced_root.join("nvd-cves-2000.json"))?)?;
    let nvd_plan = value_plan("total-results", json_pointer("/totalResults")?)?;
    assert_eq!(
        matched_values(&nvd.locate(&nvd_plan))?,
        vec![("/totalResults".to_owned(), serde_json::json!(398_152))]
    );

    let usgs = source_json(&fs::read(
        advanced_root.join("usgs-earthquakes-all-month.geojson"),
    )?)?;
    let usgs_plan = value_plan("magnitudes", json_path("$.features[*].properties.mag")?)?;
    let selected = matched_values(&usgs.locate(&usgs_plan))?;
    assert_eq!(selected.len(), 10_790);
    let mut coordinates = Sha256::new();
    for (pointer, _) in &selected {
        coordinates.update(pointer.as_bytes());
        coordinates.update(b"\n");
    }
    assert_eq!(
        format!("{:x}", coordinates.finalize()),
        "cd4c546c50bae3f7f7b40b002b79e757aa58260a653c13aafc2be2cc16e9d32c"
    );
    assert_eq!(
        selected.first(),
        Some(&(
            "/features/0/properties/mag".to_owned(),
            serde_json::json!(0.72)
        ))
    );
    assert_eq!(
        selected.last(),
        Some(&(
            "/features/10789/properties/mag".to_owned(),
            serde_json::json!(0.83)
        ))
    );
    Ok(())
}
