//! Runnable public-SDK counterparts to the Python review examples.

use std::{env, error::Error};
use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = env::args().skip(1);
    let command = arguments.next().unwrap_or_else(|| "locate".to_owned());
    let target = arguments
        .next()
        .unwrap_or_else(|| "https://example.org/".to_owned());
    let policy = ys::Policy::default();
    match command.as_str() {
        "policy" => {
            println!("{}", serde_json::to_string_pretty(&policy)?);
            let identity = policy.effective_identity()?;
            println!(
                "Policy identity: v{} {}",
                identity.version(),
                identity.digest()
            );
        }
        "locate" => {
            let document =
                ys::Document::html("review", b"<main><h1>Public Rust SDK</h1></main>".to_vec())?;
            let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
            println!("{}", serde_json::to_string_pretty(&plan)?);
            println!("{}", serde_json::to_string_pretty(&document.locate(&plan))?);
            println!(
                "{}",
                serde_json::to_string_pretty(&document.parse()?.locate(&plan))?
            );
        }
        "request" | "cancel" => {
            let token = ys::request::CancellationToken::new();
            if command == "cancel" {
                token.cancel();
            }
            let response = ys::request::new(target)
                .bind(&policy)
                .send_cancellable(&token)
                .await?;
            println!(
                "Request {}: {:?}",
                response.request_id(),
                response.termination()
            );
            for attempt in response.attempts() {
                println!(
                    "{:?}: {:?}, HTTP {:?}",
                    attempt.acquisition(),
                    attempt.state(),
                    attempt.status()
                );
                for item in attempt.documents() {
                    println!("{:?}: {:?}", item.requested(), item.outcome());
                }
            }
        }
        "map" => {
            let mut policy = policy;
            policy.map.limits.max_requests = ys::policy::Budget::new(4)?;
            policy.map.limits.max_link_depth = 0;
            policy.map.limits.max_concurrency = ys::policy::Budget::new(1)?;
            let outcome = ys::map::new(target).bind(&policy).send().await?;
            println!("Termination: {:?}", outcome.termination());
            println!("{}", serde_json::to_string_pretty(outcome.summary())?);
            println!("{}", serde_json::to_string_pretty(outcome.pages())?);
        }
        "search" => {
            use ys::policy::search::{Provider, Search};
            let policy = ys::Policy {
                search: Search::new([Provider::Bing])?,
                ..policy
            };
            let response = ys::search::new(target)?.bind(&policy).send().await?;
            println!("Termination: {:?}", response.termination());
            for provider in response.providers() {
                println!("{:?}: {:?}", provider.provider(), provider.outcome());
                if let ys::search::ProviderOutcome::Results(page) = provider.outcome() {
                    for hit in page.hits() {
                        println!("{} {:?}", hit.url(), hit.title());
                    }
                }
            }
        }
        _ => return Err("choose policy, locate, request, map, search, or cancel".into()),
    }
    Ok(())
}
