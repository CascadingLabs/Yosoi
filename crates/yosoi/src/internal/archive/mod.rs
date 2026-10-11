//! Narrow asynchronous local persistence for validated Yosoi values.
//!
//! The first executable slices archive authored [`crate::internal::policy::Policy`], exact
//! [`crate::internal::web_capture::CaptureBundle`] evidence, compiled [`crate::internal::documents::Plan`],
//! normalized [`crate::internal::documents::Document`] values, and
//! [`crate::internal::contracts::ContractSchema`] definitions. Archive also owns bounded
//! request-run, offline-evaluation, locator-result, and Contract-result
//! records without depending on the high-level request executor. Its sealed
//! `write` and `read` methods remain closed to arbitrary application types and
//! storage providers.

use std::path::{Path, PathBuf};

#[cfg(test)]
extern crate self as yosoi_archive;

#[cfg(test)]
mod integration_tests;

mod capture;
mod contract_run;
mod contract_schema;
mod dispatch;
mod document;
mod error;
mod evaluation_run;
mod locator_run;
mod plan;
mod policy;
mod refs;
mod request_run;
mod storage;
mod wire;

pub use capture::{MAX_CAPTURE_MATERIALIZED_BYTES, MAX_CAPTURE_PAYLOADS};
pub use contract_run::{
    ArchivedCandidateField, ArchivedContractField, ArchivedContractFieldValue,
    ArchivedContractOutcome, ArchivedContractRecordIssue, ArchivedContractValue,
    ArchivedExtractionDiagnostic, ArchivedExtractionFailure, ArchivedExtractionLimit,
    ArchivedFieldIssue, ArchivedFieldIssueKind, ArchivedValidatedContractRecord,
    ArchivedValidationCode, ArchivedValidationFailure, ContractRunRecord, ContractRunRecordError,
};
#[doc(hidden)]
pub use dispatch::{ArchiveReference, ArchiveValue};
pub use document::MAX_ARCHIVED_DOCUMENT_BYTES;
pub use error::ArchiveError;
pub use evaluation_run::{
    ArchivedDocumentInput, EvaluationRunError, EvaluationRunRecord, MAX_EVALUATION_DOCUMENTS,
};
pub use locator_run::{LocatorRunRecord, LocatorRunRecordError};
pub use refs::{
    ArchiveRefError, CaptureArchiveRef, ContractRunArchiveRef, ContractSchemaArchiveRef,
    DocumentArchiveRef, EvaluationRunArchiveRef, LocatorRunArchiveRef, PlanArchiveRef,
    PolicyArchiveRef, RequestRunArchiveRef,
};
pub use request_run::{
    AuthoredDocumentSelection, EffectivePolicyIdentityRecord, RequestAttemptDiagnostic,
    RequestAttemptFailureKind, RequestAttemptOutcome, RequestAttemptRecord,
    RequestBrowserDocumentObservation, RequestDirectHttpRedirectDiagnostic,
    RequestDirectHttpTransportDiagnostic, RequestDocumentOutcome, RequestDocumentPartialReason,
    RequestDocumentRecord, RequestDocumentUnavailableReason, RequestDocumentUnprojectableReason,
    RequestNotStartedReason, RequestRunRecord, RequestRunRecordError, RequestRunTermination,
};
pub use wire::{ARCHIVE_FORMAT_VERSION, ARCHIVE_WRITER_PACKAGE, ARCHIVE_WRITER_VERSION};

/// One concrete handle to a local `.yosoi` Archive.
///
/// The handle owns only an absolute root path. It has no background writer and
/// holds no files open between operations, so dropping it is sufficient cleanup.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Archive {
    root: PathBuf,
}

impl Archive {
    /// Opens or creates the current local Archive format beneath `root`.
    pub async fn open(root: impl AsRef<Path>) -> Result<Self, ArchiveError> {
        storage::open(root.as_ref()).await
    }

    /// Returns the caller-selected root as an absolute path.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Returns the current physical format root.
    pub fn format_root(&self) -> PathBuf {
        self.root
            .join("archive")
            .join(format!("v{ARCHIVE_FORMAT_VERSION}"))
    }

    /// Writes one supported value and returns its exact typed reference.
    pub async fn write<V>(&self, value: &V) -> Result<V::Reference, ArchiveError>
    where
        V: ArchiveValue,
    {
        V::write_to(self, value).await
    }

    /// Reads the exact value selected by one typed Archive reference.
    pub async fn read<R>(&self, reference: &R) -> Result<R::Value, ArchiveError>
    where
        R: ArchiveReference,
    {
        R::read_from(self, reference).await
    }
}

pub use crate::internal::types::BrowserFailureReason;
