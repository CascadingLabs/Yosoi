use crate::internal::types as yosoi_types;
use crate::internal::web_capture as yosoi_web_capture;

use crate::internal::web_capture::{CaptureOffset, WebArtifactFamily};
use thiserror::Error;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserByteLayer {
    DecodedResponseBody,
    DecodedSourceUtf8,
    SourceRepresentation,
    RenderedDomUtf8,
    AccessibilityTreeUtf8,
    Png,
    RuntimeDiagnosticsUtf8,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserStagingFamily {
    Artifact(WebArtifactFamily),
    SourceRepresentation,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserArtifactMapping {
    family: BrowserStagingFamily,
    layer: BrowserByteLayer,
    snapshot: Option<BrowserSnapshotObservation>,
    source_binding: Option<yosoi_types::Sha256Digest>,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserSnapshotObservation {
    family: BrowserStagingFamily,
    pub scope: yosoi_web_capture::BrowserDocumentScope,
    pub at: CaptureOffset,
    pub accessibility_nodes: Option<u32>,
    pub accessibility_depth: Option<i64>,
    pub accessibility_ignored_nodes_included: Option<bool>,
    pub visual: Option<yosoi_web_capture::BrowserVisualFact>,
}
impl BrowserSnapshotObservation {
    const fn plain(
        family: WebArtifactFamily,
        scope: yosoi_web_capture::BrowserDocumentScope,
        at: CaptureOffset,
    ) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(family),
            scope,
            at,
            accessibility_nodes: None,
            accessibility_depth: None,
            accessibility_ignored_nodes_included: None,
            visual: None,
        }
    }
    pub const fn source(scope: yosoi_web_capture::BrowserDocumentScope, at: CaptureOffset) -> Self {
        Self::plain(WebArtifactFamily::Source, scope, at)
    }
    pub const fn rendered_dom(
        scope: yosoi_web_capture::BrowserDocumentScope,
        at: CaptureOffset,
    ) -> Self {
        Self::plain(WebArtifactFamily::RenderedDom, scope, at)
    }
    pub const fn accessibility_tree(
        scope: yosoi_web_capture::BrowserDocumentScope,
        at: CaptureOffset,
        nodes: u32,
    ) -> Self {
        Self::accessibility_tree_descriptor(scope, at, nodes, None, true)
    }
    pub const fn accessibility_tree_descriptor(
        scope: yosoi_web_capture::BrowserDocumentScope,
        at: CaptureOffset,
        nodes: u32,
        depth: Option<i64>,
        ignored_nodes_included: bool,
    ) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
            scope,
            at,
            accessibility_nodes: Some(nodes),
            accessibility_depth: depth,
            accessibility_ignored_nodes_included: Some(ignored_nodes_included),
            visual: None,
        }
    }
    pub const fn visual(scope: yosoi_web_capture::BrowserDocumentScope, at: CaptureOffset) -> Self {
        Self::plain(WebArtifactFamily::Visual, scope, at)
    }
    pub const fn visual_fact(fact: yosoi_web_capture::BrowserVisualFact) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
            scope: fact.scope,
            at: fact.at,
            accessibility_nodes: None,
            accessibility_depth: None,
            accessibility_ignored_nodes_included: None,
            visual: Some(fact),
        }
    }
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("staging family and representation layer do not match")]
pub struct BrowserMappingError;
impl BrowserArtifactMapping {
    pub fn new(
        family: BrowserStagingFamily,
        layer: BrowserByteLayer,
    ) -> Result<Self, BrowserMappingError> {
        let valid = matches!(
            (family, layer),
            (
                BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
                BrowserByteLayer::DecodedResponseBody
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
                BrowserByteLayer::DecodedSourceUtf8
            ) | (
                BrowserStagingFamily::SourceRepresentation,
                BrowserByteLayer::SourceRepresentation
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
                BrowserByteLayer::RenderedDomUtf8
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
                BrowserByteLayer::AccessibilityTreeUtf8
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
                BrowserByteLayer::Png
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics),
                BrowserByteLayer::RuntimeDiagnosticsUtf8
            )
        );
        if !valid {
            return Err(BrowserMappingError);
        }
        Ok(Self {
            family,
            layer,
            snapshot: None,
            source_binding: None,
        })
    }
    pub fn derived_from_source(mut self, source: &[u8]) -> Self {
        self.source_binding = Some(yosoi_types::Sha256Digest::digest(source));
        self
    }
    pub const fn source_binding(self) -> Option<yosoi_types::Sha256Digest> {
        self.source_binding
    }
    pub fn with_snapshot(
        mut self,
        snapshot: BrowserSnapshotObservation,
    ) -> Result<Self, BrowserMappingError> {
        if snapshot.family != self.family
            || matches!(self.family, BrowserStagingFamily::SourceRepresentation)
        {
            return Err(BrowserMappingError);
        }
        self.snapshot = Some(snapshot);
        Ok(self)
    }
    pub const fn snapshot(self) -> Option<BrowserSnapshotObservation> {
        self.snapshot
    }
    pub const fn family(self) -> BrowserStagingFamily {
        self.family
    }
    pub const fn layer(self) -> BrowserByteLayer {
        self.layer
    }
}
