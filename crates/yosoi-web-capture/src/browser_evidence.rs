//! Owned, capture-local structured evidence; identifiers are not durable artifact IDs.
use std::fmt;

use crate::{CaptureOffset, LossExtent};
use serde::{Serialize, de::Error as _};
use thiserror::Error;
pub use yosoi_types::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema,
    BrowserDocumentEpoch, BrowserFrameId, BrowserResourceId, BrowserResourceOutcome,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserDocumentScope {
    pub frame: BrowserFrameId,
    pub epoch: BrowserDocumentEpoch,
}
#[derive(Clone, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserResourceFact {
    pub id: BrowserResourceId,
    pub redirect_from: Option<BrowserResourceId>,
    pub scope: Option<BrowserDocumentScope>,
    pub url: Option<crate::ResolvedWebUrl>,
    pub status: Option<u16>,
    pub outcome: BrowserResourceOutcome,
    pub from_cache: bool,
    pub from_service_worker: bool,
    /// Provider-reported transfer metric, never a retained body extent.
    pub encoded_data_length: Option<u64>,
}

impl fmt::Debug for BrowserResourceFact {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserResourceFact")
            .field("id", &self.id)
            .field("redirect_from", &self.redirect_from)
            .field("scope", &self.scope)
            .field("has_url", &self.url.is_some())
            .field("status", &self.status)
            .field("outcome", &self.outcome)
            .field("from_cache", &self.from_cache)
            .field("from_service_worker", &self.from_service_worker)
            .field("encoded_data_length", &self.encoded_data_length)
            .finish()
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
/// Durable observation classification, distinct from provider receipt enums
/// whose authority and established serialized spelling differ.
pub enum BrowserObservationKind {
    DocumentRequestStarted,
    ResourceRequestStarted,
    ResponseReceived,
    RequestFinished,
    RequestFailed,
    ConsoleApiCalled,
    RuntimeExceptionThrown,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserObservationFact {
    pub sequence: u64,
    pub at: CaptureOffset,
    pub kind: BrowserObservationKind,
    pub resource: Option<BrowserResourceId>,
}
#[derive(Clone, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserRedirectFact {
    pub from: BrowserResourceId,
    pub to: BrowserResourceId,
    pub status: Option<u16>,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserExtraInfoEvidence {
    UnavailableInCurrentClient,
}
#[derive(Clone, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserMainDocumentFact {
    pub resource: BrowserResourceId,
    pub url: Option<crate::ResolvedWebUrl>,
    pub status: Option<u16>,
    pub headers: Vec<(String, String)>,
    pub mime_type: Option<String>,
    pub from_cache: bool,
    pub from_service_worker: bool,
}

impl fmt::Debug for BrowserMainDocumentFact {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserMainDocumentFact")
            .field("resource", &self.resource)
            .field("has_url", &self.url.is_some())
            .field("status", &self.status)
            .field("header_count", &self.headers.len())
            .field("has_mime_type", &self.mime_type.is_some())
            .field("from_cache", &self.from_cache)
            .field("from_service_worker", &self.from_service_worker)
            .finish()
    }
}
/// Integer micro-CSS-pixel geometry avoids nonfinite floating-point values.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserLayoutRect {
    pub x_micro_css: i64,
    pub y_micro_css: i64,
    pub width_micro_css: u64,
    pub height_micro_css: u64,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserLayoutFact {
    pub scope: BrowserDocumentScope,
    pub at: CaptureOffset,
    pub layout_viewport: BrowserLayoutRect,
    pub visual_viewport: BrowserLayoutRect,
    pub content: BrowserLayoutRect,
    pub device_scale_micro: Option<u64>,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
/// Durable visual artifact format; provider-native visual receipt enums keep
/// their separately frozen serialized spelling.
pub enum BrowserVisualFormat {
    Png,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserVisualLayoutCorrelation {
    SameDocumentEpochOnly,
    Unavailable,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserVisualFact {
    pub scope: BrowserDocumentScope,
    pub at: CaptureOffset,
    pub format: BrowserVisualFormat,
    pub width_pixels: u32,
    pub height_pixels: u32,
    pub viewport_width_css: u32,
    pub viewport_height_css: u32,
    pub scroll_x_micro_css: i64,
    pub scroll_y_micro_css: i64,
    pub device_scale_micro: u64,
    pub layout_correlation: BrowserVisualLayoutCorrelation,
    pub paired_layout_at: Option<CaptureOffset>,
}
/// Durable browser-only context required to interpret raw artifact payload bytes offline.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserArtifactContext {
    DocumentSnapshot {
        scope: BrowserDocumentScope,
        captured_at: CaptureOffset,
    },
    Visual(BrowserVisualFact),
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserConsoleLevel {
    Log,
    Debug,
    Info,
    Error,
    Warning,
    Dir,
    DirXml,
    Table,
    Trace,
    Clear,
    StartGroup,
    StartGroupCollapsed,
    EndGroup,
    Assert,
    Profile,
    ProfileEnd,
    Count,
    TimeEnd,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserRuntimeDiagnosticKind {
    Console { level: BrowserConsoleLevel },
    Exception,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserRuntimeValueType {
    RedactedText,
}
#[derive(Clone, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserRuntimeDiagnosticFact {
    pub sequence: u64,
    pub at: CaptureOffset,
    pub kind: BrowserRuntimeDiagnosticKind,
    pub value_type: BrowserRuntimeValueType,
    pub complete_utf8_bytes: u64,
    pub retained_utf8_bytes: u64,
    pub truncated: bool,
    pub redacted_sha256: yosoi_types::Sha256Digest,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserByteAccounting {
    pub configured_limit: u64,
    pub enforcement: crate::BrowserLimitEnforcement,
    pub budget_scope: crate::BrowserBudgetScope,
    pub observed: u64,
    pub retained: u64,
    pub lost: LossExtent,
    pub complete: bool,
}
#[derive(Clone, Eq, PartialEq, Serialize, serde::Deserialize)]
pub struct BrowserAccessibilityEvidence {
    pub schema: BrowserAccessibilitySchema,
    pub schema_version: u32,
    pub capture_mode: BrowserAccessibilityCaptureMode,
    pub requested_depth: Option<i64>,
    pub ignored_nodes: BrowserAccessibilityIgnoredNodes,
    pub scope: BrowserDocumentScope,
    pub at: CaptureOffset,
    pub nodes_observed: u64,
    pub nodes_retained: u64,
    pub nodes_lost: LossExtent,
    pub bytes: BrowserByteAccounting,
    pub canonical_node_bytes: Vec<u8>,
}

impl fmt::Debug for BrowserAccessibilityEvidence {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserAccessibilityEvidence")
            .field("schema", &self.schema)
            .field("schema_version", &self.schema_version)
            .field("capture_mode", &self.capture_mode)
            .field("requested_depth", &self.requested_depth)
            .field("ignored_nodes", &self.ignored_nodes)
            .field("scope", &self.scope)
            .field("at", &self.at)
            .field("nodes_observed", &self.nodes_observed)
            .field("nodes_retained", &self.nodes_retained)
            .field("nodes_lost", &self.nodes_lost)
            .field("bytes", &self.bytes)
            .field("canonical_node_byte_len", &self.canonical_node_bytes.len())
            .field("canonical_node_bytes", &"<redacted>")
            .finish()
    }
}
/// Admitted, retained, and exact-or-unknown lost network resource records.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct BrowserResourceAccounting {
    admitted: u64,
    retained: u64,
    lost: LossExtent,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserResourceAccountingError {
    #[error("retained resources cannot exceed admitted resources")]
    RetainedExceedsAdmitted,
    #[error("retained and known lost resources must equal admitted resources")]
    KnownLossMismatch,
    #[error("resource accounting exceeds its integer representation")]
    Overflow,
}
impl BrowserResourceAccounting {
    pub fn new(
        admitted: u64,
        retained: u64,
        lost: LossExtent,
    ) -> Result<Self, BrowserResourceAccountingError> {
        if retained > admitted {
            return Err(BrowserResourceAccountingError::RetainedExceedsAdmitted);
        }
        if let LossExtent::Known(lost) = lost
            && retained
                .checked_add(lost)
                .ok_or(BrowserResourceAccountingError::Overflow)?
                != admitted
        {
            return Err(BrowserResourceAccountingError::KnownLossMismatch);
        }
        Ok(Self {
            admitted,
            retained,
            lost,
        })
    }
    pub const fn admitted(self) -> u64 {
        self.admitted
    }
    pub const fn retained(self) -> u64 {
        self.retained
    }
    pub const fn lost(self) -> LossExtent {
        self.lost
    }
}
#[derive(serde::Deserialize)]
struct BrowserResourceAccountingWire {
    admitted: u64,
    retained: u64,
    lost: LossExtent,
}
impl<'de> serde::Deserialize<'de> for BrowserResourceAccounting {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let wire = BrowserResourceAccountingWire::deserialize(deserializer)?;
        Self::new(wire.admitted, wire.retained, wire.lost).map_err(D::Error::custom)
    }
}
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Eq, PartialEq, Serialize, serde::Deserialize)]
pub enum BrowserStructuredEvidence {
    Network {
        requested_url: Option<crate::ResolvedWebUrl>,
        final_url: Option<crate::ResolvedWebUrl>,
        redirects: Vec<BrowserRedirectFact>,
        main_document: Option<BrowserMainDocumentFact>,
        extra_info: BrowserExtraInfoEvidence,
        resources: Vec<BrowserResourceFact>,
        events: Vec<BrowserObservationFact>,
        resource_accounting: BrowserResourceAccounting,
        event_accounting: crate::EventAccounting,
    },
    Accessibility(BrowserAccessibilityEvidence),
    Layout(BrowserLayoutFact),
    RuntimeDiagnostics {
        /// Provider-observed document scope, when diagnostics carry enough
        /// information to establish one without inference.
        scope: Option<BrowserDocumentScope>,
        diagnostics: Vec<BrowserRuntimeDiagnosticFact>,
        runtime_event_accounting: crate::EventAccounting,
        byte_accounting: BrowserByteAccounting,
    },
}

impl fmt::Debug for BrowserStructuredEvidence {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Network {
                requested_url,
                final_url,
                redirects,
                main_document,
                extra_info,
                resources,
                events,
                resource_accounting,
                event_accounting,
            } => formatter
                .debug_struct("BrowserStructuredEvidence::Network")
                .field("has_requested_url", &requested_url.is_some())
                .field("has_final_url", &final_url.is_some())
                .field("redirect_count", &redirects.len())
                .field("main_document", main_document)
                .field("extra_info", extra_info)
                .field("resource_count", &resources.len())
                .field("event_count", &events.len())
                .field("resource_accounting", resource_accounting)
                .field("event_accounting", event_accounting)
                .finish(),
            Self::Accessibility(evidence) => formatter
                .debug_tuple("BrowserStructuredEvidence::Accessibility")
                .field(evidence)
                .finish(),
            Self::Layout(layout) => formatter
                .debug_tuple("BrowserStructuredEvidence::Layout")
                .field(layout)
                .finish(),
            Self::RuntimeDiagnostics {
                scope,
                diagnostics,
                runtime_event_accounting,
                byte_accounting,
            } => formatter
                .debug_struct("BrowserStructuredEvidence::RuntimeDiagnostics")
                .field("scope", scope)
                .field("diagnostic_count", &diagnostics.len())
                .field("runtime_event_accounting", runtime_event_accounting)
                .field("byte_accounting", byte_accounting)
                .finish(),
        }
    }
}
impl BrowserStructuredEvidence {
    pub const fn family(&self) -> crate::WebArtifactFamily {
        match self {
            Self::Network { .. } => crate::WebArtifactFamily::Network,
            Self::Accessibility(_) => crate::WebArtifactFamily::AccessibilityTree,
            Self::Layout(_) => crate::WebArtifactFamily::Layout,
            Self::RuntimeDiagnostics { .. } => crate::WebArtifactFamily::RuntimeDiagnostics,
        }
    }
    /// Deterministic provider-neutral payload consumed by finalization without
    /// reinterpreting or re-hashing provider DTOs.
    pub fn to_canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }

    /// Parses exact structured browser evidence bytes after bundle integrity validation.
    pub fn from_json(bytes: &[u8]) -> Result<Self, serde_json::Error> {
        serde_json::from_slice(bytes)
    }
}
