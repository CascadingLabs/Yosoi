//! Packaged SDK acceptance fixture; selectors belong to the counted test page.
use std::{error::Error, fs, path::PathBuf};
use yosoi::{
    Archive,
    automation_record::{AutomationRecord, OperationStatus},
    browser::{BrowserConfig, BrowserEngine, MoliProfile},
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    request, session,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let directory = PathBuf::from(std::env::var("BIDI_CONSUMER_RECORDS")?);
    let endpoint = std::env::var("YOSOI_MOLI_ENDPOINT")?;
    let url = std::env::var("YOSOI_BIDI_FIXTURE_URL")?;
    let policy = Policy {
        browser: BrowserConfig {
            engine: BrowserEngine::Moli,
            endpoint: Some(endpoint),
            moli_profile: MoliProfile::Layout,
            moli_resources: true,
            moli_allow_private_networks: true,
            ..BrowserConfig::default()
        },
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let owner = session::new().bind(&policy).acquire().await?;
    let operations = async {
        let work = owner.work().await?;
        let receipts = vec![
            work.navigate(&url).await?,
            work.click("#go").await?,
            work.enter_text("#input", "packaged").await?,
            work.screenshot().await?,
        ];
        if receipts
            .iter()
            .any(|receipt| receipt.status != OperationStatus::Observed)
        {
            return Err("packaged native operation was not Observed".into());
        }
        let observations = receipts
            .iter()
            .filter_map(|receipt| receipt.observation.clone())
            .collect::<Vec<_>>();
        if observations.len() != 4
            || receipts.iter().any(|receipt| {
                receipt.browser.as_ref().is_none_or(|identity| {
                    identity.engine != BrowserEngine::Moli
                        || identity.process_owned
                        || identity.executable_sha256.is_some()
                })
            })
        {
            return Err("packaged provenance missing or fabricated".into());
        }
        let record = AutomationRecord::new("packaged-rust-native", observations, receipts)?;
        work.release().await?;
        Ok::<_, Box<dyn Error>>(record)
    }
    .await;
    let cleanup = owner.close().await;
    let record = operations?;
    cleanup?;
    let response = request::new(&url).bind(&policy).send().await?;
    if response.attempts().len() != 1
        || response
            .attempts()
            .any(|attempt| attempt.state() != request::AttemptState::Completed)
        || response
            .attempts()
            .flat_map(|attempt| attempt.documents())
            .count()
            != 1
        || response
            .attempts()
            .flat_map(|attempt| attempt.documents())
            .any(|document| !matches!(document.outcome(), request::DocumentOutcome::Produced(_)))
    {
        return Err("packaged DOM request failed".into());
    }
    let archive = Archive::open(&directory).await?;
    let reference = record.write_to(&archive).await?;
    fs::write(
        directory.join("reference.json"),
        serde_json::to_vec(&reference)?,
    )?;
    println!(
        "{}",
        serde_json::json!({"native_operations":record.operations().len(),"dom_requests":1,"engine":"moli","process_owned":false})
    );
    Ok(())
}
