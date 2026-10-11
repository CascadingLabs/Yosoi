use crate::internal::direct_http::{ArtifactRequest, WebArtifactFamily, WebArtifactRequestSet};

use super::{DirectHttpCaptureSpecError, DirectHttpOutputSchemas, SourceRetentionPolicy};

pub(super) fn validate_artifact_requests(
    artifacts: WebArtifactRequestSet,
) -> Result<(), DirectHttpCaptureSpecError> {
    if artifacts.source() != ArtifactRequest::Required {
        return Err(DirectHttpCaptureSpecError::SourceMustBeRequired);
    }

    let unsupported = [
        (WebArtifactFamily::RenderedDom, artifacts.rendered_dom()),
        (
            WebArtifactFamily::AccessibilityTree,
            artifacts.accessibility_tree(),
        ),
        (WebArtifactFamily::Cookies, artifacts.cookies()),
        (WebArtifactFamily::Storage, artifacts.storage()),
        (WebArtifactFamily::Layout, artifacts.layout()),
        (WebArtifactFamily::Visual, artifacts.visual()),
        (
            WebArtifactFamily::RuntimeDiagnostics,
            artifacts.runtime_diagnostics(),
        ),
    ];
    for (family, request) in unsupported {
        if request != ArtifactRequest::NotRequested {
            return Err(DirectHttpCaptureSpecError::UnsupportedArtifactFamily { family });
        }
    }
    Ok(())
}

pub(super) fn validate_output_schemas(
    artifacts: WebArtifactRequestSet,
    retention: SourceRetentionPolicy,
    schemas: &DirectHttpOutputSchemas,
) -> Result<(), DirectHttpCaptureSpecError> {
    if schemas.source() == schemas.source_representation() {
        return Err(DirectHttpCaptureSpecError::SourceRepresentationSchemaMustDiffer);
    }
    if schemas
        .unicode_view()
        .is_some_and(|view| view == schemas.source() || view == schemas.source_representation())
    {
        return Err(DirectHttpCaptureSpecError::UnicodeViewSchemaMustDiffer);
    }
    match (artifacts.network(), schemas.network()) {
        (ArtifactRequest::NotRequested, Some(_)) => {
            return Err(DirectHttpCaptureSpecError::UnexpectedNetworkSchema);
        }
        (ArtifactRequest::Optional | ArtifactRequest::Required, None) => {
            return Err(DirectHttpCaptureSpecError::MissingNetworkSchema);
        }
        (ArtifactRequest::NotRequested, None)
        | (ArtifactRequest::Optional | ArtifactRequest::Required, Some(_)) => {}
    }

    match (retention.retains_unicode_view(), schemas.unicode_view()) {
        (true, None) => Err(DirectHttpCaptureSpecError::MissingUnicodeViewSchema),
        (false, Some(_)) => Err(DirectHttpCaptureSpecError::UnexpectedUnicodeViewSchema),
        (true, Some(_)) | (false, None) => Ok(()),
    }
}
