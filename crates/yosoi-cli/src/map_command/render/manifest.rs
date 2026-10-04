use std::io::{self, Write};

use anyhow::{Context as _, Result};
use serde::Serialize;
use thiserror::Error;
use yosoi::policy::Map as MapPolicy;
use yosoi::{Document, map};

mod inventory;
mod sources;

use super::wire::TerminationView;

const MAX_MANIFEST_BYTES: usize = 16_777_216;
const MAP_DOCUMENT_ID: &str = "map-result";

pub(super) fn document(
    outcome: &map::MapOutcome,
    seed: &str,
    profile: Option<&str>,
) -> Result<Document> {
    let snapshot = outcome.policy_snapshot();
    let identity = snapshot.identity();
    let manifest = Manifest {
        schema_version: 1,
        cli_version: env!("CARGO_PKG_VERSION"),
        seed,
        policy_profile: profile,
        policy_identity: PolicyIdentity {
            version: identity.version(),
            sha256: identity.digest().to_string(),
        },
        map_policy: &snapshot.effective_policy().map,
        termination: TerminationView(outcome.termination()),
        summary: SummaryView {
            counts: CountsView {
                hosts: outcome.hosts().len(),
                pages: outcome.pages().len(),
                relationships: outcome.relationships().len(),
                wildcard_patterns: outcome.wildcard_names().len(),
                tree: outcome.tree().len(),
                sources: outcome.sources().len(),
                support_documents: outcome.support_documents().len(),
                frontier: outcome.frontier().len(),
            },
            requests: outcome.summary().requests,
            provider_concurrency_peak: outcome.summary().provider_concurrency_peak,
            page_concurrency_peak: outcome.summary().page_concurrency_peak,
            unused_page_prefetches: outcome.summary().unused_page_prefetches,
            response_bytes: outcome.summary().response_bytes,
            inventory_bytes: outcome.summary().inventory_bytes,
            observations: outcome.summary().observations,
            omitted: outcome.summary().omitted,
            retained_document_bytes: outcome.summary().retained_document_bytes,
        },
        hosts: inventory::HostsView(outcome.hosts()),
        wildcard_patterns: outcome.wildcard_names(),
        wildcard_provenance: inventory::WildcardsView(outcome.wildcards()),
        pages: inventory::PagesView(outcome.pages()),
        relationships: inventory::RelationshipsView(outcome.relationships()),
        tree: inventory::TreeView(outcome.tree()),
        sources: sources::SourcesView(outcome.sources()),
        support_documents: sources::SupportDocumentsView(outcome.support_documents()),
        omissions: sources::OmissionsView(outcome.omissions()),
        frontier: sources::FrontierView(outcome.frontier()),
        request_trace: sources::RequestTraceView(outcome.request_trace()),
    };

    let mut encoded = BoundedJsonBuffer::new();
    let serialization = serde_json::to_writer(&mut encoded, &manifest);
    if encoded.exceeded_limit {
        return Err(RenderError::ManifestTooLarge.into());
    }
    serialization.context("could not serialize map manifest")?;
    Document::json(MAP_DOCUMENT_ID, encoded.into_bytes())
        .context("could not create typed map manifest document")
}

#[derive(Serialize)]
struct Manifest<'a> {
    schema_version: u16,
    cli_version: &'static str,
    seed: &'a str,
    policy_profile: Option<&'a str>,
    policy_identity: PolicyIdentity,
    map_policy: &'a MapPolicy,
    termination: TerminationView,
    summary: SummaryView,
    hosts: inventory::HostsView<'a>,
    wildcard_patterns: &'a [String],
    wildcard_provenance: inventory::WildcardsView<'a>,
    pages: inventory::PagesView<'a>,
    relationships: inventory::RelationshipsView<'a>,
    tree: inventory::TreeView<'a>,
    sources: sources::SourcesView<'a>,
    support_documents: sources::SupportDocumentsView<'a>,
    omissions: sources::OmissionsView<'a>,
    frontier: sources::FrontierView<'a>,
    request_trace: sources::RequestTraceView<'a>,
}

#[derive(Serialize)]
struct PolicyIdentity {
    version: u16,
    sha256: String,
}

#[derive(Serialize)]
struct SummaryView {
    counts: CountsView,
    requests: u32,
    provider_concurrency_peak: u32,
    page_concurrency_peak: u32,
    unused_page_prefetches: u32,
    response_bytes: u64,
    inventory_bytes: u64,
    observations: u32,
    omitted: u64,
    retained_document_bytes: u64,
}

#[derive(Serialize)]
struct CountsView {
    hosts: usize,
    pages: usize,
    relationships: usize,
    wildcard_patterns: usize,
    tree: usize,
    sources: usize,
    support_documents: usize,
    frontier: usize,
}

struct BoundedJsonBuffer {
    bytes: Vec<u8>,
    limit: usize,
    exceeded_limit: bool,
}

impl BoundedJsonBuffer {
    const fn new() -> Self {
        Self::with_limit(MAX_MANIFEST_BYTES)
    }

    const fn with_limit(limit: usize) -> Self {
        Self {
            bytes: Vec::new(),
            limit,
            exceeded_limit: false,
        }
    }

    fn into_bytes(self) -> Vec<u8> {
        self.bytes
    }
}

impl Write for BoundedJsonBuffer {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let remaining = self
            .limit
            .checked_sub(self.bytes.len())
            .ok_or_else(|| io::Error::other("map manifest buffer exceeded its configured limit"))?;
        if bytes.len() > remaining {
            self.exceeded_limit = true;
            return Err(io::Error::other("map manifest exceeds 16 MiB"));
        }
        self.bytes
            .try_reserve(bytes.len())
            .map_err(io::Error::other)?;
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Debug, Error)]
enum RenderError {
    #[error("map manifest exceeds the 16 MiB output limit")]
    ManifestTooLarge,
}

#[cfg(test)]
mod tests {
    use std::io::Write as _;

    use super::BoundedJsonBuffer;

    #[test]
    fn bounded_buffer_accepts_limit_and_rejects_next_byte() {
        let mut output = BoundedJsonBuffer::with_limit(4);

        assert!(matches!(output.write(b"1234"), Ok(4)));
        assert!(output.write(b"5").is_err());
        assert_eq!(output.bytes.as_slice(), b"1234");
        assert!(output.exceeded_limit);
    }
}
