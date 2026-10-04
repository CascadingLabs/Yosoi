#![cfg(feature = "browser")]
#![allow(
    clippy::expect_used,
    clippy::panic,
    clippy::unwrap_used,
    reason = "CAS-326 black-box adapter assertions use fixed test fixtures"
)]

use super::fixture;

use std::{
    num::{NonZeroU32, NonZeroU64},
    str,
};
use tokio_util::sync::CancellationToken;
use yosoi_types::{
    CaptureId, OperationId, Producer, ProducerId, ProducerVersion, ReasonCode, Schema, SchemaId,
    SchemaVersion, Sha256Digest,
};
use yosoi_web_capture::*;

const SECRET: &str = "CAS326_SECRET_SENTINEL";

fn reason() -> ReasonCode {
    ReasonCode::new("test.unavailable").unwrap()
}

fn producer() -> Producer {
    Producer::new(
        ProducerId::new("com.cascadinglabs.void_crawl_core").unwrap(),
        ProducerVersion::new("0.5.0").unwrap(),
    )
}

fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::new(NonZeroU32::MIN),
    )
}

fn capabilities() -> CertifiedBrowserCapabilities {
    let supported = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let profile = WebProviderCapabilityProfile::new(
        producer(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            BrowserMode::Headless,
        )),
        WebArtifactCapabilitySet::new(
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            ArtifactCapability::Unsupported { reason: reason() },
            supported.clone(),
            supported.clone(),
            supported,
        ),
    )
    .unwrap();
    CertifiedBrowserCapabilities::new(
        profile,
        &producer(),
        BrowserMode::Headless,
        BrowserInstrumentationMode::Normal,
        BrowserFamilyCapabilities::new(
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Unsupported { reason: reason() },
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
        ),
    )
    .unwrap()
}

fn spec(target: &str, source_limit: u64, dom_limit: u64) -> ResolvedBrowserCaptureSpec {
    spec_with_admission(
        target,
        source_limit,
        dom_limit,
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::AdmitNetworkUrls,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::AdmitDecodedRepresentation,
        ),
    )
}

fn spec_with_admission(
    target: &str,
    source_limit: u64,
    dom_limit: u64,
    admission: BrowserEvidenceAdmissionPolicy,
) -> ResolvedBrowserCaptureSpec {
    let capture_id = CaptureId::random();
    let required = ArtifactRequest::Required;
    let no = ArtifactRequest::NotRequested;
    ResolvedBrowserCaptureSpec::new(
        WebCaptureRequest::new(
            capture_id,
            RequestedWebTarget::parse(target).unwrap(),
            WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
                NavigationContext::FreshTopLevel,
            )),
        ),
        WebArtifactRequestSet::new(required, required, no, required, no, no, no, no, no),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(30_000_000).unwrap(), None, None),
            SettlementPolicy::QuietPeriod(QuietPeriodPolicy::new(
                SettlementPolicyId::new("test.cas328.quiet").unwrap(),
                QuietPeriod::try_from(200_000).unwrap(),
                ActivityCount::new(0),
            )),
        ),
        BrowserNavigationPolicy::new(NavigationCompletionPolicy::ControllerCompleted),
        BrowserAttemptEnvironment::new(BrowserMode::Headless),
        BrowserProviderBounds::new(
            vec![
                BrowserByteBound::new(
                    BrowserByteDomain::CdpDecodedBody,
                    NonZeroU64::new(source_limit).unwrap(),
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                    BrowserBudgetScope::PerPayload,
                ),
                BrowserByteBound::new(
                    BrowserByteDomain::DecodedSourceUtf8,
                    NonZeroU64::new(source_limit).unwrap(),
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                    BrowserBudgetScope::PerPayload,
                ),
                BrowserByteBound::new(
                    BrowserByteDomain::RenderedDomUtf8,
                    NonZeroU64::new(dom_limit).unwrap(),
                    BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
                    BrowserBudgetScope::PerPayload,
                ),
            ],
            NonZeroU64::new(100).unwrap(),
            NonZeroU32::new(100).unwrap(),
            NonZeroU32::new(100).unwrap(),
        )
        .unwrap(),
        capabilities(),
        producer(),
        OperationId::new("test.cas326").unwrap(),
        BrowserOutputSchemas::new(
            Some(schema("test.source")),
            Some(schema("test.source-representation")),
            Some(schema("test.decoded-source")),
            Some(schema("test.dom")),
            None,
            Some(schema("test.network")),
            None,
            None,
            None,
            None,
            None,
        ),
        BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        admission,
    )
    .unwrap()
}

fn staged_slot(facts: &BrowserAdapterFacts, family: BrowserStagingFamily) -> &BrowserStagingSlot {
    facts
        .staging()
        .slots()
        .iter()
        .find(|slot| slot.family() == family)
        .unwrap()
}

/// Runs only with an explicitly installed Chromium; compile this suite with --no-run in CI.
#[tokio::test]
async fn source_is_decoded_lineage_bound_and_distinct_from_javascript_mutated_dom() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let result = yosoi_web_capture::browser_capture(&spec(
        &fixture.url("/redirect").unwrap(),
        1_000_000,
        1_000_000,
    ))
    .await
    .unwrap();
    fixture.shutdown().await.unwrap();

    let facts = &result;
    let debug = format!("{result:?}");
    assert!(!debug.contains("shell source only"));
    assert!(!debug.contains("live-dom-mutation"));
    assert!(!debug.contains("/redirect"));
    assert!(debug.contains("<redacted>"));
    let source_slot = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
    );
    let representation_slot = staged_slot(facts, BrowserStagingFamily::SourceRepresentation);
    let decoded_slot = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
    );
    let dom_slot = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
    );
    let network_slot = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Network),
    );
    let source = source_slot.outcome();
    let representation = representation_slot.outcome();
    let dom = dom_slot.outcome();
    let network = network_slot.outcome();
    let source_bytes = source.bytes().unwrap();
    let dom_bytes = dom.bytes().unwrap();

    assert_eq!(source.state(), StagingState::Complete);
    assert_eq!(source_bytes, fixture::SHELL_HTML);
    assert_eq!(
        Sha256Digest::digest(source_bytes),
        Sha256Digest::digest(fixture::SHELL_HTML)
    );
    assert_eq!(representation.state(), StagingState::Complete);
    assert_eq!(
        representation.mapping().unwrap().source_binding(),
        Some(Sha256Digest::digest(source_bytes))
    );
    let source_envelope = source_slot.envelope().expect("source envelope");
    let representation_envelope = representation_slot
        .envelope()
        .expect("source-representation envelope");
    let decoded_envelope = decoded_slot.envelope().expect("decoded-source envelope");
    let dom_envelope = dom_slot.envelope().expect("DOM envelope");
    let network_envelope = network_slot.envelope().expect("network envelope");
    assert_eq!(source_envelope.digest(), Sha256Digest::digest(source_bytes));
    assert_eq!(dom_envelope.digest(), Sha256Digest::digest(dom_bytes));
    assert_eq!(
        representation_envelope.derived_from(),
        &[source_envelope.reference()]
    );
    let evidence = SourceRepresentationEvidence::from_json(representation_envelope.bytes())
        .expect("canonical source representation");
    assert_eq!(evidence.source().as_untyped(), source_envelope.reference());
    match evidence.decoding() {
        DurableCharacterDecoding::Complete(view)
        | DurableCharacterDecoding::OutputTruncated(view) => {
            assert_eq!(
                view.decoded_source(),
                Some(DecodedSourceArtifactRef::from_untyped(
                    decoded_envelope.reference()
                ))
            );
        }
        other => panic!("expected classified HTML decoding facts, got {other:?}"),
    }
    assert_ne!(source_bytes, dom_bytes);
    assert!(
        str::from_utf8(dom_bytes)
            .unwrap()
            .contains("live-dom-mutation")
    );
    assert!(
        str::from_utf8(dom_bytes)
            .unwrap()
            .contains("DOM AX and layout evidence from deterministic secondary request")
    );

    let BrowserStagingParts::Structured {
        evidence: network_evidence @ BrowserStructuredEvidence::Network { resources, .. },
        ..
    } = network.parts()
    else {
        panic!("network evidence must remain structured");
    };
    assert_eq!(
        network_envelope.bytes(),
        network_evidence.to_canonical_json().unwrap()
    );
    assert_eq!(resources[0].status, Some(302));
    assert!(
        resources[0]
            .url
            .as_ref()
            .unwrap()
            .as_str()
            .ends_with("/redirect")
    );
    assert_eq!(resources[1].redirect_from, Some(resources[0].id));
    assert!(
        resources[1]
            .url
            .as_ref()
            .unwrap()
            .as_str()
            .ends_with("/shell")
    );
    assert_eq!(resources[1].encoded_data_length, Some(820));
    assert_eq!(
        source_bytes.len(),
        fixture::SHELL_HTML.len(),
        "decoded source bytes, never encoded transfer bytes"
    );
}

#[tokio::test]
async fn blocking_challenge_is_a_neutral_fact_with_normal_cleanup() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let result = yosoi_web_capture::capture_attempt(
        &spec_with_admission(
            &fixture.url("/challenge").unwrap(),
            1_000_000,
            1_000_000,
            BrowserEvidenceAdmissionPolicy::new(
                BrowserUrlAdmission::AdmitNetworkUrls,
                BrowserHeaderAdmission::AdmitSafeMainDocument,
                BrowserMainBodyAdmission::AdmitDecodedRepresentation,
            ),
        ),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    fixture.shutdown().await.unwrap();

    assert!(result.is_ready());
    assert_eq!(result.facts().cleanup(), CleanupState::Complete);
    let challenge = result.facts().challenge();
    assert_eq!(challenge.presence(), BrowserChallengeState::Present);
    assert_eq!(challenge.active_challenge(), BrowserChallengeState::Present);
    assert_eq!(challenge.challenge_vendor(), Some("cloudflare"));
    assert_eq!(challenge.evidence(), BrowserChallengeEvidenceTier::Headers);
    assert!(matches!(
        challenge.completeness(),
        BrowserResponseSignalCompleteness::Complete
    ));
}

#[tokio::test]
async fn source_and_dom_over_limit_are_retained_without_global_termination() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let result = yosoi_web_capture::capture_attempt(
        &spec(&fixture.url("/redirect").unwrap(), 700, 64),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    fixture.shutdown().await.unwrap();

    assert!(result.is_ready());
    assert!(matches!(
        result.terminal().kind(),
        BrowserTerminalKind::QuietSettled
    ));
    let facts = result.facts();
    let source = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
    );
    let representation = staged_slot(facts, BrowserStagingFamily::SourceRepresentation);
    let dom = staged_slot(
        facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
    );
    assert_eq!(source.outcome().state(), StagingState::Truncated);
    assert_eq!(representation.outcome().state(), StagingState::Complete);
    assert_eq!(dom.outcome().state(), StagingState::Truncated);
    assert!(source.envelope().is_some());
    assert!(representation.envelope().is_some());
    assert!(dom.envelope().is_some());
}

#[tokio::test]
async fn cancelled_source_and_dom_are_never_reported_complete() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let error = yosoi_web_capture::capture_attempt(
        &spec(&fixture.url("/partial").unwrap(), 1, 1),
        &cancellation,
    )
    .await
    .unwrap_err();
    fixture.shutdown().await.unwrap();

    let printed = format!("{error:?} {error}");
    assert!(!printed.contains(SECRET));
    // A cancellation before ownership is allowed; after ownership the adapter must retain
    // partial/truncated source evidence with explicit known or unknown loss, never Complete.
    assert!(printed.contains("cancelled") || printed.contains("cancelled before"));
}

#[tokio::test]
async fn explicit_omission_policy_retains_no_protected_urls_headers_or_source_body() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let facts = yosoi_web_capture::browser_capture(&spec_with_admission(
        &fixture.url("/redirect").unwrap(),
        1_000_000,
        1_000_000,
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::Omit,
        ),
    ))
    .await
    .unwrap();
    fixture.shutdown().await.unwrap();

    let source = staged_slot(
        &facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
    );
    let representation = staged_slot(&facts, BrowserStagingFamily::SourceRepresentation);
    assert_eq!(source.outcome().state(), StagingState::Discarded);
    assert!(source.outcome().bytes().is_none());
    assert!(source.envelope().is_none());
    assert_eq!(representation.outcome().state(), StagingState::Unavailable);
    assert!(representation.envelope().is_none());

    let network = staged_slot(
        &facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Network),
    );
    let BrowserStagingParts::Structured {
        evidence:
            BrowserStructuredEvidence::Network {
                requested_url,
                final_url,
                main_document,
                resources,
                ..
            },
        ..
    } = network.outcome().parts()
    else {
        panic!("network evidence must remain structured");
    };
    assert!(requested_url.is_none() && final_url.is_none());
    assert!(resources.iter().all(|resource| resource.url.is_none()));
    assert!(
        main_document
            .as_ref()
            .is_some_and(|main| { main.url.is_none() && main.headers.is_empty() })
    );
}

#[tokio::test]
async fn safe_header_admission_preserves_content_type_declaration_only() {
    let fixture = fixture::BrowserFixture::start().await.unwrap();
    let facts = yosoi_web_capture::browser_capture(&spec_with_admission(
        &fixture.url("/redirect").unwrap(),
        1_000_000,
        1_000_000,
        BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::AdmitSafeMainDocument,
            BrowserMainBodyAdmission::AdmitDecodedRepresentation,
        ),
    ))
    .await
    .unwrap();
    fixture.shutdown().await.unwrap();

    let representation = staged_slot(&facts, BrowserStagingFamily::SourceRepresentation)
        .envelope()
        .expect("source-representation envelope");
    let evidence = SourceRepresentationEvidence::from_json(representation.bytes()).unwrap();
    assert!(matches!(
        evidence.declaration(),
        MediaDeclaration::Parsed {
            essence,
            charset: CharsetDeclaration::Label { canonical, .. }
        } if essence == "text/html" && canonical == "utf-8"
    ));

    let network = staged_slot(
        &facts,
        BrowserStagingFamily::Artifact(WebArtifactFamily::Network),
    );
    let BrowserStagingParts::Structured {
        evidence: BrowserStructuredEvidence::Network { main_document, .. },
        ..
    } = network.outcome().parts()
    else {
        panic!("network evidence must remain structured");
    };
    let headers = &main_document.as_ref().expect("main document").headers;
    assert!(headers.iter().any(|(name, _)| name == "content-type"));
    assert!(headers.iter().all(|(name, _)| matches!(
        name.as_str(),
        "content-type" | "content-language" | "content-length" | "last-modified"
    )));
}

#[tokio::test]
async fn rejected_source_request_does_not_echo_secret_target() {
    let error = yosoi_web_capture::capture_attempt(
        &spec(
            &format!("http://127.0.0.1/redirect?token={SECRET}"),
            1_000,
            1_000,
        ),
        &CancellationToken::new(),
    )
    .await
    .unwrap_err();
    assert!(!error.to_string().contains(SECRET));
    assert!(!format!("{error:?}").contains(SECRET));
}
