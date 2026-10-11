use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::types::{ArtifactAvailability, Sha256Digest};
use crate::internal::web_capture::{CaptureBundle, WebArtifactRef, WebCapture, WebCaptureWire};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{Archive, ArchiveError, CaptureArchiveRef};

const CAPTURE_SCHEMA_VERSION: u32 = 1;

/// Maximum retained payload count materialized by one Archive operation.
pub const MAX_CAPTURE_PAYLOADS: u64 = 4_096;
/// Maximum total retained payload bytes materialized by one Archive operation.
pub const MAX_CAPTURE_MATERIALIZED_BYTES: u64 = 268_435_456;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CaptureRecord {
    /// Complete owning-domain wire value; payload membership remains in its manifest.
    web_capture: Box<RawValue>,
}

impl PartialEq for CaptureRecord {
    fn eq(&self, other: &Self) -> bool {
        self.web_capture.get() == other.web_capture.get()
    }
}

impl Eq for CaptureRecord {}

#[derive(Clone, Copy, Debug)]
struct PayloadRequirement {
    reference: WebArtifactRef,
    length: u64,
    digest: Sha256Digest,
}

impl sealed::Value for CaptureBundle {}

impl ArchiveValue for CaptureBundle {
    type Reference = CaptureArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        let reference = CaptureArchiveRef::new_current(value.capture().id());
        match archive.read(&reference).await {
            Ok(existing) if &existing == value => return Ok(reference),
            Ok(_) => {
                return Err(ArchiveError::IdentityConflict {
                    kind: RecordKind::Capture.as_str(),
                    key: reference.capture_id().to_string(),
                });
            }
            Err(ArchiveError::RecordNotFound { .. }) => {}
            Err(error) => return Err(error),
        }

        let record = record_from_capture(value.capture())?;
        let requirements = payload_requirements(value.capture())?;
        for requirement in requirements {
            let bytes = value.payload(requirement.reference).ok_or_else(|| {
                ArchiveError::InvalidCaptureBundle(yosoi_web_capture::CaptureBundleError::Missing)
            })?;
            verify_payload(&requirement, bytes)?;
            archive
                .write_capture_payload(reference.capture_id(), requirement.reference, bytes)
                .await?;
        }

        let key = reference.key();
        archive
            .write_record(RecordKind::Capture, CAPTURE_SCHEMA_VERSION, &key, &record)
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for CaptureArchiveRef {}

impl ArchiveReference for CaptureArchiveRef {
    type Value = CaptureBundle;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        if reference.format_version() != ARCHIVE_FORMAT_VERSION {
            return Err(ArchiveError::UnsupportedFormat {
                found: reference.format_version(),
                supported: ARCHIVE_FORMAT_VERSION,
            });
        }
        let key = reference.key();
        let record: CaptureRecord = archive
            .read_record(RecordKind::Capture, CAPTURE_SCHEMA_VERSION, &key)
            .await?;
        let capture = WebCaptureWire::from_json(record.web_capture.get().as_bytes())
            .map_err(ArchiveError::InvalidWebCapture)?;
        if capture.id() != reference.capture_id() {
            return Err(ArchiveError::CaptureIdentityMismatch {
                expected: reference.capture_id(),
                found: capture.id(),
            });
        }

        let requirements = payload_requirements(&capture)?;
        let mut builder = CaptureBundle::builder(capture);
        for requirement in requirements {
            let bytes = archive
                .read_capture_payload(
                    reference.capture_id(),
                    requirement.reference,
                    requirement.length,
                )
                .await?;
            verify_payload(&requirement, &bytes)?;
            builder
                .insert(requirement.reference, bytes)
                .map_err(ArchiveError::InvalidCaptureBundle)?;
        }
        builder
            .finalize()
            .map_err(ArchiveError::InvalidCaptureBundle)
    }
}

fn record_from_capture(capture: &WebCapture) -> Result<CaptureRecord, ArchiveError> {
    let bytes =
        WebCaptureWire::to_canonical_json(capture).map_err(ArchiveError::InvalidWebCapture)?;
    let web_capture = serde_json::from_slice(&bytes).map_err(ArchiveError::CaptureRecordJson)?;
    Ok(CaptureRecord { web_capture })
}

fn payload_requirements(capture: &WebCapture) -> Result<Vec<PayloadRequirement>, ArchiveError> {
    let mut requirements = Vec::new();
    let mut materialized = 0_u64;
    for artifact in capture.artifacts().results().all_artifacts() {
        if !matches!(
            artifact.metadata().record().availability(),
            ArtifactAvailability::Retained | ArtifactAvailability::Truncated
        ) {
            continue;
        }
        let observed = u64::try_from(requirements.len())
            .ok()
            .and_then(|count| count.checked_add(1))
            .ok_or(ArchiveError::CapturePayloadCountExceeded {
                maximum: MAX_CAPTURE_PAYLOADS,
                observed: u64::MAX,
            })?;
        if observed > MAX_CAPTURE_PAYLOADS {
            return Err(ArchiveError::CapturePayloadCountExceeded {
                maximum: MAX_CAPTURE_PAYLOADS,
                observed,
            });
        }
        let length = artifact
            .metadata()
            .extent()
            .retained_bytes()
            .ok_or_else(|| {
                ArchiveError::InvalidCaptureBundle(
                    yosoi_web_capture::CaptureBundleError::SizeMismatch,
                )
            })?
            .get();
        materialized = materialized.checked_add(length).ok_or(
            ArchiveError::CaptureMaterializationTooLarge {
                maximum: MAX_CAPTURE_MATERIALIZED_BYTES,
                observed: u64::MAX,
            },
        )?;
        if materialized > MAX_CAPTURE_MATERIALIZED_BYTES {
            return Err(ArchiveError::CaptureMaterializationTooLarge {
                maximum: MAX_CAPTURE_MATERIALIZED_BYTES,
                observed: materialized,
            });
        }
        let digest = artifact.metadata().content_digest().ok_or_else(|| {
            ArchiveError::InvalidCaptureBundle(
                yosoi_web_capture::CaptureBundleError::DigestMismatch,
            )
        })?;
        let reference = artifact.reference();
        requirements.push(PayloadRequirement {
            reference,
            length,
            digest,
        });
    }
    Ok(requirements)
}

fn verify_payload(requirement: &PayloadRequirement, bytes: &[u8]) -> Result<(), ArchiveError> {
    let observed =
        u64::try_from(bytes.len()).map_err(|_| ArchiveError::CapturePayloadLengthMismatch {
            artifact: requirement.reference,
            expected: requirement.length,
            observed: u64::MAX,
        })?;
    if observed != requirement.length {
        return Err(ArchiveError::CapturePayloadLengthMismatch {
            artifact: requirement.reference,
            expected: requirement.length,
            observed,
        });
    }
    if Sha256Digest::digest(bytes) != requirement.digest {
        return Err(ArchiveError::CapturePayloadDigestMismatch {
            artifact: requirement.reference,
        });
    }
    Ok(())
}
