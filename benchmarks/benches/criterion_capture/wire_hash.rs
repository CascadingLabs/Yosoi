use crate::capture_stages_support::{bytes, manifest};
use criterion::{BenchmarkId, Criterion, Throughput};
use sha2::{Digest, Sha256};
use std::{fs, hint::black_box, path::PathBuf};
use yosoi_web_capture_direct_http::WebCaptureWire;

pub fn sha256(c: &mut Criterion) {
    let mut group = c.benchmark_group("sha256_only");
    for fixture in manifest()
        .fixtures
        .iter()
        .filter(|f| matches!(f.name.as_str(), "small-html" | "medium-html" | "large-html"))
    {
        let input = bytes(fixture);
        group.throughput(Throughput::Bytes(fixture.encoded_bytes));
        group.bench_with_input(
            BenchmarkId::new("encoded_bytes", &fixture.name),
            &input,
            |b, value| b.iter(|| black_box(Sha256::digest(black_box(value)))),
        );
    }
    group.finish();
}

pub fn canonical_wire(c: &mut Criterion) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures/web-capture/v1/complete-capture-v1.json");
    let input = fs::read(path).unwrap_or_else(|e| panic!("wire read: {e}"));
    let capture = WebCaptureWire::from_json(&input).unwrap_or_else(|e| panic!("wire parse: {e}"));
    let canonical = WebCaptureWire::to_canonical_json(&capture)
        .unwrap_or_else(|e| panic!("wire serialize: {e}"));
    let mut group = c.benchmark_group("canonical_web_capture_wire");
    group.throughput(Throughput::Bytes(canonical.len() as u64));
    group.bench_function("serialize_complete_capture", |b| {
        b.iter(|| {
            black_box(WebCaptureWire::to_canonical_json(black_box(&capture)))
                .unwrap_or_else(|e| panic!("serialize: {e}"))
        })
    });
    group.throughput(Throughput::Bytes(input.len() as u64));
    group.bench_function("deserialize_complete_capture", |b| {
        b.iter(|| {
            black_box(WebCaptureWire::from_json(black_box(&input)))
                .unwrap_or_else(|e| panic!("deserialize: {e}"))
        })
    });
    group.finish();
}
