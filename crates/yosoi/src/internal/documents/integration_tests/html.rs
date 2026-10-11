#![allow(clippy::panic_in_result_fn, clippy::redundant_closure_for_method_calls)] // Conformance tests use direct assertions and readable projections.

use std::{error::Error, io::Error as IoError};

use crate::internal::documents::{
    Document, DocumentClass, HtmlParseError, HtmlParserProfile, LocateFailure, LocateOutcome,
    NativeCoordinate, ParsedHtmlDocument, Plan, PlanError, ProjectedValue, ResourceBudget,
    ResourceBudgetValues, ResourceLimit, TreeCoordinate, css, output, tree_text_contains, xpath,
};

#[path = "html/selector_edge_tests.rs"]
mod selector_edge_tests;

const PRODUCTS: &str = "<!doctype html>\n<html lang=\"en\">\n  <body>\n    <article class=\"product\" data-id=\"ada\">\n      <div class=\"author\">Ada</div>\n      <span class=\"price\">$12</span>\n    </article>\n    <article class=\"product\" data-id=\"grace\">\n      <div class=\"author\">Grace</div>\n      <span class=\"price\">$18</span>\n    </article>\n  </body>\n</html>";

fn html_document(source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html("products.html", source.as_bytes().to_vec())?)
}

fn limits(
    max_input_bytes: u64,
    max_query_steps: u32,
    max_matches: u64,
    max_depth: u32,
    max_output_bytes: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes: 100_000,
        max_selector_visits: 1_000_000,
        max_query_bytes: 65_536,
        max_query_steps,
        max_regions: 64,
        max_matches,
        max_captures: 16_384,
        max_depth,
        max_output_bytes,
    })?)
}

fn limits_with_nodes(max_nodes: u64) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 10_000,
        max_nodes,
        max_selector_visits: 1_000_000,
        max_query_bytes: 65_536,
        max_query_steps: 256,
        max_regions: 64,
        max_matches: 100,
        max_captures: 16_384,
        max_depth: 1_024,
        max_output_bytes: 100_000,
    })?)
}

#[test]
fn html5_repair_uses_versioned_profile_and_never_fabricates_source_ranges()
-> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><body><ul><li>One<li>Two";
    let document = html_document(source)?;
    let parsed = ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?;
    assert_eq!(parsed.profile(), HtmlParserProfile::StaticHtml5Utf8V1);
    assert_eq!(parsed.profile().as_str(), "html5-static-utf8-v1");

    let plan = Plan::new([output("items", css("li")?.text())?])?;
    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected repaired list matches").into());
    };
    assert_eq!(result.findings().len(), 2);
    for finding in result.findings() {
        let NativeCoordinate::SourceTree(coordinate) = finding.coordinate() else {
            return Err(IoError::other("expected source-tree coordinate").into());
        };
        assert_eq!(coordinate.source_bytes(), None);
    }
    Ok(())
}

#[test]
fn region_only_output_bytes_fail_before_membership_is_retained() -> Result<(), Box<dyn Error>> {
    let document = html_document(PRODUCTS)?;
    let products = css("article.product")?.each_as_region("product")?;
    let plan = Plan::new([output(
        "missing",
        products.find(css("span.absent")?).text(),
    )?])?;
    assert!(matches!(
        document.locate_with_budget(&plan, limits(10_000, 256, 100, 1_024, 1)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 1,
                ..
            }
        }
    ));
    Ok(())
}

#[test]
fn css_descendant_text_projection_accepts_empty_selected_nodes() -> Result<(), Box<dyn Error>> {
    let document = html_document("<dfn id=\"empty\"></dfn><dfn id=\"term\">term</dfn>")?;
    let plan = Plan::new([output("dfns", css("dfn[id]")?.text())?])?;

    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected advanced CSS text projection matches").into());
    };
    assert_eq!(result.findings().len(), 2);
    let empty = result
        .findings()
        .first()
        .ok_or_else(|| IoError::other("empty dfn finding is missing"))?;
    assert_eq!(empty.value(), &ProjectedValue::Text(String::new()));
    let term = result
        .findings()
        .get(1)
        .ok_or_else(|| IoError::other("text dfn finding is missing"))?;
    assert_eq!(term.value(), &ProjectedValue::Text("term".to_owned()));
    Ok(())
}

#[test]
fn product_regions_preserve_lineage_order_and_html5_element_paths() -> Result<(), Box<dyn Error>> {
    let document = html_document(PRODUCTS)?;
    let products = css("article.product")?.each_as_region("product")?;
    let plan = Plan::new([
        output("authors", products.find(css(".author")?).text())?,
        output("prices", products.find(css(".price")?).text())?,
    ])?;

    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected product-region findings").into());
    };
    assert_eq!(result.findings().len(), 4);
    let first = result
        .findings()
        .first()
        .ok_or_else(|| IoError::other("first region output is missing"))?;
    assert_eq!(first.value(), &ProjectedValue::Text("Ada".to_owned()));
    let first_lineage = first
        .parent_region()
        .ok_or_else(|| IoError::other("first finding has no region lineage"))?;
    assert_eq!(first_lineage.region_id().as_str(), "product");
    assert_eq!(first_lineage.region_ordinal(), 1);
    assert_eq!(
        first_lineage.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1], None)?)
    );
    let second = result
        .findings()
        .get(1)
        .ok_or_else(|| IoError::other("second region output is missing"))?;
    assert_eq!(second.value(), &ProjectedValue::Text("Grace".to_owned()));
    assert_eq!(
        second.parent_region().map(|region| region.region_ordinal()),
        Some(2)
    );
    Ok(())
}

#[test]
fn xpath_and_tree_text_project_values_and_exact_node_references() -> Result<(), Box<dyn Error>> {
    let document = html_document(PRODUCTS)?;
    let ids = Plan::new([output(
        "product_ids",
        xpath("//article[@class='product']")?.attribute("data-id")?,
    )?])?;
    let LocateOutcome::Matched { result } = document.locate(&ids) else {
        return Err(IoError::other("expected XPath attribute matches").into());
    };
    let values = result
        .findings()
        .iter()
        .map(|finding| finding.value().clone())
        .collect::<Vec<_>>();
    assert_eq!(
        values,
        vec![
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "ada".to_owned(),
            },
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "grace".to_owned(),
            },
        ]
    );

    let text = Plan::new([output("author", tree_text_contains("Grace")?.node())?])?;
    let LocateOutcome::Matched { result } = document.locate(&text) else {
        return Err(IoError::other("expected tree-text node reference").into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| IoError::other("tree-text finding is missing"))?;
    assert_eq!(
        finding.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 2, 1], None)?)
    );
    assert!(matches!(finding.value(), ProjectedValue::Node(_)));
    Ok(())
}

#[test]
fn names_are_namespace_aware_and_attribute_values_remain_case_sensitive()
-> Result<(), Box<dyn Error>> {
    let document = html_document(
        "<!doctype html><html><body><DIV Class=\"Product\" data-ID=\"ada\"></DIV></body></html>",
    )?;
    let matching_plan = Plan::new([output(
        "product",
        css("DIV[class='Product']")?.attribute("DATA-ID")?,
    )?])?;
    let LocateOutcome::Matched { result } = document.locate(&matching_plan) else {
        return Err(IoError::other("HTML names should match without value folding").into());
    };
    assert_eq!(
        result.findings().first().map(|finding| finding.value()),
        Some(&ProjectedValue::Attribute {
            name: "data-id".to_owned(),
            value: "ada".to_owned(),
        })
    );

    let class_case_mismatch = Plan::new([output("product", css("div.product")?.text())?])?;
    assert!(matches!(
        document.locate(&class_case_mismatch),
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}

#[test]
fn selector_grammars_and_all_resource_limits_fail_closed() -> Result<(), Box<dyn Error>> {
    let document = html_document(PRODUCTS)?;
    let unsupported_css = Plan::new([output("items", css("article:nth-child(2)")?.text())?]);
    assert!(matches!(
        unsupported_css,
        Err(PlanError::InvalidQuerySyntax { .. })
    ));

    let unsupported_xpath = Plan::new([output(
        "items",
        xpath("//article[contains(@class, 'product')]")?.text(),
    )?]);
    assert!(matches!(
        unsupported_xpath,
        Err(PlanError::InvalidQuerySyntax { .. })
    ));

    let xml_only_xpath = Plan::new([output("first_item", xpath("//article[1]")?.text())?])?;
    assert!(matches!(
        document.locate(&xml_only_xpath),
        LocateOutcome::Failed {
            failure: LocateFailure::UnsupportedCombination {
                document: DocumentClass::SourceHtml,
            }
        }
    ));

    let many = Plan::new([output("items", css("article")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(&many, limits(10_000, 256, 1, 1_024, 100_000)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                ..
            }
        }
    ));

    let small_output = Plan::new([output("items", css("article")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(&small_output, limits(10_000, 256, 100, 1_024, 1)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                ..
            }
        }
    ));

    let source = Document::html("large.html", PRODUCTS.as_bytes().to_vec())?;
    assert!(matches!(
        ParsedHtmlDocument::parse(&source, limits(1, 256, 100, 1_024, 100_000)?),
        Err(HtmlParseError::InputLimitExceeded { .. })
    ));
    assert!(matches!(
        ParsedHtmlDocument::parse(&source, limits(10_000, 256, 100, 2, 100_000)?),
        Err(HtmlParseError::DepthLimitExceeded { .. })
    ));
    Ok(())
}

#[test]
fn only_source_html_can_enter_the_static_parser() -> Result<(), Box<dyn Error>> {
    let document = Document::text("text.txt", b"not HTML".to_vec())?;
    assert_eq!(document.class(), DocumentClass::SourceText);
    assert!(matches!(
        ParsedHtmlDocument::parse(&document, ResourceBudget::conservative()),
        Err(HtmlParseError::UnsupportedDocument {
            document: DocumentClass::SourceText
        })
    ));
    Ok(())
}

#[test]
fn scripts_are_data_noscript_uses_static_tree_rules_and_resources_are_not_loaded()
-> Result<(), Box<dyn Error>> {
    let document = html_document(
        "<!doctype html><html><body><noscript><strong>static fallback</strong></noscript><script>window.executed = true</script><img src=\"https://invalid.example/image.png\"></body></html>",
    )?;
    let plan = Plan::new([
        output("fallback", css("noscript > strong")?.text())?,
        output("script_source", css("script")?.text())?,
    ])?;
    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err(IoError::other("expected static HTML data matches").into());
    };
    assert_eq!(result.findings().len(), 2);
    assert_eq!(
        result.findings().first().map(|finding| finding.value()),
        Some(&ProjectedValue::Text("static fallback".to_owned()))
    );
    assert_eq!(
        result.findings().get(1).map(|finding| finding.value()),
        Some(&ProjectedValue::Text("window.executed = true".to_owned()))
    );
    Ok(())
}

#[test]
fn invalid_utf8_and_complicated_queries_fail_without_lossy_byte_coordinates()
-> Result<(), Box<dyn Error>> {
    let invalid_utf8 = Document::html(
        "invalid.html",
        vec![b'<', b'p', b'>', 0xff, b'<', b'/', b'p', b'>'],
    )?;
    assert!(matches!(
        ParsedHtmlDocument::parse(&invalid_utf8, ResourceBudget::conservative()),
        Err(HtmlParseError::InvalidUtf8)
    ));

    let document = html_document(PRODUCTS)?;
    let steps_limited = Plan::new([output("items", css("article.product")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(&steps_limited, limits(10_000, 1, 100, 1_024, 100_000)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                ..
            }
        }
    ));
    Ok(())
}

#[test]
fn node_limits_apply_during_parse_and_locate() -> Result<(), Box<dyn Error>> {
    let document = Document::html("node-limited.html", b"<p>value</p>".to_vec())?;
    assert!(matches!(
        ParsedHtmlDocument::parse(&document, limits_with_nodes(1)?),
        Err(HtmlParseError::NodeLimitExceeded {
            maximum: 1,
            observed,
        }) if observed > 1
    ));

    let parsed = ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?;
    assert_eq!(parsed.node_count(), 6);
    let plan = Plan::new([output("paragraph", css("p")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(&plan, limits_with_nodes(1)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum: 1,
                observed,
            }
        } if observed > 1
    ));
    Ok(())
}

#[test]
fn selector_visit_budget_exhaustion_is_a_failure_not_a_no_match() -> Result<(), Box<dyn Error>> {
    let document = html_document("<p>present</p>")?;
    let tiny_limits = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 1_024,
        max_nodes: 100,
        max_selector_visits: 1,
        max_query_bytes: 1_024,
        max_query_steps: 64,
        max_regions: 4,
        max_matches: 16,
        max_captures: 16_384,
        max_depth: 64,
        max_output_bytes: 4_096,
    })?;
    let plan = Plan::new([output("missing", css(".missing")?.text())?])?;

    assert!(matches!(
        document.locate_with_budget(&plan, tiny_limits),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 1,
                observed: 2,
            }
        }
    ));
    Ok(())
}
