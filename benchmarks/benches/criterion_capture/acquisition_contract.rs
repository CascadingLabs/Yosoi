use criterion::{BatchSize, BenchmarkId, Criterion, Throughput};
use std::{hint::black_box, sync::Arc};
use void_crawl_core::{BrowserByteAccounting as ProviderByteAccounting, MeasuredBrowserBytes};
use yosoi_benchmarks::finalization_support::{FinalizationCase, plan};
use yosoi_web_capture::{
    AcquiredPayloadOutcome, ArtifactStagingOutcome, BrowserArtifactMapping, BrowserByteLayer,
    BrowserStagingFamily, ByteAccounting, ByteCount, MeasuredCount, RetainedSource,
    WebArtifactFamily,
};

fn mapping() -> BrowserArtifactMapping {
    BrowserArtifactMapping::new(
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
        BrowserByteLayer::DecodedResponseBody,
    )
    .unwrap_or_else(|error| panic!("mapping: {error}"))
}

pub fn shared_acquisition_contracts(c: &mut Criterion) {
    let mut accounting = c.benchmark_group("shared_acquisition_exact_byte_accounting");
    for observed in [0_u64, 4_096, 1_048_576] {
        accounting.throughput(Throughput::Elements(1));
        accounting.bench_function(BenchmarkId::new("web_capture", observed), |b| {
            b.iter(|| {
                black_box(ByteAccounting::new(
                    ByteCount::new(observed),
                    ByteCount::new(observed),
                    MeasuredCount::Known(ByteCount::new(0)),
                ))
            });
        });
        accounting.bench_function(BenchmarkId::new("voidcrawl", observed), |b| {
            b.iter(|| {
                black_box(ProviderByteAccounting::new(
                    ByteCount::new(observed),
                    ByteCount::new(observed),
                    MeasuredBrowserBytes::Known {
                        value: ByteCount::new(0),
                    },
                ))
            });
        });
    }
    accounting.finish();

    let mut payload = c.benchmark_group("shared_acquisition_complete_payload_construction");
    for size in [1_024_usize, 16_384, 262_144] {
        let bytes = vec![b'x'; size];
        payload.throughput(Throughput::Bytes(
            u64::try_from(size).unwrap_or_else(|error| panic!("payload size: {error}")),
        ));
        payload.bench_function(BenchmarkId::new("direct_http", size), |b| {
            b.iter(|| black_box(AcquiredPayloadOutcome::complete(bytes.clone())));
        });
        payload.bench_function(BenchmarkId::new("web_capture", size), |b| {
            b.iter(|| black_box(RetainedSource::complete(bytes.clone())));
        });
        payload.bench_function(BenchmarkId::new("browser_staging", size), |b| {
            b.iter(|| {
                black_box(ArtifactStagingOutcome::complete(
                    mapping(),
                    Arc::from(bytes.clone()),
                    u64::try_from(size).unwrap_or_else(|error| panic!("payload size: {error}")),
                ))
            });
        });
    }
    payload.finish();

    let mut finalization = c.benchmark_group("shared_acquisition_finalization");
    for case in [
        FinalizationCase::Minimal,
        FinalizationCase::Complete,
        FinalizationCase::Truncated,
    ] {
        finalization.throughput(Throughput::Elements(1));
        finalization.bench_function(BenchmarkId::from_parameter(format!("{case:?}")), |b| {
            b.iter_batched(
                || plan(case),
                |plan| {
                    black_box(
                        yosoi_web_capture::finalize_acquisition(plan)
                            .unwrap_or_else(|error| panic!("finalization: {error}")),
                    )
                },
                BatchSize::SmallInput,
            );
        });
    }
    finalization.finish();
}
