//! Allocation evidence for one end-to-end golden locate per document modality.
#![allow(
    clippy::panic,
    clippy::unwrap_used,
    reason = "benchmark setup fails fast when committed fixtures or plans are invalid"
)]

use divan::{AllocProfiler, Bencher, black_box};
use yosoi_documents::{
    Document, DocumentEpoch, OutputPlan, Plan, ResourceBudget, css, json_path, json_pointer,
    output, regex, role, xpath,
};

#[global_allocator]
static ALLOCATOR: AllocProfiler = AllocProfiler::system();

const HTML: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/products.html");
const XML: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/catalog.xml");
const JSON: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/product.json");
const DOM: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/rendered-dom.json");
const AX: &[u8] =
    include_bytes!("../../fixtures/document-locators/v1/golden/accessibility-tree.json");
const TEXT: &[u8] = include_bytes!("../../fixtures/document-locators/v1/golden/orders.txt");

fn locator_plan(id: &str, selection: OutputPlan) -> Plan {
    let named_output = output(id, selection)
        .unwrap_or_else(|error| panic!("author named locator output: {error}"));
    Plan::new([named_output]).unwrap_or_else(|error| panic!("construct locator plan: {error}"))
}

fn main() {
    divan::main();
}

#[divan::bench]
fn html_end_to_end(bencher: Bencher<'_, '_>) {
    let document = Document::html("html", HTML.to_vec())
        .unwrap_or_else(|error| panic!("construct HTML document: {error}"));
    let plan = locator_plan(
        "products",
        css("article.product")
            .unwrap_or_else(|error| panic!("author HTML CSS: {error}"))
            .text(),
    );
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}

#[divan::bench]
fn xml_end_to_end(bencher: Bencher<'_, '_>) {
    let document = Document::xml("xml", XML.to_vec())
        .unwrap_or_else(|error| panic!("construct XML document: {error}"));
    let plan = locator_plan(
        "currencies",
        xpath("/catalog/product/price")
            .unwrap_or_else(|error| panic!("author XML XPath: {error}"))
            .attribute("currency")
            .unwrap_or_else(|error| panic!("author currency attribute: {error}")),
    );
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}

#[divan::bench]
fn json_end_to_end(bencher: Bencher<'_, '_>) {
    let document = Document::json("json", JSON.to_vec())
        .unwrap_or_else(|error| panic!("construct JSON document: {error}"));
    let currency = output(
        "currency",
        json_pointer("/currency")
            .unwrap_or_else(|error| panic!("author JSON Pointer: {error}"))
            .value(),
    )
    .unwrap_or_else(|error| panic!("author JSON output: {error}"));
    let prices = output(
        "prices",
        json_path("$.products[*].price")
            .unwrap_or_else(|error| panic!("author JSONPath: {error}"))
            .value(),
    )
    .unwrap_or_else(|error| panic!("author JSON output: {error}"));
    let plan = Plan::new([currency, prices])
        .unwrap_or_else(|error| panic!("construct JSON plan: {error}"));
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}

#[divan::bench]
fn rendered_dom_end_to_end(bencher: Bencher<'_, '_>) {
    let epoch = DocumentEpoch::try_from(1).unwrap_or_else(|error| panic!("DOM epoch: {error}"));
    let document = Document::rendered_dom("dom", epoch, DOM.to_vec())
        .unwrap_or_else(|error| panic!("construct DOM document: {error}"));
    let plan = locator_plan(
        "button",
        css("button.buy-now")
            .unwrap_or_else(|error| panic!("author DOM CSS: {error}"))
            .text(),
    );
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}

#[divan::bench]
fn accessibility_end_to_end(bencher: Bencher<'_, '_>) {
    let epoch = DocumentEpoch::try_from(1).unwrap_or_else(|error| panic!("AX epoch: {error}"));
    let document = Document::accessibility_tree("ax", epoch, AX.to_vec())
        .unwrap_or_else(|error| panic!("construct AX document: {error}"));
    let plan = locator_plan(
        "button",
        role("button")
            .unwrap_or_else(|error| panic!("author AX role: {error}"))
            .node(),
    );
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}

#[divan::bench]
fn decoded_text_end_to_end(bencher: Bencher<'_, '_>) {
    let document = Document::text("text", TEXT.to_vec())
        .unwrap_or_else(|error| panic!("construct text document: {error}"));
    let plan = locator_plan(
        "orders",
        regex(r"Order\s+#(?P<id>\d+)")
            .unwrap_or_else(|error| panic!("author text regex: {error}"))
            .text(),
    );
    let budget = ResourceBudget::conservative();
    bencher.bench_local(|| black_box(document.locate_with_budget(black_box(&plan), budget)));
}
