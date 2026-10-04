#![allow(
    clippy::panic,
    clippy::unwrap_used,
    reason = "benchmark harness reports invalid local setup immediately"
)]

use criterion::{BatchSize, BenchmarkId, Criterion, criterion_group, criterion_main};
use std::{env, hint::black_box};
use tokio::runtime::Runtime;
use yosoi_benchmarks::browser_support::{self, ArtifactSet, BrowserRunMode, LoopbackFixture};

fn label(set: ArtifactSet, mode: BrowserRunMode) -> String {
    let growth = match set {
        ArtifactSet::Minimal => "payload_139b__events_0",
        ArtifactSet::Full => "payload_244b__events_16",
        ArtifactSet::Growth => "payload_32995b__events_128",
    };
    format!(
        "artifacts_{}__{growth}__{}",
        set.label(),
        mode.native_label()
    )
}

fn selected_modes() -> Vec<BrowserRunMode> {
    match env::var("CAS333_BROWSER_MODE").as_deref() {
        Ok("native-headless") => vec![BrowserRunMode::Headless],
        Ok("native-headful") => vec![BrowserRunMode::Headful],
        Ok("both") => vec![BrowserRunMode::Headless, BrowserRunMode::Headful],
        Ok(value) => panic!(
            "CAS333_BROWSER_MODE must be native-headless, native-headful, or both; got {value}"
        ),
        Err(error) => {
            panic!(
                "CAS333_BROWSER_MODE is required and must be readable ({error}); set native-headless, native-headful, or both"
            )
        }
    }
}

fn selected_artifact_sets() -> Vec<ArtifactSet> {
    match env::var("CAS333_ARTIFACT_SET").as_deref() {
        Ok("minimal") => vec![ArtifactSet::Minimal],
        Ok("full") => vec![ArtifactSet::Full],
        Ok("growth") => vec![ArtifactSet::Growth],
        Ok("all") => vec![ArtifactSet::Minimal, ArtifactSet::Full, ArtifactSet::Growth],
        Ok(value) => {
            panic!("CAS333_ARTIFACT_SET must be minimal, full, growth, or all; got {value}")
        }
        Err(error) => {
            panic!(
                "CAS333_ARTIFACT_SET is required and must be readable ({error}); set minimal, full, growth, or all"
            )
        }
    }
}

fn browser_capture_groups(c: &mut Criterion) {
    let mut group = c.benchmark_group("browser_acquisition");
    let runtime =
        Runtime::new().unwrap_or_else(|error| panic!("create benchmark runtime: {error}"));
    for mode in selected_modes() {
        for set in selected_artifact_sets() {
            let fixture = runtime
                .block_on(LoopbackFixture::start(set))
                .unwrap_or_else(|error| panic!("start loopback fixture: {error:#}"));
            let url = fixture.url();
            let spec = browser_support::spec(&url, set, mode)
                .unwrap_or_else(|error| panic!("build browser spec: {error:#}"));
            let id = BenchmarkId::new("cold_process_capture_to_staged_facts", label(set, mode));
            group.bench_function(id, |b| {
                b.iter(|| {
                    runtime.block_on(async {
                        black_box(
                            browser_support::capture_to_staged_facts(&spec)
                                .await
                                .unwrap_or_else(|error| panic!("cold capture: {error:#}")),
                        )
                    });
                });
            });

            let warm_manager = browser_support::warm_manager(mode)
                .unwrap_or_else(|error| panic!("create warm manager: {error:#}"));
            let id = BenchmarkId::new(
                "warm_process_fresh_context_capture_to_staged_facts",
                label(set, mode),
            );
            group.bench_function(id, |b| {
                b.iter(|| {
                    runtime.block_on(async {
                        black_box(
                            browser_support::capture_to_staged_facts_managed(&warm_manager, &spec)
                                .await
                                .unwrap_or_else(|error| panic!("warm capture: {error:#}")),
                        )
                    });
                });
            });

            let id = BenchmarkId::new(
                "yosoi_browser_finalization_capture_setup_excluded",
                label(set, mode),
            );
            group.bench_function(id, |b| {
                b.iter_batched(
                    || {
                        runtime
                            .block_on(browser_support::capture_to_staged_facts(&spec))
                            .unwrap_or_else(|error| panic!("capture setup: {error:#}"))
                    },
                    |result| {
                        black_box(
                            browser_support::finalize(result)
                                .unwrap_or_else(|error| panic!("finalize: {error:#}")),
                        )
                    },
                    BatchSize::SmallInput,
                );
            });

            let id = BenchmarkId::new(
                "browser_capture_plus_finalization_end_to_end",
                label(set, mode),
            );
            group.bench_function(id, |b| {
                b.iter(|| {
                    runtime.block_on(async {
                        let result = browser_support::capture_to_staged_facts(&spec)
                            .await
                            .unwrap_or_else(|error| panic!("capture: {error:#}"));
                        black_box(
                            browser_support::finalize(result)
                                .unwrap_or_else(|error| panic!("finalize: {error:#}")),
                        )
                    });
                });
            });
            runtime
                .block_on(warm_manager.shutdown())
                .unwrap_or_else(|error| panic!("shutdown warm manager: {error}"));
        }
    }
    group.finish();
}

criterion_group!(browser, browser_capture_groups);
criterion_main!(browser);
