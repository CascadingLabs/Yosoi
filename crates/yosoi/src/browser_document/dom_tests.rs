#![allow(clippy::panic_in_result_fn)]

use std::{error::Error, io};

use serde_json::Value;
use yosoi_documents::{DocumentClass, ResourceBudget, ResourceBudgetValues};

use crate::Document;

use super::{RenderedDomNormalizationError, normalize_rendered_dom};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn budget(
    max_input_bytes: u64,
    max_nodes: u64,
    max_depth: u32,
    max_output_bytes: u64,
) -> TestResult<ResourceBudget> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes,
        max_selector_visits: 1_000_000,
        max_query_bytes: 65_536,
        max_query_steps: 256,
        max_regions: 64,
        max_matches: 100_000,
        max_captures: 16_384,
        max_depth,
        max_output_bytes,
    })?)
}

fn wire(document: &Document) -> TestResult<Value> {
    Ok(serde_json::from_slice(document.bytes())?)
}

#[test]
fn canonical_wire_has_stable_preorder_ids_and_explicitly_omits_non_tree_nodes() -> TestResult {
    let html = br##"<!doctype html><!--outside--><main id="root" data-z="z" class="x" data-a="a">alpha<span>beta</span><!--inside--><template><b>hidden template</b></template><noscript><aside id="invented">fallback</aside></noscript><svg><path xlink:href="#vector" d="M0 0"></path></svg></main>"##;
    let budget = budget(1_000_000, 1_000, 1_024, 1_000_000)?;

    let first = normalize_rendered_dom("capture:4", 41, html.to_vec(), budget)?;
    let second = normalize_rendered_dom("capture:4", 41, html.to_vec(), budget)?;
    assert_eq!(first.id().as_str(), "capture:4");
    assert_eq!(first.class(), DocumentClass::RenderedDom);
    assert_eq!(first.bytes(), second.bytes());
    let value = wire(&first)?;
    assert_eq!(
        value.get("schema").and_then(Value::as_str),
        Some("yosoi.rendered-dom.v1")
    );
    assert_eq!(
        value.get("document_epoch").and_then(Value::as_u64),
        Some(41)
    );
    assert_eq!(
        value.get("tree_model").and_then(Value::as_str),
        Some("document_light_dom")
    );
    assert_eq!(value.get("root").and_then(Value::as_u64), Some(1));

    let nodes = value
        .get("nodes")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("rendered DOM nodes are missing"))?;
    assert!(!nodes.is_empty());
    for (index, node) in nodes.iter().enumerate() {
        assert_eq!(
            node.get("id").and_then(Value::as_u64),
            u64::try_from(index)
                .ok()
                .and_then(|value| value.checked_add(1))
        );
    }
    let root = nodes
        .first()
        .ok_or_else(|| io::Error::other("rendered DOM root node is missing"))?;
    assert_eq!(root.get("kind").and_then(Value::as_str), Some("document"));
    assert_eq!(
        root.get("children").and_then(Value::as_array).map(Vec::len),
        Some(1)
    );
    assert!(!String::from_utf8_lossy(first.bytes()).contains("outside"));
    assert!(!String::from_utf8_lossy(first.bytes()).contains("inside"));
    assert!(!String::from_utf8_lossy(first.bytes()).contains("hidden template"));
    assert!(
        !nodes
            .iter()
            .any(|node| { node.get("tag_name").and_then(Value::as_str) == Some("aside") })
    );

    let main = nodes
        .iter()
        .find(|node| node.get("tag_name").and_then(Value::as_str) == Some("main"))
        .ok_or_else(|| io::Error::other("main element is missing"))?;
    let attribute_names = main
        .get("attributes")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("main attributes are missing"))?
        .iter()
        .map(|attribute| attribute.get("name").and_then(Value::as_str))
        .collect::<Vec<_>>();
    assert_eq!(
        attribute_names,
        vec![Some("class"), Some("data-a"), Some("data-z"), Some("id")]
    );

    let path = nodes
        .iter()
        .find(|node| node.get("tag_name").and_then(Value::as_str) == Some("path"))
        .ok_or_else(|| io::Error::other("SVG path element is missing"))?;
    let xlink = path
        .get("attributes")
        .and_then(Value::as_array)
        .and_then(|attributes| {
            attributes.iter().find(|attribute| {
                attribute.get("namespace_uri").and_then(Value::as_str)
                    == Some("http://www.w3.org/1999/xlink")
            })
        })
        .ok_or_else(|| io::Error::other("xlink attribute namespace was lost"))?;
    assert_eq!(xlink.get("name").and_then(Value::as_str), Some("href"));
    assert_eq!(xlink.get("value").and_then(Value::as_str), Some("#vector"));
    Ok(())
}

#[test]
fn html_namespace_preserves_literal_colon_tag_names() -> TestResult {
    let document = normalize_rendered_dom(
        "colon-tag",
        1,
        b"<!doctype html><html><body><vendor:widget>ready</vendor:widget></body></html>".to_vec(),
        budget(100_000, 100, 100, 100_000)?,
    )?;
    let value = wire(&document)?;
    let nodes = value
        .get("nodes")
        .and_then(Value::as_array)
        .ok_or_else(|| io::Error::other("rendered DOM nodes are missing"))?;
    let widget = nodes
        .iter()
        .find(|node| node.get("tag_name").and_then(Value::as_str) == Some("vendor:widget"))
        .ok_or_else(|| io::Error::other("colon tag was not retained"))?;
    assert_eq!(
        widget.get("namespace_uri").and_then(Value::as_str),
        Some("http://www.w3.org/1999/xhtml")
    );
    Ok(())
}

#[test]
fn input_node_depth_and_output_limits_fail_with_typed_errors() -> TestResult {
    let html = b"<p>bounded</p>".to_vec();

    let error = normalize_rendered_dom("dom", 7, html.clone(), budget(1, 1_000, 100, 1_000_000)?)
        .err()
        .ok_or_else(|| io::Error::other("input-byte limit was not enforced"))?;
    assert!(matches!(
        error,
        RenderedDomNormalizationError::InputLimitExceeded { .. }
    ));

    let error = normalize_rendered_dom("dom", 7, html.clone(), budget(1_000, 1, 100, 1_000_000)?)
        .err()
        .ok_or_else(|| io::Error::other("node limit was not enforced"))?;
    assert!(matches!(
        error,
        RenderedDomNormalizationError::NodeLimitExceeded { .. }
    ));

    let error = normalize_rendered_dom("dom", 7, html.clone(), budget(1_000, 1_000, 1, 1_000_000)?)
        .err()
        .ok_or_else(|| io::Error::other("depth limit was not enforced"))?;
    assert!(matches!(
        error,
        RenderedDomNormalizationError::DepthLimitExceeded { .. }
    ));

    let error = normalize_rendered_dom("dom", 7, html, budget(1_000, 1_000, 100, 1)?)
        .err()
        .ok_or_else(|| io::Error::other("output-byte limit was not enforced"))?;
    assert!(matches!(
        error,
        RenderedDomNormalizationError::OutputLimitExceeded { .. }
    ));
    Ok(())
}

#[test]
fn zero_epoch_and_non_utf8_input_are_rejected() -> TestResult {
    let limits = budget(1_000, 1_000, 100, 1_000)?;
    let error = normalize_rendered_dom("dom", 0, b"<html></html>".to_vec(), limits)
        .err()
        .ok_or_else(|| io::Error::other("zero epoch was accepted"))?;
    assert!(matches!(error, RenderedDomNormalizationError::InvalidEpoch));

    let error = normalize_rendered_dom("dom", 1, vec![0xff], limits)
        .err()
        .ok_or_else(|| io::Error::other("invalid UTF-8 was accepted"))?;
    assert!(matches!(error, RenderedDomNormalizationError::InvalidUtf8));
    Ok(())
}
