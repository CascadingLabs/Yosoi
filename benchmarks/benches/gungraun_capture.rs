//! One-shot deterministic CPU, cache, and heap measurements for representative capture stages.
//!
//! Criterion remains the wall-clock suite. Gungraun runs these narrower cases under
//! Callgrind so instruction and modeled-cache estimates are not inferred from timing.
//! Heap profiling runs separately because measurement instrumentation must not overlap.
#![allow(
    dead_code,
    clippy::absolute_paths,
    clippy::arithmetic_side_effects,
    clippy::as_conversions,
    clippy::cast_possible_truncation,
    clippy::exit,
    clippy::missing_panics_doc,
    clippy::needless_pass_by_value,
    clippy::panic,
    clippy::unwrap_used,
    clippy::wildcard_imports,
    reason = "benchmark harness macros and shared fail-fast setup are not production code"
)]

extern crate gungraun;

use std::hint::black_box;

use gungraun::prelude::*;
use yosoi_types::Sha256Digest;
use yosoi_web_capture_direct_http::{
    BoundedAcquisitionLifecycle, CaptureBundle, LifecycleFinalizationInput,
    ResolvedDirectHttpCaptureSpec, WebCapture, WebCaptureWire, finalize_direct_http_attempt,
};

use yosoi_benchmarks::support as capture_stages_support;
#[path = "criterion_capture/finalization_setup.rs"]
mod finalization_setup;

fn large_html_bytes() -> Vec<u8> {
    capture_stages_support::bytes(&capture_stages_support::fixture("large-html"))
}

fn canonical_capture_bytes() -> Vec<u8> {
    WebCaptureWire::to_canonical_json(&capture_stages_support::capture_fixture())
        .unwrap_or_else(|error| panic!("canonical capture setup: {error}"))
}

fn capture_model() -> WebCapture {
    capture_stages_support::capture_fixture()
}

fn finalization_input() -> (
    ResolvedDirectHttpCaptureSpec,
    BoundedAcquisitionLifecycle,
    LifecycleFinalizationInput,
) {
    let source = large_html_bytes();
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

#[library_benchmark(setup = large_html_bytes)]
fn sha256_large_html(bytes: Vec<u8>) -> Sha256Digest {
    black_box(Sha256Digest::digest(black_box(&bytes)))
}

#[library_benchmark(setup = capture_model)]
fn serialize_canonical_capture(capture: WebCapture) -> Vec<u8> {
    black_box(
        WebCaptureWire::to_canonical_json(black_box(&capture))
            .unwrap_or_else(|error| panic!("canonical serialization: {error}")),
    )
}

#[library_benchmark(setup = canonical_capture_bytes)]
fn deserialize_canonical_capture(bytes: Vec<u8>) -> WebCapture {
    black_box(
        WebCaptureWire::from_json(black_box(&bytes))
            .unwrap_or_else(|error| panic!("canonical deserialization: {error}")),
    )
}

#[library_benchmark(setup = finalization_input)]
fn finalize_large_source(
    (spec, lifecycle, input): (
        ResolvedDirectHttpCaptureSpec,
        BoundedAcquisitionLifecycle,
        LifecycleFinalizationInput,
    ),
) -> CaptureBundle {
    black_box(
        finalize_direct_http_attempt(spec, lifecycle, black_box(input))
            .unwrap_or_else(|error| panic!("capture finalization: {error}")),
    )
}

library_benchmark_group!(
    name = deterministic_capture_stages;
    benchmarks =
        sha256_large_html,
        serialize_canonical_capture,
        deserialize_canonical_capture,
        finalize_large_source
);

main!(library_benchmark_groups = deterministic_capture_stages);
