//! Synthetic provider-neutral finalization inputs used by tests and benchmarks.

use chrono::{DateTime, TimeDelta, Utc};
use yosoi_dev_support::internal::types::{
    ArtifactAvailability, ArtifactId, ArtifactRecord, CaptureId, Producer, ProducerId,
    ProducerVersion, Provenance, ReasonCode, Sha256Digest,
};
use yosoi_dev_support::internal::web_capture::*;

const TARGET: &str = "https://finalization.invalid/source";
const TERMINAL_MICROS: u64 = 1_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalizationCase {
    Minimal,
    Complete,
    Truncated,
}

fn producer() -> Producer {
    Producer::new(
        ProducerId::new("com.cascadinglabs.yosoi.finalization-characterization")
            .unwrap_or_else(|error| panic!("producer id: {error}")),
        ProducerVersion::new("1.0.0").unwrap_or_else(|error| panic!("producer version: {error}")),
    )
}

fn reason(value: &'static str) -> ReasonCode {
    ReasonCode::new(value).unwrap_or_else(|error| panic!("reason code: {error}"))
}

fn requests(case: FinalizationCase) -> WebArtifactRequestSet {
    WebArtifactRequestSet::new(
        if case == FinalizationCase::Minimal {
            ArtifactRequest::NotRequested
        } else {
            ArtifactRequest::Required
        },
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

fn source_result(
    case: FinalizationCase,
    capture_id: CaptureId,
    generated_at: DateTime<Utc>,
) -> (
    ArtifactFamilyResult<SourceArtifact>,
    Vec<(WebArtifactRef, Vec<u8>)>,
) {
    if case == FinalizationCase::Minimal {
        return (ArtifactFamilyResult::NotRequested, Vec::new());
    }
    let complete = b"<main>provider-neutral finalization</main>";
    let bytes = if case == FinalizationCase::Truncated {
        complete
            .get(..16)
            .unwrap_or_else(|| panic!("committed fixture has a 16-byte prefix"))
            .to_vec()
    } else {
        complete.to_vec()
    };
    let retained = ByteCount::new(
        u64::try_from(bytes.len()).unwrap_or_else(|error| panic!("retained length: {error}")),
    );
    let (availability, extent, why) = if case == FinalizationCase::Truncated {
        (
            ArtifactAvailability::Truncated,
            ArtifactByteExtent::truncated(
                retained,
                MeasuredCount::Known(ByteCount::new(
                    u64::try_from(complete.len())
                        .unwrap_or_else(|error| panic!("complete length: {error}")),
                )),
            )
            .unwrap_or_else(|error| panic!("truncated extent: {error}")),
            Some(reason("characterization.source-truncated")),
        )
    } else {
        (
            ArtifactAvailability::Retained,
            ArtifactByteExtent::Complete {
                retained_bytes: retained,
            },
            None,
        )
    };
    let provenance = Provenance::new(
        capture_id.activity_id(),
        producer(),
        crate::support::schema("com.cascadinglabs.yosoi.finalization-characterization.source"),
        generated_at,
        Vec::new(),
    );
    let record = ArtifactRecord::new(
        ArtifactId::try_from(1).unwrap_or_else(|error| panic!("artifact id: {error}")),
        Some(Sha256Digest::digest(&bytes)),
        availability,
        why.clone(),
        provenance,
    )
    .unwrap_or_else(|error| panic!("artifact record: {error}"));
    let metadata = WebArtifactMetadata::new(
        record,
        MediaType::new("text/html").unwrap_or_else(|error| panic!("media type: {error}")),
        extent,
        ArtifactSensitivity::NonSensitive,
    )
    .unwrap_or_else(|error| panic!("metadata: {error}"));
    let artifact = SourceArtifact::new(metadata);
    let reference = artifact.reference().into();
    let artifacts = ArtifactCollection::new(vec![artifact])
        .unwrap_or_else(|error| panic!("artifact collection: {error}"));
    let result = if case == FinalizationCase::Truncated {
        ArtifactFamilyResult::Partial {
            artifacts,
            reason: why.unwrap_or_else(|| panic!("truncated source reason")),
        }
    } else {
        ArtifactFamilyResult::Complete { artifacts }
    };
    (result, vec![(reference, bytes)])
}

const fn results(source: ArtifactFamilyResult<SourceArtifact>) -> WebArtifactResults {
    WebArtifactResults::new_with_derived_source(
        source,
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::NotRequested,
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

pub fn plan(case: FinalizationCase) -> AcquisitionFinalizationPlan {
    let started_at = DateTime::from_timestamp(1_700_000_000, 0)
        .unwrap_or_else(|| panic!("valid fixed timestamp"));
    plan_generated_at(case, started_at, started_at)
}

pub fn plan_generated_at(
    case: FinalizationCase,
    started_at: DateTime<Utc>,
    generated_at: DateTime<Utc>,
) -> AcquisitionFinalizationPlan {
    let capture_id = CaptureId::random();
    let target = RequestedWebTarget::parse(TARGET)
        .unwrap_or_else(|error| panic!("requested target: {error}"));
    let request = WebCaptureRequest::new(
        capture_id,
        target,
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    let requests = requests(case);
    let (source, payloads) = source_result(case, capture_id, generated_at);
    let manifest = WebArtifactManifest::new(requests, results(source))
        .unwrap_or_else(|error| panic!("manifest: {error}"));
    let resolved =
        ResolvedWebUrl::parse(TARGET).unwrap_or_else(|error| panic!("resolved target: {error}"));
    let resolution = CaptureResolution::new(
        Observation::Observed(resolved.clone()),
        Observation::Observed(Vec::new()),
        Observation::Observed(ObservedWebOrigin::Tuple(resolved.origin())),
        Observation::Unobserved,
    )
    .unwrap_or_else(|error| panic!("resolution: {error}"));
    let unsupported = || ArtifactCapability::Unsupported {
        reason: reason("characterization.artifact-unsupported"),
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
    .unwrap_or_else(|error| panic!("capabilities: {error}"));
    let unavailable = reason("characterization.environment-unavailable");
    let environment = CaptureEnvironment::Http(HttpCaptureEnvironment::new(
        producer(),
        EnvironmentValue::unavailable(unavailable.clone()),
        EnvironmentValue::unavailable(unavailable),
    ));
    let observation_policy = ObservationPolicy::new(
        ObservationLimits::new(
            CaptureDeadline::try_from(1_000_000)
                .unwrap_or_else(|error| panic!("maximum elapsed: {error}")),
            None,
            None,
        ),
        SettlementPolicy::Disabled,
    );
    let zero_events = EventAccounting::new(
        EventCount::new(0),
        EventCount::new(0),
        MeasuredCount::Known(EventCount::new(0)),
    )
    .unwrap_or_else(|error| panic!("event accounting: {error}"));
    let zero_bytes = ByteAccounting::new(
        ByteCount::new(0),
        ByteCount::new(0),
        MeasuredCount::Known(ByteCount::new(0)),
    )
    .unwrap_or_else(|error| panic!("byte accounting: {error}"));
    let mut lifecycle =
        BoundedAcquisitionLifecycle::start(request.capture_id(), observation_policy, started_at);
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(TERMINAL_MICROS),
            LifecycleStop::Completed(ControllerStopReason::GoalSatisfied),
        )
        .unwrap_or_else(|error| panic!("stop lifecycle: {error}"));
    AcquisitionFinalizationPlan {
        request,
        operation: "characterization.finalize"
            .parse()
            .unwrap_or_else(|error| panic!("operation: {error}")),
        producer: producer(),
        lifecycle,
        finished_at: started_at
            .checked_add_signed(TimeDelta::milliseconds(1))
            .unwrap_or_else(|| panic!("fixed finish timestamp")),
        terminal_offset: CaptureOffset::from_microseconds(TERMINAL_MICROS),
        events: zero_events,
        bytes: zero_bytes,
        in_flight: InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0))
            .unwrap_or_else(|error| panic!("in-flight accounting: {error}")),
        resolution,
        environment,
        capabilities,
        manifest,
        artifact_timestamp_order: ArtifactTimestampOrder::ManifestOrder,
        relationships: Vec::new(),
        payloads,
        activity_result: None,
        browser_execution: None,
        browser_challenge: None,
    }
}
