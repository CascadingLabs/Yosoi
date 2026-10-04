//! Bundle-last orchestration for one bounded Direct HTTP attempt.
#![allow(
    clippy::collapsible_if,
    clippy::needless_pass_by_value,
    clippy::result_large_err,
    clippy::type_complexity,
    clippy::wildcard_imports,
    clippy::redundant_pub_crate,
    clippy::absolute_paths,
    clippy::large_futures,
    reason = "the orchestration boundary keeps owned non-lossy evidence together"
)]

use std::{ops::Deref, time::SystemTime};

use chrono::{DateTime, Utc};
use thiserror::Error;
use tokio_util::sync::CancellationToken;
use yosoi_types::{
    ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Provenance, ReasonCode,
};

use crate::{
    ArtifactByteExtent, ArtifactCollection, ArtifactFamilyResult, ArtifactSensitivity,
    BodyTerminal, ByteCount, CaptureBundle, CaptureEnvironment, CaptureOffset,
    CharacterDecodingOutcome, DecodedOutputIdentity, DecodedOutputIdentityError,
    DecodedSourceArtifact, DecodedSourceArtifactRef, DirectHttpFailure, LifecycleError,
    LifecycleFinalizationInput, MeasuredCount, MediaDeclaration, MediaType, NetworkArtifact,
    ResponseBodyFailure, ResponseBodyOutcome, RetainedSource, RetainedSourceExtent,
    RetainedSourceReplayError, SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE, SourceArtifact,
    SourceClassificationOutcome, SourceFormat, SourceRepresentationArtifact,
    SourceRepresentationEvidence, SourceRepresentationFacts, SourceRetentionPolicy,
    StagedPayloadError, StagedPayloads, UnsupportedSourceFormatBehavior, ValidatedSourceBinding,
    WebArtifactManifest, WebArtifactResults, WebProviderCapabilityProfile, parse_media_declaration,
};

mod artifacts;
mod error;
mod finalize;
mod outcome;

pub use error::DirectHttpCaptureEvidence;
pub use error::{DirectHttpCaptureError, DirectHttpConstructionError, DirectHttpReplayError};
pub use finalize::{
    DirectHttpCaptureTimestamps, capture_direct_http, capture_direct_http_at,
    capture_direct_http_at_with_redirect_policy, capture_direct_http_with_clock,
    capture_direct_http_with_redirect_policy,
};
#[cfg(test)]
pub(crate) use finalize::{capture_direct_http_with_client_at, capture_direct_http_with_sink_at};
pub use outcome::DirectHttpCapture;
