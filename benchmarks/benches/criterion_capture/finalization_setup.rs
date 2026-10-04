use crate::capture_stages_support::{schema, started_at};
use yosoi_types::{
    ArtifactAvailability, ArtifactId, ArtifactRecord, CaptureId, Producer, ProducerId,
    ProducerVersion, Provenance, ReasonCode, Sha256Digest,
};
use yosoi_web_capture_direct_http::*;

const TARGET: &str = "https://benchmark.invalid/source";
const TERMINAL_MICROS: u64 = 1_000_000;

#[derive(Clone, Copy)]
pub enum CaseKind {
    CompleteSource,
    CompleteDecoded,
    Truncated,
    Unavailable,
}

pub struct Case {
    pub name: String,
    pub retained_bytes: u64,
    pub complete_bytes: u64,
    pub kind: CaseKind,
    pub source: Vec<u8>,
    pub decoded: Option<Vec<u8>>,
}

fn producer() -> Producer {
    Producer::new(
        ProducerId::new("com.cascadinglabs.yosoi.benchmark")
            .unwrap_or_else(|e| panic!("producer id: {e}")),
        ProducerVersion::new("1.0.0").unwrap_or_else(|e| panic!("producer version: {e}")),
    )
}

const fn requests() -> WebArtifactRequestSet {
    WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    )
}

fn spec(capture_id: CaptureId, retention: SourceRetentionPolicy) -> ResolvedDirectHttpCaptureSpec {
    let request = WebCaptureRequest::new(
        capture_id,
        RequestedWebTarget::parse(TARGET).unwrap_or_else(|e| panic!("target: {e}")),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    let limit = ByteLimit::try_from(10_000_000_u64).unwrap_or_else(|e| panic!("body limit: {e}"));
    let unicode_schema = matches!(
        retention,
        SourceRetentionPolicy::RepresentationAndUnicodeView
    )
    .then(|| schema("com.cascadinglabs.yosoi.benchmark.unicode"));
    ResolvedDirectHttpCaptureSpec::new(
        request,
        requests(),
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(2_000_000).unwrap_or_else(|e| panic!("deadline: {e}")),
                None,
                None,
            ),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(limit, limit, limit),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html])
            .unwrap_or_else(|e| panic!("formats: {e}")),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        retention,
        producer(),
        "benchmark.finalize"
            .parse()
            .unwrap_or_else(|e| panic!("operation: {e}")),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.benchmark.source"),
            schema("com.cascadinglabs.yosoi.benchmark.source-representation"),
            None,
            unicode_schema,
        ),
    )
    .unwrap_or_else(|e| panic!("spec: {e}"))
}

#[allow(
    clippy::too_many_arguments,
    reason = "artifact metadata fields are intentionally explicit"
)]
fn metadata(
    capture_id: CaptureId,
    artifact_id: u32,
    payload: &[u8],
    schema_value: yosoi_types::Schema,
    availability: ArtifactAvailability,
    reason: Option<ReasonCode>,
    extent: ArtifactByteExtent,
    derived_from: Vec<yosoi_types::ArtifactRef>,
    media_type: &str,
) -> WebArtifactMetadata {
    let provenance = Provenance::new(
        capture_id.activity_id(),
        producer(),
        schema_value,
        started_at(),
        derived_from,
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(artifact_id).unwrap_or_else(|e| panic!("artifact id: {e}")),
        Some(Sha256Digest::digest(payload)),
        availability,
        reason,
        provenance,
    )
    .unwrap_or_else(|e| panic!("record: {e}"));
    WebArtifactMetadata::new(
        record,
        MediaType::new(media_type).unwrap_or_else(|e| panic!("media type: {e}")),
        extent,
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap_or_else(|e| panic!("metadata: {e}"))
}

const fn other_results(
    source: ArtifactFamilyResult<SourceArtifact>,
    decoded: ArtifactFamilyResult<DecodedSourceArtifact>,
) -> WebArtifactResults {
    WebArtifactResults::new_with_decoded_source(
        source,
        decoded,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
    )
}

pub fn setup(
    case: &Case,
) -> (
    ResolvedDirectHttpCaptureSpec,
    BoundedAcquisitionLifecycle,
    LifecycleFinalizationInput,
) {
    let capture_id = CaptureId::random();
    let retention = if case.decoded.is_some() {
        SourceRetentionPolicy::RepresentationAndUnicodeView
    } else {
        SourceRetentionPolicy::Representation
    };
    let spec = spec(capture_id, retention);
    let mut lifecycle = BoundedAcquisitionLifecycle::start(
        spec.capture_id(),
        spec.observation().clone(),
        started_at(),
    );
    let interruption = || {
        LifecycleStop::Interrupted(InterruptionEvidence::new(
            InterruptionInitiator::Provider,
            ReasonCode::new("benchmark.capture-interrupted")
                .unwrap_or_else(|e| panic!("interruption reason: {e}")),
        ))
    };
    let stop = if matches!(case.kind, CaseKind::Truncated | CaseKind::Unavailable) {
        interruption()
    } else {
        LifecycleStop::Completed(ControllerStopReason::GoalSatisfied)
    };
    lifecycle
        .stop(CaptureOffset::from_microseconds(TERMINAL_MICROS), stop)
        .unwrap_or_else(|e| panic!("stop: {e}"));

    let (source_result, decoded_result, payloads) = if matches!(case.kind, CaseKind::Unavailable) {
        (
            ArtifactFamilyResult::Unavailable {
                reason: ReasonCode::new("benchmark.source-unavailable")
                    .unwrap_or_else(|e| panic!("unavailable reason: {e}")),
            },
            ArtifactFamilyResult::NotRequested,
            StagedPayloads::default(),
        )
    } else {
        let retained = ByteCount::new(case.source.len() as u64);
        let (availability, reason, extent) = if matches!(case.kind, CaseKind::Truncated) {
            (
                ArtifactAvailability::Truncated,
                Some(
                    ReasonCode::new("benchmark.source-truncated")
                        .unwrap_or_else(|e| panic!("truncated reason: {e}")),
                ),
                ArtifactByteExtent::truncated(
                    retained,
                    MeasuredCount::Known(ByteCount::new(case.complete_bytes)),
                )
                .unwrap_or_else(|e| panic!("truncated extent: {e}")),
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
        let source = SourceArtifact::new(metadata(
            capture_id,
            1,
            &case.source,
            schema("com.cascadinglabs.yosoi.benchmark.source"),
            availability,
            reason.clone(),
            extent,
            Vec::new(),
            "text/html",
        ));
        let mut payloads = StagedPayloads::default();
        payloads
            .insert(source.reference().into(), case.source.clone())
            .unwrap_or_else(|e| panic!("source payload: {e}"));
        let source_result = if matches!(case.kind, CaseKind::Truncated) {
            ArtifactFamilyResult::Partial {
                artifacts: ArtifactCollection::new(vec![source.clone()])
                    .unwrap_or_else(|e| panic!("source collection: {e}")),
                reason: reason.unwrap_or_else(|| panic!("partial reason")),
            }
        } else {
            ArtifactFamilyResult::Complete {
                artifacts: ArtifactCollection::new(vec![source.clone()])
                    .unwrap_or_else(|e| panic!("source collection: {e}")),
            }
        };
        let decoded_result =
            case.decoded
                .as_ref()
                .map_or(ArtifactFamilyResult::NotRequested, |decoded| {
                    let metadata = metadata(
                        capture_id,
                        2,
                        decoded,
                        schema("com.cascadinglabs.yosoi.benchmark.unicode"),
                        ArtifactAvailability::Retained,
                        None,
                        ArtifactByteExtent::Complete {
                            retained_bytes: ByteCount::new(decoded.len() as u64),
                        },
                        vec![source.reference().as_untyped()],
                        DECODED_SOURCE_UTF8_MEDIA_TYPE,
                    );
                    let artifact =
                        DecodedSourceArtifact::try_from_source(metadata, source.reference())
                            .unwrap_or_else(|e| panic!("decoded artifact: {e}"));
                    payloads
                        .insert(artifact.reference().into(), decoded.clone())
                        .unwrap_or_else(|e| panic!("decoded payload: {e}"));
                    ArtifactFamilyResult::Complete {
                        artifacts: ArtifactCollection::new(vec![artifact])
                            .unwrap_or_else(|e| panic!("decoded collection: {e}")),
                    }
                });
        (source_result, decoded_result, payloads)
    };
    let manifest =
        WebArtifactManifest::new(requests(), other_results(source_result, decoded_result))
            .unwrap_or_else(|e| panic!("manifest: {e}"));
    let resolution = CaptureResolution::new(
        Observation::Observed(
            ResolvedWebUrl::parse(TARGET).unwrap_or_else(|e| panic!("resolved: {e}")),
        ),
        Observation::Observed(Vec::new()),
        Observation::Observed(ObservedWebOrigin::Tuple(
            ResolvedWebUrl::parse(TARGET)
                .unwrap_or_else(|e| panic!("origin URL: {e}"))
                .origin(),
        )),
        Observation::Unobserved,
    )
    .unwrap_or_else(|e| panic!("resolution: {e}"));
    let unavailable = ReasonCode::new("benchmark.environment-unobserved")
        .unwrap_or_else(|e| panic!("environment reason: {e}"));
    let environment = CaptureEnvironment::Http(HttpCaptureEnvironment::new(
        producer(),
        EnvironmentValue::unavailable(unavailable.clone()),
        EnvironmentValue::unavailable(unavailable),
    ));
    let unsupported = || ArtifactCapability::Unsupported {
        reason: ReasonCode::new("benchmark.artifact-unsupported")
            .unwrap_or_else(|e| panic!("capability reason: {e}")),
    };
    let capabilities = WebProviderCapabilityProfile::new(
        producer(),
        AcquisitionCapabilityProfile::DirectHttp,
        WebArtifactCapabilitySet::new(
            ArtifactCapability::Supported {
                multiplicity: ArtifactMultiplicity::ExactlyOne,
            },
            unsupported(),
            unsupported(),
            unsupported(),
            unsupported(),
            unsupported(),
            unsupported(),
            unsupported(),
            unsupported(),
        ),
    )
    .unwrap_or_else(|e| panic!("capabilities: {e}"));
    let input = LifecycleFinalizationInput {
        finished_at: started_at() + chrono::Duration::microseconds(1_000_000),
        terminal_offset: CaptureOffset::from_microseconds(TERMINAL_MICROS),
        dropped_events: MeasuredCount::Known(EventCount::new(0)),
        dropped_bytes: MeasuredCount::Known(ByteCount::new(0)),
        in_flight: InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0))
            .unwrap_or_else(|e| panic!("in flight: {e}")),
        resolution,
        environment,
        capabilities,
        manifest,
        relationships: Vec::new(),
        payloads,
    };
    (spec, lifecycle, input)
}
