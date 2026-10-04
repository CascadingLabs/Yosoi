#![allow(
    clippy::as_conversions,
    clippy::needless_pass_by_value,
    clippy::panic_in_result_fn,
    clippy::redundant_closure_for_method_calls,
    clippy::too_many_arguments
)] // Conformance tests favor compact fixtures and direct assertions.

use std::{error::Error, io::Error as IoError};

use serde_json::{Value, json};
use yosoi_documents::{
    Document, DocumentEpoch, DocumentProfile, DomCoordinate, DomNodeId, LocateFailure,
    LocateOutcome, NativeCoordinate, NodeReference, Plan, PlanError, ProjectedValue,
    RenderedDomDocument, ResourceBudget, ResourceBudgetValues, ResourceLimit, css, output, role,
    tree_text_contains, xpath,
};

const EPOCH: u64 = 23;
const HTML_NAMESPACE: &str = "http://www.w3.org/1999/xhtml";

fn fixture() -> Value {
    json!({
        "schema": "yosoi.rendered-dom.v1",
        "document_epoch": EPOCH,
        "tree_model": "document_light_dom",
        "root": 900,
        "nodes": [
            { "kind": "document", "id": 900, "parent": null, "children": [40] },
            { "kind": "element", "id": 40, "parent": 900, "children": [80], "namespace_uri": HTML_NAMESPACE, "tag_name": "html", "attributes": [] },
            { "kind": "element", "id": 80, "parent": 40, "children": [70, 20, 5], "namespace_uri": HTML_NAMESPACE, "tag_name": "body", "attributes": [] },
            { "kind": "element", "id": 70, "parent": 80, "children": [12, 13], "namespace_uri": HTML_NAMESPACE, "tag_name": "article", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "product" },
                { "namespace_uri": "", "name": "data-id", "value": "ada" },
                { "namespace_uri": "urn:meta", "name": "data-id", "value": "shadowed-value" }
            ] },
            { "kind": "element", "id": 12, "parent": 70, "children": [300], "namespace_uri": HTML_NAMESPACE, "tag_name": "span", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "name" }
            ] },
            { "kind": "text", "id": 300, "parent": 12, "children": [], "value": "  Ada  \n Lovelace " },
            { "kind": "element", "id": 13, "parent": 70, "children": [301], "namespace_uri": HTML_NAMESPACE, "tag_name": "span", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "price" }
            ] },
            { "kind": "text", "id": 301, "parent": 13, "children": [], "value": "$12" },
            { "kind": "element", "id": 20, "parent": 80, "children": [10, 11], "namespace_uri": HTML_NAMESPACE, "tag_name": "article", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "product" },
                { "namespace_uri": "", "name": "data-id", "value": "grace" }
            ] },
            { "kind": "element", "id": 10, "parent": 20, "children": [302], "namespace_uri": HTML_NAMESPACE, "tag_name": "span", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "name" }
            ] },
            { "kind": "text", "id": 302, "parent": 10, "children": [], "value": "Grace" },
            { "kind": "element", "id": 11, "parent": 20, "children": [303], "namespace_uri": HTML_NAMESPACE, "tag_name": "span", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "price" }
            ] },
            { "kind": "text", "id": 303, "parent": 11, "children": [], "value": "$18" },
            { "kind": "element", "id": 5, "parent": 80, "children": [4], "namespace_uri": HTML_NAMESPACE, "tag_name": "article", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "product" },
                { "namespace_uri": "", "name": "data-id", "value": "empty" }
            ] },
            { "kind": "element", "id": 4, "parent": 5, "children": [100], "namespace_uri": HTML_NAMESPACE, "tag_name": "span", "attributes": [
                { "namespace_uri": "", "name": "class", "value": "name" }
            ] },
            { "kind": "text", "id": 100, "parent": 4, "children": [], "value": "" }
        ]
    })
}

fn limits(
    max_input_bytes: u64,
    max_nodes: u64,
    max_selector_visits: u64,
    max_query_bytes: u64,
    max_query_steps: u32,
    max_regions: u32,
    max_matches: u64,
    max_depth: u32,
    max_output_bytes: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes,
        max_selector_visits,
        max_query_bytes,
        max_query_steps,
        max_regions,
        max_matches,
        max_captures: 16_384,
        max_depth,
        max_output_bytes,
    })?)
}

fn generous_limits() -> Result<ResourceBudget, Box<dyn Error>> {
    limits(
        1_000_000, 1_000, 1_000_000, 65_536, 256, 64, 100, 1_024, 1_000_000,
    )
}

fn document(wire: &Value, profile_epoch: u64) -> Result<Document, Box<dyn Error>> {
    Ok(Document::rendered_dom(
        "rendered-dom.json",
        DocumentEpoch::try_from(profile_epoch)?,
        serde_json::to_vec(wire)?,
    )?)
}

fn parse_wire(
    wire: &Value,
    profile_epoch: u64,
    limits: ResourceBudget,
) -> Result<RenderedDomDocument, Box<dyn Error>> {
    let document = document(wire, profile_epoch)?;
    Ok(RenderedDomDocument::parse(&document, limits)?)
}

fn dom_coordinate(node_id: u64) -> Result<NativeCoordinate, Box<dyn Error>> {
    Ok(NativeCoordinate::RenderedDom(DomCoordinate::new(
        DocumentEpoch::try_from(EPOCH)?,
        DomNodeId::try_new(node_id)?,
    )))
}

fn node_mut(wire: &mut Value, id: u64) -> Result<&mut Value, IoError> {
    wire.get_mut("nodes")
        .and_then(Value::as_array_mut)
        .and_then(|nodes| {
            nodes
                .iter_mut()
                .find(|node| node.get("id").and_then(Value::as_u64) == Some(id))
        })
        .ok_or_else(|| IoError::other(format!("fixture node {id} is missing")))
}

fn reject_wire(wire: Value) -> Result<(), Box<dyn Error>> {
    assert!(parse_wire(&wire, EPOCH, generous_limits()?).is_err());
    Ok(())
}

#[test]
fn css_xpath_and_tree_text_share_preorder_text_and_dom_coordinates() -> Result<(), Box<dyn Error>> {
    let mut wire = fixture();
    wire.get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?
        .reverse();
    let document = document(&wire, EPOCH)?;
    let parsed = document.parse()?;

    let products = css("article.product")?.each_as_region("product")?;
    let names = Plan::new([output("names", products.find(css(".name")?).text())?])?;
    let LocateOutcome::Matched { result } = parsed.locate(&names) else {
        return Err(IoError::other("expected rendered-DOM name matches").into());
    };
    assert_eq!(
        result
            .findings()
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Text("Ada Lovelace".to_owned()),
            ProjectedValue::Text("Grace".to_owned()),
            ProjectedValue::Text(String::new()),
        ]
    );
    let expected_nodes = [12, 10, 4];
    let expected_regions = [70, 20, 5];
    for (index, finding) in result.findings().iter().enumerate() {
        let region = finding
            .parent_region()
            .ok_or_else(|| IoError::other("name finding has no region lineage"))?;
        assert_eq!(region.region_ordinal(), index as u64 + 1);
        assert_eq!(
            region.coordinate(),
            &dom_coordinate(expected_regions[index])?
        );
        assert_eq!(
            finding.coordinate(),
            &dom_coordinate(expected_nodes[index])?
        );
    }

    let xpath_ids = Plan::new([output(
        "ids",
        xpath("//article[@class='product']")?.attribute("data-id")?,
    )?])?;
    let LocateOutcome::Matched { result } = parsed.locate(&xpath_ids) else {
        return Err(IoError::other("expected rendered-DOM XPath matches").into());
    };
    assert_eq!(
        result
            .findings()
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "ada".to_owned(),
            },
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "grace".to_owned(),
            },
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "empty".to_owned(),
            },
        ]
    );

    let selected = Plan::new([output(
        "ada",
        css("article[DATA-ID='ada']")?.attribute("DATA-ID")?,
    )?])?;
    let LocateOutcome::Matched { result } = parsed.locate(&selected) else {
        return Err(IoError::other("unnamespaced attribute selector did not match").into());
    };
    assert_eq!(
        result.findings().first().map(|finding| finding.value()),
        Some(&ProjectedValue::Attribute {
            name: "data-id".to_owned(),
            value: "ada".to_owned(),
        })
    );

    let text_reference = Plan::new([output("grace_text", tree_text_contains("Grace")?.node())?])?;
    let LocateOutcome::Matched { result } = parsed.locate(&text_reference) else {
        return Err(IoError::other("expected rendered-DOM tree-text match").into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| IoError::other("tree-text node reference is missing"))?;
    let coordinate = dom_coordinate(10)?;
    assert_eq!(finding.coordinate(), &coordinate);
    assert_eq!(
        finding.value(),
        &ProjectedValue::Node(NodeReference::new(document.id().clone(), coordinate,))
    );
    Ok(())
}

#[test]
fn colon_attribute_names_and_foreign_namespaced_attributes_keep_their_identity()
-> Result<(), Box<dyn Error>> {
    let mut wire = fixture();
    node_mut(&mut wire, 80)?["children"] = json!([70, 20, 5, 600, 700]);
    wire.get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?
        .extend([
            json!({
                "kind": "element",
                "id": 600,
                "parent": 80,
                "children": [],
                "namespace_uri": HTML_NAMESPACE,
                "tag_name": "div",
                "attributes": [
                    { "namespace_uri": "", "name": "class", "value": "language" },
                    { "namespace_uri": "", "name": "xml:lang", "value": "en-GB" }
                ]
            }),
            json!({
                "kind": "element",
                "id": 700,
                "parent": 80,
                "children": [],
                "namespace_uri": "http://www.w3.org/2000/svg",
                "tag_name": "svg",
                "attributes": [
                    { "namespace_uri": "", "name": "class", "value": "icon" },
                    {
                        "namespace_uri": "http://www.w3.org/1999/xlink",
                        "name": "href",
                        "value": "#vector"
                    }
                ]
            }),
        ]);
    let document = document(&wire, EPOCH)?;

    let language = Plan::new([output(
        "language",
        css("div.language")?.attribute("xml:lang")?,
    )?])?;
    let LocateOutcome::Matched { result } = document.locate(&language) else {
        return Err(IoError::other("expected unnamespaced xml:lang projection").into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or_else(|| IoError::other("xml:lang finding is missing"))?;
    assert_eq!(finding.coordinate(), &dom_coordinate(600)?);
    assert_eq!(
        finding.value(),
        &ProjectedValue::Attribute {
            name: "xml:lang".to_owned(),
            value: "en-GB".to_owned(),
        }
    );

    let unprefixed_href = Plan::new([output("href", css("svg.icon")?.attribute("href")?)?])?;
    assert!(matches!(
        document.locate(&unprefixed_href),
        LocateOutcome::Failed {
            failure: LocateFailure::InvalidPlan { .. }
        }
    ));
    Ok(())
}

#[test]
fn no_match_is_complete_and_unsupported_queries_or_projections_are_rejected()
-> Result<(), Box<dyn Error>> {
    let document = document(&fixture(), EPOCH)?;

    let missing = Plan::new([output("missing", css("aside.absent")?.text())?])?;
    assert!(matches!(
        document.locate(&missing),
        LocateOutcome::NoMatch { .. }
    ));

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
                document: yosoi_documents::DocumentClass::RenderedDom,
            }
        }
    ));

    let unsupported_role = Plan::new([output("button", role("button")?.node())?])?;
    assert!(matches!(
        document.locate(&unsupported_role),
        LocateOutcome::Failed {
            failure: LocateFailure::UnsupportedCombination {
                document: yosoi_documents::DocumentClass::RenderedDom,
            }
        }
    ));
    Ok(())
}

#[test]
fn repeated_regions_remain_matched_when_all_outputs_miss() -> Result<(), Box<dyn Error>> {
    let document = document(&fixture(), EPOCH)?;
    let products = css("article.product")?.each_as_region("product")?;
    let plan = Plan::new([output(
        "missing",
        products.find(css("span.absent")?).text(),
    )?])?;
    let LocateOutcome::Matched { result } = document.locate(&plan) else {
        return Err("expected repeated rendered-DOM roots to remain matched".into());
    };
    assert_eq!(result.regions().len(), 3);
    assert_eq!(result.findings().len(), 0);
    assert!(matches!(
        document.locate_with_budget(
            &plan,
            limits(1_000_000, 1_000, 1_000_000, 65_536, 256, 64, 100, 1_024, 1)?
        ),
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
fn rendered_dom_wire_and_profile_are_strictly_versioned_and_light_dom_only()
-> Result<(), Box<dyn Error>> {
    let mut unknown_document_field = fixture();
    unknown_document_field
        .as_object_mut()
        .ok_or_else(|| IoError::other("fixture root is not an object"))?
        .insert("future_field".to_owned(), json!(true));
    reject_wire(unknown_document_field)?;

    let mut unknown_node_field = fixture();
    node_mut(&mut unknown_node_field, 40)?
        .as_object_mut()
        .ok_or_else(|| IoError::other("element node is not an object"))?
        .insert("future_field".to_owned(), json!(true));
    reject_wire(unknown_node_field)?;

    let mut unknown_text_field = fixture();
    node_mut(&mut unknown_text_field, 300)?
        .as_object_mut()
        .ok_or_else(|| IoError::other("text node is not an object"))?
        .insert("future_field".to_owned(), json!(true));
    reject_wire(unknown_text_field)?;

    let mut unknown_attribute_field = fixture();
    let attributes = node_mut(&mut unknown_attribute_field, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    attributes
        .first_mut()
        .and_then(Value::as_object_mut)
        .ok_or_else(|| IoError::other("article attribute is not an object"))?
        .insert("future_field".to_owned(), json!(true));
    reject_wire(unknown_attribute_field)?;

    let mut wrong_schema = fixture();
    wrong_schema["schema"] = json!("yosoi.rendered-dom.v2");
    reject_wire(wrong_schema)?;

    let mut wrong_tree_model = fixture();
    wrong_tree_model["tree_model"] = json!("composed_dom");
    reject_wire(wrong_tree_model)?;

    let mut mismatched_epoch = fixture();
    mismatched_epoch["document_epoch"] = json!(EPOCH + 1);
    reject_wire(mismatched_epoch)?;

    let mut zero_epoch = fixture();
    zero_epoch["document_epoch"] = json!(0);
    reject_wire(zero_epoch)?;

    let mut zero_root = fixture();
    zero_root["root"] = json!(0);
    node_mut(&mut zero_root, 900)?["id"] = json!(0);
    reject_wire(zero_root)?;

    let mut zero_node_id = fixture();
    node_mut(&mut zero_node_id, 4)?["children"] = json!([0]);
    node_mut(&mut zero_node_id, 100)?["id"] = json!(0);
    reject_wire(zero_node_id)?;

    let mut string_root_id = fixture();
    string_root_id["root"] = json!("900");
    reject_wire(string_root_id)?;

    let mut string_node_id = fixture();
    node_mut(&mut string_node_id, 40)?["id"] = json!("40");
    reject_wire(string_node_id)?;

    let invalid_profile = json!({
        "representation": "rendered_dom",
        "source_format": "json",
        "schema": "html5",
        "epoch": EPOCH
    });
    assert!(serde_json::from_value::<DocumentProfile>(invalid_profile).is_err());

    let profile_with_unknown_field = json!({
        "representation": "rendered_dom",
        "source_format": "json",
        "schema": "yosoi_rendered_dom_v1",
        "epoch": EPOCH,
        "unknown": true
    });
    assert!(serde_json::from_value::<DocumentProfile>(profile_with_unknown_field).is_err());

    let source_html = Document::html(
        "source.html",
        b"<html><body>source HTML</body></html>".to_vec(),
    )?;
    assert!(RenderedDomDocument::parse(&source_html, generous_limits()?).is_err());

    let ax_document = Document::accessibility_tree(
        "accessibility.json",
        DocumentEpoch::try_from(EPOCH)?,
        serde_json::to_vec(&json!({}))?,
    )?;
    assert!(RenderedDomDocument::parse(&ax_document, generous_limits()?).is_err());
    Ok(())
}

#[test]
fn rendered_dom_rejects_invalid_graphs_names_and_attributes() -> Result<(), Box<dyn Error>> {
    let mut duplicate_id = fixture();
    let nodes = duplicate_id
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?;
    let duplicate = nodes
        .iter()
        .find(|node| node.get("id").and_then(Value::as_u64) == Some(40))
        .cloned()
        .ok_or_else(|| IoError::other("fixture html node is missing"))?;
    nodes.push(duplicate);
    reject_wire(duplicate_id)?;

    let mut disconnected = fixture();
    let nodes = disconnected
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?;
    nodes.push(json!({ "kind": "document", "id": 901, "parent": null, "children": [902] }));
    nodes.push(
        json!({ "kind": "text", "id": 902, "parent": 901, "children": [], "value": "detached" }),
    );
    reject_wire(disconnected)?;

    let mut cyclic = fixture();
    let nodes = cyclic
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?;
    nodes.push(json!({ "kind": "element", "id": 901, "parent": 902, "children": [902], "namespace_uri": HTML_NAMESPACE, "tag_name": "a", "attributes": [] }));
    nodes.push(json!({ "kind": "element", "id": 902, "parent": 901, "children": [901], "namespace_uri": HTML_NAMESPACE, "tag_name": "b", "attributes": [] }));
    reject_wire(cyclic)?;

    let mut mismatched_edges = fixture();
    node_mut(&mut mismatched_edges, 900)?
        .get_mut("children")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("document children are missing"))?
        .retain(|child| child.as_u64() != Some(40));
    reject_wire(mismatched_edges)?;

    let mut text_with_children = fixture();
    node_mut(&mut text_with_children, 100)?["children"] = json!([999]);
    text_with_children
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?
        .push(
            json!({ "kind": "text", "id": 999, "parent": 100, "children": [], "value": "child" }),
        );
    reject_wire(text_with_children)?;

    let mut empty_tag = fixture();
    node_mut(&mut empty_tag, 40)?["tag_name"] = json!("");
    reject_wire(empty_tag)?;

    let mut nul_tag = fixture();
    node_mut(&mut nul_tag, 40)?["tag_name"] = json!("bad\u{0000}name");
    reject_wire(nul_tag)?;

    let mut nul_attribute = fixture();
    let attributes = node_mut(&mut nul_attribute, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    *attributes = vec![json!({
        "namespace_uri": "",
        "name": "bad\u{0000}name",
        "value": "invalid"
    })];
    reject_wire(nul_attribute)?;

    let mut duplicate_attribute = fixture();
    let attributes = node_mut(&mut duplicate_attribute, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    attributes.insert(
        1,
        json!({ "namespace_uri": "", "name": "class", "value": "duplicate" }),
    );
    reject_wire(duplicate_attribute)?;

    let mut case_duplicate_attribute = fixture();
    let attributes = node_mut(&mut case_duplicate_attribute, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    attributes.insert(
        0,
        json!({ "namespace_uri": "", "name": "CLASS", "value": "duplicate" }),
    );
    reject_wire(case_duplicate_attribute)?;

    let mut empty_attribute_name = fixture();
    let attributes = node_mut(&mut empty_attribute_name, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    *attributes = vec![json!({ "namespace_uri": "", "name": "", "value": "invalid" })];
    reject_wire(empty_attribute_name)?;

    let mut unsorted_attributes = fixture();
    let attributes = node_mut(&mut unsorted_attributes, 70)?
        .get_mut("attributes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("article attributes are missing"))?;
    attributes.swap(0, 1);
    reject_wire(unsorted_attributes)?;
    Ok(())
}

#[test]
fn rendered_dom_document_node_has_exactly_one_element_child() -> Result<(), Box<dyn Error>> {
    let mut zero_children = fixture();
    zero_children
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?
        .retain(|node| node.get("id").and_then(Value::as_u64) == Some(900));
    node_mut(&mut zero_children, 900)?["children"] = json!([]);
    assert!(parse_wire(&zero_children, EPOCH, generous_limits()?).is_err());

    let mut direct_text_child = fixture();
    let nodes = direct_text_child
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?;
    nodes.retain(|node| node.get("id").and_then(Value::as_u64) == Some(900));
    nodes.push(json!({
        "kind": "text",
        "id": 901,
        "parent": 900,
        "children": [],
        "value": "direct text"
    }));
    node_mut(&mut direct_text_child, 900)?["children"] = json!([901]);
    assert!(parse_wire(&direct_text_child, EPOCH, generous_limits()?).is_err());

    let mut multiple_element_children = fixture();
    node_mut(&mut multiple_element_children, 900)?["children"] = json!([40, 901]);
    multiple_element_children
        .get_mut("nodes")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| IoError::other("fixture nodes are missing"))?
        .push(json!({
            "kind": "element",
            "id": 901,
            "parent": 900,
            "children": [],
            "namespace_uri": HTML_NAMESPACE,
            "tag_name": "html",
            "attributes": []
        }));
    assert!(parse_wire(&multiple_element_children, EPOCH, generous_limits()?).is_err());

    assert!(parse_wire(&fixture(), EPOCH, generous_limits()?).is_ok());
    Ok(())
}

#[test]
fn rendered_dom_enforces_parse_and_locate_limits() -> Result<(), Box<dyn Error>> {
    let wire = fixture();
    assert!(
        parse_wire(
            &wire,
            EPOCH,
            limits(1, 1_000, 1_000_000, 65_536, 256, 64, 100, 1_024, 1_000_000)?,
        )
        .is_err()
    );
    assert!(
        parse_wire(
            &wire,
            EPOCH,
            limits(
                1_000_000, 4, 1_000_000, 65_536, 256, 64, 100, 1_024, 1_000_000
            )?,
        )
        .is_err()
    );
    assert!(
        parse_wire(
            &wire,
            EPOCH,
            limits(
                1_000_000, 1_000, 1_000_000, 65_536, 256, 64, 100, 1, 1_000_000
            )?,
        )
        .is_err()
    );

    let document = document(&wire, EPOCH)?;
    let items = Plan::new([output("items", css("article.product")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(
            &items,
            limits(
                1_000_000, 1_000, 1_000_000, 4, 256, 64, 100, 1_024, 1_000_000
            )?,
        ),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QueryBytes,
                maximum: 4,
                ..
            }
        }
    ));

    let region_query = css("article.product")?.each_as_region("product")?;
    let region_plan = Plan::new([output("names", region_query.find(css(".name")?).text())?])?;
    assert!(matches!(
        document.locate_with_budget(
            &region_plan,
            limits(
                1_000_000, 1_000, 1_000_000, 65_536, 1, 64, 100, 1_024, 1_000_000
            )?,
        ),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 1,
                ..
            }
        }
    ));

    let match_limited = Plan::new([output("items", css("article.product")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(
            &match_limited,
            limits(
                1_000_000, 1_000, 1_000_000, 65_536, 256, 64, 1, 1_024, 1_000_000,
            )?,
        ),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                ..
            }
        }
    ));

    let output_limited = Plan::new([output("names", css(".name")?.text())?])?;
    assert!(matches!(
        document.locate_with_budget(
            &output_limited,
            limits(1_000_000, 1_000, 1_000_000, 65_536, 256, 64, 100, 1_024, 1,)?,
        ),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                ..
            }
        }
    ));
    Ok(())
}

#[test]
fn selector_visit_limit_fails_instead_of_returning_no_match() -> Result<(), Box<dyn Error>> {
    let document = document(&fixture(), EPOCH)?;
    let query = css("article.product > .absent")?;

    let complete_no_match = Plan::new([output("missing", query.clone().text())?])?;
    assert!(matches!(
        document.locate(&complete_no_match),
        LocateOutcome::NoMatch { .. }
    ));

    let visit_limited = Plan::new([output("missing", query.text())?])?;
    assert!(matches!(
        document.locate_with_budget(
            &visit_limited,
            limits(1_000_000, 1_000, 1, 65_536, 256, 64, 100, 1_024, 1_000_000,)?,
        ),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                ..
            }
        }
    ));
    Ok(())
}
