use chrono::{DateTime, Utc};
use yosoi_types::{
    ArtifactAvailability, ArtifactId, ArtifactRecord, ArtifactRef, Provenance, ReasonCode,
};

use crate::{
    AcceptedSourceFormat, ArtifactByteExtent, ArtifactCollection, ArtifactFamilyResult,
    ArtifactRequest, ArtifactSensitivity, BodyTerminal, ByteCount, CharacterDecodingOutcome,
    DecodedOutputIdentity, DecodedSourceArtifact, DecodedSourceArtifactRef, DecodedSourceView,
    DirectHttpResponseFacts, MeasuredCount, MediaDeclaration, MediaType, MediaTypeError,
    NetworkArtifact, ResolvedDirectHttpCaptureSpec, ResponseBodyOutcome, RetainedSource,
    RetainedSourceExtent, SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE, SourceArtifact,
    SourceArtifactRef, SourceClassificationOutcome, SourceFormat, SourceRepresentationArtifact,
    SourceRepresentationEvidence, SourceRepresentationFacts, SourceRetentionPolicy, StagedPayloads,
    UnsupportedSourceFormatBehavior, ValidatedSourceBinding, WebArtifactMetadata, XmlProfile,
    XmlSourceProfile, body::terminal_reason, classify_and_decode, parse_media_declaration,
    source_decoder_producer,
};

use super::DirectHttpConstructionError;

#[allow(
    clippy::type_complexity,
    reason = "artifact families and their staged payloads come from one validation pass"
)]
pub(super) fn build_artifacts(
    spec: &ResolvedDirectHttpCaptureSpec,
    outcome: &ResponseBodyOutcome,
    response: &DirectHttpResponseFacts,
    source_generated_at: DateTime<Utc>,
    decoded_generated_at: DateTime<Utc>,
) -> Result<
    (
        ArtifactFamilyResult<SourceArtifact>,
        ArtifactFamilyResult<SourceRepresentationArtifact>,
        ArtifactFamilyResult<DecodedSourceArtifact>,
        ArtifactFamilyResult<NetworkArtifact>,
        StagedPayloads,
        Option<SourceRepresentationFacts>,
    ),
    DirectHttpConstructionError,
> {
    let network = match spec.artifacts().network() {
        ArtifactRequest::NotRequested => ArtifactFamilyResult::NotRequested,
        ArtifactRequest::Optional | ArtifactRequest::Required => {
            ArtifactFamilyResult::Unavailable {
                reason: reason("web_capture.direct_http.network_bytes_unavailable")?,
            }
        }
    };
    let Some(source_input) = outcome.payload().retained_source() else {
        return Ok((
            ArtifactFamilyResult::Unavailable {
                reason: reason(body_reason(outcome))?,
            },
            ArtifactFamilyResult::Unavailable {
                reason: reason(body_reason(outcome))?,
            },
            if matches!(
                spec.retention(),
                SourceRetentionPolicy::RepresentationAndUnicodeView
            ) {
                ArtifactFamilyResult::Unavailable {
                    reason: reason(body_reason(outcome))?,
                }
            } else {
                ArtifactFamilyResult::NotRequested
            },
            network,
            StagedPayloads::default(),
            None,
        ));
    };
    // Classification needs a validated source identity, while the source media type itself
    // depends on classification. Classify once against an octet-stream provisional record,
    // then build the durable source and decoding facts from the exact final metadata.
    let media_type = response.source_media_type();
    let provisional = source_artifact(
        spec,
        source_input,
        outcome.terminal(),
        response,
        None,
        source_generated_at,
    )?;
    let provisional_decoder = decoder_identity(spec, provisional.reference())?;
    let provisional_facts = classify_and_decode(
        ValidatedSourceBinding::new(source_input, &provisional)
            .map_err(DirectHttpConstructionError::SourceBinding)?,
        &media_type,
        &provisional_decoder,
        spec.content_limits().unicode_utf8_bytes().get(),
    );
    let source = source_artifact(
        spec,
        source_input,
        outcome.terminal(),
        response,
        Some(provisional_facts.classification()),
        source_generated_at,
    )?;
    let decoder =
        decoder_identity(spec, source.reference())?.with_generated_at(decoded_generated_at);
    let facts = classify_and_decode(
        ValidatedSourceBinding::new(source_input, &source)
            .map_err(DirectHttpConstructionError::SourceBinding)?,
        &media_type,
        &decoder,
        spec.content_limits().unicode_utf8_bytes().get(),
    );
    if should_fail_unsupported(spec, facts.classification()) {
        return Err(DirectHttpConstructionError::UnsupportedSource {
            facts: Box::new(facts),
        });
    }
    let source_collection = ArtifactCollection::new(vec![source.clone()])
        .map_err(DirectHttpConstructionError::Collection)?;
    let mut decoded_result = ArtifactFamilyResult::NotRequested;
    let mut payloads = StagedPayloads::default();
    payloads
        .insert(source.reference().into(), source_input.bytes().to_vec())
        .map_err(DirectHttpConstructionError::Staging)?;
    if matches!(
        spec.retention(),
        SourceRetentionPolicy::RepresentationAndUnicodeView
    ) {
        if let Some(view) = decoded_view(facts.decoding()) {
            let decoded = view.artifact().clone();
            payloads
                .insert(decoded.reference().into(), view.bytes().to_vec())
                .map_err(DirectHttpConstructionError::Staging)?;
            let collection = ArtifactCollection::new(vec![decoded])
                .map_err(DirectHttpConstructionError::Collection)?;
            decoded_result = if matches!(facts.decoding(), CharacterDecodingOutcome::Complete(_)) {
                ArtifactFamilyResult::Complete {
                    artifacts: collection,
                }
            } else {
                ArtifactFamilyResult::Partial {
                    artifacts: collection,
                    reason: reason("web_capture.decoded_source.output_truncated")?,
                }
            };
        } else {
            decoded_result = ArtifactFamilyResult::Unavailable {
                reason: reason("web_capture.decoded_source.unavailable")?,
            };
        }
    }
    let decoded_reference = decoded_result
        .artifacts()
        .and_then(<[DecodedSourceArtifact]>::first)
        .map(DecodedSourceArtifact::reference);
    let (source_representation, source_representation_payload) = source_representation_artifact(
        spec,
        &source,
        decoded_reference,
        &facts,
        decoded_generated_at,
    )?;
    payloads
        .insert(
            source_representation.reference().into(),
            source_representation_payload,
        )
        .map_err(DirectHttpConstructionError::Staging)?;
    let source_representation_result = ArtifactFamilyResult::Complete {
        artifacts: ArtifactCollection::new(vec![source_representation])
            .map_err(DirectHttpConstructionError::Collection)?,
    };
    let source_result = if source_input.extent() == RetainedSourceExtent::Complete {
        ArtifactFamilyResult::Complete {
            artifacts: source_collection,
        }
    } else {
        ArtifactFamilyResult::Partial {
            artifacts: source_collection,
            reason: reason(body_reason(outcome))?,
        }
    };
    Ok((
        source_result,
        source_representation_result,
        decoded_result,
        network,
        payloads,
        Some(facts),
    ))
}

fn source_representation_artifact(
    spec: &ResolvedDirectHttpCaptureSpec,
    source: &SourceArtifact,
    decoded_source: Option<DecodedSourceArtifactRef>,
    facts: &SourceRepresentationFacts,
    at: DateTime<Utc>,
) -> Result<(SourceRepresentationArtifact, Vec<u8>), DirectHttpConstructionError> {
    let evidence =
        SourceRepresentationEvidence::from_facts(source.reference(), decoded_source, facts)
            .map_err(DirectHttpConstructionError::SourceRepresentationEvidence)?;
    let bytes = evidence
        .to_canonical_json()
        .map_err(DirectHttpConstructionError::SourceRepresentationEvidence)?;
    let id = ArtifactId::try_from(3).map_err(DirectHttpConstructionError::ArtifactId)?;
    let provenance = Provenance::new(
        spec.capture_id().activity_id(),
        spec.producer().clone(),
        spec.output_schemas().source_representation().clone(),
        at,
        vec![source.reference().as_untyped()],
    );
    let record = ArtifactRecord::new(
        id,
        Some(yosoi_types::Sha256Digest::digest(&bytes)),
        ArtifactAvailability::Retained,
        None,
        provenance,
    )
    .map_err(DirectHttpConstructionError::ArtifactRecord)?;
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new(SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE)
            .map_err(DirectHttpConstructionError::MediaType)?,
        ArtifactByteExtent::Complete {
            retained_bytes: ByteCount::new(size(&bytes)),
        },
        ArtifactSensitivity::Unassessed,
    )
    .map_err(DirectHttpConstructionError::Metadata)?;
    let artifact = SourceRepresentationArtifact::try_from_source(metadata, source.reference())
        .map_err(DirectHttpConstructionError::SourceRepresentationArtifact)?;
    artifact
        .parse_payload(&bytes)
        .map_err(DirectHttpConstructionError::SourceRepresentationArtifact)?;
    Ok((artifact, bytes))
}

fn source_artifact(
    spec: &ResolvedDirectHttpCaptureSpec,
    source: &RetainedSource,
    terminal: BodyTerminal,
    response: &DirectHttpResponseFacts,
    classification: Option<&SourceClassificationOutcome>,
    at: DateTime<Utc>,
) -> Result<SourceArtifact, DirectHttpConstructionError> {
    let id = ArtifactId::try_from(1).map_err(DirectHttpConstructionError::ArtifactId)?;
    let (availability, extent, why) = match source.extent() {
        RetainedSourceExtent::Complete => (
            ArtifactAvailability::Retained,
            ArtifactByteExtent::Complete {
                retained_bytes: ByteCount::new(size(source.bytes())),
            },
            None,
        ),
        RetainedSourceExtent::Truncated => (
            ArtifactAvailability::Truncated,
            ArtifactByteExtent::truncated(
                ByteCount::new(size(source.bytes())),
                MeasuredCount::Unavailable {
                    reason: reason("web_capture.body.complete_size_unavailable")?,
                },
            )
            .map_err(DirectHttpConstructionError::Extent)?,
            Some(reason(terminal_reason(terminal))?),
        ),
    };
    let provenance = Provenance::new(
        spec.capture_id().activity_id(),
        spec.producer().clone(),
        spec.output_schemas().source().clone(),
        at,
        Vec::new(),
    );
    let record = ArtifactRecord::new(id, Some(source.digest()), availability, why, provenance)
        .map_err(DirectHttpConstructionError::ArtifactRecord)?;
    let media =
        observed_media(response, classification).map_err(DirectHttpConstructionError::MediaType)?;
    let metadata = WebArtifactMetadata::new(record, media, extent, ArtifactSensitivity::Unassessed)
        .map_err(DirectHttpConstructionError::Metadata)?;
    Ok(SourceArtifact::new(metadata))
}

fn decoder_identity(
    spec: &ResolvedDirectHttpCaptureSpec,
    source: SourceArtifactRef,
) -> Result<DecodedOutputIdentity, DirectHttpConstructionError> {
    let id = ArtifactId::try_from(2).map_err(DirectHttpConstructionError::ArtifactId)?;
    let reference = DecodedSourceArtifactRef::from_untyped(ArtifactRef::new(
        spec.capture_id().activity_id(),
        id,
    ));
    let producer =
        source_decoder_producer().map_err(DirectHttpConstructionError::DecoderProducer)?;
    let schema = spec
        .output_schemas()
        .unicode_view()
        .cloned()
        .unwrap_or_else(|| spec.output_schemas().source().clone());
    DecodedOutputIdentity::new(
        reference,
        producer,
        schema,
        vec![source.as_untyped()],
        source,
    )
    .map_err(DirectHttpConstructionError::DecodedIdentity)
}

const fn decoded_view(outcome: &CharacterDecodingOutcome) -> Option<&DecodedSourceView> {
    match outcome {
        CharacterDecodingOutcome::Complete(v) | CharacterDecodingOutcome::OutputTruncated(v) => {
            Some(v)
        }
        _ => None,
    }
}
fn should_fail_unsupported(
    spec: &ResolvedDirectHttpCaptureSpec,
    outcome: &SourceClassificationOutcome,
) -> bool {
    if !matches!(
        spec.unsupported_format(),
        UnsupportedSourceFormatBehavior::FailAttempt
    ) {
        return false;
    }
    match outcome {
        SourceClassificationOutcome::Classified(value) => {
            !spec.accepted_formats().contains(match value.format() {
                SourceFormat::Html => AcceptedSourceFormat::Html,
                SourceFormat::Xml(XmlProfile::Generic) => {
                    AcceptedSourceFormat::Xml(XmlSourceProfile::Generic)
                }
                SourceFormat::Xml(XmlProfile::Xhtml) => {
                    AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml)
                }
                SourceFormat::Json => AcceptedSourceFormat::Json,
                SourceFormat::PlainText => AcceptedSourceFormat::PlainText,
            })
        }
        _ => true,
    }
}
fn observed_media(
    response: &DirectHttpResponseFacts,
    classification: Option<&SourceClassificationOutcome>,
) -> Result<MediaType, MediaTypeError> {
    if let MediaDeclaration::Parsed { essence, .. } =
        parse_media_declaration(&response.source_media_type())
    {
        return MediaType::new(&essence);
    }
    let canonical = match classification {
        Some(SourceClassificationOutcome::Classified(value)) => match value.format() {
            SourceFormat::Html => "text/html",
            SourceFormat::Xml(XmlProfile::Generic) => "application/xml",
            SourceFormat::Xml(XmlProfile::Xhtml) => "application/xhtml+xml",
            SourceFormat::Json => "application/json",
            SourceFormat::PlainText => "text/plain",
        },
        _ => "application/octet-stream",
    };
    MediaType::new(canonical)
}
fn size(bytes: &[u8]) -> u64 {
    u64::try_from(bytes.len()).unwrap_or(u64::MAX)
}
const fn body_reason(outcome: &ResponseBodyOutcome) -> &'static str {
    terminal_reason(outcome.terminal())
}
fn reason(value: &'static str) -> Result<ReasonCode, DirectHttpConstructionError> {
    ReasonCode::new(value).map_err(DirectHttpConstructionError::Reason)
}
