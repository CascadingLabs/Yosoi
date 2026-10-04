use crate::corpus::CorpusCase;
use crate::fixture::Response;
use chrono::{DateTime, Utc};
use yosoi_types::{Schema, SchemaId, SchemaVersion};
use yosoi_web_capture_direct_http::*;

pub const EXPECTED_CAPTURE_ID: &str = "123e4567-e89b-42d3-a456-426614174002";
pub const EXPECTED_OPERATION_ID: &str = "com.cascadinglabs.yosoi.web-capture";

fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
pub fn spec(url: &str) -> ResolvedDirectHttpCaptureSpec {
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
            ArtifactRequest::Optional,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        ),
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(2_000_000).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(1_000_000_u64).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
        ),
        DirectHttpRedirectPolicy::Disabled,
        AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::Json,
            AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
            AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml),
            AcceptedSourceFormat::PlainText,
        ])
        .unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        wreq_adapter_producer().unwrap(),
        seed.acquisition().receipt().receipt().operation().clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.corpus-source"),
            schema("com.cascadinglabs.yosoi.corpus-source-representation"),
            Some(schema("com.cascadinglabs.yosoi.corpus-network")),
            Some(schema("com.cascadinglabs.yosoi.corpus-decoded")),
        ),
    )
    .unwrap()
}
pub const fn at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}
pub fn source_activity_id(bundle: &CaptureBundle) -> yosoi_types::ActivityId {
    bundle
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap()
        .reference()
        .as_untyped()
        .activity_id()
}
pub fn route(case: &CorpusCase) -> (String, Response) {
    (
        format!("/{}", case.name),
        Response::bytes(case.status, case.content_type, case.bytes),
    )
}
