#![allow(
    clippy::panic_in_result_fn,
    reason = "focused black-box conformance tests use assertions while propagating fixture errors"
)]

use crate::internal::documents as internal_documents;
use std::{error::Error, io};

use crate::internal::documents::{
    Document, DocumentClass, DocumentEpoch, LocateFailure, LocateOutcome, Plan, ProjectedValue,
    css, output,
};
use serde_json::json;

const HTML_NAMESPACE: &str = "http://www.w3.org/1999/xhtml";

fn card_plan() -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "cards",
        css("main article[class='card']")?.text(),
    )?])?)
}

fn assert_tree_results_match(document: &Document, plan: &Plan) -> Result<(), Box<dyn Error>> {
    let retained = document.parse()?.locate(plan);
    let direct = document.locate(plan);
    assert_eq!(direct, retained);

    let result = match &direct {
        LocateOutcome::Matched { result } => result,
        other => return Err(io::Error::other(format!("expected matches, got {other:?}")).into()),
    };
    assert_eq!(
        result
            .findings()
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Text("Ada".to_owned()),
            ProjectedValue::Text("Grace".to_owned()),
        ]
    );
    assert_eq!(
        result
            .findings()
            .iter()
            .map(internal_documents::Finding::order)
            .collect::<Vec<_>>(),
        vec![0, 1]
    );
    Ok(())
}

fn rendered_dom_document() -> Result<Document, Box<dyn Error>> {
    let wire = json!({
        "schema": "yosoi.rendered-dom.v1",
        "document_epoch": 7,
        "tree_model": "document_light_dom",
        "root": 1,
        "nodes": [
            { "kind": "document", "id": 1, "parent": null, "children": [2] },
            { "kind": "element", "id": 2, "parent": 1, "children": [3], "namespace_uri": HTML_NAMESPACE, "tag_name": "html", "attributes": [] },
            { "kind": "element", "id": 3, "parent": 2, "children": [4], "namespace_uri": HTML_NAMESPACE, "tag_name": "body", "attributes": [] },
            { "kind": "element", "id": 4, "parent": 3, "children": [5, 7], "namespace_uri": HTML_NAMESPACE, "tag_name": "main", "attributes": [] },
            { "kind": "element", "id": 5, "parent": 4, "children": [6], "namespace_uri": HTML_NAMESPACE, "tag_name": "article", "attributes": [{ "namespace_uri": "", "name": "class", "value": "card" }] },
            { "kind": "text", "id": 6, "parent": 5, "children": [], "value": "Ada" },
            { "kind": "element", "id": 7, "parent": 4, "children": [8], "namespace_uri": HTML_NAMESPACE, "tag_name": "article", "attributes": [{ "namespace_uri": "", "name": "class", "value": "card" }] },
            { "kind": "text", "id": 8, "parent": 7, "children": [], "value": "Grace" }
        ]
    });
    Ok(Document::rendered_dom(
        "rendered-dom.json",
        DocumentEpoch::try_from(7)?,
        serde_json::to_vec(&wire)?,
    )?)
}

#[test]
fn two_step_css_results_agree_for_html_xml_and_rendered_dom() -> Result<(), Box<dyn Error>> {
    let plan = card_plan()?;
    let html = Document::html(
        "cards.html",
        b"<!doctype html><html><body><main><article class='card'>Ada</article><article class='card'>Grace</article></main></body></html>".to_vec(),
    )?;
    let xml = Document::xml(
        "cards.xml",
        b"<main><article class='card'>Ada</article><article class='card'>Grace</article></main>"
            .to_vec(),
    )?;
    let rendered_dom = rendered_dom_document()?;

    for document in [&html, &xml, &rendered_dom] {
        assert_tree_results_match(document, &plan)?;
    }
    Ok(())
}

fn assert_css_plan_is_unsupported(document: &Document, class: DocumentClass, plan: &Plan) {
    assert_eq!(
        document.locate(plan),
        LocateOutcome::Failed {
            failure: LocateFailure::UnsupportedCombination { document: class },
        }
    );
}

#[test]
fn css_plan_is_rejected_for_json_text_and_accessibility_documents() -> Result<(), Box<dyn Error>> {
    let plan = card_plan()?;
    let json = Document::json("not-a-tree.json", b"{".to_vec())?;
    let text = Document::text("not-a-tree.txt", b"plain text".to_vec())?;
    let accessibility = Document::accessibility_tree(
        "not-a-tree.ax.json",
        DocumentEpoch::try_from(7)?,
        b"{".to_vec(),
    )?;

    assert_css_plan_is_unsupported(&json, DocumentClass::SourceJson, &plan);
    assert_css_plan_is_unsupported(&text, DocumentClass::SourceText, &plan);
    assert_css_plan_is_unsupported(&accessibility, DocumentClass::AccessibilityTree, &plan);
    Ok(())
}
