//! Author and validate traffic policy without making an outbound request.

use std::error::Error;

use yosoi::prelude as ys;
use ys::policy::respectfulness::{Cooldown, Group, RateBudget, Respectfulness};
use ys::registry::Registry;

fn main() -> Result<(), Box<dyn Error>> {
    let group = Group {
        concurrency: Some(1),
        spacing_ms: Some(2000),
        budgets: vec![RateBudget {
            requests: 10,
            window_ms: 60_000,
        }],
        cooldown: Some(Cooldown {
            statuses: vec![429, 503],
            fallback_ms: 30_000,
            transport_errors: false,
        }),
        ..Group::new("qscrape", [r"^https://(?:[a-z0-9-]+\.)*qscrape\.dev/"])
    };
    let policy = ys::Policy {
        respectfulness: Some(Respectfulness::new(vec![group])?),
        ..ys::Policy::default()
    };
    let registry = Registry::default();
    let bound = ys::request::new("https://qscrape.dev/")
        .bind(&policy)
        .with_registry(&registry);
    bound.validate()?;
    println!("{}", policy.to_canonical_json()?);
    Ok(())
}
