#![allow(clippy::unwrap_used, reason = "valid test fixtures")]

use std::num::NonZeroU32;

use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ActivityCount, ArtifactRequest, BrowserContextRef,
    ByteLimit, ByteLimitError, CaptureDeadline, ContextBoundHttpAcquisition, CookieSync,
    DirectHttpAcquisition, DirectHttpCaptureSpecError, DirectHttpContentLimits,
    DirectHttpOutputSchemas, DirectHttpRedirectPolicy, DirectHttpTransportProfile, EventLimit,
    HttpSessionUse, ObservationLimits, ObservationPolicy, QuietPeriod, QuietPeriodPolicy,
    RedirectHopLimit, RequestedWebTarget, ResolvedDirectHttpCaptureSpec, SettlementPolicy,
    SettlementPolicyId, SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
    WebAcquisitionStrategy, WebArtifactFamily, WebArtifactRequestSet, WebCaptureRequest,
    XmlSourceProfile,
};
use crate::internal::types::{
    ActivityId, CaptureId, OperationId, Producer, ProducerId, ProducerVersion, Schema, SchemaId,
    SchemaVersion,
};

#[test]
fn valid_spec_preserves_occurrence_and_every_resolved_decision() {
    let capture_id = CaptureId::random();
    let request = direct_request(capture_id);
    let artifacts = direct_artifacts(ArtifactRequest::Required);
    let observation = disabled_observation();
    let limits = content_limits(10, 20, 30);
    let redirects = DirectHttpRedirectPolicy::Follow {
        max_hops: RedirectHopLimit::try_from(5).unwrap(),
    };
    let formats = accepted_formats();
    let producer = producer();
    let operation = operation();
    let schemas = output_schemas(true, true);

    let spec = ResolvedDirectHttpCaptureSpec::new(
        request.clone(),
        artifacts,
        observation.clone(),
        limits,
        redirects,
        formats.clone(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        producer.clone(),
        operation.clone(),
        schemas.clone(),
    )
    .unwrap();

    assert_eq!(spec.capture_id(), capture_id);
    assert_eq!(spec.request(), &request);
    assert_eq!(spec.target(), request.target());
    assert_eq!(spec.artifacts(), artifacts);
    assert_eq!(spec.observation(), &observation);
    assert_eq!(spec.maximum_elapsed().as_microseconds(), 1_000_000);
    assert_eq!(spec.content_limits(), limits);
    assert_eq!(spec.redirects(), redirects);
    assert_eq!(spec.accepted_formats(), &formats);
    assert_eq!(
        spec.unsupported_format(),
        UnsupportedSourceFormatBehavior::RetainAndReport
    );
    assert_eq!(
        spec.retention(),
        SourceRetentionPolicy::RepresentationAndUnicodeView
    );
    assert_eq!(spec.producer(), &producer);
    assert_eq!(spec.operation(), &operation);
    assert_eq!(spec.output_schemas(), &schemas);
    assert!(matches!(
        spec.strategy().transport_profile(),
        DirectHttpTransportProfile::Standard
    ));
}

#[test]
fn response_limits_are_positive_and_name_each_byte_domain() {
    assert_eq!(ByteLimit::try_from(0_u64), Err(ByteLimitError::Zero));
    let limit = ByteLimit::try_from(1_u64).unwrap();
    assert_eq!(limit.get(), 1);

    let limits = content_limits(2, 3, 4);
    assert_eq!(limits.content_coded_bytes().get(), 2);
    assert_eq!(limits.representation_bytes().get(), 3);
    assert_eq!(limits.unicode_utf8_bytes().get(), 4);
}

#[test]
fn accepted_formats_are_non_empty_deduplicated_and_preserve_xml_profiles() {
    assert_eq!(
        AcceptedSourceFormats::new([]),
        Err(DirectHttpCaptureSpecError::EmptyAcceptedFormats)
    );
    let formats = AcceptedSourceFormats::new([
        AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml),
        AcceptedSourceFormat::Html,
        AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
        AcceptedSourceFormat::Html,
    ])
    .unwrap();

    assert!(formats.contains(AcceptedSourceFormat::Html));
    assert!(formats.contains(AcceptedSourceFormat::Xml(XmlSourceProfile::Generic)));
    assert!(formats.contains(AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml)));
    assert_eq!(formats.iter().count(), 3);
}

#[test]
fn non_direct_strategy_is_rejected_without_losing_request_identity() {
    let capture_id = CaptureId::random();
    let browser_context = BrowserContextRef::new(ActivityId::random(), NonZeroU32::new(1).unwrap());
    let request = WebCaptureRequest::new(
        capture_id,
        RequestedWebTarget::parse("https://example.com/").unwrap(),
        WebAcquisitionStrategy::ContextBoundHttp(ContextBoundHttpAcquisition::new(
            browser_context,
            CookieSync::ReadOnlySnapshot,
        )),
    );

    assert_eq!(
        make_spec(
            request,
            direct_artifacts(ArtifactRequest::NotRequested),
            SourceRetentionPolicy::Representation,
            output_schemas(false, false)
        ),
        Err(DirectHttpCaptureSpecError::WrongStrategy)
    );
}

#[test]
fn source_is_mandatory_and_browser_only_artifact_requests_are_rejected() {
    for source in [ArtifactRequest::NotRequested, ArtifactRequest::Optional] {
        assert_eq!(
            make_spec(
                direct_request(CaptureId::random()),
                artifacts(source, ArtifactRequest::NotRequested),
                SourceRetentionPolicy::Representation,
                output_schemas(false, false),
            ),
            Err(DirectHttpCaptureSpecError::SourceMustBeRequired)
        );
    }

    let unsupported = [
        WebArtifactFamily::RenderedDom,
        WebArtifactFamily::AccessibilityTree,
        WebArtifactFamily::Cookies,
        WebArtifactFamily::Storage,
        WebArtifactFamily::Layout,
        WebArtifactFamily::Visual,
        WebArtifactFamily::RuntimeDiagnostics,
    ];
    for family in unsupported {
        assert_eq!(
            make_spec(
                direct_request(CaptureId::random()),
                requests_with_unsupported(family),
                SourceRetentionPolicy::Representation,
                output_schemas(false, false),
            ),
            Err(DirectHttpCaptureSpecError::UnsupportedArtifactFamily { family })
        );
    }
}

#[test]
fn direct_http_requires_disabled_settlement() {
    let quiet = QuietPeriodPolicy::new(
        SettlementPolicyId::new("com.cascadinglabs.http-quiet").unwrap(),
        QuietPeriod::try_from(100).unwrap(),
        ActivityCount::new(0),
    );
    let observation = ObservationPolicy::new(
        ObservationLimits::new(CaptureDeadline::try_from(1_000_000).unwrap(), None, None),
        SettlementPolicy::QuietPeriod(quiet),
    );

    let result = ResolvedDirectHttpCaptureSpec::new(
        direct_request(CaptureId::random()),
        direct_artifacts(ArtifactRequest::NotRequested),
        observation,
        content_limits(1, 1, 1),
        DirectHttpRedirectPolicy::Disabled,
        accepted_formats(),
        UnsupportedSourceFormatBehavior::FailAttempt,
        SourceRetentionPolicy::Representation,
        producer(),
        operation(),
        output_schemas(false, false),
    );
    assert_eq!(
        result,
        Err(DirectHttpCaptureSpecError::SettlementMustBeDisabled)
    );
}

#[test]
fn output_schema_presence_matches_requested_outputs_and_retention() {
    let capture_id = CaptureId::random();
    let shared = schema("com.cascadinglabs.yosoi.shared-source");
    assert_eq!(
        make_spec(
            direct_request(capture_id),
            direct_artifacts(ArtifactRequest::NotRequested),
            SourceRetentionPolicy::Representation,
            DirectHttpOutputSchemas::new(shared.clone(), shared, None, None),
        ),
        Err(DirectHttpCaptureSpecError::SourceRepresentationSchemaMustDiffer)
    );
    assert_eq!(
        make_spec(
            direct_request(capture_id),
            direct_artifacts(ArtifactRequest::Required),
            SourceRetentionPolicy::Representation,
            output_schemas(false, false),
        ),
        Err(DirectHttpCaptureSpecError::MissingNetworkSchema)
    );
    assert_eq!(
        make_spec(
            direct_request(capture_id),
            direct_artifacts(ArtifactRequest::NotRequested),
            SourceRetentionPolicy::Representation,
            output_schemas(true, false),
        ),
        Err(DirectHttpCaptureSpecError::UnexpectedNetworkSchema)
    );
    assert_eq!(
        make_spec(
            direct_request(capture_id),
            direct_artifacts(ArtifactRequest::NotRequested),
            SourceRetentionPolicy::RepresentationAndUnicodeView,
            output_schemas(false, false),
        ),
        Err(DirectHttpCaptureSpecError::MissingUnicodeViewSchema)
    );
    assert_eq!(
        make_spec(
            direct_request(capture_id),
            direct_artifacts(ArtifactRequest::NotRequested),
            SourceRetentionPolicy::Representation,
            output_schemas(false, true),
        ),
        Err(DirectHttpCaptureSpecError::UnexpectedUnicodeViewSchema)
    );
}

#[test]
fn observation_limits_and_artifact_intent_are_composed_without_duplication() {
    let observation = ObservationPolicy::new(
        ObservationLimits::new(
            CaptureDeadline::try_from(42).unwrap(),
            Some(EventLimit::try_from(7).unwrap()),
            None,
        ),
        SettlementPolicy::Disabled,
    );
    let artifacts = direct_artifacts(ArtifactRequest::Optional);
    let spec = ResolvedDirectHttpCaptureSpec::new(
        direct_request(CaptureId::random()),
        artifacts,
        observation,
        content_limits(8, 9, 10),
        DirectHttpRedirectPolicy::Disabled,
        accepted_formats(),
        UnsupportedSourceFormatBehavior::FailAttempt,
        SourceRetentionPolicy::Representation,
        producer(),
        operation(),
        output_schemas(true, false),
    )
    .unwrap();

    assert_eq!(spec.maximum_elapsed().as_microseconds(), 42);
    assert_eq!(spec.observation().limits().event_limit().unwrap().get(), 7);
    assert_eq!(spec.artifacts().network(), ArtifactRequest::Optional);
}

fn make_spec(
    request: WebCaptureRequest,
    artifacts: WebArtifactRequestSet,
    retention: SourceRetentionPolicy,
    schemas: DirectHttpOutputSchemas,
) -> Result<ResolvedDirectHttpCaptureSpec, DirectHttpCaptureSpecError> {
    ResolvedDirectHttpCaptureSpec::new(
        request,
        artifacts,
        disabled_observation(),
        content_limits(10, 20, 30),
        DirectHttpRedirectPolicy::Disabled,
        accepted_formats(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        retention,
        producer(),
        operation(),
        schemas,
    )
}

fn direct_request(capture_id: CaptureId) -> WebCaptureRequest {
    WebCaptureRequest::new(
        capture_id,
        RequestedWebTarget::parse("https://example.com/path").unwrap(),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    )
}

fn disabled_observation() -> ObservationPolicy {
    ObservationPolicy::new(
        ObservationLimits::new(CaptureDeadline::try_from(1_000_000).unwrap(), None, None),
        SettlementPolicy::Disabled,
    )
}

fn content_limits(encoded: u64, representation: u64, unicode: u64) -> DirectHttpContentLimits {
    DirectHttpContentLimits::new(
        ByteLimit::try_from(encoded).unwrap(),
        ByteLimit::try_from(representation).unwrap(),
        ByteLimit::try_from(unicode).unwrap(),
    )
}

fn accepted_formats() -> AcceptedSourceFormats {
    AcceptedSourceFormats::new([
        AcceptedSourceFormat::Html,
        AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
        AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml),
        AcceptedSourceFormat::Json,
        AcceptedSourceFormat::PlainText,
    ])
    .unwrap()
}

const fn direct_artifacts(network: ArtifactRequest) -> WebArtifactRequestSet {
    artifacts(ArtifactRequest::Required, network)
}

const fn artifacts(source: ArtifactRequest, network: ArtifactRequest) -> WebArtifactRequestSet {
    WebArtifactRequestSet::new(
        source,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        network,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    )
}

fn requests_with_unsupported(family: WebArtifactFamily) -> WebArtifactRequestSet {
    let request = |candidate| {
        if candidate == family {
            ArtifactRequest::Optional
        } else {
            ArtifactRequest::NotRequested
        }
    };
    WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        request(WebArtifactFamily::RenderedDom),
        request(WebArtifactFamily::AccessibilityTree),
        ArtifactRequest::NotRequested,
        request(WebArtifactFamily::Cookies),
        request(WebArtifactFamily::Storage),
        request(WebArtifactFamily::Layout),
        request(WebArtifactFamily::Visual),
        request(WebArtifactFamily::RuntimeDiagnostics),
    )
}

fn producer() -> Producer {
    Producer::new(
        ProducerId::new("com.cascadinglabs.yosoi.direct-http").unwrap(),
        ProducerVersion::new("0.1.0").unwrap(),
    )
}

fn operation() -> OperationId {
    OperationId::new("com.cascadinglabs.yosoi.direct-http.capture").unwrap()
}

fn output_schemas(network: bool, unicode: bool) -> DirectHttpOutputSchemas {
    DirectHttpOutputSchemas::new(
        schema("com.cascadinglabs.yosoi.web-source"),
        schema("com.cascadinglabs.yosoi.source-representation"),
        network.then(|| schema("com.cascadinglabs.yosoi.http-exchange")),
        unicode.then(|| schema("com.cascadinglabs.yosoi.decoded-source")),
    )
}

fn schema(id: &str) -> Schema {
    Schema::new(
        SchemaId::new(id).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
