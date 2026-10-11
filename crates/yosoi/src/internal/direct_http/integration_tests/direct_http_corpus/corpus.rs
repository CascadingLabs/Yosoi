use super::common::{
    EXPECTED_CAPTURE_ID, EXPECTED_OPERATION_ID, at, route, source_activity_id, spec,
};
use super::corpus::CASES;
use super::fixture::{FixtureService, Protocol};
use crate::internal::direct_http::*;
use crate::internal::types::ArtifactAvailability;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn public_orchestrator_corpus_preserves_independently_fixed_source_evidence() {
    let service = FixtureService::start(Protocol::Http, CASES.iter().map(route)).await;
    for case in CASES {
        let capture = capture_direct_http_at(
            spec(&service.url(&format!("/{}", case.name))),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap();
        assert_eq!(
            capture.response().status(),
            case.status,
            "{} status is classification-independent",
            case.name
        );
        assert_eq!(
            capture.response().requested_url().as_str(),
            service.url(&format!("/{}", case.name))
        );
        assert_eq!(
            capture.response().final_url().as_str(),
            service.url(&format!("/{}", case.name))
        );
        let bundle = capture.bundle();
        assert_eq!(
            capture.identity().environment(),
            bundle.capture().environment()
        );
        assert_eq!(bundle.capture().id().to_string(), EXPECTED_CAPTURE_ID);
        assert_eq!(
            bundle
                .capture()
                .acquisition()
                .request()
                .capture_id()
                .to_string(),
            EXPECTED_CAPTURE_ID
        );
        let receipt = bundle.capture().acquisition().receipt().receipt();
        assert_eq!(receipt.id().to_string(), EXPECTED_CAPTURE_ID);
        assert_eq!(source_activity_id(bundle).to_string(), EXPECTED_CAPTURE_ID);
        assert_eq!(receipt.operation().as_str(), EXPECTED_OPERATION_ID);
        assert_eq!(
            receipt.outputs().len(),
            usize::from(case.encoding.is_some()) + 2
        );
        let source = bundle
            .capture()
            .artifacts()
            .results()
            .source()
            .artifacts()
            .unwrap()
            .first()
            .unwrap();
        assert_eq!(
            source.metadata().record().availability(),
            ArtifactAvailability::Retained,
            "{} source retained",
            case.name
        );
        assert_eq!(
            source.metadata().extent().retained_bytes().unwrap().get(),
            u64::try_from(case.bytes.len()).unwrap()
        );
        assert_eq!(
            source.metadata().content_digest().unwrap().to_string(),
            case.sha256,
            "{} fixed digest",
            case.name
        );
        assert_eq!(
            bundle.payload(source.reference().into()),
            Some(case.bytes),
            "{} exact representation",
            case.name
        );
        let classification = capture.source_facts().unwrap().classification();
        match (case.format, classification) {
            ("html", SourceClassificationOutcome::Classified(value)) => {
                assert_eq!(value.format(), SourceFormat::Html);
                assert_eq!(value.extent(), ClassificationExtent::Complete);
            }
            ("xml", SourceClassificationOutcome::Classified(value)) => {
                assert_eq!(value.format(), SourceFormat::Xml(XmlProfile::Generic));
                assert_eq!(value.extent(), ClassificationExtent::Complete);
            }
            ("xhtml", SourceClassificationOutcome::Classified(value)) => {
                assert_eq!(value.format(), SourceFormat::Xml(XmlProfile::Xhtml));
                assert_eq!(value.extent(), ClassificationExtent::Complete);
            }
            ("json", SourceClassificationOutcome::Classified(value)) => {
                assert_eq!(value.format(), SourceFormat::Json);
                assert_eq!(value.extent(), ClassificationExtent::Complete);
            }
            ("plain", SourceClassificationOutcome::Classified(value)) => {
                assert_eq!(value.format(), SourceFormat::PlainText);
                assert_eq!(value.extent(), ClassificationExtent::Complete);
            }
            (
                "unknown",
                SourceClassificationOutcome::Unknown {
                    reason,
                    candidates,
                    extent,
                },
            ) => {
                let expected = if case.bytes.is_empty() {
                    UnknownReason::Empty
                } else {
                    UnknownReason::NoStrongSignature
                };
                assert_eq!(*reason, expected);
                assert_eq!(candidates.len(), 0);
                assert_eq!(*extent, ClassificationExtent::Complete);
            }
            (
                "unsupported",
                SourceClassificationOutcome::Unsupported {
                    essence,
                    candidates,
                    extent,
                    ..
                },
            ) => {
                assert_eq!(Some(essence.as_str()), case.content_type);
                let expected_candidates = if case.name == "text-json" {
                    &[SourceFormat::Json][..]
                } else {
                    &[][..]
                };
                assert_eq!(candidates, expected_candidates);
                assert_eq!(*extent, ClassificationExtent::Complete);
            }
            _ => panic!(
                "{} classification did not match fixed expected variant",
                case.name
            ),
        }
        let decoded = bundle.capture().artifacts().results().decoded_source();
        if let Some(encoding) = case.encoding {
            let artifact = decoded.artifacts().unwrap().first().unwrap();
            assert_eq!(
                artifact.interpretation().encoding(),
                encoding,
                "{} selected encoding",
                case.name
            );
            assert_eq!(
                artifact.source(),
                source.reference(),
                "{} decoded lineage",
                case.name
            );
            assert_eq!(
                artifact.metadata().provenance().derived_from(),
                &[source.reference().as_untyped()]
            );
            assert_eq!(
                artifact.metadata().media_type().as_str(),
                DECODED_SOURCE_UTF8_MEDIA_TYPE
            );
            assert!(bundle.payload(artifact.reference().into()).is_some());
        } else {
            assert!(
                decoded.artifacts().is_none(),
                "{} has no fabricated unicode view",
                case.name
            );
        }
        let decoded_reference = decoded
            .artifacts()
            .and_then(<[DecodedSourceArtifact]>::first)
            .map(DecodedSourceArtifact::reference);
        let durable = capture.source_representation_evidence().unwrap();
        assert_eq!(
            durable,
            SourceRepresentationEvidence::from_facts(
                source.reference(),
                decoded_reference,
                capture.source_facts().unwrap(),
            )
            .unwrap(),
            "{} durable facts",
            case.name
        );
        assert!(
            matches!(
                bundle.capture().artifacts().results().network(),
                ArtifactFamilyResult::Unavailable { .. }
            ),
            "{} network bytes explicitly unavailable",
            case.name
        );
        assert!(
            bundle
                .capture()
                .artifacts()
                .results()
                .rendered_dom()
                .is_not_requested()
        );
        assert!(
            bundle
                .capture()
                .artifacts()
                .results()
                .accessibility_tree()
                .is_not_requested()
        );
        let wire = WebCaptureWire::to_canonical_json(bundle.capture()).unwrap();
        let roundtrip = WebCaptureWire::from_json(&wire).unwrap();
        assert_eq!(
            WebCaptureWire::to_canonical_json(&roundtrip).unwrap(),
            wire,
            "{} canonical roundtrip",
            case.name
        );
    }
    service.shutdown().await;
}
