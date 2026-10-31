//! Opt-in Archive capture and bounded, offline Search replay.

use std::{
    env,
    fs::{File, OpenOptions},
    io::{self, Read, StdoutLock, Write},
    path::{Path, PathBuf},
    process::ExitCode,
};

use anyhow::{Context as _, Result, bail};
use clap::Args;
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use yosoi::{
    Archive,
    search::{SearchReplay, SearchResponse},
};

use super::view::{
    CoverageView, PolicyIdentityView, ProviderIdentityView, ProviderProfileView, ProviderStatus,
    RequestAttemptView, SearchEnvelope,
};

const MAX_MANIFEST_BYTES: u64 = 2_097_152;
const MAX_RECORDS: usize = 256;

#[derive(Debug, Args)]
pub struct ReplayArgs {
    /// JSON manifest written by search --diagnostics.
    pub manifest: PathBuf,
    /// Archive root override; otherwise use the manifest's parent directory.
    #[arg(long)]
    pub archive_root: Option<PathBuf>,
}

#[derive(Serialize)]
struct EvidenceBundle<'a> {
    schema_version: u16,
    cli_version: String,
    binary_sha256: String,
    source_revision: Option<String>,
    exact_source_validation: bool,
    search: SearchEvidenceSummary<'a>,
    records: Vec<SearchReplay>,
}

#[derive(Serialize)]
struct SearchEvidenceSummary<'a> {
    policy_identity: &'a PolicyIdentityView,
    termination: &'a str,
    providers: Vec<ProviderEvidenceSummary<'a>>,
}

#[derive(Serialize)]
struct ProviderEvidenceSummary<'a> {
    provider: &'static str,
    identity: &'a ProviderIdentityView<'a>,
    status: ProviderStatus,
    detail: Option<&'static str>,
    profile: &'a ProviderProfileView,
    request_id: Option<&'a str>,
    recovery_attempted: bool,
    attempts: &'a [RequestAttemptView],
    coverage: Option<&'a CoverageView>,
    hit_count: usize,
    feature_count: usize,
    issue_count: usize,
}

fn summarize<'a>(envelope: &'a SearchEnvelope<'_>) -> SearchEvidenceSummary<'a> {
    SearchEvidenceSummary {
        policy_identity: &envelope.policy_identity,
        termination: envelope.termination,
        providers: envelope
            .providers
            .iter()
            .map(|provider| ProviderEvidenceSummary {
                provider: provider.provider,
                identity: &provider.identity,
                status: provider.status,
                detail: provider.detail,
                profile: &provider.profile,
                request_id: provider.request_id.as_deref(),
                recovery_attempted: provider.recovery_query.is_some(),
                attempts: &provider.attempts,
                coverage: provider.coverage.as_ref(),
                hit_count: provider.hits.len(),
                feature_count: provider.features.len(),
                issue_count: provider.issues.len(),
            })
            .collect(),
    }
}

#[derive(Deserialize)]
struct ReplayBundle {
    schema_version: u16,
    records: Vec<SearchReplay>,
}

pub(super) async fn save(
    root: &Path,
    response: &SearchResponse,
    envelope: &SearchEnvelope<'_>,
) -> Result<PathBuf> {
    let archive = Archive::open(root)
        .await
        .context("could not open Search diagnostic Archive")?;
    let mut records = Vec::new();
    for provider in response.providers() {
        for capture in provider.captures() {
            if records.len() >= MAX_RECORDS {
                bail!("Search evidence exceeds the {MAX_RECORDS} document limit");
            }
            records.push(
                capture
                    .save(&archive)
                    .await
                    .context("could not save Search document")?,
            );
        }
    }
    let bundle = EvidenceBundle {
        schema_version: 1,
        cli_version: env!("CARGO_PKG_VERSION").to_owned(),
        binary_sha256: executable_sha256()?,
        source_revision: option_env!("YOSOI_BUILD_SOURCE_REVISION").map(str::to_owned),
        // A compiled revision assertion plus binary hash still needs exact-head test evidence.
        exact_source_validation: false,
        search: summarize(envelope),
        records,
    };
    let bytes = serde_json::to_vec_pretty(&bundle).context("could not encode Search evidence")?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_MANIFEST_BYTES {
        bail!("Search evidence manifest exceeds {MAX_MANIFEST_BYTES} bytes");
    }
    let path = archive
        .root()
        .join(format!("search-{}.json", response.request_id()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    let mut file = options
        .open(&path)
        .context("could not create private Search evidence manifest")?;
    file.write_all(&bytes)
        .context("could not write Search evidence manifest")?;
    file.sync_all()
        .context("could not persist Search evidence manifest")?;
    Ok(path)
}

pub async fn run(args: ReplayArgs) -> Result<ExitCode> {
    let mut bytes = Vec::new();
    File::open(&args.manifest)
        .context("could not open Search evidence manifest")?
        .take(MAX_MANIFEST_BYTES.saturating_add(1))
        .read_to_end(&mut bytes)
        .context("could not read Search evidence manifest")?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_MANIFEST_BYTES {
        bail!("Search evidence manifest exceeds {MAX_MANIFEST_BYTES} bytes");
    }
    let bundle: ReplayBundle =
        serde_json::from_slice(&bytes).context("invalid Search evidence manifest")?;
    if bundle.schema_version != 1 || bundle.records.len() > MAX_RECORDS {
        bail!("unsupported or excessive Search evidence manifest");
    }
    let root = args
        .archive_root
        .as_deref()
        .or_else(|| args.manifest.parent())
        .context("Search evidence manifest has no Archive parent")?;
    let archive = Archive::open(root)
        .await
        .context("could not open Search replay Archive")?;
    let mut records = Vec::with_capacity(bundle.records.len());
    let mut all_match = !bundle.records.is_empty();
    for (index, record) in bundle.records.iter().enumerate() {
        let replayed = record
            .replay(&archive)
            .await
            .context("could not replay Search document")?
            .decision();
        let matches = record.observed == replayed;
        all_match &= matches;
        records.push(
            serde_json::json!({"index": index, "provider": record.provider,
            "request_id": record.request_id, "capture_id": record.capture_id,
            "selected_for_parsing": record.selected_for_parsing,
            "recovery": record.original_provider_page_url != record.provider_page_url,
            "observed": record.observed, "replayed": replayed, "matches": matches}),
        );
    }
    serde_json::to_writer(
        io_stdout(),
        &serde_json::json!({"schema_version": 1,
        "network_requests": 0, "record_count": records.len(), "all_match": all_match,
        "source_revision": option_env!("YOSOI_BUILD_SOURCE_REVISION"), "binary_sha256": executable_sha256()?, "records": records}),
    )
    .context("could not write Search replay report")?;
    writeln!(io_stdout()).context("could not finish Search replay report")?;
    Ok(if records.is_empty() {
        ExitCode::from(2)
    } else if all_match {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    })
}

fn io_stdout() -> StdoutLock<'static> {
    io::stdout().lock()
}

fn executable_sha256() -> Result<String> {
    let path = env::current_exe().context("could not identify running CLI")?;
    let mut file = File::open(path).context("could not hash running CLI")?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 8_192];
    loop {
        let count = file
            .read(&mut buffer)
            .context("could not read running CLI")?;
        if count == 0 {
            break;
        }
        let bytes = buffer
            .get(..count)
            .context("invalid executable read extent")?;
        digest.update(bytes);
    }
    Ok(format!("{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    #![expect(
        clippy::panic_in_result_fn,
        reason = "Assertions report CLI replay regressions."
    )]
    use super::*;
    use crate::search_command::tests::fixture;
    use std::fs;
    use yosoi::{
        Document, Policy,
        archive::ArchiveError,
        policy::search::Provider,
        search::{SearchReplayPolicy, replay_document},
    };

    #[test]
    fn large_search_results_do_not_expand_the_diagnostic_manifest() -> Result<()> {
        let snippet = "retained search result content ".repeat(100_000);
        let mut envelope = fixture();
        let hit = envelope
            .providers
            .first_mut()
            .and_then(|provider| provider.hits.first_mut())
            .context("missing Search fixture hit")?;
        hit.snippet = Some(&snippet);
        let output = serde_json::to_vec(&envelope)?;
        assert!(u64::try_from(output.len())? > MAX_MANIFEST_BYTES);
        let bundle = EvidenceBundle {
            schema_version: 1,
            cli_version: "synthetic-control".to_owned(),
            binary_sha256: "synthetic-control".to_owned(),
            source_revision: None,
            exact_source_validation: false,
            search: summarize(&envelope),
            records: Vec::new(),
        };
        let manifest = serde_json::to_vec(&bundle)?;
        assert!(manifest.len() < 8_192);
        let value: serde_json::Value = serde_json::from_slice(&manifest)?;
        let provider = value
            .pointer("/search/providers/0")
            .context("missing provider summary")?;
        assert_eq!(
            provider
                .get("hit_count")
                .and_then(serde_json::Value::as_u64),
            Some(1)
        );
        assert!(provider.get("hits").is_none());
        assert!(provider.get("recovery_query").is_none());
        assert!(!String::from_utf8(manifest)?.contains("retained search result content"));
        Ok(())
    }

    #[tokio::test]
    async fn cli_replays_sdk_record_bundle_from_archive() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let opened = Archive::open(directory.path()).await;
        if cfg!(not(unix)) {
            assert!(
                matches!(opened, Err(ArchiveError::UnsupportedPlatform { platform }) if platform == env::consts::OS)
            );
            return Ok(());
        }
        let archive = opened?;
        let document = Document::html(
            "synthetic-cli",
            b"<html><body>Unknown synthetic page</body></html>".to_vec(),
        )?;
        let policy = Policy::default();
        let replay_policy = SearchReplayPolicy {
            documents: policy.documents,
            locators: policy.locators,
            tuning: policy.tuning,
            result_limit: 5,
            output_limit: 1_048_576,
        };
        let url = "https://www.bing.com/search?q=synthetic+control";
        let observed =
            replay_document(Provider::Bing, document.as_ref(), url, replay_policy).decision();
        let record = SearchReplay {
            schema_version: 1,
            sdk_version: "synthetic-control".to_owned(),
            source_revision: None,
            provider: Provider::Bing,
            adapter_version: Some("synthetic-control".to_owned()),
            parser_version: "synthetic-control".to_owned(),
            profile: serde_json::json!({}),
            request_id: "synthetic-request".to_owned(),
            capture_id: "synthetic-capture".to_owned(),
            original_provider_page_url: url.to_owned(),
            provider_page_url: url.to_owned(),
            final_url: None,
            http_status: Some(200),
            capture_complete: true,
            environment: serde_json::json!({"kind":"synthetic"}),
            replay_policy,
            selected_for_parsing: true,
            document_class: document.class(),
            document_bytes: document.byte_len(),
            document: archive.write_document(&document).await?,
            observed,
        };
        let manifest = directory.path().join("sdk-records.json");
        fs::write(
            &manifest,
            serde_json::to_vec(&serde_json::json!({
            "schema_version":1, "interface":"python", "records":[record]}))?,
        )?;
        assert_eq!(
            run(ReplayArgs {
                manifest,
                archive_root: None
            })
            .await?,
            ExitCode::SUCCESS
        );
        Ok(())
    }
}
