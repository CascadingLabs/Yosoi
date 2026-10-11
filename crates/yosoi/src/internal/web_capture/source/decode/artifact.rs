use crate::internal::types::{ArtifactAvailability, ArtifactRecord, Provenance, ReasonCode};

use super::{DECODED_SOURCE_UTF8_MEDIA_TYPE, DecodedOutputIdentity, digest};
use crate::internal::web_capture::{
    ArtifactByteExtent, ByteCount, DecodedSourceArtifact, DecodedSourceInterpretation,
    MeasuredCount, MediaType, SourceArtifact, WebArtifactMetadata,
};

const OUTPUT_TRUNCATED_REASON: &str = "source.decoded_output_truncated";
const COMPLETE_SIZE_UNAVAILABLE_REASON: &str = "source.decoded_complete_size_unavailable";

pub(super) fn decoded_artifact(
    source: &SourceArtifact,
    output: &DecodedOutputIdentity,
    bytes: &[u8],
    truncated: bool,
    interpretation: DecodedSourceInterpretation,
) -> Option<DecodedSourceArtifact> {
    let retained = ByteCount::new(u64::try_from(bytes.len()).ok()?);
    let reason = ReasonCode::new(OUTPUT_TRUNCATED_REASON).ok()?;
    let (availability, availability_reason, extent) = if truncated {
        (
            ArtifactAvailability::Truncated,
            Some(reason),
            ArtifactByteExtent::truncated(
                retained,
                MeasuredCount::Unavailable {
                    reason: ReasonCode::new(COMPLETE_SIZE_UNAVAILABLE_REASON).ok()?,
                },
            )
            .ok()?,
        )
    } else {
        (
            ArtifactAvailability::Retained,
            None,
            ArtifactByteExtent::Complete {
                retained_bytes: retained,
            },
        )
    };
    let provenance = Provenance::new(
        output.reference().as_untyped().activity_id(),
        output.producer().clone(),
        output.schema().clone(),
        output
            .generated_at()
            .copied()
            .unwrap_or_else(|| source.metadata().provenance().generated_at().to_owned()),
        output.derived_from().to_vec(),
    );
    let record = ArtifactRecord::new(
        output.reference().as_untyped().artifact_id(),
        Some(digest(bytes)),
        availability,
        availability_reason,
        provenance,
    )
    .ok()?;
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new(DECODED_SOURCE_UTF8_MEDIA_TYPE).ok()?,
        extent,
        source.metadata().sensitivity(),
    )
    .ok()?;
    DecodedSourceArtifact::try_from_source_with_interpretation(
        metadata,
        source.reference(),
        interpretation,
    )
    .ok()
}
