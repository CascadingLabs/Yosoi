use crate::{
    ArtifactCapability, ArtifactRequest, BrowserStagingFamily, WebArtifactFamily,
    WebArtifactRequestSet, WebProviderCapabilityProfile,
};

use super::BrowserByteDomain;

pub(super) const FAMILIES: [WebArtifactFamily; 9] = [
    WebArtifactFamily::Source,
    WebArtifactFamily::RenderedDom,
    WebArtifactFamily::AccessibilityTree,
    WebArtifactFamily::Network,
    WebArtifactFamily::Cookies,
    WebArtifactFamily::Storage,
    WebArtifactFamily::Layout,
    WebArtifactFamily::Visual,
    WebArtifactFamily::RuntimeDiagnostics,
];

pub const fn byte_domain_for_staging(family: BrowserStagingFamily) -> Option<BrowserByteDomain> {
    match family {
        BrowserStagingFamily::Artifact(WebArtifactFamily::Source) => {
            Some(BrowserByteDomain::CdpDecodedBody)
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource) => {
            Some(BrowserByteDomain::DecodedSourceUtf8)
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom) => {
            Some(BrowserByteDomain::RenderedDomUtf8)
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree) => {
            Some(BrowserByteDomain::AccessibilityJsonUtf8)
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
            Some(BrowserByteDomain::ScreenshotPng)
        }
        BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics) => {
            Some(BrowserByteDomain::RuntimeDiagnosticUtf8)
        }
        BrowserStagingFamily::SourceRepresentation | BrowserStagingFamily::Artifact(_) => None,
    }
}

pub const fn byte_domain_for(family: WebArtifactFamily) -> Option<BrowserByteDomain> {
    byte_domain_for_staging(match family {
        WebArtifactFamily::SourceRepresentation => BrowserStagingFamily::SourceRepresentation,
        family => BrowserStagingFamily::Artifact(family),
    })
}

pub(super) const fn family_index(family: WebArtifactFamily) -> usize {
    match family {
        WebArtifactFamily::Source
        | WebArtifactFamily::SourceRepresentation
        | WebArtifactFamily::DecodedSource => 0,
        WebArtifactFamily::RenderedDom => 1,
        WebArtifactFamily::AccessibilityTree => 2,
        WebArtifactFamily::Network => 3,
        WebArtifactFamily::Cookies => 4,
        WebArtifactFamily::Storage => 5,
        WebArtifactFamily::Layout => 6,
        WebArtifactFamily::Visual => 7,
        WebArtifactFamily::RuntimeDiagnostics => 8,
    }
}

pub(super) fn profile_capability(
    profile: &WebProviderCapabilityProfile,
    family: WebArtifactFamily,
) -> &ArtifactCapability {
    match family {
        WebArtifactFamily::Source => profile.artifacts().source(),
        WebArtifactFamily::RenderedDom => profile.artifacts().rendered_dom(),
        WebArtifactFamily::AccessibilityTree => profile.artifacts().accessibility_tree(),
        WebArtifactFamily::Network => profile.artifacts().network(),
        WebArtifactFamily::Cookies => profile.artifacts().cookies(),
        WebArtifactFamily::Storage => profile.artifacts().storage(),
        WebArtifactFamily::Layout => profile.artifacts().layout(),
        WebArtifactFamily::Visual => profile.artifacts().visual(),
        WebArtifactFamily::RuntimeDiagnostics => profile.artifacts().runtime_diagnostics(),
        WebArtifactFamily::SourceRepresentation | WebArtifactFamily::DecodedSource => {
            profile.artifacts().source()
        }
    }
}

pub const fn request_for(
    artifacts: WebArtifactRequestSet,
    family: WebArtifactFamily,
) -> ArtifactRequest {
    match family {
        WebArtifactFamily::Source
        | WebArtifactFamily::SourceRepresentation
        | WebArtifactFamily::DecodedSource => artifacts.source(),
        WebArtifactFamily::RenderedDom => artifacts.rendered_dom(),
        WebArtifactFamily::AccessibilityTree => artifacts.accessibility_tree(),
        WebArtifactFamily::Network => artifacts.network(),
        WebArtifactFamily::Cookies => artifacts.cookies(),
        WebArtifactFamily::Storage => artifacts.storage(),
        WebArtifactFamily::Layout => artifacts.layout(),
        WebArtifactFamily::Visual => artifacts.visual(),
        WebArtifactFamily::RuntimeDiagnostics => artifacts.runtime_diagnostics(),
    }
}
