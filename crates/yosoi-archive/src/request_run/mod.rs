use std::collections::BTreeSet;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use yosoi_policy::{
    EffectivePolicyIdentity,
    policy::{AcquisitionKind, DocumentRequest},
};
use yosoi_types::{ActivityId, CaptureId, Sha256Digest};
use yosoi_web_capture::TupleWebOrigin;

use crate::{ARCHIVE_FORMAT_VERSION, CaptureArchiveRef, PolicyArchiveRef};

mod archive;
mod debug;
mod diagnostics;
mod document;
mod error;

pub use diagnostics::{
    RequestAttemptDiagnostic, RequestAttemptFailureKind, RequestDirectHttpRedirectDiagnostic,
    RequestDirectHttpTransportDiagnostic, RequestNotStartedReason,
};
pub use document::{
    RequestBrowserDocumentObservation, RequestDocumentOutcome, RequestDocumentPartialReason,
    RequestDocumentRecord, RequestDocumentUnavailableReason, RequestDocumentUnprojectableReason,
};
pub use error::RequestRunRecordError;

const MAX_REQUEST_ATTEMPTS: usize = 3;

/// Stable serialized projection of an effective Policy identity.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectivePolicyIdentityRecord {
    version: u16,
    digest: Sha256Digest,
}

impl EffectivePolicyIdentityRecord {
    pub const fn try_new(
        version: u16,
        digest: Sha256Digest,
    ) -> Result<Self, RequestRunRecordError> {
        if version == 0 {
            return Err(RequestRunRecordError::ZeroEffectivePolicyIdentityVersion);
        }
        Ok(Self { version, digest })
    }

    pub const fn from_identity(identity: EffectivePolicyIdentity) -> Self {
        Self {
            version: identity.version(),
            digest: identity.digest(),
        }
    }

    pub const fn version(self) -> u16 {
        self.version
    }

    pub const fn digest(self) -> Sha256Digest {
        self.digest
    }
}

impl<'de> Deserialize<'de> for EffectivePolicyIdentityRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            version: u16,
            digest: Sha256Digest,
        }

        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(wire.version, wire.digest).map_err(D::Error::custom)
    }
}

/// Why request execution stopped after its ordered attempts.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestRunTermination {
    Completed,
    Cancelled,
}

/// Whether the caller used current defaults or an explicit document set.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthoredDocumentSelection {
    Current,
    Exact,
}

/// Durable result of one authored acquisition attempt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum RequestAttemptOutcome {
    Completed {
        capture: CaptureArchiveRef,
        response_status: Option<u16>,
        documents: Vec<RequestDocumentRecord>,
    },
    Failed {
        kind: RequestAttemptFailureKind,
        diagnostic: RequestAttemptDiagnostic,
        capture: Option<CaptureArchiveRef>,
        response_status: Option<u16>,
    },
    NotStarted {
        reason: RequestNotStartedReason,
    },
}

impl RequestAttemptOutcome {
    pub const fn capture(&self) -> Option<&CaptureArchiveRef> {
        match self {
            Self::Completed { capture, .. } => Some(capture),
            Self::Failed { capture, .. } => capture.as_ref(),
            Self::NotStarted { .. } => None,
        }
    }
}

/// One ordered request attempt and its immutable outcome.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestAttemptRecord {
    capture_id: CaptureId,
    acquisition: AcquisitionKind,
    authored_selection: AuthoredDocumentSelection,
    requested_documents: Vec<DocumentRequest>,
    outcome: RequestAttemptOutcome,
}

impl RequestAttemptRecord {
    pub fn try_new(
        capture_id: CaptureId,
        acquisition: AcquisitionKind,
        authored_selection: AuthoredDocumentSelection,
        requested_documents: Vec<DocumentRequest>,
        outcome: RequestAttemptOutcome,
    ) -> Result<Self, RequestRunRecordError> {
        let record = Self {
            capture_id,
            acquisition,
            authored_selection,
            requested_documents,
            outcome,
        };
        record.validate()?;
        Ok(record)
    }

    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }
    pub const fn acquisition(&self) -> AcquisitionKind {
        self.acquisition
    }
    pub const fn authored_selection(&self) -> AuthoredDocumentSelection {
        self.authored_selection
    }
    pub fn requested_documents(&self) -> &[DocumentRequest] {
        &self.requested_documents
    }
    pub const fn outcome(&self) -> &RequestAttemptOutcome {
        &self.outcome
    }

    fn validate(&self) -> Result<(), RequestRunRecordError> {
        if let Some(capture) = self.outcome.capture() {
            validate_format("capture", capture.format_version())?;
            if capture.capture_id() != self.capture_id {
                return Err(RequestRunRecordError::CaptureReferenceMismatch {
                    attempt: self.capture_id,
                    archived: capture.capture_id(),
                });
            }
        }
        if let RequestAttemptOutcome::Completed { documents, .. } = &self.outcome {
            if documents.len() != self.requested_documents.len() {
                return Err(RequestRunRecordError::DocumentOutcomeCountMismatch {
                    expected: self.requested_documents.len(),
                    observed: documents.len(),
                });
            }
            for (position, (expected, document)) in
                self.requested_documents.iter().zip(documents).enumerate()
            {
                if *expected != document.requested() {
                    return Err(RequestRunRecordError::DocumentOutcomeOrderMismatch {
                        position,
                        expected: *expected,
                        recorded: document.requested(),
                    });
                }
                match document.outcome() {
                    RequestDocumentOutcome::Produced { document }
                    | RequestDocumentOutcome::Partial {
                        document: Some(document),
                        ..
                    } if document.source_artifact().is_none() => {
                        return Err(RequestRunRecordError::DocumentSourceArtifactMissing {
                            requested: *expected,
                        });
                    }
                    RequestDocumentOutcome::Produced { .. }
                    | RequestDocumentOutcome::Partial { .. }
                    | RequestDocumentOutcome::Unavailable { .. }
                    | RequestDocumentOutcome::Unprojectable { .. } => {}
                }
                if let RequestDocumentOutcome::Partial {
                    document: archived,
                    artifact,
                    reasons,
                } = document.outcome()
                {
                    if reasons.is_empty() {
                        return Err(RequestRunRecordError::PartialDocumentReasonsEmpty {
                            requested: document.requested(),
                        });
                    }
                    if archived.is_some() == artifact.is_some() {
                        return Err(RequestRunRecordError::NonCanonicalPartialDocument {
                            requested: document.requested(),
                        });
                    }
                }
                for artifact in document
                    .outcome()
                    .artifact_references()
                    .into_iter()
                    .flatten()
                {
                    let artifact_activity = artifact.as_untyped().activity_id();
                    if artifact_activity != self.capture_id.activity_id() {
                        return Err(RequestRunRecordError::DocumentArtifactOwnershipMismatch {
                            requested: document.requested(),
                            artifact_activity,
                            capture_id: self.capture_id,
                        });
                    }
                }
            }
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for RequestAttemptRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            capture_id: CaptureId,
            acquisition: AcquisitionKind,
            authored_selection: AuthoredDocumentSelection,
            requested_documents: Vec<DocumentRequest>,
            outcome: RequestAttemptOutcome,
        }
        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(
            wire.capture_id,
            wire.acquisition,
            wire.authored_selection,
            wire.requested_documents,
            wire.outcome,
        )
        .map_err(D::Error::custom)
    }
}

/// Immutable request provenance and ordered attempt outcomes.
#[derive(Clone, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestRunRecord {
    request_id: ActivityId,
    target_origin: TupleWebOrigin,
    policy: PolicyArchiveRef,
    effective_policy: EffectivePolicyIdentityRecord,
    termination: RequestRunTermination,
    attempts: Vec<RequestAttemptRecord>,
}

impl RequestRunRecord {
    pub fn try_new(
        request_id: ActivityId,
        target_origin: TupleWebOrigin,
        policy: PolicyArchiveRef,
        effective_policy: EffectivePolicyIdentityRecord,
        termination: RequestRunTermination,
        attempts: Vec<RequestAttemptRecord>,
    ) -> Result<Self, RequestRunRecordError> {
        let record = Self {
            request_id,
            target_origin,
            policy,
            effective_policy,
            termination,
            attempts,
        };
        record.validate()?;
        Ok(record)
    }

    pub const fn request_id(&self) -> ActivityId {
        self.request_id
    }
    pub const fn target_origin(&self) -> &TupleWebOrigin {
        &self.target_origin
    }
    pub const fn policy(&self) -> &PolicyArchiveRef {
        &self.policy
    }
    pub const fn effective_policy(&self) -> EffectivePolicyIdentityRecord {
        self.effective_policy
    }
    pub const fn termination(&self) -> RequestRunTermination {
        self.termination
    }
    pub fn attempts(&self) -> &[RequestAttemptRecord] {
        &self.attempts
    }

    pub(crate) fn validate(&self) -> Result<(), RequestRunRecordError> {
        validate_format("policy", self.policy.format_version())?;
        if self.attempts.len() > MAX_REQUEST_ATTEMPTS {
            return Err(RequestRunRecordError::TooManyAttempts {
                maximum: MAX_REQUEST_ATTEMPTS,
                observed: self.attempts.len(),
            });
        }
        let mut captures = BTreeSet::new();
        for attempt in &self.attempts {
            attempt.validate()?;
            if !captures.insert(attempt.capture_id()) {
                return Err(RequestRunRecordError::DuplicateCaptureId {
                    capture_id: attempt.capture_id(),
                });
            }
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for RequestRunRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            request_id: ActivityId,
            target_origin: TupleWebOrigin,
            policy: PolicyArchiveRef,
            effective_policy: EffectivePolicyIdentityRecord,
            termination: RequestRunTermination,
            attempts: Vec<RequestAttemptRecord>,
        }
        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(
            wire.request_id,
            wire.target_origin,
            wire.policy,
            wire.effective_policy,
            wire.termination,
            wire.attempts,
        )
        .map_err(D::Error::custom)
    }
}

const fn validate_format(kind: &'static str, found: u32) -> Result<(), RequestRunRecordError> {
    if found != ARCHIVE_FORMAT_VERSION {
        return Err(RequestRunRecordError::ReferenceFormatMismatch {
            reference_kind: kind,
            found,
            expected: ARCHIVE_FORMAT_VERSION,
        });
    }
    Ok(())
}
