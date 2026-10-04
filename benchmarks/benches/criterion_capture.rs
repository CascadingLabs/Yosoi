#![allow(
    clippy::absolute_paths,
    clippy::as_conversions,
    clippy::arithmetic_side_effects,
    clippy::panic,
    clippy::semicolon_if_nothing_returned,
    clippy::significant_drop_tightening,
    clippy::unwrap_used,
    clippy::wildcard_imports,
    reason = "benchmark harness fails fast on invalid committed setup"
)]

#[path = "criterion_capture/acquisition_contract.rs"]
mod acquisition_contract;
#[path = "criterion_capture/body.rs"]
mod body;
use yosoi_benchmarks::support as capture_stages_support;
#[path = "criterion_capture/finalization.rs"]
mod finalization;
#[path = "criterion_capture/finalization_setup.rs"]
mod finalization_setup;
#[path = "criterion_capture/full.rs"]
mod full;
#[path = "criterion_capture/source.rs"]
mod source;
#[path = "criterion_capture/wire_hash.rs"]
mod wire_hash;

use criterion::{criterion_group, criterion_main};

criterion_group!(
    benches,
    wire_hash::sha256,
    acquisition_contract::shared_acquisition_contracts,
    body::yosoi_body_pipeline,
    wire_hash::canonical_wire,
    source::source_classification_character_decode,
    finalization::capture_finalization_bundle,
    full::raw_full_and_redirects,
);
criterion_main!(benches);
