use std::error::Error;

use tempfile::tempdir;
use yosoi::prelude as ys;

const fn require_policy_ref(_reference: &ys::PolicyArchiveRef) {}

#[tokio::test]
async fn facade_writes_and_reads_the_exact_policy_type() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let mut policy = ys::Policy::default();
    policy.locators.max_matches = ys::CountLimit::try_from(42_u64)?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;

    let reference = archive.write(&policy).await?;
    require_policy_ref(&reference);
    let reopened: ys::Policy = archive.read(&reference).await?;
    if reopened != policy {
        return Err("the yosoi facade reopened a different Policy".into());
    }
    Ok(())
}
