use std::fmt;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    archive::{Archive, ArchiveError, DocumentArchiveRef},
    documents::{Document, DocumentClass, DocumentRef},
    internal::{
        engine::search::{parse_document, status_failure},
        web_capture::CaptureCompleteness,
    },
    policy::{
        Policy,
        search::{Provider, ProviderDefaultsVersion},
    },
};

use super::{SearchCapture, SearchParserDecision, SearchReplayPolicy, SearchReplayResult};

#[cfg(test)]
mod tests;

/// Persisted reference to one bounded Search document and its replay inputs.
///
/// This contains query URLs and safe capture environment facts. It excludes
/// cookies, headers, launch arguments, credentials, and complete Requests policy.
/// Archive validates document identity, profile, byte length, and integrity.
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SearchReplay {
    /// Search diagnostic manifest format; currently one.
    pub schema_version: u16,
    /// SDK version that captured this evidence; this alone is not exact-source proof.
    pub sdk_version: String,
    /// Optional source revision embedded at build time through YOSOI_BUILD_SOURCE_REVISION.
    pub source_revision: Option<String>,
    /// Provider whose single-document parser should replay the evidence.
    pub provider: Provider,
    /// Adapter implementation label for the selected acquisition route.
    pub adapter_version: Option<String>,
    /// Parser implementation label recorded when this document was captured.
    pub parser_version: String,
    /// Secret-safe route/defaults and effective Requests policy identity facts.
    pub profile: serde_json::Value,
    /// Request identity for this original or recovery acquisition.
    pub request_id: String,
    /// Capture identity shared by paired projected representations.
    pub capture_id: String,
    /// Original authored provider URL, preserved when this is recovery evidence.
    pub original_provider_page_url: String,
    /// Provider URL used for this document's parser decision, including its query.
    pub provider_page_url: String,
    /// Final observed URL, absent when Requests did not record one.
    pub final_url: Option<String>,
    /// Observed HTTP status; status success does not establish useful results.
    pub http_status: Option<u16>,
    /// Whether every requested capture artifact was complete.
    pub capture_complete: bool,
    /// Secret-safe capture environment, including available browser/controller identities.
    pub environment: serde_json::Value,
    /// Exact parser bounds and tuning, with no transport configuration.
    pub replay_policy: SearchReplayPolicy,
    /// Whether live Search selected this representation for its provider outcome.
    pub selected_for_parsing: bool,
    /// Representation class of the exact archived document.
    pub document_class: DocumentClass,
    /// Exact retained normalized document byte count.
    pub document_bytes: u64,
    /// Exact normalized Document reference in the caller-selected Archive.
    pub document: DocumentArchiveRef,
    /// Content-free observed decision for comparison after a provider repair.
    pub observed: SearchParserDecision,
}

impl fmt::Debug for SearchReplay {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SearchReplay")
            .field("provider", &self.provider)
            .field("request_id", &self.request_id)
            .field("capture_id", &self.capture_id)
            .field("document", &self.document)
            .field("observed", &self.observed)
            .finish_non_exhaustive()
    }
}

/// A bounded evidence record could not be replayed from the selected Archive.
#[derive(Debug, Error)]
pub enum SearchReplayError {
    /// The manifest version is not supported by this SDK.
    #[error("unsupported Search replay schema version {0}")]
    UnsupportedVersion(u16),
    /// The record exceeded a diagnostic input or output bound.
    #[error("Search replay metadata or parser limits exceed the supported bounds")]
    InvalidBounds,
    /// Archive could not store or restore the exact document.
    #[error(transparent)]
    Archive(#[from] ArchiveError),
    /// Secret-safe capture metadata could not be encoded.
    #[error("could not encode Search capture environment")]
    Metadata(#[source] serde_json::Error),
}

impl SearchReplayPolicy {
    pub(crate) fn policy(self) -> Policy {
        Policy {
            documents: self.documents,
            locators: self.locators,
            tuning: self.tuning,
            ..Policy::default()
        }
    }
}

impl SearchCapture {
    /// Returns an owned SDK Document with the exact captured identity, profile, and bytes.
    pub fn document(&self) -> Document {
        Document {
            inner: self.document.clone(),
        }
    }

    /// Returns the provider parser associated with this capture.
    pub const fn provider(&self) -> Provider {
        self.provider
    }

    /// Returns the underlying original or recovery Request identity.
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    /// Returns the capture identity shared by paired projected documents.
    pub fn capture_id(&self) -> String {
        self.capture_id.to_string()
    }

    /// Returns the original authored provider URL; this contains query content.
    pub fn original_provider_page_url(&self) -> &str {
        &self.original_provider_page_url
    }

    /// Returns the URL used by this parser invocation; this contains query content.
    pub fn provider_page_url(&self) -> &str {
        &self.provider_page_url
    }

    /// Returns the final observed URL, which can contain page/query content.
    pub fn final_url(&self) -> Option<&str> {
        self.final_url.as_deref()
    }

    /// Returns observed HTTP status without interpreting parser success.
    pub const fn http_status(&self) -> Option<u16> {
        self.http_status
    }

    /// Returns whether Requests recorded a complete capture.
    pub fn capture_complete(&self) -> bool {
        self.completeness == CaptureCompleteness::Complete
    }

    /// Returns secret-safe producer, browser, and representation environment facts.
    pub fn environment(&self) -> Result<serde_json::Value, SearchReplayError> {
        serde_json::to_value(&self.environment).map_err(SearchReplayError::Metadata)
    }

    /// Returns the exact document/locator policy and parser output bounds.
    pub const fn replay_policy(&self) -> SearchReplayPolicy {
        self.replay_policy
    }

    /// Returns whether live Search selected this representation for provider interpretation.
    pub const fn selected_for_parsing(&self) -> bool {
        self.selected_for_parsing
    }

    /// Borrows this document's original parser interpretation, before cross-request recovery.
    pub const fn observed(&self) -> &SearchReplayResult {
        &self.observed
    }

    /// Repeats the single-document parser decision without contacting a provider.
    pub fn replay(&self) -> SearchReplayResult {
        if let Some(failure) = status_failure(self.http_status) {
            return SearchReplayResult {
                outcome: super::ProviderOutcome::Failed(failure),
                parser_diagnostic: None,
            };
        }
        parse_document(
            self.provider,
            &self.document,
            &self.replay_policy.policy(),
            &self.provider_page_url,
            self.replay_policy.result_limit,
            self.replay_policy.output_limit,
        )
    }

    /// Saves the exact Document through Archive and returns a portable JSON manifest record.
    ///
    /// This is explicit query/page retention. Sanitize content before committing fixtures.
    pub async fn save(&self, archive: &Archive) -> Result<SearchReplay, SearchReplayError> {
        let document = archive.write_document(&self.document()).await?;
        Ok(SearchReplay {
            schema_version: 1,
            sdk_version: env!("CARGO_PKG_VERSION").to_owned(),
            source_revision: option_env!("YOSOI_BUILD_SOURCE_REVISION").map(str::to_owned),
            provider: self.provider,
            adapter_version: self.adapter_version.map(str::to_owned),
            parser_version: self.parser_version.to_owned(),
            profile: serde_json::json!({"acquisition": self.profile.acquisition,
                "defaults_status": self.profile.defaults_status,
                "defaults_version": self.profile.defaults_version.map(ProviderDefaultsVersion::get),
                "effective_request_policy": self.profile.effective_request_policy.map(|identity| serde_json::json!({
                    "version": identity.version(), "digest": identity.digest().to_string()}))}),
            request_id: self.request_id.clone(),
            capture_id: self.capture_id(),
            original_provider_page_url: self.original_provider_page_url.clone(),
            provider_page_url: self.provider_page_url.clone(),
            final_url: self.final_url.clone(),
            http_status: self.http_status,
            capture_complete: self.capture_complete(),
            environment: self.environment()?,
            replay_policy: self.replay_policy,
            selected_for_parsing: self.selected_for_parsing,
            document_class: self.document.class(),
            document_bytes: self.document.byte_len(),
            document,
            observed: self.observed.decision(),
        })
    }
}

impl SearchReplay {
    /// Restores the exact Document from Archive and reruns only its bounded provider parser.
    ///
    /// No Requests executor, browser, network, or recovery query is started. Compare
    /// `observed` to the returned `decision()`; changed parser versions can differ.
    pub async fn replay(&self, archive: &Archive) -> Result<SearchReplayResult, SearchReplayError> {
        if self.schema_version != 1 {
            return Err(SearchReplayError::UnsupportedVersion(self.schema_version));
        }
        if self.provider_page_url.len() > 8_192
            || self.original_provider_page_url.len() > 8_192
            || self.final_url.as_ref().is_some_and(|url| url.len() > 8_192)
            || self.replay_policy.result_limit == 0
            || self.replay_policy.result_limit > usize::from(u16::MAX)
            || self.replay_policy.output_limit == 0
        {
            return Err(SearchReplayError::InvalidBounds);
        }
        let document = archive.read_document(&self.document).await?;
        if let Some(failure) = status_failure(self.http_status) {
            return Ok(SearchReplayResult {
                outcome: super::ProviderOutcome::Failed(failure),
                parser_diagnostic: None,
            });
        }
        Ok(replay_document(
            self.provider,
            document.as_ref(),
            &self.provider_page_url,
            self.replay_policy,
        ))
    }
}

/// Interprets an existing immutable Document with the live provider parser and explicit bounds.
///
/// The URL must describe that provider's endpoint and query. This function performs
/// no acquisition; it cannot reconstruct HTTP status, final URL, or missing evidence.
pub fn replay_document(
    provider: Provider,
    document: DocumentRef<'_>,
    provider_page_url: &str,
    policy: SearchReplayPolicy,
) -> SearchReplayResult {
    parse_document(
        provider,
        document.as_internal(),
        &policy.policy(),
        provider_page_url,
        policy.result_limit,
        policy.output_limit,
    )
}
