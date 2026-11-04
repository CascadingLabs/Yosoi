#![cfg(unix)]
#![expect(
    clippy::panic_in_result_fn,
    reason = "Assertions verify archived routing evidence."
)]
use std::{error::Error, fs};
use yosoi::{
    Archive, Policy,
    policy::respectfulness::{Group, Respectfulness},
    registry::Registry,
    search::{self, AutoRotationTrace, SearchReplayError},
};
type TestResult = Result<(), Box<dyn Error>>;

#[tokio::test(flavor = "current_thread")]
async fn rejected_auto_audit_survives_registry_compaction_and_offline_restore() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("registry.jsonl");
    let registry = Registry::jsonl(&path)?;
    let policy = Policy {
        respectfulness: Some(Respectfulness::new(vec![Group {
            blocked: true,
            ..Group::new("blocked", ["^https://"])
        }])?),
        ..Policy::default()
    };
    let response = search::new("no outbound work")?
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    let trace = response.rotation().ok_or("missing rejection audit")?;
    assert_eq!(trace.search_request_id, response.request_id().to_string());
    assert_eq!(trace.cursor_before, None);
    assert_eq!(trace.cursor_after, None);
    assert_eq!(trace.revision_before, trace.revision_after);
    assert!(trace.transaction.is_none());
    assert_eq!(trace.skipped.len(), 4);
    let archive = Archive::open(directory.path().join("archive")).await?;
    let evidence = response.save_diagnostics(&archive).await?;
    assert_eq!(evidence.records.len(), 0);
    let reference = evidence
        .rotation
        .ok_or("missing metadata-only Archive reference")?;
    let before = registry.snapshot()?;
    registry.compact()?;
    assert_eq!(registry.snapshot()?, before);
    drop(registry);
    fs::rename(&path, directory.path().join("registry-offline.jsonl"))?;
    let reopened = Archive::open(archive.root()).await?;
    assert_eq!(
        AutoRotationTrace::read_from(&reopened, &reference).await?,
        *trace
    );
    assert!(
        !path.exists(),
        "reading audit must not reopen or initialize Registry"
    );
    let mut invalid = trace.clone();
    invalid.cursor_after = Some(1);
    assert!(matches!(
        invalid.write_to(&reopened).await,
        Err(SearchReplayError::InvalidBounds)
    ));
    Ok(())
}
