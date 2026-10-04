use super::Page;
use super::validation::validate_accessibility_options;
use crate::ax::compact_outline;
use crate::document_snapshot::AccessibilitySnapshot;
use crate::document_snapshot::AccessibilitySnapshotOptions;
use crate::document_snapshot::SnapshotUnavailableReason;
use crate::document_snapshot::accessibility;
use crate::document_snapshot::unavailable_accessibility;
use crate::error::Result;
use crate::error::VoidCrawlError;
use chromiumoxide::cdp::browser_protocol::accessibility::AxNode;
use chromiumoxide::cdp::browser_protocol::accessibility::GetFullAxTreeParams;
use chromiumoxide::cdp::browser_protocol::accessibility::QueryAxTreeParams;
use chromiumoxide::cdp::browser_protocol::dom::GetDocumentParams;
use chromiumoxide::cdp::browser_protocol::page::FrameId;
use serde_json::Value;

impl Page {
    /// Fetch the browser-computed accessibility (AX) tree for the root frame.
    ///
    /// Wraps CDP `Accessibility.getFullAXTree`. The result is the raw,
    /// browser-computed semantic view assistive tech sees: a **flat JSON
    /// array of nodes** linked by `childIds`/`parentId`, each carrying
    /// `role`, computed accessible `name`, `properties` (state like
    /// `focusable`/`expanded`), and `backendDOMNodeId` (the bridge back to
    /// the DOM). Implicit roles are resolved and `aria-hidden`/`display:none`
    /// nodes are pruned, so this is far more redesign-durable than markup.
    ///
    /// The tree only reflects real content once JavaScript has rendered the
    /// page — call it after navigation has settled.
    ///
    /// `depth` bounds how far descendants are walked; `None` returns the
    /// whole tree. Nodes are returned verbatim from CDP (no reshaping) so
    /// callers can address into them however they like.
    pub async fn get_full_ax_tree(&self, depth: Option<i64>) -> Result<Value> {
        let nodes = self.full_ax_nodes(depth, None).await?;
        serde_json::to_value(&nodes).map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Capture the top-level raw accessibility tree with explicit bounds.
    pub async fn accessibility_snapshot(
        &self,
        options: AccessibilitySnapshotOptions,
    ) -> Result<AccessibilitySnapshot> {
        validate_accessibility_options(options)?;
        for attempt in 0..2 {
            let before = self.top_level_document_identity().await?;
            let nodes = self.full_ax_nodes(options.depth, None).await?;
            let after = self.top_level_document_identity().await?;
            if before.same_document(&after) {
                let scope = self.scope_for_identity(&after, false)?;
                return accessibility(&nodes, scope, options).map_err(|_| {
                    VoidCrawlError::InvalidInput {
                        operation: "accessibility_snapshot",
                        reason: "max_bytes does not fit browser byte accounting",
                    }
                });
            }
            self.observe_document_identity(&after, false)?;
            if attempt == 1 {
                let scope = self.scope_for_identity(&after, false)?;
                return Ok(unavailable_accessibility(
                    scope,
                    options,
                    SnapshotUnavailableReason::BrowserDidNotReport,
                ));
            }
        }
        Err(VoidCrawlError::PageError(
            "document changed during accessibility capture".into(),
        ))
    }

    /// Capture the top-level accessibility tree using a validated byte limit.
    pub async fn accessibility_snapshot_with_limit(
        &self,
        depth: Option<i64>,
        max_nodes: usize,
        max_bytes: yosoi_types::ByteLimit,
    ) -> Result<AccessibilitySnapshot> {
        let max_bytes = max_bytes
            .as_usize()
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "accessibility_snapshot",
                reason: "max_bytes does not fit in usize",
            })?;
        self.accessibility_snapshot(AccessibilitySnapshotOptions {
            depth,
            max_nodes,
            max_bytes,
        })
        .await
    }

    pub(super) async fn full_ax_nodes(
        &self,
        depth: Option<i64>,
        frame_id: Option<FrameId>,
    ) -> Result<Vec<AxNode>> {
        let params = GetFullAxTreeParams { depth, frame_id };
        let response = if let Some(frame_id) = params.frame_id.clone() {
            let session_id = self
                .inner
                .frame_session(frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{frame_id:?}")))?;
            self.inner
                .execute_in_frame_session(frame_id, session_id, params)
                .await
        } else {
            self.inner.execute(params).await
        }
        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(response.result.nodes)
    }

    /// Fetch the AX tree and render it as a compact, indented `role "name"`
    /// outline — the readable view, with text-noise and hidden nodes pruned.
    /// See [`crate::ax::compact_outline`] for the raw-nodes → string helper.
    pub async fn ax_tree_outline(&self, depth: Option<i64>) -> Result<String> {
        let tree = self.get_full_ax_tree(depth).await?;
        let nodes = tree.as_array().map_or(&[][..], Vec::as_slice);
        Ok(compact_outline(nodes))
    }

    /// Query the accessibility tree for nodes matching `role` and/or the
    /// computed accessible `name`, rooted at the document.
    ///
    /// Wraps CDP `Accessibility.queryAXTree`. Name matching is exact (the
    /// browser's computed accessible name). Returns the matching nodes as
    /// raw CDP JSON — the AX analogue of `query_selector_all`, but addressing
    /// by semantics rather than markup. Passing neither `role` nor `name`
    /// returns every node under the root.
    pub async fn query_ax_tree(&self, role: Option<&str>, name: Option<&str>) -> Result<Value> {
        let nodes = self.query_ax_nodes(role, name).await?;
        serde_json::to_value(&nodes).map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Internal: run `Accessibility.queryAXTree` rooted at the document and
    /// return the typed matches.
    pub(super) async fn query_ax_nodes(
        &self,
        role: Option<&str>,
        name: Option<&str>,
    ) -> Result<Vec<AxNode>> {
        let doc = self
            .inner
            .execute(GetDocumentParams::default())
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let params = QueryAxTreeParams {
            node_id: Some(doc.result.root.node_id),
            accessible_name: name.map(str::to_string),
            role: role.map(str::to_string),
            ..Default::default()
        };
        let resp = self
            .inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(resp.result.nodes)
    }
}
