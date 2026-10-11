//! Allocation-count and allocated-byte measurements for representative synchronous stages.
//!
//! Divan's allocator instrumentation perturbs timing, so these results are allocation
//! evidence only. Callgrind and Criterion remain separate measurement runs.
#![allow(
    dead_code,
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::as_conversions,
    clippy::cast_possible_truncation,
    clippy::missing_panics_doc,
    clippy::panic,
    clippy::unwrap_used,
    clippy::wildcard_imports,
    reason = "benchmark harness and shared fail-fast setup are not production code"
)]

use divan::{AllocProfiler, Bencher, black_box};
use yosoi_dev_support::internal::direct_http::{
    BoundedAcquisitionLifecycle, LifecycleFinalizationInput, ResolvedDirectHttpCaptureSpec,
    WebCaptureWire, finalize_direct_http_attempt,
};
use yosoi_dev_support::internal::types::Sha256Digest;

#[global_allocator]
static ALLOCATOR: AllocProfiler = AllocProfiler::system();

use yosoi_benchmarks::support as capture_stages_support;
#[path = "criterion_capture/finalization_setup.rs"]
mod finalization_setup;

fn main() {
    divan::main();
}

#[divan::bench]
fn sha256_large_html(bencher: Bencher<'_, '_>) {
    let bytes = capture_stages_support::bytes(&capture_stages_support::fixture("large-html"));
    bencher.bench_local(|| black_box(Sha256Digest::digest(black_box(&bytes))));
}

#[divan::bench]
fn serialize_canonical_capture(bencher: Bencher<'_, '_>) {
    let capture = capture_stages_support::capture_fixture();
    bencher.bench_local(|| {
        black_box(
            WebCaptureWire::to_canonical_json(black_box(&capture))
                .unwrap_or_else(|error| panic!("canonical serialization: {error}")),
        )
    });
}

#[divan::bench]
fn deserialize_canonical_capture(bencher: Bencher<'_, '_>) {
    let bytes = WebCaptureWire::to_canonical_json(&capture_stages_support::capture_fixture())
        .unwrap_or_else(|error| panic!("canonical capture setup: {error}"));
    bencher.bench_local(|| {
        black_box(
            WebCaptureWire::from_json(black_box(&bytes))
                .unwrap_or_else(|error| panic!("canonical deserialization: {error}")),
        )
    });
}

#[divan::bench]
fn finalize_large_source(bencher: Bencher<'_, '_>) {
    bencher
        .with_inputs(finalization_input)
        .bench_values(|(spec, lifecycle, input)| {
            black_box(
                finalize_direct_http_attempt(spec, lifecycle, black_box(input))
                    .unwrap_or_else(|error| panic!("capture finalization: {error}")),
            )
        });
}

fn finalization_input() -> (
    ResolvedDirectHttpCaptureSpec,
    BoundedAcquisitionLifecycle,
    LifecycleFinalizationInput,
) {
    let source = capture_stages_support::bytes(&capture_stages_support::fixture("large-html"));
    let retained_bytes = u64::try_from(source.len())
        .unwrap_or_else(|error| panic!("fixture size conversion: {error}"));
    let case = finalization_setup::Case {
        name: "complete_source_large_html".to_owned(),
        retained_bytes,
        complete_bytes: retained_bytes,
        kind: finalization_setup::CaseKind::CompleteSource,
        source,
        decoded: None,
    };
    finalization_setup::setup(&case)
}
