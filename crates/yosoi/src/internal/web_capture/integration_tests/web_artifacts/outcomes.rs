use crate::internal::types::ActivityId;
use crate::internal::web_capture::{
    AccessibilityTreeArtifact, ArtifactCollection, ArtifactFamilyResult, ArtifactRequest,
    CookieArtifact, LayoutArtifact, NetworkArtifact, RenderedDomArtifact,
    RuntimeDiagnosticsArtifact, SourceArtifact, StorageArtifact, VisualArtifact, WebArtifactFamily,
    WebArtifactManifest, WebArtifactManifestError, WebArtifactRequestSet, WebArtifactResults,
};
use serde_json::json;

use super::support::{reason, retained_metadata};

#[test]
fn empty_produced_collections_are_rejected_but_multiple_artifacts_are_deliberate() {
    assert!(ArtifactCollection::<NetworkArtifact>::new(Vec::new()).is_err());
    assert!(
        serde_json::from_value::<ArtifactFamilyResult<VisualArtifact>>(json!({
            "status": "complete",
            "artifacts": []
        }))
        .is_err()
    );

    let activity = ActivityId::random();
    let artifacts = ArtifactCollection::new(vec![
        NetworkArtifact::new(retained_metadata(
            activity,
            1,
            "application/json",
            b"chunk-one",
        )),
        NetworkArtifact::new(retained_metadata(
            activity,
            2,
            "application/json",
            b"chunk-two",
        )),
    ])
    .unwrap();
    let result = ArtifactFamilyResult::Complete { artifacts };

    assert_eq!(result.artifacts().unwrap().len(), 2);
    assert_eq!(
        serde_json::from_value::<ArtifactFamilyResult<NetworkArtifact>>(
            serde_json::to_value(&result).unwrap()
        )
        .unwrap(),
        result
    );
}

#[test]
fn negative_results_remain_distinct_from_absence_and_each_other() {
    let results: [ArtifactFamilyResult<SourceArtifact>; 4] = [
        ArtifactFamilyResult::NotRequested,
        ArtifactFamilyResult::Unavailable {
            reason: reason("capture.source-unavailable"),
        },
        ArtifactFamilyResult::OmittedByPolicy {
            reason: reason("policy.source-omitted"),
        },
        ArtifactFamilyResult::Unsupported {
            reason: reason("provider.source-unsupported"),
        },
    ];
    let statuses: Vec<_> = results
        .iter()
        .map(|result| serde_json::to_value(result).unwrap()["status"].clone())
        .collect();

    assert_eq!(
        statuses,
        vec![
            json!("not_requested"),
            json!("unavailable"),
            json!("omitted_by_policy"),
            json!("unsupported"),
        ]
    );
}

#[test]
fn requests_and_results_account_for_every_family() {
    let requests = WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::Required,
        ArtifactRequest::Optional,
        ArtifactRequest::Required,
        ArtifactRequest::Optional,
        ArtifactRequest::NotRequested,
        ArtifactRequest::Optional,
        ArtifactRequest::Optional,
        ArtifactRequest::Optional,
    );
    let activity = ActivityId::random();
    let visual = ArtifactCollection::new(vec![VisualArtifact::new(retained_metadata(
        activity,
        1,
        "image/png",
        b"frame",
    ))])
    .unwrap();
    let results = WebArtifactResults::new(
        ArtifactFamilyResult::<SourceArtifact>::Unavailable {
            reason: reason("capture.source-unavailable"),
        },
        ArtifactFamilyResult::<RenderedDomArtifact>::Unavailable {
            reason: reason("capture.dom-unavailable"),
        },
        ArtifactFamilyResult::<AccessibilityTreeArtifact>::Unsupported {
            reason: reason("provider.ax-unsupported"),
        },
        ArtifactFamilyResult::<NetworkArtifact>::Unavailable {
            reason: reason("capture.network-unavailable"),
        },
        ArtifactFamilyResult::<CookieArtifact>::OmittedByPolicy {
            reason: reason("policy.cookies-omitted"),
        },
        ArtifactFamilyResult::<StorageArtifact>::NotRequested,
        ArtifactFamilyResult::<LayoutArtifact>::Unsupported {
            reason: reason("provider.layout-unsupported"),
        },
        ArtifactFamilyResult::Partial {
            artifacts: visual,
            reason: reason("capture.visual-limit"),
        },
        ArtifactFamilyResult::<RuntimeDiagnosticsArtifact>::Unavailable {
            reason: reason("capture.runtime-unavailable"),
        },
    );
    let manifest = WebArtifactManifest::new(requests, results).unwrap();

    assert_eq!(
        manifest.requests().runtime_diagnostics(),
        ArtifactRequest::Optional
    );
    assert_eq!(manifest.results().visual().artifacts().unwrap().len(), 1);
    assert_eq!(
        serde_json::from_value::<WebArtifactManifest>(serde_json::to_value(&manifest).unwrap())
            .unwrap(),
        manifest
    );
    let mut invalid_manifest = serde_json::to_value(&manifest).unwrap();
    invalid_manifest["requests"]["source"] = json!("not_requested");
    assert!(serde_json::from_value::<WebArtifactManifest>(invalid_manifest).is_err());

    let mut encoded_requests = serde_json::to_value(requests).unwrap();
    encoded_requests
        .as_object_mut()
        .unwrap()
        .remove("runtime_diagnostics");
    assert!(serde_json::from_value::<WebArtifactRequestSet>(encoded_requests).is_err());

    let mut encoded_results = serde_json::to_value(manifest.results()).unwrap();
    encoded_results
        .as_object_mut()
        .unwrap()
        .remove("runtime_diagnostics");
    assert!(serde_json::from_value::<WebArtifactResults>(encoded_results).is_err());
}

#[test]
fn request_and_result_mismatches_are_rejected() {
    let unrequested_with_result = WebArtifactManifest::new(
        all_not_requested(),
        WebArtifactResults::new(
            ArtifactFamilyResult::<SourceArtifact>::Unavailable {
                reason: reason("capture.source-unavailable"),
            },
            ArtifactFamilyResult::<RenderedDomArtifact>::NotRequested,
            ArtifactFamilyResult::<AccessibilityTreeArtifact>::NotRequested,
            ArtifactFamilyResult::<NetworkArtifact>::NotRequested,
            ArtifactFamilyResult::<CookieArtifact>::NotRequested,
            ArtifactFamilyResult::<StorageArtifact>::NotRequested,
            ArtifactFamilyResult::<LayoutArtifact>::NotRequested,
            ArtifactFamilyResult::<VisualArtifact>::NotRequested,
            ArtifactFamilyResult::<RuntimeDiagnosticsArtifact>::NotRequested,
        ),
    );
    assert_eq!(
        unrequested_with_result,
        Err(WebArtifactManifestError::UnexpectedResult {
            family: WebArtifactFamily::Source,
        })
    );

    let requested_without_result = WebArtifactManifest::new(
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
        ),
        all_not_requested_results(),
    );
    assert_eq!(
        requested_without_result,
        Err(WebArtifactManifestError::MissingResult {
            family: WebArtifactFamily::Source,
        })
    );
}

const fn all_not_requested() -> WebArtifactRequestSet {
    WebArtifactRequestSet::new(
        ArtifactRequest::NotRequested,
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

const fn all_not_requested_results() -> WebArtifactResults {
    WebArtifactResults::new(
        ArtifactFamilyResult::<SourceArtifact>::NotRequested,
        ArtifactFamilyResult::<RenderedDomArtifact>::NotRequested,
        ArtifactFamilyResult::<AccessibilityTreeArtifact>::NotRequested,
        ArtifactFamilyResult::<NetworkArtifact>::NotRequested,
        ArtifactFamilyResult::<CookieArtifact>::NotRequested,
        ArtifactFamilyResult::<StorageArtifact>::NotRequested,
        ArtifactFamilyResult::<LayoutArtifact>::NotRequested,
        ArtifactFamilyResult::<VisualArtifact>::NotRequested,
        ArtifactFamilyResult::<RuntimeDiagnosticsArtifact>::NotRequested,
    )
}
