//! Live shipping-quote Flows: real HTTP, retained tab leases and bounded workers.
//! cargo run -p yosoi --features browser --example tab_yielding -- --iterations 3
//! Use run-yielding.sh for a hardened headless/headful Docker comparison.
use serde::Serialize;
use std::time as std_time;
use std::{
    env,
    error::Error,
    fs, io,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
use tokio::time as tokio_time;
use tokio::{sync::oneshot, task::JoinSet, time::timeout};
use yosoi::flow as yosoi_flow;
use yosoi::{
    action::{self, check},
    flow::{self, Condition},
    prelude as ys,
    session::{self, ExecutionPool, SessionPolicy, Work},
};
#[path = "support/yield_fixture.rs"]
mod fixture;
type DemoError = Box<dyn Error + Send + Sync>;

#[derive(ys::Contract)]
#[ys(id="shipping-quote", description="A service-confirmed shipping quote", root=ys::locator::css(".quote"))]
struct ShippingQuote {
    #[ys(description="Request identity", locator=ys::locator::css(".job-id").text())]
    job_id: String,
    #[ys(description="Quote status", locator=ys::locator::css(".status").text())]
    status: String,
    #[ys(description="Quoted price", locator=ys::locator::css(".price").text())]
    price: ys::Money,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct Scenario {
    name: &'static str,
    browsers: u32,
    tabs_per_browser: u32,
    workers: u32,
    latency_ms: u64,
    staged_arrival: bool,
    backend_concurrency: Option<u32>,
}
const SCENARIOS: [Scenario; 10] = [
    Scenario {
        name: "one-tab",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 1,
        workers: 1,
        latency_ms: 700,
        staged_arrival: true,
    },
    Scenario {
        name: "four-tabs-one-worker",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 4,
        workers: 1,
        latency_ms: 700,
        staged_arrival: true,
    },
    Scenario {
        name: "four-tabs-two-workers",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 4,
        workers: 2,
        latency_ms: 700,
        staged_arrival: true,
    },
    Scenario {
        name: "four-tabs-four-workers",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 4,
        workers: 4,
        latency_ms: 700,
        staged_arrival: true,
    },
    Scenario {
        name: "simultaneous-arrival",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 4,
        workers: 1,
        latency_ms: 700,
        staged_arrival: false,
    },
    Scenario {
        name: "no-service-wait",
        backend_concurrency: None,
        browsers: 1,
        tabs_per_browser: 4,
        workers: 1,
        latency_ms: 0,
        staged_arrival: false,
    },
    Scenario {
        name: "two-browser-processes",
        backend_concurrency: None,
        browsers: 2,
        tabs_per_browser: 2,
        workers: 1,
        latency_ms: 700,
        staged_arrival: true,
    },
    Scenario {
        name: "slow-htmx-four-tabs",
        browsers: 1,
        tabs_per_browser: 4,
        workers: 1,
        latency_ms: 8_000,
        staged_arrival: true,
        backend_concurrency: None,
    },
    Scenario {
        name: "slow-htmx-eight-tabs",
        browsers: 1,
        tabs_per_browser: 8,
        workers: 2,
        latency_ms: 8_000,
        staged_arrival: true,
        backend_concurrency: None,
    },
    Scenario {
        name: "htmx-backend-bottleneck",
        browsers: 1,
        tabs_per_browser: 4,
        workers: 2,
        latency_ms: 5_000,
        staged_arrival: true,
        backend_concurrency: Some(2),
    },
];
impl Scenario {
    fn wait_budget_ms(self) -> Result<u64, DemoError> {
        let total = self
            .browsers
            .checked_mul(self.tabs_per_browser)
            .ok_or_else(|| io::Error::other("job count overflow"))?;
        // Bound a fully serialized batch as well: upstream and browser HTTP/1
        // connection queues must not turn a comparison into a timeout contest.
        let waves = total;
        self.latency_ms
            .checked_mul(u64::from(waves))
            .and_then(|n| n.checked_add(5_000))
            .ok_or_else(|| io::Error::other("wait budget overflow").into())
    }
}
#[derive(Default, Debug, Serialize)]
struct MemoryPeak {
    /// Sampled every 100 ms; includes SDK, browser, file cache and kernel memory.
    cgroup_bytes: Option<u64>,
    /// Sum of Chrome process PSS, avoiding RSS double-counting shared pages.
    chrome_pss_kib: Option<u64>,
    sdk_rss_kib: Option<u64>,
    parked: u32,
}
#[derive(Debug, Serialize)]
struct Round {
    mode: &'static str,
    iteration: u32,
    warmup: bool,
    elapsed_ms: u64,
    completed: u32,
    admitted_operations: u64,
    peak_active: u32,
    memory: MemoryPeak,
    jobs: Vec<JobTiming>,
    completed_jobs_per_second: f64,
}
#[derive(Debug, Serialize)]
struct JobTiming {
    id: u32,
    submitted_ms: u64,
    service_request_ms: u64,
    completed_ms: u64,
}
#[derive(Debug, Serialize)]
struct Case {
    scenario: Scenario,
    startup_ms: u64,
    rounds: Vec<Round>,
}

fn millis(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
}
fn field_kib(path: impl AsRef<Path>, field: &str) -> Option<u64> {
    fs::read_to_string(path).ok()?.lines().find_map(|line| {
        line.strip_prefix(field)?
            .split_whitespace()
            .next()?
            .parse()
            .ok()
    })
}
fn memory_sample() -> MemoryPeak {
    let mut pss = None;
    if let Ok(processes) = fs::read_dir("/proc") {
        for process in processes.flatten() {
            let name = fs::read_to_string(process.path().join("comm")).unwrap_or_default();
            if name.trim().starts_with("chrome")
                && let Some(value) = field_kib(process.path().join("smaps_rollup"), "Pss:")
            {
                pss = Some(pss.unwrap_or(0_u64).saturating_add(value));
            }
        }
    }
    MemoryPeak {
        cgroup_bytes: fs::read_to_string("/sys/fs/cgroup/memory.current")
            .ok()
            .and_then(|v| v.trim().parse().ok()),
        chrome_pss_kib: pss,
        sdk_rss_kib: field_kib("/proc/self/status", "VmRSS:"),
        parked: 0,
    }
}
fn maximize(target: &mut Option<u64>, sample: Option<u64>) {
    if let Some(value) = sample {
        *target = Some(target.unwrap_or(0).max(value));
    }
}
async fn sample_memory(pool: ExecutionPool, mut stop: oneshot::Receiver<()>) -> MemoryPeak {
    let mut peak = MemoryPeak::default();
    // Telemetry sampling is intentional, not a readiness or retry loop.
    let mut ticks = tokio_time::interval(Duration::from_millis(100));
    ticks.set_missed_tick_behavior(tokio_time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            biased;
            _ = &mut stop => break,
            _ = ticks.tick() => {
                let sample = memory_sample();
                maximize(&mut peak.cgroup_bytes, sample.cgroup_bytes);
                maximize(&mut peak.chrome_pss_kib, sample.chrome_pss_kib);
                maximize(&mut peak.sdk_rss_kib, sample.sdk_rss_kib);
                peak.parked = peak.parked.max(pool.snapshot().parked);
            }
        }
    }
    peak
}

fn shipping_quote(url: String, id: u32, wait_ms: u64) -> Result<ys::Flow, DemoError> {
    let expected_id = id.to_string();
    let expected_price = 1_000_i64.saturating_add(i64::from(id));
    Ok(flow::new([
        action::navigate(url),
        action::wait_until(
            Condition::Exists {
                selector: "body[data-htmx-ready='true']".into(),
            },
            5_000,
        ),
        action::click("#start"),
        action::wait_until(
            Condition::Visible {
                selector: "#done".into(),
            },
            wait_ms,
        ),
        action::assert_all::<ShippingQuote>(
            ShippingQuote::plan()?,
            [
                check(move |quote: &ShippingQuote| quote.job_id == expected_id)
                    .named("request identity"),
                check(|quote: &ShippingQuote| quote.status == "ready").named("service confirmed"),
                check(move |quote: &ShippingQuote| quote.price.minor_units() == expected_price)
                    .named("quoted amount"),
            ],
        )
        .into(),
        action::screenshot(),
    ])
    .timeout(
        wait_ms
            .checked_add(10_000)
            .ok_or_else(|| io::Error::other("action budget overflow"))?,
    ))
}
async fn quote_job(
    work: Work,
    url: String,
    id: u32,
    wait_ms: u64,
) -> Result<(u32, std_time::Instant, yosoi_flow::FlowOutcome), DemoError> {
    let recipe = shipping_quote(url, id, wait_ms)?;
    let executed = recipe.with_lease(&work).invoke().await;
    let release = work.release().await;
    let outcome = executed?;
    release?;
    Ok((id, Instant::now(), outcome))
}
fn save_quote(
    id: u32,
    outcome: &yosoi_flow::FlowOutcome,
    directory: &Path,
) -> Result<(), DemoError> {
    fs::create_dir_all(directory)?;
    fs::write(
        directory.join(format!("quote-{id}-receipts.json")),
        serde_json::to_vec_pretty(outcome)?,
    )?;
    if let Some(bytes) = outcome
        .steps
        .last()
        .and_then(|step| step.receipt.observation.as_ref())
        .and_then(|observation| observation.screenshot.as_ref())
    {
        fs::write(directory.join(format!("quote-{id}.png")), bytes)?;
    }
    Ok(())
}
#[derive(Clone, Copy)]
struct BatchLabel {
    mode: &'static str,
    iteration: u32,
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "Keep fixture ownership through verification and explicit cleanup; values moved into asynchronous tasks are not local owners to drop early."
)]
async fn batch(
    scenario: Scenario,
    browsers: &[session::Session],
    tabs: &[session::Tab],
    pool: &ExecutionPool,
    service: &fixture::QuoteService,
    output: Option<PathBuf>,
    label: BatchLabel,
) -> Result<Round, DemoError> {
    let BatchLabel { mode, iteration } = label;
    let mut leases = Vec::new();
    let mut tab_cursor = 0_usize;
    for browser in browsers {
        leases.push(browser.work().await?);
        for _ in 1..scenario.tabs_per_browser {
            let tab = tabs
                .get(tab_cursor)
                .ok_or_else(|| io::Error::other("tab accounting mismatch"))?;
            leases.push(tab.work().await?);
            tab_cursor = tab_cursor
                .checked_add(1)
                .ok_or_else(|| io::Error::other("tab count overflow"))?;
        }
    }
    let before = pool.snapshot();
    let (stop, stopped) = oneshot::channel();
    let sampling = tokio::spawn(sample_memory(pool.clone(), stopped));
    let mut events = pool.subscribe();
    let mut arrivals = service.subscribe_requests();
    let mut jobs = JoinSet::new();
    let started = Instant::now();
    let mut submitted = Vec::new();
    let mut service_requests = Vec::new();
    let anchor_count = if scenario.latency_ms >= 3_000 {
        scenario.workers
    } else {
        1
    };
    for (index, work) in leases.into_iter().enumerate() {
        let id = u32::try_from(index)?;
        submitted.push((id, millis(started.elapsed())));
        jobs.spawn(quote_job(
            work,
            service.url(id),
            id,
            scenario.wait_budget_ms()?,
        ));
        // Event-driven staged arrivals: remaining work arrives while job zero
        // is already awaiting a quote. Also compare simultaneous arrivals.
        if id < anchor_count && scenario.staged_arrival && scenario.latency_ms > 0 {
            timeout(Duration::from_secs(15), async {
                loop {
                    let arrival = arrivals.recv().await?;
                    let arrived_id = arrival.id;
                    service_requests.push(arrival);
                    if arrived_id == id {
                        break;
                    }
                }
                while pool.snapshot().waiting <= id {
                    events.recv().await?;
                }
                Ok::<_, DemoError>(())
            })
            .await??;
        }
    }
    let mut completed = 0_u32;
    let mut failure: Option<DemoError> = None;
    let mut outcomes = Vec::new();
    while let Some(result) = jobs.join_next().await {
        match result {
            Ok(Ok((id, at, outcome))) => {
                match outcome.require_completed() {
                    Ok(()) => completed = completed.saturating_add(1),
                    Err(error) => {
                        if failure.is_none() {
                            failure = Some(Box::new(error));
                        }
                    }
                }
                outcomes.push((id, at, outcome));
            }
            Ok(Err(error)) => {
                if failure.is_none() {
                    failure = Some(error);
                }
            }
            Err(error) => {
                if failure.is_none() {
                    failure = Some(Box::new(error));
                }
            }
        }
    }
    let elapsed_ms = millis(started.elapsed());
    let elapsed_seconds = started.elapsed().as_secs_f64();
    while let Ok(arrival) = arrivals.try_recv() {
        service_requests.push(arrival);
    }
    let _ = stop.send(());
    let mut memory = sampling.await?;
    let final_sample = memory_sample();
    maximize(&mut memory.cgroup_bytes, final_sample.cgroup_bytes);
    maximize(&mut memory.chrome_pss_kib, final_sample.chrome_pss_kib);
    maximize(&mut memory.sdk_rss_kib, final_sample.sdk_rss_kib);
    // Persist after the timed/sampled interval, identically for both policies.
    if let Some(directory) = output {
        for (id, _, outcome) in &outcomes {
            save_quote(*id, outcome, &directory)?;
        }
    }
    if let Some(error) = failure {
        return Err(error);
    }
    let mut timings = Vec::new();
    for (id, at, _) in &outcomes {
        let submitted_ms = submitted
            .iter()
            .find(|(job, _)| job == id)
            .map(|(_, at)| *at)
            .ok_or_else(|| io::Error::other("missing submission"))?;
        let service_request_ms = service_requests
            .iter()
            .find(|arrival| arrival.id == *id)
            .map(|arrival| millis(arrival.at.saturating_duration_since(started)))
            .ok_or_else(|| io::Error::other("missing service request event"))?;
        timings.push(JobTiming {
            id: *id,
            submitted_ms,
            service_request_ms,
            completed_ms: millis(at.saturating_duration_since(started)),
        });
    }
    timings.sort_by_key(|job| job.id);
    let after = pool.snapshot();
    if after.active != 0 || after.queued != 0 || after.parked != 0 || after.waiting != 0 {
        return Err(io::Error::other(format!("execution capacity leaked: {after:?}")).into());
    }
    if after.peak_active > scenario.workers {
        return Err(io::Error::other("worker capacity exceeded").into());
    }
    Ok(Round {
        mode,
        iteration,
        warmup: iteration == 0,
        elapsed_ms,
        completed,
        admitted_operations: after.admitted.saturating_sub(before.admitted),
        peak_active: after.peak_active,
        memory,
        jobs: timings,
        completed_jobs_per_second: if elapsed_seconds > 0.0 {
            f64::from(completed) / elapsed_seconds
        } else {
            0.0
        },
    })
}
#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn run_case(
    scenario: Scenario,
    yielded: bool,
    repeats: u32,
    output: &Path,
) -> Result<Case, DemoError> {
    let service = fixture::QuoteService::start_bottleneck(
        Some(Duration::from_millis(scenario.latency_ms)),
        scenario.backend_concurrency,
    )
    .await?;
    let pool = ExecutionPool::new(scenario.workers, 64)?;
    let mode = if yielded { "yield" } else { "retain-worker" };
    let browser_mode = if env::var("YOSOI_YIELD_MODE").as_deref() == Ok("headful") {
        session::BrowserMode::Headful
    } else {
        session::BrowserMode::Headless
    };
    let starting = Instant::now();
    let mut browsers = Vec::new();
    let mut tabs = Vec::new();
    for _ in 0..scenario.browsers {
        let browser = session::new()
            .configure(SessionPolicy {
                mode: browser_mode,
                maximum_tabs: scenario.tabs_per_browser,
                yield_on_wait: yielded,
                execution_concurrency: scenario.workers,
                ..SessionPolicy::default()
            })
            .execution_pool(&pool)
            .acquire()
            .await?;
        for _ in 1..scenario.tabs_per_browser {
            tabs.push(browser.new_tab().await?);
        }
        browsers.push(browser);
    }
    let startup_ms = millis(starting.elapsed());
    let mut rounds = Vec::new();
    let mut failure = None;
    for iteration in 0..=repeats {
        let artifact =
            (iteration == repeats).then(|| output.join(format!("{}-{mode}", scenario.name)));
        match batch(
            scenario,
            &browsers,
            &tabs,
            &pool,
            &service,
            artifact,
            BatchLabel { mode, iteration },
        )
        .await
        {
            Ok(round) => {
                println!(
                    "{} {mode} round={iteration} elapsed={}ms memory={:?}",
                    scenario.name, round.elapsed_ms, round.memory
                );
                rounds.push(round);
            }
            Err(error) => {
                failure = Some(error);
                break;
            }
        }
    }
    for browser in &browsers {
        if let Err(error) = browser.close().await
            && failure.is_none()
        {
            failure = Some(Box::new(error));
        }
    }
    service.stop().await?;
    if let Some(error) = failure {
        return Err(error);
    }
    Ok(Case {
        scenario,
        startup_ms,
        rounds,
    })
}
#[tokio::main(flavor = "current_thread")]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn main() -> Result<(), DemoError> {
    let mut output = env::var_os("YOSOI_BROWSER_OUTPUT_DIR").map_or_else(
        || PathBuf::from("target/tab-yielding-evidence"),
        PathBuf::from,
    );
    let mut repeats = 3_u32;
    let mut selected = None;
    let mut network_url = None;
    let mut network_selector = "body".to_owned();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| io::Error::other("argument requires a value"))?;
        match arg.as_str() {
            "--output" => output = value.into(),
            "--iterations" => {
                repeats = value.parse()?;
                if !(1..=10).contains(&repeats) {
                    return Err(io::Error::other("iterations must be 1..10").into());
                }
            }
            "--case" => selected = Some(value),
            "--network-url" => network_url = Some(value),
            "--network-selector" => network_selector = value,
            _ => return Err(io::Error::other(format!("unknown argument {arg}")).into()),
        }
    }
    fs::create_dir_all(&output)?;
    let mut cases = Vec::new();
    for scenario in SCENARIOS {
        if selected.as_ref().is_some_and(|name| name != scenario.name) {
            continue;
        }
        for yielded in [false, true] {
            cases.push(run_case(scenario, yielded, repeats, &output).await?);
            fs::write(
                output.join("comparison.json"),
                serde_json::to_vec_pretty(&serde_json::json!({
                    "source":env::var("YOSOI_SPIKE_SOURCE_REVISION").ok(),
                    "browser":env::var("YOSOI_SPIKE_BROWSER_IDENTITY").ok(),
                    "controller":"chromiumoxide 0.9.1; CDP 0.10.0-yosoi.m153.1",
                    "build_profile":"debug", "telemetry_interval_ms":100,
                "framework":"htmx 2.0.11", "artifact_io_in_timing":false,
                    "cpu_limit":fs::read_to_string("/sys/fs/cgroup/cpu.max").ok(),
                    "memory_limit":fs::read_to_string("/sys/fs/cgroup/memory.max").ok(),
                    "cases":cases,
                }))?,
            )?;
        }
    }
    if cases.is_empty() {
        return Err(io::Error::other("unknown scenario").into());
    }
    if let Some(url) = network_url {
        let browser = session::new().acquire().await?;
        let work = browser.work().await?;
        let probe = flow::new([
            action::navigate(url),
            action::wait_until(
                Condition::Exists {
                    selector: network_selector.clone(),
                },
                5_000,
            ),
            action::screenshot(),
        ]);
        let result = probe.with_lease(&work).invoke().await;
        let release = work.release().await;
        let close = browser.close().await;
        let outcome = result?;
        fs::write(
            output.join("network-probe.json"),
            serde_json::to_vec_pretty(&outcome)?,
        )?;
        release?;
        close?;
        outcome.require_completed()?;
        println!("external network probe completed with retained observations");
    }
    println!("Evidence written to {}", output.display());
    Ok(())
}
