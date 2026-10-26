#![expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report offline Search diagnostic regressions."
)]

use std::{env, error::Error, io, path::Path};

use crate::{
    Policy,
    internal::{
        engine::search::{ProviderOutcome, SearchIssueKind, SearchProfileFacts, parse_document},
        policy::policy::ProviderDefaultsStatus,
        types::CaptureId,
        web_capture::CaptureCompleteness,
    },
    policy::AcquisitionKind,
    search::{SearchFailure, SearchParserStatus},
};

use super::*;

const ORIGINAL: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/src/internal/engine/tests/fixtures/search-diagnostics/bing-synthetic-original.html"
));
const RECOVERY: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/src/internal/engine/tests/fixtures/search-diagnostics/bing-synthetic-recovery.html"
));
const ORIGINAL_URL: &str = "https://www.bing.com/search?q=history+of+photosynthesis";

fn capture(
    bytes: &[u8],
    provider_page_url: &str,
    phase: &str,
) -> Result<SearchCapture, Box<dyn Error>> {
    let policy = Policy::default();
    let document = Document::html(format!("synthetic-{phase}"), bytes)?.inner;
    let replay_policy = SearchReplayPolicy::from_policy(&policy, 5, 1_048_576);
    let observed = parse_document(
        Provider::Bing,
        &document,
        &policy,
        provider_page_url,
        5,
        1_048_576,
    );
    Ok(SearchCapture {
        document,
        provider: Provider::Bing,
        profile: SearchProfileFacts {
            acquisition: Some(AcquisitionKind::DirectHttp),
            defaults_status: ProviderDefaultsStatus::Exact,
            defaults_version: None,
            effective_request_policy: Some(policy.effective_identity()?),
        },
        adapter_version: Some("synthetic-control"),
        parser_version: "synthetic-control",
        request_id: format!("synthetic-{phase}"),
        capture_id: CaptureId::random(),
        provider_page_url: provider_page_url.to_owned(),
        original_provider_page_url: ORIGINAL_URL.to_owned(),
        final_url: Some(provider_page_url.to_owned()),
        http_status: Some(200),
        completeness: CaptureCompleteness::Complete,
        environment: serde_json::from_value(serde_json::json!({"kind":"http","environment":{
            "client":{"id":"synthetic.control","version":"1"},
            "user_agent":{"status":"omitted","reason":"synthetic.control"},
            "preferred_languages":{"status":"omitted","reason":"synthetic.control"}}}))?,
        replay_policy,
        selected_for_parsing: true,
        observed,
    })
}

async fn supported_archive(root: &Path) -> Result<Option<Archive>, Box<dyn Error>> {
    let opened = Archive::open(root).await;
    if cfg!(not(unix)) {
        assert!(
            matches!(opened, Err(ArchiveError::UnsupportedPlatform { platform }) if platform == env::consts::OS)
        );
        return Ok(None);
    }
    Ok(Some(opened?))
}

#[tokio::test]
async fn archive_replays_original_and_recovery_decisions_with_exact_profiles()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let Some(archive) = supported_archive(directory.path()).await? else {
        return Ok(());
    };
    let original = capture(ORIGINAL, ORIGINAL_URL, "original")?;
    let recovery = capture(
        RECOVERY,
        "https://www.bing.com/search?q=photosynthesis",
        "recovery",
    )?;
    assert_eq!(
        original.observed().decision().status,
        SearchParserStatus::Results
    );
    assert!(original.observed().decision().partial);
    assert_eq!(original.observed().decision().hit_count, 3);
    let ProviderOutcome::Results(original_page) = &original.observed().outcome else {
        return Err(io::Error::other("synthetic original should retain parsed hits").into());
    };
    assert!(
        original_page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    );
    assert_eq!(
        recovery.observed().decision().status,
        SearchParserStatus::Results
    );
    assert_ne!(original.capture_id(), recovery.capture_id());
    for captured in [original, recovery] {
        let record = captured.save(&archive).await?;
        let json = serde_json::to_string(&record)?;
        let restored: SearchReplay = serde_json::from_str(&json)?;
        let replayed = restored.replay(&archive).await?;
        assert_eq!(record.observed, replayed.decision());
        assert_eq!(
            captured.document().profile(),
            archive.read_document(&record.document).await?.profile()
        );
        assert_eq!(
            captured.document().bytes(),
            archive.read_document(&record.document).await?.bytes()
        );
        assert_eq!(restored.original_provider_page_url, ORIGINAL_URL);
        let diagnostic = format!("{captured:?} {record:?}");
        assert!(!diagnostic.contains("photosynthesis"));
        assert!(!diagnostic.contains("Space telescopes"));
    }
    Ok(())
}

#[tokio::test]
async fn replay_accepts_a_valid_large_live_output_budget() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let Some(archive) = supported_archive(directory.path()).await? else {
        return Ok(());
    };
    let mut captured = capture(ORIGINAL, ORIGINAL_URL, "large-output-budget")?;
    captured.replay_policy.output_limit = 67_108_865;
    let record = captured.save(&archive).await?;
    assert_eq!(record.observed, record.replay(&archive).await?.decision());
    Ok(())
}

#[tokio::test]
async fn replay_retains_http_blocks_and_rejects_invalid_manifest_bounds()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let Some(archive) = supported_archive(directory.path()).await? else {
        return Ok(());
    };
    let mut captured = capture(ORIGINAL, ORIGINAL_URL, "rate-limit")?;
    captured.http_status = Some(429);
    captured.observed = SearchReplayResult {
        outcome: super::super::ProviderOutcome::Failed(SearchFailure::RateLimited),
        parser_diagnostic: None,
    };
    let mut record = captured.save(&archive).await?;
    assert_eq!(
        record.replay(&archive).await?.decision().failure,
        Some(SearchFailure::RateLimited)
    );
    record.schema_version = 2;
    assert!(matches!(
        record.replay(&archive).await,
        Err(SearchReplayError::UnsupportedVersion(2))
    ));
    record.schema_version = 1;
    record.replay_policy.output_limit = 0;
    assert!(matches!(
        record.replay(&archive).await,
        Err(SearchReplayError::InvalidBounds)
    ));
    Ok(())
}

#[test]
fn replay_policy_does_not_retain_network_credentials() -> Result<(), Box<dyn Error>> {
    let mut policy = Policy::default();
    policy.network.proxy = Some("http://secret-user:secret-password@127.0.0.1:8888".to_owned());
    let replay = SearchReplayPolicy::from_policy(&policy, 5, 1_048_576);
    let json = serde_json::to_string(&replay)?;
    assert!(!json.contains("secret-user"));
    assert!(!json.contains("secret-password"));
    assert!(!json.contains("network"));
    assert_eq!(replay.documents, policy.documents);
    assert_eq!(replay.locators, policy.locators);
    Ok(())
}
