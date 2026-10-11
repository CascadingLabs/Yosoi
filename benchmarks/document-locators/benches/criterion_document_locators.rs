#![allow(
    clippy::absolute_paths,
    clippy::expect_used,
    clippy::panic,
    reason = "benchmark setup fails fast when its pinned fixture contract is invalid"
)]

use std::{error::Error, hint::black_box};

use criterion::{Criterion, criterion_group, criterion_main};
use yosoi_dev_support::internal::documents::{
    AccessibilityStateName, Document, DocumentEpoch, OutputPlan, Plan, ResourceBudget,
    accessibility_state, accessibility_text, accessible_name, css, output, role,
};

const CATALOG_XML: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/catalog.xml");
const LOCATOR_MATRIX: &str = include_str!("../../fixtures/document-locators/v1/matrix.json");
const ACCESSIBILITY_FIXTURE: &[u8] =
    include_bytes!("../../fixtures/document-locators/v1/golden/accessibility-tree.json");

struct AccessibilityCase {
    id: &'static str,
    plan: Plan,
}

fn require_xml_oracles_locked() {
    let matrix: serde_json::Value =
        serde_json::from_str(LOCATOR_MATRIX).expect("locator matrix must be valid JSON");
    let cases = matrix
        .get("advanced_cases")
        .and_then(serde_json::Value::as_array)
        .expect("locator matrix must contain advanced cases");
    for required_id in ["xml_css", "xml_xpath", "xml_text"] {
        let case = cases
            .iter()
            .find(|case| case.get("id").and_then(serde_json::Value::as_str) == Some(required_id))
            .expect("all XML advanced oracle cases must be present");
        let state: &str = case
            .get("expectation_state")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        assert!(
            state.starts_with("verified-")
                && case
                    .get("expected")
                    .is_some_and(|expected| !expected.is_null()),
            "XML advanced oracle {required_id} must be locked before benchmarking"
        );
    }
}

fn document() -> Document {
    Document::xml("golden-xml-catalog", CATALOG_XML.to_vec())
        .expect("pinned XML fixture must create a document")
}

fn product_plan() -> Plan {
    let products = output(
        "products",
        css("product")
            .expect("static XML CSS query must be non-empty")
            .text(),
    )
    .expect("static XML output identity must be valid");
    Plan::new([products]).expect("static XML locator plan must be valid")
}

fn parse(c: &mut Criterion) {
    require_xml_oracles_locked();
    let document = document();
    let budget = ResourceBudget::conservative();
    c.bench_function("document_locator/xml/parse", |bencher| {
        bencher.iter(|| {
            let parsed = black_box(&document)
                .parse_with_budget(black_box(budget))
                .expect("pinned XML fixture must parse");
            black_box(parsed);
        });
    });
}

fn locate(c: &mut Criterion) {
    require_xml_oracles_locked();
    let document = document();
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .expect("pinned XML fixture must parse");
    let plan = product_plan();
    c.bench_function("document_locator/xml/locate", |bencher| {
        bencher.iter(|| black_box(parsed.locate(&plan)));
    });
}

fn end_to_end(c: &mut Criterion) {
    require_xml_oracles_locked();
    let document = document();
    let plan = product_plan();
    let budget = ResourceBudget::conservative();
    c.bench_function("document_locator/xml/end_to_end", |bencher| {
        bencher.iter(|| {
            black_box(black_box(&document).locate_with_budget(black_box(&plan), budget));
        });
    });
}

fn accessibility_document() -> Result<Document, Box<dyn Error>> {
    let epoch = DocumentEpoch::try_from(1)?;
    Ok(Document::accessibility_tree(
        "benchmark-products.ax",
        epoch,
        ACCESSIBILITY_FIXTURE.to_vec(),
    )?)
}

fn compile_accessibility_case(
    id: &'static str,
    selection: OutputPlan,
) -> Result<AccessibilityCase, Box<dyn Error>> {
    let result = output("result", selection)?;
    let plan = Plan::new([result])?;
    Ok(AccessibilityCase { id, plan })
}

fn accessibility_cases() -> Result<Vec<AccessibilityCase>, Box<dyn Error>> {
    Ok(vec![
        compile_accessibility_case("ax_role", role("button")?.node())?,
        compile_accessibility_case("ax_name", accessible_name("Buy now")?.name())?,
        compile_accessibility_case("ax_text", accessibility_text("Buy now")?.text())?,
        compile_accessibility_case(
            "ax_state",
            accessibility_state(AccessibilityStateName::Expanded, true).node(),
        )?,
    ])
}

fn accessibility_tree_phases(criterion: &mut Criterion) {
    let document = accessibility_document()
        .unwrap_or_else(|error| panic!("create AX benchmark document: {error}"));
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .unwrap_or_else(|error| panic!("parse AX benchmark fixture: {error}"));
    let cases =
        accessibility_cases().unwrap_or_else(|error| panic!("compile AX benchmark plans: {error}"));

    criterion.bench_function(
        "document_locator/ax/parse/golden_accessibility_tree",
        |bencher| {
            bencher.iter(|| {
                let parsed = document
                    .parse_with_budget(black_box(budget))
                    .unwrap_or_else(|error| panic!("parse AX fixture: {error}"));
                black_box(parsed);
            });
        },
    );

    for case in &cases {
        let locate_id = format!("document_locator/ax/locate/{}", case.id);
        criterion.bench_function(&locate_id, |bencher| {
            bencher.iter(|| black_box(parsed.locate(black_box(&case.plan))));
        });

        let end_to_end_id = format!("document_locator/ax/end_to_end/{}", case.id);
        criterion.bench_function(&end_to_end_id, |bencher| {
            bencher.iter(|| {
                black_box(black_box(&document).locate_with_budget(black_box(&case.plan), budget));
            });
        });
    }
}

criterion_group!(
    benches,
    parse,
    locate,
    end_to_end,
    accessibility_tree_phases,
);
criterion_main!(benches);
