//! Four real public sites, one owned browser, two execution slots.
//! cargo run -p yosoi --features browser --example live_tab_flows -- evidence-dir
use std::{env, error::Error, fs, io, path::PathBuf, time::Instant};
use tokio::task::JoinSet;
use yosoi::{
    action,
    flow::{self, Condition},
    session::{self, ExecutionPool, SessionPolicy},
};
type LiveError = Box<dyn Error + Send + Sync>;
#[derive(Clone, Copy, Debug)]
struct Site {
    name: &'static str,
    url: &'static str,
    ready: &'static str,
    confirmation: &'static str,
}
const SITES: [Site; 4] = [
    Site {
        name: "rust-learn",
        url: "https://rust-lang.org/learn/",
        ready: "h1",
        confirmation: "a[href*='doc.rust-lang.org/book']",
    },
    Site {
        name: "qscrape-shop",
        url: "https://qscrape.dev/l2/eshop/",
        ready: "[data-slot='product-grid'] [data-fw]:not([hidden]) article[data-sku='VM-MIN-001']",
        confirmation: "[data-slot='product-grid'] [data-fw]:not([hidden]) article[data-sku='VM-MIN-001']",
    },
    Site {
        name: "chrome-devtools",
        url: "https://developer.chrome.com/docs/devtools",
        ready: "#devtools",
        confirmation: "a[href$='/docs/devtools/performance/overview']",
    },
    Site {
        name: "tokio-semaphore",
        url: "https://docs.rs/tokio/latest/tokio/sync/struct.Semaphore.html",
        ready: "h1",
        confirmation: "[id='method.acquire']",
    },
];
#[tokio::main(flavor = "current_thread")]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn main() -> Result<(), LiveError> {
    let output = env::args()
        .nth(1)
        .map(PathBuf::from)
        .or_else(|| env::var_os("YOSOI_BROWSER_OUTPUT_DIR").map(PathBuf::from))
        .ok_or_else(|| io::Error::other("live_tab_flows <evidence-dir>"))?;
    fs::create_dir_all(&output)?;
    let pool = ExecutionPool::new(2, 16)?;
    let mode = if env::var("YOSOI_YIELD_MODE").as_deref() == Ok("headful") {
        session::BrowserMode::Headful
    } else {
        session::BrowserMode::Headless
    };
    let browser = session::new()
        .configure(SessionPolicy {
            mode,
            maximum_tabs: 4,
            ..SessionPolicy::default()
        })
        .execution_pool(&pool)
        .acquire()
        .await?;
    let mut jobs = JoinSet::new();
    let started = Instant::now();
    for (index, site) in SITES.into_iter().enumerate() {
        let work = if index == 0 {
            browser.work().await?
        } else {
            browser.new_tab().await?.work().await?
        };
        jobs.spawn(async move {
            let recipe = flow::new([
                action::navigate(site.url),
                action::wait_until(
                    Condition::Visible {
                        selector: site.ready.into(),
                    },
                    15_000,
                ),
                action::assert(Condition::Exists {
                    selector: site.confirmation.into(),
                })
                .into(),
                action::screenshot(),
            ])
            .timeout(20_000);
            let began = Instant::now();
            let executed = recipe.with_lease(&work).invoke().await;
            let released = work.release().await;
            let outcome = executed?;
            released?;
            Ok::<_, LiveError>((site, began.elapsed(), outcome))
        });
    }
    let mut results = Vec::new();
    let mut failed = false;
    while let Some(result) = jobs.join_next().await {
        match result {
            Ok(Ok((site, elapsed, outcome))) => {
                fs::write(
                    output.join(format!("{}-receipts.json", site.name)),
                    serde_json::to_vec_pretty(&outcome)?,
                )?;
                if let Some(bytes) = outcome
                    .steps
                    .last()
                    .and_then(|step| step.receipt.observation.as_ref())
                    .and_then(|observation| observation.screenshot.as_ref())
                {
                    fs::write(output.join(format!("{}.png", site.name)), bytes)?;
                }
                let succeeded = outcome.require_completed().is_ok();
                failed |= !succeeded;
                println!(
                    "{}: {:?}, {} ms, {} retained steps",
                    site.name,
                    outcome.terminal,
                    elapsed.as_millis(),
                    outcome.steps.len()
                );
                results.push(serde_json::json!({"site":site.name,"url":site.url,"elapsed_ms":elapsed.as_millis(),"terminal":outcome.terminal,"retained_steps":outcome.steps.len()}));
            }
            other => {
                failed = true;
                results.push(serde_json::json!({"error":format!("{other:?}")}));
            }
        }
    }
    let elapsed = started.elapsed();
    let snapshot = pool.snapshot();
    browser.close().await?;
    fs::write(
        output.join("live-sites.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "source":env::var("YOSOI_SPIKE_SOURCE_REVISION").ok(), "browser":env::var("YOSOI_SPIKE_BROWSER_IDENTITY").ok(),
            "elapsed_ms":elapsed.as_millis(), "worker_capacity":snapshot.capacity,"peak_active":snapshot.peak_active,
            "active_after":snapshot.active,"queued_after":snapshot.queued,"parked_after":snapshot.parked,"sites":results,
        }))?,
    )?;
    if failed {
        return Err(io::Error::other("live-site failures retained; no automatic retries").into());
    }
    if snapshot.active != 0
        || snapshot.queued != 0
        || snapshot.parked != 0
        || snapshot.peak_active > 2
    {
        return Err(io::Error::other("execution accounting did not settle").into());
    }
    Ok(())
}
