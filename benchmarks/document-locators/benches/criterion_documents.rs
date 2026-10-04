#![allow(
    clippy::absolute_paths,
    clippy::as_conversions,
    clippy::arithmetic_side_effects,
    clippy::option_if_let_else,
    clippy::panic,
    clippy::unwrap_used,
    reason = "benchmark setup fails fast when the committed fixture or plan is invalid"
)]

use std::{env, fs, hint::black_box, path::PathBuf};

use criterion::{BenchmarkId, Criterion, criterion_group, criterion_main};
use yosoi_documents::{Document, Plan, ResourceBudget, output, regex};

const ADVANCED_FIXTURE_DIR: &str = "YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR";
const ADVANCED_TEXT_RELATIVE_PATH: &str = "derived/whatwg-html-standard.txt";

fn fixture_path(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../fixtures/document-locators/v1")
        .join(relative)
}

fn document_and_query() -> (Document, String, &'static str) {
    let advanced = env::var_os(ADVANCED_FIXTURE_DIR)
        .map(PathBuf::from)
        .map(|root| root.join(ADVANCED_TEXT_RELATIVE_PATH));
    let (bytes, expression, fixture_label) = match advanced {
        Some(path) => (
            fs::read(&path).unwrap_or_else(|error| {
                panic!(
                    "read explicitly selected advanced text fixture {}: {error}",
                    path.display()
                )
            }),
            r"(?P<term>HTML Standard)".to_owned(),
            "advanced_whatwg",
        ),
        None => (
            fs::read(fixture_path("golden/orders.txt"))
                .unwrap_or_else(|error| panic!("read golden text: {error}")),
            r"Order\s+#(?P<id>\d+)".to_owned(),
            "golden_orders",
        ),
    };
    let document = Document::text("document-benchmark", bytes)
        .unwrap_or_else(|error| panic!("construct source-text document: {error}"));
    (document, expression, fixture_label)
}

fn locator_plan(expression: &str) -> Plan {
    let named_output = output(
        "matches",
        regex(expression)
            .unwrap_or_else(|error| panic!("author regex query: {error}"))
            .text(),
    )
    .unwrap_or_else(|error| panic!("author text output: {error}"));
    Plan::new([named_output]).unwrap_or_else(|error| panic!("construct text locator plan: {error}"))
}

fn document_locator(c: &mut Criterion) {
    let (document, expression, fixture_label) = document_and_query();
    let plan = locator_plan(&expression);
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .unwrap_or_else(|error| panic!("parse text fixture: {error}"));
    let mut group = c.benchmark_group("document_locator");
    group.bench_function(BenchmarkId::new("parse", fixture_label), |b| {
        b.iter(|| {
            black_box(
                black_box(&document)
                    .parse_with_budget(budget)
                    .unwrap_or_else(|error| panic!("parse text fixture: {error}")),
            );
        });
    });
    group.bench_function(BenchmarkId::new("locate", fixture_label), |b| {
        b.iter(|| black_box(parsed.locate(black_box(&plan))));
    });
    group.bench_function(BenchmarkId::new("end_to_end", fixture_label), |b| {
        b.iter(|| {
            black_box(black_box(&document).locate_with_budget(black_box(&plan), budget));
        });
    });
    group.finish();
}

criterion_group!(benches, document_locator);
criterion_main!(benches);
