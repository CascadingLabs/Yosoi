#![allow(
    clippy::expect_used,
    clippy::panic,
    clippy::semicolon_if_nothing_returned,
    clippy::significant_drop_tightening,
    clippy::unwrap_used
)] // Benchmark setup fails fast; measured loops remain explicit.

use criterion::{Criterion, Throughput, criterion_group, criterion_main};
use std::{fs, hint::black_box, path::PathBuf};
use yosoi_documents::{Document, Plan, ResourceBudget, json_path, json_pointer, output};

fn json_document_locator_phases(c: &mut Criterion) {
    let fixture_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../fixtures/document-locators/v1/golden/product.json");
    let bytes = fs::read(&fixture_path)
        .unwrap_or_else(|error| panic!("read JSON document-locator fixture: {error}"));
    let document = Document::json("golden-json-products", bytes)
        .unwrap_or_else(|error| panic!("construct JSON benchmark document: {error}"));
    let currency = output(
        "currency",
        json_pointer("/currency")
            .unwrap_or_else(|error| panic!("construct JSON Pointer: {error}"))
            .value(),
    )
    .unwrap_or_else(|error| panic!("add currency output: {error}"));
    let prices = output(
        "prices",
        json_path("$.products[*].price")
            .unwrap_or_else(|error| panic!("construct JSONPath: {error}"))
            .value(),
    )
    .unwrap_or_else(|error| panic!("add price output: {error}"));
    let locator_plan = Plan::new([currency, prices])
        .unwrap_or_else(|error| panic!("construct JSON benchmark plan: {error}"));
    let budget = ResourceBudget::conservative();
    let parsed = document
        .parse_with_budget(budget)
        .unwrap_or_else(|error| panic!("parse JSON benchmark fixture: {error}"));

    let mut parse = c.benchmark_group("document_locator_json_parse");
    parse.throughput(Throughput::Bytes(document.byte_len()));
    parse.bench_function("golden_product_json", |b| {
        b.iter(|| {
            let value = black_box(&document)
                .parse_with_budget(black_box(budget))
                .unwrap_or_else(|error| panic!("parse JSON fixture: {error}"));
            black_box(value)
        })
    });
    parse.finish();

    let mut locate = c.benchmark_group("document_locator_json_locate");
    locate.throughput(Throughput::Bytes(document.byte_len()));
    locate.bench_function("golden_pointer_and_jsonpath", |b| {
        b.iter(|| black_box(parsed.locate(black_box(&locator_plan))))
    });
    locate.finish();

    let mut end_to_end = c.benchmark_group("document_locator_json_end_to_end");
    end_to_end.throughput(Throughput::Bytes(document.byte_len()));
    end_to_end.bench_function("golden_pointer_and_jsonpath", |b| {
        b.iter(|| {
            black_box(black_box(&document).locate_with_budget(black_box(&locator_plan), budget))
        })
    });
    end_to_end.finish();
}

criterion_group!(benches, json_document_locator_phases);
criterion_main!(benches);
