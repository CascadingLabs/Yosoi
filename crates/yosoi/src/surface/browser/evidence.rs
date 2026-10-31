//! Native browser evidence representation selection and normalization.
#[cfg(feature = "browser")]
use crate::documents::{Document, DocumentEpoch};
#[cfg(feature = "browser")]
use crate::surface::{DocumentPolicies, DocumentPolicy};
use serde::{Deserialize, Serialize};

/// Independently captured browser evidence. Only DOM references grant candidates
/// for live target validation; AX and network references remain read-only.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserRepresentation {
    /// Current light DOM with live adapter coordinates.
    #[default]
    Dom,
    /// Native Chrome accessibility evidence, with explicit depth-limited coverage.
    Ax,
    /// Chrome network events since the previous network observation or session open.
    Network,
}
/// Descriptor and root address of one immutable browser evidence observation.
/// Captures of different representations are sequential, never an atomic snapshot.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BrowserObservation {
    /// Read capabilities and exact representation schema.
    pub descriptor: super::super::model::Descriptor,
    /// Immutable identity and completeness of this captured view.
    pub observation: super::super::model::Observation,
    /// Producer-issued root address, usable only with this view's observation.
    pub root: super::super::model::Reference,
}
#[cfg(feature = "browser")]
impl BrowserRepresentation {
    /// Selects the independent retention and reading policy for this representation.
    pub(super) const fn policy(self, policies: &DocumentPolicies) -> DocumentPolicy {
        match self {
            Self::Dom => policies.dom,
            Self::Ax => policies.ax,
            Self::Network => policies.network,
        }
    }
}

#[cfg(feature = "browser")]
pub(super) fn accessibility_document(
    id: String,
    epoch: u64,
    nodes: &serde_json::Value,
    policy: DocumentPolicy,
) -> super::super::connection::Result<Document> {
    use crate::internal::engine::browser_document::accessibility::normalize_accessibility;
    use crate::internal::{
        documents::{ResourceBudget, ResourceBudgetValues},
        types::{CaptureOffset, LossExtent},
        web_capture::{
            BrowserAccessibilityCaptureMode, BrowserAccessibilityEvidence,
            BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema, BrowserBudgetScope,
            BrowserByteAccounting, BrowserDocumentEpoch, BrowserDocumentScope, BrowserFrameId,
            BrowserLimitEnforcement,
        },
    };
    use std::io;
    let count = u64::try_from(
        nodes
            .as_array()
            .ok_or_else(|| io::Error::other("AX nodes missing"))?
            .len(),
    )?;
    let observed_bytes = u64::try_from(serde_json::to_vec(nodes)?.len())?;
    let retained = bounded_ax_nodes(nodes, policy)?;
    let retained_count = u64::try_from(retained.len())?;
    let bytes = serde_json::to_vec(&retained)?;
    let len = u64::try_from(bytes.len())?;
    let maximum = u64::try_from(policy.max_bytes)?;
    let depth = i64::try_from(policy.max_depth)?;
    let evidence = BrowserAccessibilityEvidence {
        schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
        schema_version: 1,
        capture_mode: BrowserAccessibilityCaptureMode::DepthLimited,
        requested_depth: Some(depth),
        ignored_nodes: BrowserAccessibilityIgnoredNodes::Included,
        scope: BrowserDocumentScope {
            frame: BrowserFrameId(1),
            epoch: BrowserDocumentEpoch(epoch),
        },
        at: CaptureOffset::from_microseconds(0),
        nodes_observed: count,
        nodes_retained: retained_count,
        nodes_lost: LossExtent::Known(count.saturating_sub(retained_count)),
        bytes: BrowserByteAccounting {
            configured_limit: maximum,
            enforcement: BrowserLimitEnforcement::RetentionAfterProviderMaterialization,
            budget_scope: BrowserBudgetScope::PerPayload,
            observed: observed_bytes,
            retained: len,
            lost: LossExtent::Known(observed_bytes.saturating_sub(len)),
            complete: observed_bytes == len,
        },
        canonical_node_bytes: bytes,
    };
    let budget = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: maximum,
        max_nodes: u64::try_from(policy.max_nodes)?,
        max_selector_visits: 1_000_000,
        max_query_bytes: 4096,
        max_query_steps: 128,
        max_regions: 100_000,
        max_matches: 100_000,
        max_captures: 100_000,
        // Surface/CDP root depth is zero; the Document parser counts root as level one.
        max_depth: u32::try_from(policy.max_depth)?
            .checked_add(1)
            .ok_or_else(|| io::Error::other("AX parser depth overflow"))?,
        max_output_bytes: maximum,
    })?;
    let document = normalize_accessibility(id.clone(), evidence, budget)?;
    Ok(Document::accessibility_tree(
        id,
        DocumentEpoch::try_from(epoch)?,
        document.bytes().to_vec(),
    )?)
}

#[cfg(feature = "browser")]
fn bounded_ax_nodes(
    nodes: &serde_json::Value,
    policy: DocumentPolicy,
) -> super::super::connection::Result<Vec<serde_json::Value>> {
    use serde_json::Value;
    use std::{
        collections::{BTreeMap, BTreeSet},
        io,
    };
    let nodes = nodes
        .as_array()
        .ok_or_else(|| io::Error::other("AX nodes missing"))?;
    let mut by_id = BTreeMap::new();
    let mut roots = Vec::new();
    for node in nodes {
        let id = node
            .get("nodeId")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("AX node lacks identity"))?;
        if let Some(prior) = by_id.insert(id, node) {
            if prior != node {
                return Err(io::Error::other("conflicting AX node identity").into());
            }
            continue;
        }
        if node.get("parentId").is_none_or(Value::is_null) {
            roots.push(id);
        }
    }
    let [root] = roots.as_slice() else {
        return Err(io::Error::other("AX capture requires one native root").into());
    };
    let mut pending = vec![(*root, 0usize)];
    let mut seen = BTreeSet::new();
    let mut retained = Vec::new();
    let mut bytes = 2usize;
    while let Some((id, depth)) = pending.pop() {
        if !seen.insert(id) {
            return Err(io::Error::other("AX tree repeats a child").into());
        }
        let Some(node) = by_id.get(id) else { continue };
        let next_bytes = bytes
            .saturating_add(serde_json::to_vec(node)?.len())
            .saturating_add(usize::from(!retained.is_empty()));
        if retained.len() >= policy.max_nodes || next_bytes > policy.max_bytes {
            break;
        }
        bytes = next_bytes;
        retained.push((*node).clone());
        // Chrome's requested depth may include ignored structural nodes beyond
        // that level. Bound the retained native graph ourselves; do not raise
        // the requested policy to accommodate a deeper provider response.
        if depth < policy.max_depth {
            let children = node
                .get("childIds")
                .map(|value| {
                    value
                        .as_array()
                        .ok_or_else(|| io::Error::other("invalid AX children"))
                })
                .transpose()?;
            if let Some(children) = children {
                let next_depth = depth
                    .checked_add(1)
                    .ok_or_else(|| io::Error::other("AX depth overflow"))?;
                for child in children.iter().rev() {
                    pending.push((
                        child
                            .as_str()
                            .ok_or_else(|| io::Error::other("invalid AX child identity"))?,
                        next_depth,
                    ));
                }
            }
        }
    }
    if retained.is_empty() {
        return Err(io::Error::other("AX byte budget cannot retain the root").into());
    }
    Ok(retained)
}

#[cfg(all(test, feature = "browser"))]
mod tests {
    use super::{DocumentPolicy, accessibility_document};
    use crate::surface::Surface;
    use serde_json::json;
    use std::error::Error;
    #[test]
    #[expect(
        clippy::panic_in_result_fn,
        reason = "Assertions verify the parser depth boundary."
    )]
    fn zero_based_capture_depth_is_translated_to_parser_levels()
    -> Result<(), Box<dyn Error + Send + Sync>> {
        let nodes = json!([
            {"nodeId":"root","ignored":false,"role":{"type":"role","value":"RootWebArea"},"childIds":["button"]},
            {"nodeId":"button","parentId":"root","ignored":false,"role":{"type":"role","value":"button"},"name":{"type":"computedString","value":"Search"},"childIds":["deeper"]},
            {"nodeId":"deeper","parentId":"button","ignored":false,"role":{"type":"role","value":"StaticText"},"name":{"type":"computedString","value":"Search"},"childIds":[]}
        ]);
        let policy = DocumentPolicy {
            max_depth: 1,
            ..DocumentPolicy::default()
        };
        let document = accessibility_document("depth".into(), 1, &nodes, policy)?;
        let index = Surface::with_limits(&document, policy.limits()?)?;
        assert_eq!(index.node_count(), 2);
        assert!(!index.coverage().complete);
        Ok(())
    }
}
