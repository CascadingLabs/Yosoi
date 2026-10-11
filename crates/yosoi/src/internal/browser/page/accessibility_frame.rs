use crate::internal::types as yosoi_types;

use super::Page;
use super::document_identity::identity_in_tree;
use super::validation::validate_accessibility_options;
use crate::internal::browser::document_snapshot::AccessibilitySnapshot;
use crate::internal::browser::document_snapshot::AccessibilitySnapshotOptions;
use crate::internal::browser::document_snapshot::DocumentFrameScope;
use crate::internal::browser::document_snapshot::DocumentScope;
use crate::internal::browser::document_snapshot::SnapshotUnavailableReason;
use crate::internal::browser::document_snapshot::accessibility;
use crate::internal::browser::document_snapshot::unavailable_accessibility;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::accessibility::GetFullAxTreeParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::page::GetFrameTreeParams;

impl Page {
    /// Capture one matching frame's raw accessibility tree with explicit
    /// bounds. Missing or ambiguous frame patterns remain typed errors; a
    /// browser that cannot expose the matched frame returns an unavailable
    /// snapshot rather than an observed empty tree.
    pub async fn accessibility_snapshot_in_frame(
        &self,
        frame_url_pattern: &str,
        options: AccessibilitySnapshotOptions,
    ) -> Result<AccessibilitySnapshot> {
        validate_accessibility_options(options)?;
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let before_top = self.top_level_document_identity().await?;
        let before_tree = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFrameTreeParams::default(),
            )
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .result
            .frame_tree;
        let Some(before_frame) = identity_in_tree(&before_tree, &frame_id) else {
            let top = self.scope_for_identity(&before_top, false)?;
            return Ok(unavailable_accessibility(
                DocumentScope {
                    frame_id: self.browser_frame_id(&frame_id)?,
                    epoch: top.epoch,
                    frame: DocumentFrameScope::Frame { url: None },
                    url: top.url,
                },
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            ));
        };
        let nodes = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFullAxTreeParams {
                    depth: options.depth,
                    frame_id: Some(frame_id.clone()),
                },
            )
            .await
            .map(|response| response.result.nodes);
        let after_top = self.top_level_document_identity().await?;
        let after_tree = self
            .inner
            .execute_in_frame_session(frame_id.clone(), session_id, GetFrameTreeParams::default())
            .await
            .map(|response| response.result.frame_tree);
        let after_frame = after_tree
            .as_ref()
            .ok()
            .and_then(|tree| identity_in_tree(tree, &frame_id));
        let top = self.scope_for_identity(&after_top, false)?;
        let scope =
            self.scope_for_frame_identity(after_frame.as_ref().unwrap_or(&before_frame), &top)?;
        if !before_top.same_document(&after_top)
            || !after_frame
                .as_ref()
                .is_some_and(|after| before_frame.same_document(after))
        {
            return Ok(unavailable_accessibility(
                scope,
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            ));
        }
        match nodes {
            Ok(nodes) => {
                accessibility(&nodes, scope, options).map_err(|_| VoidCrawlError::InvalidInput {
                    operation: "accessibility_snapshot",
                    reason: "max_bytes does not fit browser byte accounting",
                })
            }
            Err(_) => Ok(unavailable_accessibility(
                scope,
                options,
                SnapshotUnavailableReason::FrameUnavailable,
            )),
        }
    }

    /// Capture one matching frame's accessibility tree using a validated byte
    /// limit.
    pub async fn accessibility_snapshot_in_frame_with_limit(
        &self,
        frame_url_pattern: &str,
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
        self.accessibility_snapshot_in_frame(
            frame_url_pattern,
            AccessibilitySnapshotOptions {
                depth,
                max_nodes,
                max_bytes,
            },
        )
        .await
    }
}
