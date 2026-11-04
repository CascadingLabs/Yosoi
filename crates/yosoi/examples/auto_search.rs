//! Author Auto routing and validate it without contacting a provider.
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::search::{Provider, Search};
fn main() -> Result<(), Box<dyn Error>> {
    let policy = ys::Policy {
        search: Search::auto([Provider::Bing, Provider::Brave])?,
        ..ys::Policy::default()
    };
    ys::search::new("qscrape catalog")?
        .bind(&policy)
        .validate()?;
    println!("{}", policy.to_canonical_json()?);
    Ok(())
}
