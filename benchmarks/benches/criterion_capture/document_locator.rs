use criterion::{Criterion, Throughput};
use std::{fs, hint::black_box, path::PathBuf};
use yosoi_documents::{
    Document, DocumentProfile, EvaluationLimits, evaluate_json, json_path, json_pointer,
    json_value, parse_json_document, plan,
};

pub fn json_document_locator_phases(c: &mut Criterion) {
    let fixture_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures/document-locators/v1/golden/product.json");
    let bytes = fs::read(&fixture_path)
        .unwrap_or_else(|error| panic!("read JSON document-locator fixture: {error}"));
    let document = Document::try_new(
        "golden-json-products",
        DocumentProfile::source_json(),
        bytes,
    )
    .unwrap_or_else(|error| panic!("construct JSON benchmark document: {error}"));
    let limits = EvaluationLimits::conservative();
    let locator_plan = plan()
        .emit(
            "currency",
            json_pointer("/currency")
                .unwrap_or_else(|error| panic!("construct JSON Pointer: {error}"))
                .project(json_value()),
        )
        .unwrap_or_else(|error| panic!("add currency output: {error}"))
        .emit(
            "prices",
            json_path("$.products[*].price")
                .unwrap_or_else(|error| panic!("construct JSONPath: {error}"))
                .project(json_value()),
        )
        .unwrap_or_else(|error| panic!("add price output: {error}"))
        .compile(limits)
        .unwrap_or_else(|error| panic!("compile JSON benchmark plan: {error}"));
    let parsed = parse_json_document(&document, limits)
        .unwrap_or_else(|error| panic!("parse JSON benchmark fixture: {error}"));

    let mut parse = c.benchmark_group("document_locator_json_parse");
    parse.throughput(Throughput::Bytes(document.byte_len()));
    parse.bench_function("golden_product_json", |b| {
        b.iter(|| {
            let value = parse_json_document(black_box(&document), limits)
                .unwrap_or_else(|error| panic!("parse JSON fixture: {error}"));
            black_box(value)
        })
    });
    parse.finish();

    let mut locate = c.benchmark_group("document_locator_json_locate");
    locate.throughput(Throughput::Bytes(document.byte_len()));
    locate.bench_function("golden_pointer_and_jsonpath", |b| {
        b.iter(|| black_box(parsed.evaluate(black_box(&locator_plan))))
    });
    locate.finish();

    let mut end_to_end = c.benchmark_group("document_locator_json_end_to_end");
    end_to_end.throughput(Throughput::Bytes(document.byte_len()));
    end_to_end.bench_function("golden_pointer_and_jsonpath", |b| {
        b.iter(|| {
            black_box(evaluate_json(
                black_box(&document),
                black_box(&locator_plan),
            ))
        })
    });
    end_to_end.finish();
}
