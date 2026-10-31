//! Per-representation preparation and reading limits.
use super::{Budget, Limits, SurfaceError};
use crate::documents::{Document, DocumentClass};
use serde::{Deserialize, Serialize};

/// Independent source-tree and response limits for one evidence representation.
///
/// Preparation rejects oversized supplied documents. Live producers may return a
/// smaller, explicitly partial tree instead; a response budget never implies completeness.
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DocumentPolicy {
    /// Maximum retained serialized document bytes, before indexing.
    pub max_bytes: usize,
    /// Maximum tree depth, counting the root as level zero.
    pub max_depth: usize,
    /// Maximum indexed nodes, including structural and scalar nodes.
    pub max_nodes: usize,
    /// Maximum automatically expanded depth in an overview.
    pub overview_depth: usize,
    /// Maximum serialized read-result bytes, independent of capture retention.
    pub response_bytes: usize,
}
impl Default for DocumentPolicy {
    fn default() -> Self {
        Self {
            max_bytes: 8 * 1024 * 1024,
            max_depth: 96,
            max_nodes: 100_000,
            overview_depth: 6,
            response_bytes: 65_536,
        }
    }
}
impl DocumentPolicy {
    pub(super) const fn maximum_limits() -> Limits {
        Limits {
            input_bytes: 128 * 1024 * 1024,
            depth: 256,
            nodes: 200_000,
            overview_depth: 6,
        }
    }
    /// Checks finite bounds before acquiring resources or interpreting evidence.
    pub(super) fn validate(self) -> Result<(), SurfaceError> {
        let maximum = Self::maximum_limits();
        if !(1..=maximum.input_bytes).contains(&self.max_bytes)
            || !(1..=maximum.depth).contains(&self.max_depth)
            || !(1..=maximum.nodes).contains(&self.max_nodes)
            || self.overview_depth > maximum.depth
            || !(512..=65_536).contains(&self.response_bytes)
        {
            return Err(SurfaceError::Invalid(
                "invalid document policy limits".into(),
            ));
        }
        Ok(())
    }
    /// Converts checked policy into the existing immutable index limits.
    pub fn limits(self) -> Result<Limits, SurfaceError> {
        self.validate()?;
        Ok(Limits {
            input_bytes: self.max_bytes,
            depth: self.max_depth,
            nodes: self.max_nodes,
            overview_depth: self.overview_depth.min(self.max_depth),
        })
    }
    pub(super) fn budget(self, requested: Budget) -> Budget {
        Budget {
            bytes: requested.bytes.min(self.response_bytes),
            items: requested.items,
        }
    }
}

/// SDK policy selecting separate bounds for each document/evidence type.
///
/// Network evidence is a JSON document with an explicitly bounded observation
/// interval; its policy remains independent of ordinary JSON documents.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DocumentPolicies {
    /// Rendered DOM capture, indexing and response bounds.
    pub dom: DocumentPolicy,
    /// Browser-computed accessibility tree bounds.
    pub ax: DocumentPolicy,
    /// Source HTML indexing and response bounds.
    pub html: DocumentPolicy,
    /// Source XML indexing and response bounds.
    pub xml: DocumentPolicy,
    /// Source JSON indexing and response bounds.
    pub json: DocumentPolicy,
    /// Plain text indexing and response bounds.
    pub text: DocumentPolicy,
    /// Network event-document indexing and response bounds.
    pub network: DocumentPolicy,
}
impl Default for DocumentPolicies {
    fn default() -> Self {
        Self {
            dom: DocumentPolicy {
                max_bytes: 32 * 1024 * 1024,
                max_nodes: 200_000,
                ..DocumentPolicy::default()
            },
            ax: DocumentPolicy {
                max_nodes: 100_000,
                ..DocumentPolicy::default()
            },
            html: DocumentPolicy::default(),
            xml: DocumentPolicy::default(),
            json: DocumentPolicy::default(),
            text: DocumentPolicy::default(),
            network: DocumentPolicy::default(),
        }
    }
}
impl DocumentPolicies {
    /// Validates every representation, including types not yet captured.
    pub(super) fn validate(&self) -> Result<(), SurfaceError> {
        for policy in [
            self.dom,
            self.ax,
            self.html,
            self.xml,
            self.json,
            self.text,
            self.network,
        ] {
            policy.validate()?;
        }
        if self.ax.max_nodes > 100_000 {
            return Err(SurfaceError::Invalid(
                "AX supports at most 100000 nodes".into(),
            ));
        }
        Ok(())
    }
    /// Selects the policy matching an immutable document's declared profile.
    pub(super) fn for_document(&self, document: &Document) -> DocumentPolicy {
        match document.class() {
            DocumentClass::RenderedDom => self.dom,
            DocumentClass::AccessibilityTree => self.ax,
            DocumentClass::SourceHtml => self.html,
            DocumentClass::SourceXml => self.xml,
            DocumentClass::SourceJson => {
                if serde_json::from_slice::<serde_json::Value>(document.bytes())
                    .ok()
                    .and_then(|v| {
                        v.get("schema")
                            .and_then(serde_json::Value::as_str)
                            .map(str::to_owned)
                    })
                    .as_deref()
                    == Some("yosoi.network.v1")
                {
                    self.network
                } else {
                    self.json
                }
            }
            DocumentClass::SourceText => self.text,
        }
    }
}
