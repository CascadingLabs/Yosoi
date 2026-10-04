//! Write a Policy, release the Archive handle, and reopen it from a typed ref.

use std::env;
use std::error::Error;

use yosoi::prelude as ys;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let root = env::args_os().nth(1).unwrap_or_else(|| ".yosoi".into());
    let mut policy = ys::Policy::default();
    policy.locators.max_matches = ys::CountLimit::try_from(42_u64)?;

    let archive = ys::Archive::open(&root).await?;
    let policy_ref: ys::PolicyArchiveRef = archive.write(&policy).await?;
    let serialized_ref = policy_ref.to_string();
    println!("archived Policy as {serialized_ref}");
    drop(archive);

    let archive = ys::Archive::open(&root).await?;
    let parsed_ref: ys::PolicyArchiveRef = serialized_ref.parse()?;
    let reopened: ys::Policy = archive.read(&parsed_ref).await?;
    if reopened != policy {
        return Err("reopened Policy differs from the archived Policy".into());
    }
    println!("reopened the same Policy after dropping the first handle");
    Ok(())
}
