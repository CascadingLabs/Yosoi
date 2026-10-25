//! Reopen optional-engine records with no browser execution feature or binary.
use std::{error::Error, fs, path::PathBuf};
use yosoi::{
    Archive,
    automation_record::{AutomationRecord, AutomationRecordRef},
    browser::BrowserEngine,
};
#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let directory = PathBuf::from(std::env::var("BIDI_CONSUMER_RECORDS")?);
    let reference: AutomationRecordRef =
        serde_json::from_slice(&fs::read(directory.join("reference.json"))?)?;
    let archive = Archive::open(directory).await?;
    let record = AutomationRecord::read_from(&archive, &reference).await?;
    if record.operations().len() != 4
        || record.operations().iter().any(|operation| {
            operation
                .browser
                .as_ref()
                .is_none_or(|identity| identity.engine != BrowserEngine::Moli)
        })
    {
        return Err("offline optional-engine evidence was lost".into());
    }
    println!(
        "{}",
        serde_json::json!({"offline_operations":record.operations().len(),"browser_feature":false})
    );
    Ok(())
}
