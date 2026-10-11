use super::fixture::Response;
use crate::internal::direct_http::*;
use crate::internal::types::{Schema, SchemaId, SchemaVersion};
use chrono::{DateTime, Utc};

pub const fn at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}
pub fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
#[derive(Clone, Copy)]
pub struct Options {
    pub encoded: u64,
    pub representation: u64,
    pub unicode: u64,
    pub elapsed: u64,
    pub event_limit: Option<u64>,
    pub byte_limit: Option<u64>,
    pub behavior: UnsupportedSourceFormatBehavior,
    pub retention: SourceRetentionPolicy,
    pub network: ArtifactRequest,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            encoded: 1_000_000,
            representation: 1_000_000,
            unicode: 1_000_000,
            elapsed: 2_000_000,
            event_limit: None,
            byte_limit: None,
            behavior: UnsupportedSourceFormatBehavior::RetainAndReport,
            retention: SourceRetentionPolicy::RepresentationAndUnicodeView,
            network: ArtifactRequest::Optional,
        }
    }
}
pub fn spec(url: &str, options: Options) -> ResolvedDirectHttpCaptureSpec {
    let seed =
        WebCaptureWire::from_json(include_bytes!("../fixtures/web-capture/complete-v1.json"))
            .unwrap();
    let request = WebCaptureRequest::new(
        seed.id(),
        RequestedWebTarget::parse(url).unwrap(),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        WebArtifactRequestSet::new(
            ArtifactRequest::Required,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            options.network,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        ),
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(options.elapsed).unwrap(),
                options
                    .event_limit
                    .map(|v| EventLimit::try_from(v).unwrap()),
                options.byte_limit.map(|v| ByteLimit::try_from(v).unwrap()),
            ),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(options.encoded).unwrap(),
            ByteLimit::try_from(options.representation).unwrap(),
            ByteLimit::try_from(options.unicode).unwrap(),
        ),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::Json,
            AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
            AcceptedSourceFormat::PlainText,
        ])
        .unwrap(),
        options.behavior,
        options.retention,
        wreq_adapter_producer().unwrap(),
        seed.acquisition().receipt().receipt().operation().clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.c2-source"),
            schema("com.cascadinglabs.yosoi.c2-source-representation"),
            (!matches!(options.network, ArtifactRequest::NotRequested))
                .then(|| schema("com.cascadinglabs.yosoi.c2-network")),
            Some(schema("com.cascadinglabs.yosoi.c2-decoded")),
        ),
    )
    .unwrap()
}
pub fn source(capture: &DirectHttpCapture) -> (&SourceArtifact, &[u8]) {
    let artifact = capture
        .bundle()
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    (
        artifact,
        capture
            .bundle()
            .payload(artifact.reference().into())
            .unwrap(),
    )
}
pub fn output(capture: &DirectHttpCapture, source: &SourceArtifact) -> DecodedOutputIdentity {
    let decoded = capture
        .bundle()
        .capture()
        .artifacts()
        .results()
        .decoded_source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    DecodedOutputIdentity::new(
        decoded.reference(),
        decoded.metadata().provenance().producer().clone(),
        decoded.metadata().provenance().schema().clone(),
        decoded.metadata().provenance().derived_from().to_vec(),
        source.reference(),
    )
    .unwrap()
    .with_generated_at(*decoded.metadata().provenance().generated_at())
}
pub fn response(body: &[u8], content_type: Option<&str>) -> Response {
    Response::bytes(200, content_type, body)
}
