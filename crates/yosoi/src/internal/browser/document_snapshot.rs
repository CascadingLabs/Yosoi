//! Bounded rendered-DOM and raw accessibility observations.
//!
//! Raw payload bytes remain provider-native. Compact document/AX outlines are
//! presentation projections and are not stored in these authoritative results.

use std::{
    fmt,
    result::Result as StdResult,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::accessibility::AxNode;
use crate::internal::types::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema,
    BrowserFrameId, ByteCount, ByteLimit, ByteLimitError,
};
use serde::Serialize;

use crate::internal::browser::{
    BrowserBudgetScope, BrowserByteDomain, BrowserByteReport, BrowserByteReportError,
    BrowserByteSpec, BrowserLimitScope, BrowserPayloadUnavailableReason, ProtectedUrl,
};

/// Capture-local navigation epoch for document correlation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum DocumentEpoch {
    Known(u64),
    /// The page was adopted from an attached browser and has not subsequently
    /// been navigated by this VoidCrawl handle.
    UnavailableForAttachedPage,
}

/// Document/frame scope of a snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DocumentFrameScope {
    TopLevel,
    Frame { url: Option<ProtectedUrl> },
}

/// Context needed to relate DOM, AX, layout, and visual observations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocumentScope {
    /// Opaque capture-local identity allocated from the provider frame id.
    pub frame_id: BrowserFrameId,
    pub epoch: DocumentEpoch,
    pub frame: DocumentFrameScope,
    pub url: Option<ProtectedUrl>,
}

/// Complete, truncated, or unavailable snapshot payload state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotState {
    Complete,
    Truncated,
    Unavailable { reason: SnapshotUnavailableReason },
}

/// Why a requested DOM or AX payload was unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotUnavailableReason {
    BrowserDidNotReport,
    FrameUnavailable,
    SerializationFailed,
}

/// Bounded rendered-DOM serialization.
#[derive(Clone, PartialEq, Eq)]
pub struct RenderedDomSnapshot {
    pub scope: DocumentScope,
    pub generated_at_unix_ms: Option<u64>,
    pub state: SnapshotState,
    pub retained_bytes: usize,
    pub complete_bytes: Option<usize>,
    payload: Arc<[u8]>,
    byte_spec: BrowserByteSpec,
}

impl RenderedDomSnapshot {
    pub fn bytes(&self) -> &[u8] {
        &self.payload
    }

    /// Canonical accounting for the rendered DOM UTF-8 payload.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::RenderedDomUtf8,
            Some(self.byte_spec),
            ByteCount::try_from_usize(self.complete_bytes.unwrap_or(self.retained_bytes))?,
            ByteCount::try_from_usize(self.retained_bytes)?,
        )
    }
}

impl fmt::Debug for RenderedDomSnapshot {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RenderedDomSnapshot")
            .field("scope", &self.scope)
            .field("generated_at_unix_ms", &self.generated_at_unix_ms)
            .field("state", &self.state)
            .field("retained_bytes", &self.retained_bytes)
            .field("complete_bytes", &self.complete_bytes)
            .finish_non_exhaustive()
    }
}

/// Bounds for one accessibility snapshot.
#[derive(Debug, Clone, Copy)]
pub struct AccessibilitySnapshotOptions {
    pub depth: Option<i64>,
    pub max_nodes: usize,
    pub max_bytes: usize,
}

impl Default for AccessibilitySnapshotOptions {
    fn default() -> Self {
        Self {
            depth: None,
            max_nodes: 10_000,
            max_bytes: 8 * 1024 * 1024,
        }
    }
}

/// Bounded, explicitly schema-bound CDP accessibility-tree serialization.
#[derive(Clone, PartialEq, Eq)]
pub struct AccessibilitySnapshot {
    pub payload_schema: BrowserAccessibilitySchema,
    pub payload_version: u32,
    pub capture_mode: BrowserAccessibilityCaptureMode,
    pub ignored_node_policy: BrowserAccessibilityIgnoredNodes,
    pub scope: DocumentScope,
    pub generated_at_unix_ms: Option<u64>,
    pub state: SnapshotState,
    pub requested_depth: Option<i64>,
    pub nodes_observed: usize,
    pub nodes_retained: usize,
    pub retained_bytes: usize,
    pub complete_bytes: Option<usize>,
    payload: Arc<[u8]>,
    byte_spec: BrowserByteSpec,
}

impl AccessibilitySnapshot {
    pub fn bytes(&self) -> &[u8] {
        &self.payload
    }

    /// Canonical accounting for the accessibility JSON UTF-8 payload.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        if matches!(self.state, SnapshotState::Unavailable { .. }) {
            return BrowserByteReport::unavailable_with_spec(
                BrowserByteDomain::AccessibilityJsonUtf8,
                Some(self.byte_spec),
                BrowserPayloadUnavailableReason::ProviderDidNotReport,
            );
        }
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::AccessibilityJsonUtf8,
            Some(self.byte_spec),
            ByteCount::try_from_usize(self.complete_bytes.unwrap_or(self.retained_bytes))?,
            ByteCount::try_from_usize(self.retained_bytes)?,
        )
    }
}

impl fmt::Debug for AccessibilitySnapshot {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AccessibilitySnapshot")
            .field("scope", &self.scope)
            .field("payload_schema", &self.payload_schema)
            .field("payload_version", &self.payload_version)
            .field("capture_mode", &self.capture_mode)
            .field("ignored_node_policy", &self.ignored_node_policy)
            .field("generated_at_unix_ms", &self.generated_at_unix_ms)
            .field("state", &self.state)
            .field("requested_depth", &self.requested_depth)
            .field("nodes_observed", &self.nodes_observed)
            .field("nodes_retained", &self.nodes_retained)
            .field("retained_bytes", &self.retained_bytes)
            .field("complete_bytes", &self.complete_bytes)
            .finish_non_exhaustive()
    }
}

pub(in crate::internal::browser) fn rendered_dom(
    html: String,
    scope: DocumentScope,
    max_bytes: usize,
) -> StdResult<RenderedDomSnapshot, ByteLimitError> {
    let byte_limit = ByteLimit::try_from(max_bytes)?;
    let complete_bytes = html.len();
    let retained_bytes = (0..=complete_bytes.min(max_bytes))
        .rev()
        .find(|&index| html.is_char_boundary(index))
        .unwrap_or(0);
    let bytes = html.into_bytes();
    Ok(RenderedDomSnapshot {
        scope,
        generated_at_unix_ms: unix_millis(),
        state: if retained_bytes == complete_bytes {
            SnapshotState::Complete
        } else {
            SnapshotState::Truncated
        },
        retained_bytes,
        complete_bytes: Some(complete_bytes),
        payload: Arc::from(bytes.get(..retained_bytes).unwrap_or(&bytes).to_vec()),
        byte_spec: BrowserByteSpec::new(
            BrowserByteDomain::RenderedDomUtf8,
            byte_limit,
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ),
    })
}

pub(in crate::internal::browser) fn accessibility(
    nodes: &[AxNode],
    scope: DocumentScope,
    options: AccessibilitySnapshotOptions,
) -> StdResult<AccessibilitySnapshot, ByteLimitError> {
    let byte_limit = ByteLimit::try_from(options.max_bytes)?;
    if options.max_bytes < 2 {
        return Ok(unavailable_accessibility(
            scope,
            options,
            SnapshotUnavailableReason::SerializationFailed,
        ));
    }
    let nodes_observed = nodes.len();
    let Ok(complete) = serde_json::to_vec(nodes) else {
        return Ok(unavailable_accessibility(
            scope,
            options,
            SnapshotUnavailableReason::SerializationFailed,
        ));
    };
    let complete_bytes = complete.len();
    let mut payload = Vec::with_capacity(options.max_bytes.min(complete_bytes));
    payload.push(b'[');
    let mut nodes_retained = 0usize;
    for node in nodes.iter().take(options.max_nodes) {
        let Ok(encoded) = serde_json::to_vec(node) else {
            return Ok(unavailable_accessibility(
                scope,
                options,
                SnapshotUnavailableReason::SerializationFailed,
            ));
        };
        let separator = usize::from(nodes_retained > 0);
        let Some(candidate_len) = payload
            .len()
            .checked_add(separator)
            .and_then(|value| value.checked_add(encoded.len()))
            .and_then(|value| value.checked_add(1))
        else {
            break;
        };
        if candidate_len > options.max_bytes {
            break;
        }
        if separator == 1 {
            payload.push(b',');
        }
        payload.extend_from_slice(&encoded);
        nodes_retained = nodes_retained.saturating_add(1);
    }
    payload.push(b']');
    let truncated = nodes_retained < nodes_observed;
    Ok(AccessibilitySnapshot {
        payload_schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
        payload_version: 1,
        capture_mode: if options.depth.is_some() {
            BrowserAccessibilityCaptureMode::DepthLimited
        } else {
            BrowserAccessibilityCaptureMode::FullTree
        },
        ignored_node_policy: BrowserAccessibilityIgnoredNodes::Included,
        scope,
        generated_at_unix_ms: unix_millis(),
        state: if truncated {
            SnapshotState::Truncated
        } else {
            SnapshotState::Complete
        },
        requested_depth: options.depth,
        nodes_observed,
        nodes_retained,
        retained_bytes: payload.len(),
        complete_bytes: Some(complete_bytes),
        payload: Arc::from(payload),
        byte_spec: BrowserByteSpec::new(
            BrowserByteDomain::AccessibilityJsonUtf8,
            byte_limit,
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ),
    })
}

pub(in crate::internal::browser) fn unavailable_accessibility(
    scope: DocumentScope,
    options: AccessibilitySnapshotOptions,
    reason: SnapshotUnavailableReason,
) -> AccessibilitySnapshot {
    AccessibilitySnapshot {
        payload_schema: BrowserAccessibilitySchema::ChromiumCdpAxNodeJson,
        payload_version: 1,
        capture_mode: if options.depth.is_some() {
            BrowserAccessibilityCaptureMode::DepthLimited
        } else {
            BrowserAccessibilityCaptureMode::FullTree
        },
        ignored_node_policy: BrowserAccessibilityIgnoredNodes::Included,
        scope,
        generated_at_unix_ms: unix_millis(),
        state: SnapshotState::Unavailable { reason },
        requested_depth: options.depth,
        nodes_observed: 0,
        nodes_retained: 0,
        retained_bytes: 0,
        complete_bytes: None,
        payload: Arc::from([]),
        byte_spec: BrowserByteSpec::new(
            BrowserByteDomain::AccessibilityJsonUtf8,
            ByteLimit::try_from(options.max_bytes).unwrap_or(ByteLimit::one()),
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ),
    }
}

fn unix_millis() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[allow(clippy::expect_used)]
    fn rendered_dom_truncation_is_exact() {
        let snapshot = rendered_dom(
            "abcdef".into(),
            DocumentScope {
                frame_id: BrowserFrameId(1),
                epoch: DocumentEpoch::Known(1),
                frame: DocumentFrameScope::TopLevel,
                url: None,
            },
            3,
        )
        .expect("positive limit");
        assert_eq!(snapshot.state, SnapshotState::Truncated);
        assert_eq!(snapshot.bytes(), b"abc");
        assert_eq!(snapshot.retained_bytes, 3);
        assert_eq!(snapshot.complete_bytes, Some(6));
    }

    #[test]
    #[allow(clippy::expect_used)]
    fn accessibility_never_exceeds_a_too_small_json_bound() {
        let snapshot = accessibility(
            &[],
            DocumentScope {
                frame_id: BrowserFrameId(1),
                epoch: DocumentEpoch::Known(1),
                frame: DocumentFrameScope::TopLevel,
                url: None,
            },
            AccessibilitySnapshotOptions {
                depth: None,
                max_nodes: 1,
                max_bytes: 1,
            },
        )
        .expect("positive byte limit");
        assert!(matches!(snapshot.state, SnapshotState::Unavailable { .. }));
        assert_eq!(snapshot.bytes(), b"");
        assert_eq!(snapshot.retained_bytes, 0);
        assert_eq!(snapshot.byte_spec.limit().get(), 1);
    }

    #[test]
    fn unavailable_accessibility_has_no_payload() {
        let snapshot = unavailable_accessibility(
            DocumentScope {
                frame_id: BrowserFrameId(1),
                epoch: DocumentEpoch::UnavailableForAttachedPage,
                frame: DocumentFrameScope::TopLevel,
                url: None,
            },
            AccessibilitySnapshotOptions::default(),
            SnapshotUnavailableReason::BrowserDidNotReport,
        );
        assert_eq!(snapshot.bytes(), b"");
        assert_eq!(snapshot.complete_bytes, None);
    }
}
