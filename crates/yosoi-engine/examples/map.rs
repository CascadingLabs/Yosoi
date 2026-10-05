//! Run a bounded Map operation against one explicit target.
use std::{env, error::Error};

use yosoi_engine::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = env::args().skip(1);
    let Some(seed) = arguments.next() else {
        eprintln!("Usage: cargo run -p yosoi --example map -- <url> [passive|combined]");
        return Ok(());
    };
    let mode = arguments.next();
    let policy = ys::Policy {
        map: ys::policy::Map {
            scope: ys::policy::Scope {
                hosts: if mode.is_some() {
                    ys::policy::HostScope::RegistrableDomain
                } else {
                    ys::policy::HostScope::SeedHost
                },
                ..Default::default()
            },
            subdomains: if mode.is_some() {
                ys::policy::Subdomains::Passive
            } else {
                ys::policy::Subdomains::Disabled
            },
            pages: if mode.as_deref() == Some("passive") {
                ys::policy::PageDiscovery::Disabled
            } else {
                ys::policy::PageDiscovery::Explore
            },
            ..Default::default()
        },
        ..Default::default()
    };
    let outcome = ys::map::new(seed).bind(&policy).send().await?;
    println!(
        "termination={:?} identity={} requests={} response_bytes={} hosts={} pages={} edges={} frontier={}",
        outcome.termination(),
        outcome.policy_snapshot().identity().digest(),
        outcome.summary().requests,
        outcome.summary().response_bytes,
        outcome.hosts().len(),
        outcome.pages().len(),
        outcome.relationships().len(),
        outcome.frontier().len()
    );
    for source in outcome.sources() {
        println!(
            "source={:?} url={:?} status={:?}",
            source.source, source.source_url, source.status
        );
    }
    for host in outcome.hosts() {
        println!("host={} verification={:?}", host.host, host.verification);
    }
    for page in outcome.pages() {
        println!(
            "page={} depth={:?} exploration={:?}",
            page.url, page.minimum_link_depth, page.exploration
        );
    }
    Ok(())
}
