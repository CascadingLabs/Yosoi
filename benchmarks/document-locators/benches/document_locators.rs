#![allow(
    clippy::panic,
    clippy::unwrap_used,
    reason = "benchmark setup must fail immediately when its fixed local contract is invalid"
)]

use criterion::{BenchmarkId, Criterion, criterion_group, criterion_main};
use std::{env, fs, hint::black_box, path::PathBuf};
use yosoi_dev_support::internal::documents::{
    Document, DocumentEpoch, Plan, RENDERED_DOM_SCHEMA_V1, ResourceBudget, css, output,
};

const PRODUCTS_HTML: &[u8] =
    include_bytes!("../../fixtures/document-locators/v1/golden/products.html");
const RENDERED_DOM_GOLDEN: &[u8] =
    include_bytes!("../../fixtures/document-locators/v1/golden/rendered-dom.json");
const ADVANCED_RENDERED_DOM_DIR: &str = "YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR";
const ADVANCED_RENDERED_DOM_RELATIVE_PATH: &str = "browser/wcag22/rendered-dom-v1.json";

fn inputs() -> (Document, Plan) {
    let document = Document::html("golden-products.html", PRODUCTS_HTML.to_vec())
        .unwrap_or_else(|error| panic!("create golden source HTML document: {error}"));
    let products = output(
        "products",
        css("article.product")
            .unwrap_or_else(|error| panic!("author golden CSS locator: {error}"))
            .text(),
    )
    .unwrap_or_else(|error| panic!("add golden HTML output: {error}"));
    let plan =
        Plan::new([products]).unwrap_or_else(|error| panic!("construct golden HTML plan: {error}"));
    (document, plan)
}

fn html_source_phases(criterion: &mut Criterion) {
    let (document, plan) = inputs();
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .unwrap_or_else(|error| panic!("parse golden HTML setup: {error}"));
    let mut group = criterion.benchmark_group("document_locator_html");
    group.bench_function(BenchmarkId::new("parse", "golden_products"), |bencher| {
        bencher.iter(|| {
            black_box(
                document
                    .parse_with_budget(black_box(budget))
                    .unwrap_or_else(|error| panic!("parse golden HTML: {error}")),
            )
        });
    });
    group.bench_function(BenchmarkId::new("locate", "golden_products"), |bencher| {
        bencher.iter(|| black_box(parsed.locate(black_box(&plan))));
    });
    group.bench_function(
        BenchmarkId::new("end_to_end", "golden_products"),
        |bencher| {
            bencher.iter(|| {
                black_box(black_box(&document).locate_with_budget(black_box(&plan), budget));
            });
        },
    );
    group.finish();
}

fn rendered_dom_document(id: &str, bytes: &[u8]) -> Document {
    let header: serde_json::Value = serde_json::from_slice(bytes)
        .unwrap_or_else(|error| panic!("read rendered-DOM fixture header: {error}"));
    let schema = header
        .get("schema")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_else(|| panic!("rendered-DOM fixture has no schema string"));
    assert_eq!(
        schema, RENDERED_DOM_SCHEMA_V1,
        "rendered-DOM fixture schema mismatch"
    );
    let epoch_value = header
        .get("document_epoch")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or_else(|| panic!("rendered-DOM fixture has no unsigned document epoch"));
    let epoch = DocumentEpoch::try_from(epoch_value)
        .unwrap_or_else(|error| panic!("invalid rendered-DOM document epoch: {error}"));
    Document::rendered_dom(id, epoch, bytes.to_vec())
        .unwrap_or_else(|error| panic!("create rendered-DOM benchmark document: {error}"))
}

fn rendered_dom_plan() -> Plan {
    let button_text = output(
        "buy_button_text",
        css("button.buy-now")
            .unwrap_or_else(|error| panic!("author golden rendered-DOM CSS locator: {error}"))
            .text(),
    )
    .unwrap_or_else(|error| panic!("add golden rendered-DOM output: {error}"));
    Plan::new([button_text])
        .unwrap_or_else(|error| panic!("construct golden rendered-DOM plan: {error}"))
}

fn rendered_dom_phases(criterion: &mut Criterion) {
    let document = rendered_dom_document("golden-rendered-dom-products", RENDERED_DOM_GOLDEN);
    let plan = rendered_dom_plan();
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .unwrap_or_else(|error| panic!("parse golden rendered-DOM setup: {error}"));
    let mut group = criterion.benchmark_group("document_locator_rendered_dom");
    group.bench_function(BenchmarkId::new("parse", "golden_products"), |bencher| {
        bencher.iter(|| {
            black_box(
                document
                    .parse_with_budget(black_box(budget))
                    .unwrap_or_else(|error| panic!("parse golden rendered DOM: {error}")),
            )
        });
    });
    group.bench_function(BenchmarkId::new("locate", "golden_products"), |bencher| {
        bencher.iter(|| black_box(parsed.locate(black_box(&plan))));
    });
    group.bench_function(
        BenchmarkId::new("end_to_end", "golden_products"),
        |bencher| {
            bencher.iter(|| {
                black_box(black_box(&document).locate_with_budget(black_box(&plan), budget));
            });
        },
    );
    group.finish();
}

fn advanced_rendered_dom_parse(criterion: &mut Criterion) {
    let Some(materialized_root) = env::var_os(ADVANCED_RENDERED_DOM_DIR) else {
        return;
    };
    let fixture_path = PathBuf::from(materialized_root).join(ADVANCED_RENDERED_DOM_RELATIVE_PATH);
    let bytes = fs::read(&fixture_path).unwrap_or_else(|error| {
        panic!(
            "read official materialized rendered-DOM fixture {}: {error}",
            fixture_path.display()
        )
    });
    let document = rendered_dom_document("advanced-wcag-rendered-dom-v1", &bytes);
    let budget = ResourceBudget::conservative();
    let _parsed = document.parse_with_budget(budget).unwrap_or_else(|error| {
        panic!(
            "validate official materialized rendered-DOM fixture {}: {error}",
            fixture_path.display()
        )
    });
    let mut group = criterion.benchmark_group("document_locator_rendered_dom");
    group.bench_function(BenchmarkId::new("parse", "advanced_wcag"), |bencher| {
        bencher.iter(|| {
            black_box(
                document
                    .parse_with_budget(black_box(budget))
                    .unwrap_or_else(|error| panic!("parse advanced rendered DOM: {error}")),
            )
        });
    });
    group.finish();
}

criterion_group!(
    benches,
    html_source_phases,
    rendered_dom_phases,
    advanced_rendered_dom_parse
);
criterion_main!(benches);
