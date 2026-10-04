use crate::capture_stages_support::*;
use criterion::{BenchmarkId, Criterion, Throughput};
use std::{
    collections::BTreeMap,
    hint::black_box,
    time::{Duration, Instant},
};
use tokio_util::sync::CancellationToken;
use yosoi_web_capture_direct_http::{
    BodyTerminal, DirectHttpRedirectPolicy, RetainedSourceExtent, consume_response_body,
    execute_direct_http_at,
};

pub fn yosoi_body_pipeline(c: &mut Criterion) {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| panic!("runtime: {e}"));
    let cases = [
        "medium-html",
        "medium-html-gzip",
        "medium-html-br",
        "medium-html-zlib",
        "large-high-ratio-gzip",
        "medium-html-truncated",
    ];
    let mut routes = BTreeMap::new();
    for name in cases {
        let f = fixture(name);
        let coding = (f.content_coding != "identity").then_some(f.content_coding.as_str());
        let served = if name == "medium-html-truncated" {
            bytes(&fixture("medium-html"))
        } else {
            bytes(&f)
        };
        routes.insert(
            format!("/{name}"),
            Route::body(served, &f.media_type, coding),
        );
    }
    let server = LoopbackServer::start(routes);
    let mut group = c.benchmark_group("yosoi_consume_response_body_pipeline");
    for name in cases {
        let f = fixture(name);
        assert_eq!(
            f.extent == "representation-truncated",
            name == "medium-html-truncated"
        );
        let url = server.url(&format!("/{name}"));
        let limit = if name == "medium-html-truncated" {
            4096
        } else {
            f.uncompressed_bytes.saturating_mul(2).max(1024)
        };
        let spec = if name == "medium-html-truncated" {
            capture_spec_with_limits(
                &url,
                65_536,
                limit,
                65_536,
                DirectHttpRedirectPolicy::Disabled,
            )
        } else {
            capture_spec(&url, limit, DirectHttpRedirectPolicy::Disabled)
        };
        group.throughput(Throughput::Bytes(f.uncompressed_bytes.min(limit)));
        group.bench_function(BenchmarkId::new(&f.content_coding, name), |b| {
            b.iter_custom(|iterations| {
                let mut elapsed = Duration::ZERO;
                for _ in 0..iterations {
                    // Exactly one fresh response/deadline is prepared immediately before timing.
                    let pending = runtime
                        .block_on(execute_direct_http_at(
                            spec.clone(),
                            &CancellationToken::new(),
                            started_at(),
                        ))
                        .unwrap_or_else(|e| panic!("pending: {e}"));
                    let timer = Instant::now();
                    let (outcome, _, _, _, _) = runtime
                        .block_on(consume_response_body(pending, &CancellationToken::new()))
                        .unwrap_or_else(|e| panic!("consume: {e}"));
                    elapsed = elapsed.saturating_add(timer.elapsed());
                    let body = outcome
                        .payload()
                        .retained_source()
                        .unwrap_or_else(|| panic!("retained outcome required"));
                    let expected_extent = if name == "medium-html-truncated" {
                        RetainedSourceExtent::Truncated
                    } else {
                        RetainedSourceExtent::Complete
                    };
                    let expected_terminal = if name == "medium-html-truncated" {
                        BodyTerminal::RepresentationLimit
                    } else {
                        BodyTerminal::Complete
                    };
                    assert_eq!(body.extent(), expected_extent);
                    assert_eq!(outcome.terminal(), expected_terminal);
                    assert_eq!(body.bytes().len() as u64, f.uncompressed_bytes.min(limit));
                    if name == "medium-html-truncated" {
                        let full = bytes(&fixture("medium-html"));
                        assert_eq!(
                            body.bytes(),
                            full.get(..4096).unwrap_or_else(|| panic!("full prefix"))
                        );
                    }
                    black_box(body);
                }
                elapsed
            })
        });
    }
    group.finish();
}
