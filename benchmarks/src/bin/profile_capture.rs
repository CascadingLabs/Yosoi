//! Stable process boundary for RSS, CPU-utilization, hardware-counter, and heap profiling.

use std::{collections::BTreeMap, env, hint::black_box, num::NonZeroU32};

use anyhow::{Context, Result, bail};
use tokio::runtime::Builder;
use tokio_util::sync::CancellationToken;
use yosoi_benchmarks::support::{self, LoopbackServer, Route};
use yosoi_web_capture_direct_http::{
    DirectHttpRedirectPolicy, RedirectHopLimit, capture_direct_http_at,
};

const DEFAULT_ITERATIONS: u32 = 10;
const LARGE_BYTES: u64 = 262_144;
const MEDIUM_BYTES: u64 = 32_768;
const TRUNCATED_BYTES: u64 = 4_096;

#[derive(Clone, Copy, Debug)]
enum Workload {
    Full,
    Compressed,
    Redirect,
    Truncated,
}

impl Workload {
    fn parse(value: &str) -> Result<Self> {
        match value {
            "full" => Ok(Self::Full),
            "compressed" => Ok(Self::Compressed),
            "redirect" => Ok(Self::Redirect),
            "truncated" => Ok(Self::Truncated),
            _ => bail!(
                "unknown workload `{value}`; expected full, compressed, redirect, or truncated"
            ),
        }
    }

    const fn route(self) -> &'static str {
        match self {
            Self::Full => "/large-html",
            Self::Compressed => "/large-high-ratio-gzip",
            Self::Redirect => "/redirect-start",
            Self::Truncated => "/medium-html",
        }
    }

    fn redirect_policy(self) -> Result<DirectHttpRedirectPolicy> {
        if matches!(self, Self::Redirect) {
            Ok(DirectHttpRedirectPolicy::follow(
                RedirectHopLimit::try_from(3)?,
            ))
        } else {
            Ok(DirectHttpRedirectPolicy::Disabled)
        }
    }

    const fn limits(self) -> (u64, u64, u64) {
        match self {
            Self::Truncated => (MEDIUM_BYTES, TRUNCATED_BYTES, TRUNCATED_BYTES),
            Self::Full | Self::Compressed | Self::Redirect => {
                (LARGE_BYTES, LARGE_BYTES, LARGE_BYTES)
            }
        }
    }
}

fn main() -> Result<()> {
    let mut arguments = env::args().skip(1);
    let workload = Workload::parse(arguments.next().as_deref().unwrap_or("full"))?;
    let iterations = arguments
        .next()
        .map(|value| value.parse::<u32>())
        .transpose()
        .context("iterations must be a positive integer")?
        .unwrap_or(DEFAULT_ITERATIONS);
    let iterations = NonZeroU32::new(iterations).context("iterations must be greater than zero")?;
    if arguments.next().is_some() {
        bail!("usage: profile_capture [full|compressed|redirect|truncated] [iterations]");
    }

    let large = support::bytes(&support::fixture("large-html"));
    let medium = support::bytes(&support::fixture("medium-html"));
    let compressed = support::bytes(&support::fixture("large-high-ratio-gzip"));
    let routes = BTreeMap::from([
        (
            "/large-html".to_owned(),
            Route::body(large, "text/html; charset=utf-8", None),
        ),
        (
            "/medium-html".to_owned(),
            Route::body(medium, "text/html; charset=utf-8", None),
        ),
        (
            "/large-high-ratio-gzip".to_owned(),
            Route::body(compressed, "application/octet-stream", Some("gzip")),
        ),
        (
            "/redirect-start".to_owned(),
            Route::redirect("/redirect-middle"),
        ),
        (
            "/redirect-middle".to_owned(),
            Route::redirect("/large-html"),
        ),
    ]);
    let server = LoopbackServer::start(routes);
    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .context("failed to construct benchmark runtime")?;
    let (content_coded, representation, unicode) = workload.limits();

    for _ in 0..iterations.get() {
        let spec = support::capture_spec_with_limits(
            &server.url(workload.route()),
            content_coded,
            representation,
            unicode,
            workload.redirect_policy()?,
        );
        let capture = runtime
            .block_on(capture_direct_http_at(
                spec,
                &CancellationToken::new(),
                support::started_at(),
            ))
            .map_err(|error| anyhow::anyhow!("capture workload failed: {error}"))?;
        black_box(capture);
    }

    println!(
        "profile_capture workload={workload:?} iterations={}",
        iterations.get()
    );
    Ok(())
}
