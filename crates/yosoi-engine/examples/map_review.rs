//! A bounded SDK example for the final Map review.
use std::{env, error::Error, io, time::Duration};

use yosoi_engine::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let seed = args
        .next()
        .unwrap_or_else(|| "https://qscrape.dev/l1/news/".to_owned());
    if seed == "--help" || seed == "-h" {
        println!("Usage: map_review [URL] [pages|passive|combined]");
        println!("Default: https://qscrape.dev/l1/news/ pages");
        return Ok(());
    }
    let mode = args.next().unwrap_or_else(|| "pages".to_owned());
    if args.next().is_some() || !matches!(mode.as_str(), "pages" | "passive" | "combined") {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "usage: map_review [URL] [pages|passive|combined]",
        )
        .into());
    }
    let passive = mode != "pages";
    let policy = ys::Policy {
        request: ys::policy::Request {
            maximum_elapsed: ys::policy::MaximumElapsed::try_from(30_000_000)?,
            ..Default::default()
        },
        map: ys::policy::Map {
            scope: ys::policy::Scope {
                hosts: if passive {
                    ys::policy::HostScope::RegistrableDomain
                } else {
                    ys::policy::HostScope::SeedHost
                },
                ..Default::default()
            },
            pages: if mode == "passive" {
                ys::policy::PageDiscovery::Disabled
            } else {
                ys::policy::PageDiscovery::Explore
            },
            subdomains: if passive {
                ys::policy::Subdomains::Passive
            } else {
                ys::policy::Subdomains::Disabled
            },
            robots: ys::policy::Robots::Ignore,
            limits: ys::policy::Limits {
                max_link_depth: 2,
                max_requests: ys::policy::Budget::new(20)?,
                max_hosts: ys::policy::Budget::new(2_000)?,
                max_observations: ys::policy::Budget::new(10_000)?,
                max_response_bytes: ys::policy::Budget::new(8 * 1024 * 1024)?,
                max_total_response_bytes: ys::policy::Budget::new(16 * 1024 * 1024)?,
                max_inventory_bytes: ys::policy::Budget::new(16 * 1024 * 1024)?,
                max_parser_entries: ys::policy::Budget::new(50_000)?,
                maximum_elapsed: Duration::from_secs(60),
                ..Default::default()
            },
            documents: ys::policy::DiscoveryDocuments::RetainWithinBudget,
            ..Default::default()
        },
        ..Default::default()
    };

    println!(
        "Seed: {seed}; mode: {mode}; robots: {:?}",
        policy.map.robots
    );
    println!("Limits: {:#?}", policy.map.limits);
    let outcome = ys::map::new(seed).bind(&policy).send().await?;
    println!("Termination: {:?}", outcome.termination());
    println!("Consumed: {:?}", outcome.summary());
    println!(
        "Hosts: {}; pages: {}; relationships: {}; pending: {}",
        outcome.hosts().len(),
        outcome.pages().len(),
        outcome.relationships().len(),
        outcome.frontier().len()
    );
    println!("\nHosts (certificate names are unverified):");
    for host in outcome.hosts() {
        println!("{} {:?}", host.host, host.verification);
    }
    for pattern in outcome.wildcard_names() {
        println!("Wildcard pattern: {pattern}");
    }
    println!("\nPage tree (unknown depth means no observed link path):");
    for entry in outcome.tree() {
        println!(
            "depth={:?} {} <- {:?}",
            entry.depth, entry.page, entry.parent
        );
    }
    println!("\nSource outcomes:");
    for source in outcome.sources() {
        println!(
            "{:?} {:?} {:?}",
            source.source, source.source_url, source.status
        );
    }
    println!("Omissions: {:?}", outcome.omissions());
    println!("\nActual requests:");
    for trace in outcome.request_trace() {
        println!(
            "{} status={:?} charged_bytes={}",
            trace.target, trace.status, trace.charged_response_bytes
        );
    }
    println!("\nUnfinished frontier: {:?}", outcome.frontier());

    // Reuse an original Requests Document without another network request.
    let original = outcome.captures().iter().find_map(|capture| {
        capture
            .response()
            .attempts()
            .iter()
            .filter_map(ys::AttemptOutcome::result)
            .flat_map(yosoi_engine::AttemptResult::documents)
            .find_map(|document| document.outcome().document())
            .map(|document| (capture.url(), document))
    });
    if let Some((url, document)) = original {
        let plan = ys::Plan::new([ys::output("links", ys::css("a[href]")?.text())?])?;
        println!("\nReuse retained Document from {url} (no new request):");
        match document.bind(&policy).locate(&plan) {
            ys::LocateOutcome::Matched { result } => {
                for finding in result.findings().iter().take(5) {
                    println!("{:?}", finding.value());
                }
            }
            other => println!("{other:?}"),
        }
    }
    Ok(())
}
