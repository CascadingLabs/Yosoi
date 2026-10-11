use crate::internal::direct_http as internal_direct_http;
use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ActivityCount, ArtifactRequest,
    BoundedAcquisitionLifecycle, ByteCount, ByteLimit, CaptureDeadline, CaptureOffset,
    DirectHttpContentLimits, DirectHttpOutputSchemas, DirectHttpRedirectPolicy, EventCount,
    EventLimit, InFlightActivity, LifecycleEvent, LifecycleFinalizationInput, MeasuredCount,
    ObservationLimits, ObservationPolicy, ResolvedDirectHttpCaptureSpec, SettlementPolicy,
    SourceRetentionPolicy, StagedPayloads, UnsupportedSourceFormatBehavior, WebArtifactManifest,
    WebArtifactRequestSet, WebCapture, WebCaptureWire,
};
use crate::internal::types::{Schema, SchemaId, SchemaVersion};
use chrono::{DateTime, Utc};
use std::{
    fs,
    ops::{Deref, DerefMut},
};

pub const FIRST: &[u8] = b"first";
pub const SECOND: &[u8] = b"second";

pub fn fixture() -> WebCapture {
    let bytes = fs::read(format!(
        "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    WebCaptureWire::from_json(&bytes).unwrap()
}

pub fn schema(id: &str, version: u32) -> Schema {
    Schema::new(
        SchemaId::new(id).unwrap(),
        SchemaVersion::try_from(version).unwrap(),
    )
}

pub const fn requests(source: ArtifactRequest, network: ArtifactRequest) -> WebArtifactRequestSet {
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

pub fn spec(
    event_limit: Option<u64>,
    byte_limit: Option<u64>,
    deadline: u64,
) -> (WebCapture, ResolvedDirectHttpCaptureSpec) {
    spec_with_schemas(
        event_limit,
        byte_limit,
        deadline,
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.web.source", 1),
            schema("com.cascadinglabs.web.source-representation", 1),
            None,
            None,
        ),
    )
}

pub fn spec_with_schemas(
    event_limit: Option<u64>,
    byte_limit: Option<u64>,
    deadline: u64,
    schemas: DirectHttpOutputSchemas,
) -> (WebCapture, ResolvedDirectHttpCaptureSpec) {
    let capture = fixture();
    let policy = ObservationPolicy::new(
        ObservationLimits::new(
            CaptureDeadline::try_from(deadline).unwrap(),
            event_limit.map(|v| EventLimit::try_from(v).unwrap()),
            byte_limit.map(|v| ByteLimit::try_from(v).unwrap()),
        ),
        SettlementPolicy::Disabled,
    );
    let response_limit = ByteLimit::try_from(1_000_000_u64).unwrap();
    let spec = ResolvedDirectHttpCaptureSpec::new(
        capture.acquisition().request().clone(),
        requests(ArtifactRequest::Required, ArtifactRequest::NotRequested),
        policy,
        DirectHttpContentLimits::new(response_limit, response_limit, response_limit),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::Representation,
        capture.acquisition().receipt().receipt().producer().clone(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        schemas,
    )
    .unwrap();
    (capture, spec)
}

pub fn event(offset: u64, admitted: u64, retained: u64, kept: bool) -> LifecycleEvent {
    LifecycleEvent::new(
        CaptureOffset::from_microseconds(offset),
        ByteCount::new(admitted),
        ByteCount::new(retained),
        kept,
    )
    .unwrap()
}

pub const fn started_at(capture: &WebCapture) -> DateTime<Utc> {
    *capture.observation().window().started_at()
}

pub struct TestLifecycle {
    spec: ResolvedDirectHttpCaptureSpec,
    lifecycle: BoundedAcquisitionLifecycle,
}

impl TestLifecycle {
    pub fn start(spec: ResolvedDirectHttpCaptureSpec, started_at: DateTime<Utc>) -> Self {
        let lifecycle = BoundedAcquisitionLifecycle::start(
            spec.capture_id(),
            spec.observation().clone(),
            started_at,
        );
        Self { spec, lifecycle }
    }

    pub fn finalize(
        self,
        input: LifecycleFinalizationInput,
    ) -> Result<internal_direct_http::CaptureBundle, internal_direct_http::LifecycleError> {
        internal_direct_http::finalize_direct_http_attempt(self.spec, self.lifecycle, input)
    }
}

impl Deref for TestLifecycle {
    type Target = BoundedAcquisitionLifecycle;

    fn deref(&self) -> &Self::Target {
        &self.lifecycle
    }
}

impl DerefMut for TestLifecycle {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.lifecycle
    }
}

pub fn stopped() -> (WebCapture, TestLifecycle) {
    let (capture, spec) = spec(None, None, 2_000_000);
    let mut lifecycle = TestLifecycle::start(spec, started_at(&capture));
    lifecycle
        .stop(
            CaptureOffset::from_microseconds(1_000_000),
            internal_direct_http::LifecycleStop::Completed(
                internal_direct_http::ControllerStopReason::GoalSatisfied,
            ),
        )
        .unwrap();
    (capture, lifecycle)
}

pub fn input(
    capture: &WebCapture,
    dropped_events: MeasuredCount<EventCount>,
    dropped_bytes: MeasuredCount<ByteCount>,
    payloads: StagedPayloads,
) -> LifecycleFinalizationInput {
    LifecycleFinalizationInput {
        finished_at: *capture.observation().window().finished_at(),
        terminal_offset: CaptureOffset::from_microseconds(1_000_000),
        dropped_events,
        dropped_bytes,
        in_flight: InFlightActivity::new(ActivityCount::new(0), ActivityCount::new(0)).unwrap(),
        resolution: capture.acquisition().resolution().clone(),
        environment: capture.environment().clone(),
        capabilities: capture.capabilities().clone(),
        manifest: WebArtifactManifest::new(
            requests(ArtifactRequest::Required, ArtifactRequest::NotRequested),
            capture.artifacts().results().clone(),
        )
        .unwrap(),
        relationships: capture.relationships().to_vec(),
        payloads,
    }
}

pub fn valid_payloads(capture: &WebCapture) -> StagedPayloads {
    let mut payloads = StagedPayloads::default();
    let source = capture.artifacts().results().source().artifacts().unwrap();
    payloads
        .insert(source[0].reference().into(), FIRST.to_vec())
        .unwrap();
    payloads
        .insert(source[1].reference().into(), SECOND.to_vec())
        .unwrap();
    payloads
}
