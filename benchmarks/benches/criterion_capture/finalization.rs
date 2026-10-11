use crate::capture_stages_support::{bytes, fixture};
use crate::finalization_setup::{Case, CaseKind, setup};
use criterion::{BatchSize, BenchmarkId, Criterion, Throughput};
use std::hint::black_box;
use yosoi_dev_support::internal::direct_http::finalize_direct_http_attempt;

#[allow(
    clippy::needless_pass_by_value,
    reason = "Criterion closure owns each benchmark case"
)]
fn register(
    group: &mut criterion::BenchmarkGroup<'_, criterion::measurement::WallTime>,
    case: Case,
) {
    let retained = case.retained_bytes;
    let name = case.name.clone();
    let availability = if matches!(case.kind, CaseKind::Truncated) {
        "truncated"
    } else {
        "retained"
    };
    let (spec, lifecycle, input) = setup(&case);
    black_box(
        finalize_direct_http_attempt(spec, lifecycle, input)
            .unwrap_or_else(|e| panic!("setup finalize: {e:?}")),
    );
    group.throughput(Throughput::Bytes(retained));
    group.bench_function(
        BenchmarkId::new(
            name,
            format!("availability_{availability}__retained_bytes_{retained}"),
        ),
        |b| {
            b.iter_batched(
                || setup(&case),
                |(spec, lifecycle, input)| {
                    black_box(
                        finalize_direct_http_attempt(spec, lifecycle, input)
                            .unwrap_or_else(|e| panic!("finalize: {e}")),
                    )
                },
                BatchSize::SmallInput,
            )
        },
    );
}

pub fn capture_finalization_bundle(c: &mut Criterion) {
    let fixture_case = |name: &str| {
        let payload = bytes(&fixture(name));
        Case {
            name: format!("complete_source_only_{name}"),
            retained_bytes: payload.len() as u64,
            complete_bytes: payload.len() as u64,
            kind: CaseKind::CompleteSource,
            source: payload,
            decoded: None,
        }
    };
    let mut group = c.benchmark_group("capture_finalization_bundle_retained");
    for case in [
        fixture_case("small-html"),
        fixture_case("medium-html"),
        fixture_case("large-html"),
    ] {
        register(&mut group, case);
    }
    let source = b"<p>caf\xc3\xa9</p>".to_vec();
    let decoded = source.clone();
    register(
        &mut group,
        Case {
            name: "complete_source_and_decoded_two_payloads".into(),
            retained_bytes: (source.len() + decoded.len()) as u64,
            complete_bytes: source.len() as u64,
            kind: CaseKind::CompleteDecoded,
            source,
            decoded: Some(decoded),
        },
    );
    let complete = bytes(&fixture("medium-html"));
    let prefix = complete
        .get(..4096)
        .unwrap_or_else(|| panic!("medium prefix"))
        .to_vec();
    register(
        &mut group,
        Case {
            name: "partial_truncated_source".into(),
            retained_bytes: prefix.len() as u64,
            complete_bytes: complete.len() as u64,
            kind: CaseKind::Truncated,
            source: prefix,
            decoded: None,
        },
    );
    group.finish();

    let unavailable = Case {
        name: "partial_interrupted_source_unavailable".into(),
        retained_bytes: 0,
        complete_bytes: 0,
        kind: CaseKind::Unavailable,
        source: Vec::new(),
        decoded: None,
    };
    let (spec, lifecycle, input) = setup(&unavailable);
    black_box(
        finalize_direct_http_attempt(spec, lifecycle, input)
            .unwrap_or_else(|e| panic!("unavailable setup: {e}")),
    );
    let mut zero = c.benchmark_group("capture_finalization_bundle_unavailable");
    zero.throughput(Throughput::Elements(1));
    zero.bench_function(
        BenchmarkId::new(
            unavailable.name.clone(),
            "availability_unavailable_retained_0_bytes",
        ),
        |b| {
            b.iter_batched(
                || setup(&unavailable),
                |(spec, lifecycle, input)| {
                    black_box(
                        finalize_direct_http_attempt(spec, lifecycle, input)
                            .unwrap_or_else(|e| panic!("finalize: {e}")),
                    )
                },
                BatchSize::SmallInput,
            )
        },
    );
    zero.finish();
}
