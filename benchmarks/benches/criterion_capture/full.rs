use crate::capture_stages_support::*;
use criterion::{BenchmarkId, Criterion, Throughput};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, hint::black_box, time::Duration};
use tokio_util::sync::CancellationToken;
use yosoi_dev_support::internal::direct_http::*;

pub fn raw_full_and_redirects(c: &mut Criterion) {
    let direct_fixture = fixture("medium-html");
    let body = bytes(&direct_fixture);
    let expected_digest = Sha256::digest(&body);
    let mut routes = BTreeMap::new();
    routes.insert(
        "/direct".into(),
        Route::body(body.clone(), "text/html; charset=utf-8", None),
    );
    routes.insert("/one".into(), Route::redirect("/direct"));
    routes.insert("/multi-1".into(), Route::redirect("/multi-2"));
    routes.insert("/multi-2".into(), Route::redirect("/direct"));
    routes.insert("/three-1".into(), Route::redirect("/three-2"));
    routes.insert("/three-2".into(), Route::redirect("/three-3"));
    routes.insert("/three-3".into(), Route::redirect("/direct"));
    let server = LoopbackServer::start(routes);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap_or_else(|e| panic!("runtime: {e}"));
    let direct_url = server.url("/direct");

    let mut raw = c.benchmark_group("local_raw_wreq_construct_request_and_exact_body_consumption");
    raw.throughput(Throughput::Bytes(direct_fixture.encoded_bytes));
    raw.bench_function("medium_html", |b| {
        b.iter(|| {
            runtime.block_on(async {
                let client = wreq::Client::builder()
                    .no_proxy()
                    .redirect(wreq::redirect::Policy::none())
                    .referer(false)
                    .no_gzip()
                    .no_brotli()
                    .no_deflate()
                    .no_zstd()
                    .timeout(Duration::from_secs(5))
                    .build()
                    .unwrap_or_else(|e| panic!("client: {e}"));
                let response = client
                    .get(black_box(&direct_url))
                    .send()
                    .await
                    .unwrap_or_else(|e| panic!("raw send: {e}"));
                let received = response
                    .bytes()
                    .await
                    .unwrap_or_else(|e| panic!("raw body: {e}"));
                assert_eq!(received.len(), body.len());
                assert_eq!(Sha256::digest(&received), expected_digest);
                black_box(received)
            })
        })
    });
    raw.finish();

    let direct_spec = capture_spec(
        &direct_url,
        direct_fixture.encoded_bytes.saturating_mul(2),
        DirectHttpRedirectPolicy::Disabled,
    );
    let mut full =
        c.benchmark_group("full_capture_direct_http_including_hardened_client_construction");
    full.throughput(Throughput::Bytes(direct_fixture.encoded_bytes));
    full.bench_function("medium_html_same_headers_body_and_close", |b| {
        b.iter(|| {
            black_box(
                runtime
                    .block_on(capture_direct_http_at(
                        direct_spec.clone(),
                        &CancellationToken::new(),
                        started_at(),
                    ))
                    .unwrap_or_else(|e| panic!("capture: {e}")),
            )
        })
    });
    full.finish();

    let redirect_fixture = fixture("small-html-redirect-chain");
    assert_eq!(redirect_fixture.route, "three-hop-loopback");
    let cases = [
        (
            "one_hop_exact_limit_success",
            "/one",
            1_u32,
            true,
            &["/one", "/direct"][..],
        ),
        (
            "two_hops_exact_limit_success",
            "/multi-1",
            2,
            true,
            &["/multi-1", "/multi-2", "/direct"],
        ),
        (
            "three_hops_exact_limit_success",
            "/three-1",
            3,
            true,
            &["/three-1", "/three-2", "/three-3", "/direct"],
        ),
        (
            "three_hops_limit_two_failure",
            "/three-1",
            2,
            false,
            &["/three-1", "/three-2", "/three-3"],
        ),
    ];
    let mut redirects = c.benchmark_group("full_capture_redirect_chain");
    redirects.throughput(Throughput::Elements(1));
    for (name, path, hops, succeeds, expected_paths) in cases {
        let policy = DirectHttpRedirectPolicy::follow(
            RedirectHopLimit::try_from(hops).unwrap_or_else(|e| panic!("hops: {e}")),
        );
        let spec = capture_spec(
            &server.url(path),
            redirect_fixture.encoded_bytes.saturating_mul(2),
            policy,
        );
        server.enable_request_logging();
        let preflight = runtime.block_on(capture_direct_http_at(
            spec.clone(),
            &CancellationToken::new(),
            started_at(),
        ));
        server.disable_request_logging();
        let request_paths = server.take_request_paths();
        assert_eq!(request_paths, expected_paths, "{name} exact route sequence");
        assert_eq!(
            request_paths.len(),
            expected_paths.len(),
            "{name} exact request count"
        );
        assert_eq!(preflight.is_ok(), succeeds, "{name} preflight outcome");
        if let Ok(capture) = preflight {
            let resolution = capture.bundle().capture().acquisition().resolution();
            let Observation::Observed(final_url) = resolution.final_url() else {
                panic!("{name} final URL was unobserved")
            };
            assert_eq!(final_url.as_str(), direct_url, "{name} final URL");
            let Observation::Observed(path) = resolution.redirects() else {
                panic!("{name} redirect path was unobserved")
            };
            assert_eq!(path.len(), hops as usize, "{name} redirect path length");
        } else if let Err(error) = &preflight {
            let has_hop_limit =
                std::iter::successors(Some(error as &dyn std::error::Error), |cause| {
                    cause.source()
                })
                .any(|cause| {
                    cause
                        .to_string()
                        .contains("redirect traversal exhausted its hop limit")
                });
            assert!(
                has_hop_limit,
                "{name} expected hop-limit evidence, got {error:?}"
            );
        }
        redirects.bench_function(
            BenchmarkId::new(name, format!("configured_max_hops_{hops}")),
            |b| {
                b.iter(|| {
                    let result = runtime.block_on(capture_direct_http_at(
                        spec.clone(),
                        &CancellationToken::new(),
                        started_at(),
                    ));
                    assert_eq!(result.is_ok(), succeeds);
                    black_box(result)
                })
            },
        );
    }
    redirects.finish();
    assert!(server.request_count() > 0);
}
