use super::{
    VoidCrawlAdapterError, config, conversions, retained_slot, retained_slot_with_producer, slot,
    unrequested,
};
use crate as yosoi;
use std::sync::Arc;
use void_crawl_core as provider;
pub(super) fn source_representation_and_decoded_source(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    requested: yosoi::ArtifactRequest,
    source_envelope: Option<&yosoi::StagedBrowserArtifactEnvelope>,
    declaration: &yosoi::SourceMediaType,
    at: yosoi::CaptureOffset,
) -> Result<(yosoi::BrowserStagingSlot, yosoi::BrowserStagingSlot), VoidCrawlAdapterError> {
    let representation_family = yosoi::BrowserStagingFamily::SourceRepresentation;
    let decoded_family =
        yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::DecodedSource);
    if requested == yosoi::ArtifactRequest::NotRequested {
        return Ok((
            unrequested(representation_family)?,
            unrequested(decoded_family)?,
        ));
    }
    let Some(source_envelope) = source_envelope else {
        let reason = conversions::reason("yosoi.source-representation.source-bytes-unavailable")?;
        return Ok((
            slot(
                representation_family,
                yosoi::ArtifactStagingOutcome::unavailable(reason.clone()),
            )?,
            slot(
                decoded_family,
                yosoi::ArtifactStagingOutcome::unavailable(reason),
            )?,
        ));
    };
    let decoded_ref = spec
        .identity_plan()
        .reference(decoded_family)
        .map(yosoi::DecodedSourceArtifactRef::from_untyped)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let decoded_schema = spec
        .output_schemas()
        .get(yosoi::WebArtifactFamily::DecodedSource)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
        .clone();
    let unicode_limit = u64::try_from(config::byte_limit(
        spec,
        yosoi::BrowserByteDomain::DecodedSourceUtf8,
    )?)
    .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let interpreted = yosoi::canonical_browser_source_representation(
        source_envelope,
        declaration,
        decoded_ref,
        decoded_schema,
        unicode_limit,
    )
    .map_err(VoidCrawlAdapterError::SourceRepresentation)?;
    let (evidence_bytes, decoded_output) = interpreted.into_parts();
    let mapping = yosoi::BrowserArtifactMapping::new(
        representation_family,
        yosoi::BrowserByteLayer::SourceRepresentation,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
    .derived_from_source(source_envelope.bytes());
    let observed =
        u64::try_from(evidence_bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let outcome =
        yosoi::ArtifactStagingOutcome::complete(mapping, Arc::from(evidence_bytes), observed)
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let representation = retained_slot(
        spec,
        representation_family,
        outcome,
        yosoi::SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE,
        at,
        vec![source_envelope.reference()],
    )?;
    let decoded = match decoded_output {
        Some(output) => {
            let (reference, decoder_producer, bytes, output_truncated) = output.into_parts();
            if reference != decoded_ref {
                return Err(VoidCrawlAdapterError::InvalidStaging);
            }
            let mapping = yosoi::BrowserArtifactMapping::new(
                decoded_family,
                yosoi::BrowserByteLayer::DecodedSourceUtf8,
            )
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
            .derived_from_source(source_envelope.bytes());
            let observed =
                u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let outcome = if output_truncated {
                yosoi::ArtifactStagingOutcome::partial(
                    mapping,
                    bytes,
                    observed,
                    yosoi::LossExtent::Unknown,
                    conversions::reason("browser.decoded-source.output-truncated")?,
                )
            } else {
                yosoi::ArtifactStagingOutcome::complete(mapping, bytes, observed)
            }
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            retained_slot_with_producer(
                spec,
                &decoder_producer,
                decoded_family,
                outcome,
                yosoi::DECODED_SOURCE_UTF8_MEDIA_TYPE,
                at,
                vec![source_envelope.reference()],
            )?
        }
        None => slot(
            decoded_family,
            yosoi::ArtifactStagingOutcome::unavailable(conversions::reason(
                "yosoi.source-representation.decoded-source-unavailable",
            )?),
        )?,
    };
    Ok((representation, decoded))
}

pub(super) fn source_media_type(
    main: &provider::MainDocumentSource,
    admission: yosoi::BrowserEvidenceAdmissionPolicy,
) -> yosoi::SourceMediaType {
    if admission.headers() == yosoi::BrowserHeaderAdmission::AdmitSafeMainDocument {
        let mut declarations = main
            .headers
            .as_slice()
            .iter()
            .filter(|(name, _)| name.eq_ignore_ascii_case("content-type"))
            .map(|(_, value)| value.as_str());
        if let Some(value) = declarations.next() {
            return if declarations.next().is_some() {
                yosoi::SourceMediaType::Duplicate
            } else {
                yosoi::SourceMediaType::from_text(value)
            };
        }
    }
    main.mime_type
        .as_ref()
        .map_or(yosoi::SourceMediaType::Absent, |value| {
            yosoi::SourceMediaType::from_text(value.clone())
        })
}
