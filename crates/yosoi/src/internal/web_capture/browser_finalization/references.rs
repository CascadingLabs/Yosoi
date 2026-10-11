use crate::internal::types as yosoi_types;

use crate::internal::web_capture::{
    AccessibilityTreeArtifactRef, BrowserStagingFamily, CookieArtifactRef,
    DecodedSourceArtifactRef, LayoutArtifactRef, NetworkArtifactRef, RenderedDomArtifactRef,
    RuntimeDiagnosticsArtifactRef, SourceArtifactRef, SourceRepresentationArtifactRef,
    StorageArtifactRef, VisualArtifactRef, WebArtifactFamily, WebArtifactRef,
};

pub(super) const fn web_reference(
    family: BrowserStagingFamily,
    reference: yosoi_types::ArtifactRef,
) -> WebArtifactRef {
    match family {
        BrowserStagingFamily::SourceRepresentation => WebArtifactRef::SourceRepresentation(
            SourceRepresentationArtifactRef::from_untyped(reference),
        ),
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source) => {
            WebArtifactRef::Source(SourceArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom) => {
            WebArtifactRef::RenderedDom(RenderedDomArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree) => {
            WebArtifactRef::AccessibilityTree(AccessibilityTreeArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Network) => {
            WebArtifactRef::Network(NetworkArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Cookies) => {
            WebArtifactRef::Cookies(CookieArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Storage) => {
            WebArtifactRef::Storage(StorageArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Layout) => {
            WebArtifactRef::Layout(LayoutArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
            WebArtifactRef::Visual(VisualArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics) => {
            WebArtifactRef::RuntimeDiagnostics(RuntimeDiagnosticsArtifactRef::from_untyped(
                reference,
            ))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource) => {
            WebArtifactRef::DecodedSource(DecodedSourceArtifactRef::from_untyped(reference))
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::SourceRepresentation) => {
            WebArtifactRef::SourceRepresentation(SourceRepresentationArtifactRef::from_untyped(
                reference,
            ))
        }
    }
}
