#![allow(
    clippy::indexing_slicing,
    clippy::panic,
    clippy::panic_in_result_fn,
    clippy::redundant_closure_for_method_calls,
    clippy::unwrap_used,
    reason = "focused conformance tests fail immediately on invalid fixtures"
)]

use yosoi_documents::{
    Completeness, Document, LocateFailure, LocateOutcome, NativeCoordinate, OutputPlan, Plan,
    PlanError, ProjectedValue, QueryError, ResourceBudget, ResourceBudgetValues, ResourceLimit,
    XmlDocument, XmlError, css, output, xpath,
};

fn xml_document(source: &str) -> Document {
    Document::xml("xml-test", source.as_bytes().to_vec()).unwrap()
}

fn plan_for(value: OutputPlan) -> Plan {
    Plan::new([output("result", value).unwrap()]).unwrap()
}

fn outcome_text(outcome: &LocateOutcome) -> Vec<String> {
    let LocateOutcome::Matched { result } = outcome else {
        return Vec::new();
    };
    result
        .findings()
        .iter()
        .filter_map(|finding| match finding.value() {
            ProjectedValue::Text(value) => Some(value.clone()),
            _ => None,
        })
        .collect()
}

#[test]
fn parses_xml_case_sensitively_and_preserves_mixed_text_in_document_order() {
    let source = "<Catalog><Product><Name>Ada <em>Lovelace</em> &amp; Byron</Name></Product><product>lower</product></Catalog>";
    let document = xml_document(source);
    let query = css("Product").unwrap();
    let plan = plan_for(query.text());
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&plan);

    assert_eq!(outcome_text(&outcome), ["Ada Lovelace & Byron"]);
}

#[test]
fn css_descendant_and_child_combinators_match_the_xml_tree() {
    let document =
        xml_document("<Catalog><Group><Item>nested</Item></Group><Item>direct</Item></Catalog>");
    let descendant = plan_for(css("Catalog Item").unwrap().text());
    let child = plan_for(css("Catalog > Item").unwrap().text());
    let first_child = plan_for(css("Catalog > Group:first-child").unwrap().text());
    let parsed = document.parse().unwrap();

    assert_eq!(
        outcome_text(&parsed.locate(&descendant)),
        ["nested", "direct"]
    );
    assert_eq!(outcome_text(&parsed.locate(&child)), ["direct"]);
    assert_eq!(outcome_text(&parsed.locate(&first_child)), ["nested"]);
}

#[test]
fn css_namespace_prefixes_bind_to_uri_and_coordinates_drop_source_prefix_spelling() {
    let source = "<root xmlns:a='urn:catalog'><a:Product kind='book'>One</a:Product><a:Product kind='book'>Two</a:Product></root>";
    let document = xml_document(source);
    let query = css("p|Product")
        .unwrap()
        .with_namespace("p", "urn:catalog")
        .unwrap();
    let compiled = plan_for(query.node());
    assert_eq!(
        serde_json::to_value(&compiled)
            .unwrap()
            .pointer("/requirement/accepted_documents"),
        Some(&serde_json::json!(["source_xml"]))
    );
    for expression in ["*|Product", "|Product"] {
        let namespace_selector = plan_for(css(expression).unwrap().node());
        assert_eq!(
            serde_json::to_value(namespace_selector)
                .unwrap()
                .pointer("/requirement/accepted_documents"),
            Some(&serde_json::json!(["source_xml"]))
        );
    }
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&compiled);
    let LocateOutcome::Matched { result } = &outcome else {
        panic!("expected XML matches")
    };
    assert_eq!(result.findings().len(), 2);
    let coordinates = result
        .findings()
        .iter()
        .filter_map(|finding| match finding.coordinate() {
            NativeCoordinate::SourceTree(coordinate) => {
                coordinate.expanded_name_path().map(|path| path.to_vec())
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(coordinates.len(), 2);
    assert_eq!(coordinates[0][1].namespace_uri(), Some("urn:catalog"));
    assert_eq!(coordinates[0][1].local_name(), "Product");
    assert_eq!(coordinates[0][1].same_name_sibling_index(), 1);
    assert_eq!(coordinates[1][1].same_name_sibling_index(), 2);
}

#[test]
fn css_default_and_explicit_empty_namespace_follow_selector_rules() {
    let source = "<Catalog xmlns:q='urn:other'><q:Catalog/><Catalog/></Catalog>";
    let document = xml_document(source);
    let no_default = plan_for(css("Catalog").unwrap().node());
    let with_default = plan_for(
        css("Catalog")
            .unwrap()
            .with_default_namespace("urn:other")
            .unwrap()
            .node(),
    );
    let explicit_no_namespace = plan_for(css("|Catalog").unwrap().node());
    let parsed = document.parse().unwrap();

    assert!(matches!(
        parsed.locate(&no_default),
        LocateOutcome::Matched { ref result } if result.findings().len() == 3
    ));
    assert!(matches!(
        parsed.locate(&with_default),
        LocateOutcome::Matched { .. }
    ));
    assert!(matches!(
        parsed.locate(&explicit_no_namespace),
        LocateOutcome::Matched { ref result } if result.findings().len() == 2
    ));
}

#[test]
fn xpath_uses_explicit_prefix_bindings_and_standard_unprefixed_name_rules() {
    let source = "<Catalog xmlns='urn:catalog' xmlns:p='urn:product'><p:Product p:kind='book'><p:Name>Ada</p:Name></p:Product></Catalog>";
    let document = xml_document(source);
    let query = xpath("/c:Catalog/p:Product[@p:kind='book']")
        .unwrap()
        .with_namespace("c", "urn:catalog")
        .unwrap()
        .with_namespace("p", "urn:product")
        .unwrap();
    let compiled = plan_for(query.attribute("p:kind").unwrap());
    let no_namespace = plan_for(xpath("/Catalog").unwrap().node());
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&compiled);
    let LocateOutcome::Matched { result } = &outcome else {
        panic!("expected namespace-bound XPath match")
    };
    assert!(matches!(
        result.findings()[0].value(),
        ProjectedValue::Attribute { name, value }
            if name == "{urn:product}kind" && value == "book"
    ));
    assert!(matches!(
        parsed.locate(&no_namespace),
        LocateOutcome::NoMatch { .. }
    ));
}

#[test]
fn xpath_local_name_predicates_cover_default_namespace_documents() {
    let source = "<Envelope xmlns='urn:ecb'><Cube currency='USD' rate='1.2'/><Cube currency='EUR' rate='0.9'/></Envelope>";
    let document = xml_document(source);
    let query = xpath("//*[local-name()='Cube'][@currency='USD']").unwrap();
    let compiled = plan_for(query.attribute("rate").unwrap());
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&compiled);
    let LocateOutcome::Matched { result } = &outcome else {
        panic!("expected local-name XPath match")
    };
    assert!(matches!(
        result.findings()[0].value(),
        ProjectedValue::Attribute { value, .. } if value == "1.2"
    ));
}

#[test]
fn xpath_position_predicates_are_applied_per_parent_context() {
    let document = xml_document(
        "<root><group><item>one</item><item>two</item></group><group><item>three</item><item>four</item></group></root>",
    );
    let plan = plan_for(xpath("//item[1]").unwrap().text());
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&plan);

    assert_eq!(outcome_text(&outcome), ["one", "three"]);
}

#[test]
fn tree_text_contains_selects_the_deepest_complete_node() {
    let source = "<Catalog><Product><Author>Grace</Author></Product></Catalog>";
    let document = xml_document(source);
    let plan = plan_for(yosoi_documents::tree_text_contains("Grace").unwrap().node());
    let parsed = document.parse().unwrap();
    let outcome = parsed.locate(&plan);
    let LocateOutcome::Matched { result } = &outcome else {
        panic!("expected text locator match")
    };
    let NativeCoordinate::SourceTree(coordinate) = result.findings()[0].coordinate() else {
        panic!("expected XML tree coordinate")
    };
    assert_eq!(
        coordinate
            .expanded_name_path()
            .and_then(|path| path.last())
            .map(|segment| segment.local_name()),
        Some("Author")
    );
    let source_range = coordinate.source_bytes().unwrap();
    let expected_start = source.find("<Author>").unwrap();
    let expected_end = source.find("</Author>").unwrap() + "</Author>".len();
    assert_eq!(
        usize::try_from(source_range.start()).unwrap(),
        expected_start
    );
    assert_eq!(usize::try_from(source_range.end()).unwrap(), expected_end);
}

#[test]
fn namespace_bindings_are_serialized_and_missing_or_duplicate_prefixes_fail_authoring() {
    let query = css("p|Product")
        .unwrap()
        .with_namespace("p", "urn:catalog")
        .unwrap();
    let compiled = plan_for(query.node());
    let serialized = serde_json::to_string(&compiled).unwrap();
    let restored: Plan = serde_json::from_str(&serialized).unwrap();
    assert_eq!(restored, compiled);

    let missing = Plan::new([output("missing", css("p|Product").unwrap().node()).unwrap()]);
    assert!(matches!(
        missing,
        Err(PlanError::InvalidQueryNamespaces(
            QueryError::UnboundNamespacePrefix
        ))
    ));

    let duplicate = css("p|Product")
        .unwrap()
        .with_namespace("p", "urn:first")
        .unwrap()
        .with_namespace("p", "urn:second");
    assert!(matches!(
        duplicate,
        Err(QueryError::DuplicateNamespacePrefix)
    ));

    let ordered = css("a|Product")
        .unwrap()
        .with_namespace("z", "urn:last")
        .unwrap()
        .with_namespace("a", "urn:first")
        .unwrap();
    assert_eq!(
        ordered
            .namespace_bindings()
            .iter()
            .map(|binding| binding.prefix())
            .collect::<Vec<_>>(),
        ["a", "z"]
    );

    let xml_prefix_projection =
        plan_for(xpath("//Product").unwrap().attribute("xml:lang").unwrap());
    assert_eq!(
        serde_json::to_value(xml_prefix_projection)
            .unwrap()
            .pointer("/requirement/accepted_documents"),
        Some(&serde_json::json!([
            "source_html",
            "source_xml",
            "rendered_dom"
        ]))
    );
}

#[test]
fn dtd_entities_and_non_utf8_payloads_are_rejected_without_resolution() {
    let dtd = xml_document(
        "<!DOCTYPE root [<!ENTITY secret SYSTEM 'file:///etc/passwd'>]><root>&secret;</root>",
    );
    assert!(matches!(
        XmlDocument::parse(&dtd, ResourceBudget::conservative()),
        Err(XmlError::DtdProhibited)
    ));

    let invalid_utf8 = Document::xml(
        "invalid-utf8",
        vec![b'<', b'x', b'>', 0xff, b'<', b'/', b'x', b'>'],
    )
    .unwrap();
    assert!(matches!(
        XmlDocument::parse(&invalid_utf8, ResourceBudget::conservative()),
        Err(XmlError::InvalidUtf8)
    ));
}

#[test]
fn malformed_xml_and_depth_limits_are_reported_explicitly() {
    let malformed = xml_document("<root><item></root>");
    assert!(matches!(
        XmlDocument::parse(&malformed, ResourceBudget::conservative()),
        Err(XmlError::MalformedXml)
    ));

    let nested = xml_document("<a><b><c/></b></a>");
    let limits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1024,
        max_nodes: 1_000,
        max_selector_visits: 10_000,
        max_query_bytes: 128,
        max_query_steps: 8,
        max_regions: 1,
        max_matches: 8,
        max_captures: 16_384,
        max_depth: 2,
        max_output_bytes: 1024,
    })
    .unwrap();
    assert!(matches!(
        XmlDocument::parse(&nested, limits),
        Err(XmlError::DepthLimitExceeded {
            maximum: 2,
            observed: 3
        })
    ));
}

#[test]
fn input_byte_limit_is_checked_before_parsing() {
    let document = xml_document("<root/> ");
    let limits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1,
        max_nodes: 1_000,
        max_selector_visits: 10_000,
        max_query_bytes: 32,
        max_query_steps: 2,
        max_regions: 1,
        max_matches: 1,
        max_captures: 16_384,
        max_depth: 4,
        max_output_bytes: 64,
    })
    .unwrap();
    assert!(matches!(
        XmlDocument::parse(&document, limits),
        Err(XmlError::InputLimitExceeded {
            maximum: 1,
            observed: 8
        })
    ));
}

#[test]
fn query_step_match_and_output_budgets_are_enforced() {
    let document = xml_document("<root><item>A</item><item>B</item><item>C</item></root>");

    let step_limited = limits(2, 10, 4096);
    let query = css("root > item > span").unwrap();
    let plan = Plan::new([output("steps", query.node()).unwrap()]).unwrap();
    assert!(matches!(
        document.locate_with_budget(&plan, step_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 2,
                observed: 3,
            }
        }
    ));

    let match_limited = limits(32, 2, 4096);
    let plan = Plan::new([output("matches", xpath("//item").unwrap().node()).unwrap()]).unwrap();
    assert!(matches!(
        document.locate_with_budget(&plan, match_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 2,
                observed: 3,
            }
        }
    ));

    let output_limited = limits(32, 10, 1);
    let plan = Plan::new([output("output", xpath("//item").unwrap().text()).unwrap()]).unwrap();
    assert!(matches!(
        document.locate_with_budget(&plan, output_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 1,
                ..
            }
        }
    ));

    let region_output_limited = limits(32, 10, 1);
    let items = css("item").unwrap().each_as_region("item").unwrap();
    let plan = Plan::new([output("missing", items.find(css("missing").unwrap()).text()).unwrap()])
        .unwrap();
    assert!(matches!(
        document.locate_with_budget(&plan, region_output_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 1,
                ..
            }
        }
    ));
}

fn limits(max_query_steps: u32, max_matches: u64, max_output_bytes: u64) -> ResourceBudget {
    ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1024,
        max_nodes: 100_000,
        max_selector_visits: 1_000_000,
        max_query_bytes: 128,
        max_query_steps,
        max_regions: 4,
        max_matches,
        max_captures: 16_384,
        max_depth: 16,
        max_output_bytes,
    })
    .unwrap()
}

fn limits_with_budgets(max_nodes: u64, max_selector_visits: u64) -> ResourceBudget {
    ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1024,
        max_nodes,
        max_selector_visits,
        max_query_bytes: 128,
        max_query_steps: 256,
        max_regions: 4,
        max_matches: 100,
        max_captures: 16_384,
        max_depth: 16,
        max_output_bytes: 100_000,
    })
    .unwrap()
}

#[test]
fn node_limits_apply_during_parse_and_locate() {
    let document = xml_document("<root><item>value</item></root>");
    assert!(matches!(
        XmlDocument::parse(&document, limits_with_budgets(1, 1_000)),
        Err(XmlError::NodeLimitExceeded {
            maximum: 1,
            observed: 2,
        })
    ));

    let plan = Plan::new([output("item", xpath("//item").unwrap().node()).unwrap()]).unwrap();
    assert!(matches!(
        document.locate_with_budget(&plan, limits_with_budgets(1, 1_000)),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum: 1,
                observed: 2,
            }
        }
    ));
}

#[test]
fn selector_visit_budget_applies_to_xml_query_traversal() {
    let document = xml_document("<root><item/></root>");
    let plan = Plan::new([output("missing", css("missing").unwrap().node()).unwrap()]).unwrap();

    assert!(matches!(
        document.locate_with_budget(&plan, limits_with_budgets(100, 1)),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 1,
                observed: 2,
            }
        }
    ));
}

#[test]
fn complete_static_xml_findings_mark_their_evidence_complete() {
    let document = xml_document("<root><item>value</item></root>");
    let plan = plan_for(xpath("//item").unwrap().text());
    let outcome = document.locate(&plan);
    let LocateOutcome::Matched { result } = &outcome else {
        panic!("expected XML match")
    };
    assert_eq!(result.findings()[0].completeness(), &Completeness::Complete);
}

#[test]
fn multiple_xml_outputs_share_one_plan_outcome_and_global_order() {
    let document = xml_document("<root><a>A</a><b>B</b></root>");
    let plan = Plan::new([
        output("a", xpath("//a").unwrap().text()).unwrap(),
        output("b", xpath("//b").unwrap().text()).unwrap(),
    ])
    .unwrap();
    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        panic!("expected one matched XML plan outcome")
    };
    assert_eq!(result.findings().len(), 2);
    assert_eq!(result.findings()[0].output_id().as_str(), "a");
    assert_eq!(result.findings()[0].order(), 0);
    assert_eq!(result.findings()[1].output_id().as_str(), "b");
    assert_eq!(result.findings()[1].order(), 1);
}

#[test]
fn xml_location_borrows_plan_owned_queries_for_regions_and_outputs() {
    let implementation = include_str!("../src/xml/evaluation.rs");
    let locate = implementation
        .split("fn locate_checked(")
        .nth(1)
        .unwrap_or_default();
    let cache_build = locate
        .find("plan.compiled_xml_plan(budget)?")
        .unwrap_or(usize::MAX);
    let output_loop = locate
        .find("for output in plan.outputs()")
        .unwrap_or(usize::MAX);
    assert!(cache_build < output_loop);

    let select = implementation
        .split("fn select<'tree>(")
        .nth(1)
        .and_then(|body| body.split("fn append_findings(").next())
        .unwrap_or_default();
    assert!(select.contains("match query"));
    assert!(!select.contains("css::parse"));
    assert!(!select.contains("xpath::parse"));

    let plan = include_str!("../src/plan_model.rs");
    assert!(plan.contains("compiled_xml: OnceLock<Result<CompiledXmlPlan, XmlError>>"));
    assert!(plan.contains("compiled.validate_budget(budget)?"));
}
