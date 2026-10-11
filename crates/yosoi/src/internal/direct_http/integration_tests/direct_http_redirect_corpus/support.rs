use crate::internal::direct_http::*;
use crate::internal::types::{Schema, SchemaId, SchemaVersion};
use chrono::{DateTime, Utc};
use tokio_util::sync::CancellationToken;

pub const fn at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}
fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}
pub fn spec(
    url: &str,
    redirects: DirectHttpRedirectPolicy,
    elapsed_us: u64,
) -> ResolvedDirectHttpCaptureSpec {
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
            ObservationLimits::new(CaptureDeadline::try_from(elapsed_us).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(1_000_000_u64).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
            ByteLimit::try_from(1_000_000_u64).unwrap(),
        ),
        redirects,
        AcceptedSourceFormats::new([AcceptedSourceFormat::PlainText]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        wreq_adapter_producer().unwrap(),
        seed.acquisition().receipt().receipt().operation().clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.redirect-source"),
            schema("com.cascadinglabs.yosoi.redirect-source-representation"),
            Some(schema("com.cascadinglabs.yosoi.redirect-network")),
            Some(schema("com.cascadinglabs.yosoi.redirect-decoded")),
        ),
    )
    .unwrap()
}
pub fn follow(url: &str, hops: u32, elapsed_us: u64) -> ResolvedDirectHttpCaptureSpec {
    spec(
        url,
        DirectHttpRedirectPolicy::follow(RedirectHopLimit::try_from(hops).unwrap()),
        elapsed_us,
    )
}
pub async fn capture(
    spec: ResolvedDirectHttpCaptureSpec,
    cancellation: &CancellationToken,
) -> Result<DirectHttpCapture, DirectHttpCaptureError> {
    capture_direct_http_at(spec, cancellation, at()).await
}
pub fn assert_success(
    capture: &DirectHttpCapture,
    status: u16,
    final_url: &str,
    hops: usize,
    bytes: &[u8],
) {
    assert_eq!(capture.response().status(), status);
    assert_eq!(capture.response().final_url().as_str(), final_url);
    let resolution = capture.bundle().capture().acquisition().resolution();
    assert_eq!(
        resolution.final_url().as_observed().unwrap().as_str(),
        final_url
    );
    assert_eq!(resolution.redirects().as_observed().unwrap().len(), hops);
    assert!(matches!(
        resolution.resource_origin(),
        Observation::Observed(ObservedWebOrigin::Tuple(_))
    ));
    assert_eq!(
        capture.bundle().capture().id(),
        capture
            .bundle()
            .capture()
            .acquisition()
            .request()
            .capture_id()
    );
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
    assert_eq!(
        capture.bundle().payload(artifact.reference().into()),
        Some(bytes)
    );
}
pub fn transport(error: DirectHttpCaptureError) -> DirectHttpFailure {
    match error {
        DirectHttpCaptureError::Transport(failure) => failure,
        other => panic!("expected transport failure: {other:?}"),
    }
}
