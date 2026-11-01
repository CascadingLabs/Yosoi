//! Versioned live network evidence, separate from ordinary source JSON.

use crate::{
    documents::{
        Document, DocumentClass, DocumentId, DocumentProfile, DocumentSchemaProfile, FileDocument,
    },
    surface::SurfaceError,
};
use serde::{Deserialize, Serialize};
use sha2::Digest;
use std::collections::BTreeSet;
use url::Url;

/// Schema identifier for frozen native network observation Documents.
pub const NETWORK_OBSERVATION_SCHEMA: &str = "yosoi.network.v1";

/// Shared Page-lifetime CDP response buffer cap, matching the native 8 MiB body limit.
pub const NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES: usize = 8 * 1024 * 1024;
/// Shared Page-lifetime CDP aggregate buffer cap, matching the native watch byte limit.
pub const NETWORK_PROVIDER_TOTAL_BUFFER_BYTES: usize = 8 * 1024 * 1024;

/// Typed status returned after an explicitly requested native subscription starts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkSubscription {
    /// Whether event listeners are currently active.
    pub active: bool,
    /// Session-local subscription identity.
    pub subscription_id: String,
    /// Qualified event transport name.
    pub provider: String,
    /// Whether completed response bodies may be captured.
    pub body_retention: bool,
    /// Maximum event count retained by this subscription.
    pub max_events: usize,
    /// Maximum subscription lifetime in milliseconds.
    pub max_duration_ms: u64,
    /// Fixed live Surface-session body count cap; absent in older receipts.
    #[serde(default)]
    pub session_max_response_bodies: Option<usize>,
    /// Fixed live Surface-session byte cap; absent in older receipts.
    #[serde(default)]
    pub session_max_total_body_bytes: Option<usize>,
    /// Bodies still retained by frozen windows when the subscription was armed.
    #[serde(default)]
    pub session_retained_response_bodies: Option<usize>,
    /// Body bytes still retained when the subscription was armed.
    #[serde(default)]
    pub session_retained_body_bytes: Option<usize>,
}

/// Immutable network evidence produced by one bounded live subscription.
///
/// A window is a frozen observation, not a replay instruction or a network
/// client. It retains the producer's Session and tab identity, the observed
/// event sequence and time interval, requests still in flight, and explicit
/// uncertainty. Response payload bytes are stored separately and reached only
/// through [`NetworkPayloadRef`].
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkWindow {
    /// Versioned discriminator. This must be `yosoi.network.v1`.
    pub schema: String,
    /// Schema version, currently `1`.
    pub schema_version: u16,
    /// Native browser Session that owned the producer.
    pub session_id: String,
    /// Native tab selected when the subscription was armed.
    pub tab_id: String,
    /// Session-local subscription identity.
    pub subscription_id: String,
    /// Frozen window identity.
    pub window_id: String,
    /// First event sequence included, or `None` when no events were observed.
    pub first_sequence: Option<u64>,
    /// Last event sequence included, or `None` when no events were observed.
    pub last_sequence: Option<u64>,
    /// Local UTC time when the frozen interval began, in Unix microseconds.
    pub started_at_unix_us: u64,
    /// Local UTC time when the frozen interval ended, in Unix microseconds.
    pub ended_at_unix_us: u64,
    /// Events in producer delivery order. Provider timestamps remain separate.
    pub events: Vec<NetworkEvent>,
    /// Requests the producer knew were active at the prior freeze boundary.
    pub in_flight_at_start: Vec<NetworkInFlight>,
    /// Requests whose start was retained and whose terminal event was not seen.
    pub in_flight: Vec<NetworkInFlight>,
    /// Explicit intervals or causes where event evidence is missing.
    pub gaps: Vec<NetworkGap>,
    /// Known event loss and incomplete subscription coverage.
    pub coverage: NetworkCoverage,
    /// URL, header, body and filter choices that governed retained evidence.
    pub retention: NetworkRetention,
    /// Payload metadata and relationships; payload bytes live outside this window.
    pub payloads: Vec<NetworkPayloadRef>,
}

/// One typed spelling for a frozen [`NetworkWindow`].
pub type NetworkObservation = NetworkWindow;

impl NetworkWindow {
    /// Checks the version and basic sequence, interval, and relationship invariants.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.schema != NETWORK_OBSERVATION_SCHEMA || self.schema_version != 1 {
            return Err(SurfaceError::Invalid(
                "unsupported network observation schema".into(),
            ));
        }
        if self.session_id.is_empty()
            || self.tab_id.is_empty()
            || self.subscription_id.is_empty()
            || self.window_id.is_empty()
            || self.ended_at_unix_us < self.started_at_unix_us
        {
            return Err(SurfaceError::Invalid(
                "invalid network observation identity or interval".into(),
            ));
        }
        match (self.first_sequence, self.last_sequence) {
            (Some(first), Some(last)) if first > 0 && first <= last => {}
            (None, None) if self.events.is_empty() => {}
            _ => {
                return Err(SurfaceError::Invalid(
                    "invalid network observation sequence range".into(),
                ));
            }
        }
        if self.events.len() > 65_536
            || self.in_flight.len() > 65_536
            || self.payloads.len() > 65_536
        {
            return Err(SurfaceError::Limit("network observation item count"));
        }
        let mut prior_sequence = 0_u64;
        for event in &self.events {
            if event.sequence <= prior_sequence || event.request_id.is_empty() {
                return Err(SurfaceError::Invalid(
                    "network event sequences must increase and request identities must be nonempty"
                        .into(),
                ));
            }
            prior_sequence = event.sequence;
        }
        if self.events.first().map(|event| event.sequence) != self.first_sequence
            || self.events.last().map(|event| event.sequence) != self.last_sequence
        {
            return Err(SurfaceError::Invalid(
                "network event sequence range differs from its events".into(),
            ));
        }
        let mut payload_ids = BTreeSet::new();
        for payload in &self.payloads {
            if payload.id.is_empty()
                || payload.request_id.is_empty()
                || payload.response_sequence == 0
                || payload.response_window_id.is_empty()
                || !payload_ids.insert(&payload.id)
            {
                return Err(SurfaceError::Invalid(
                    "invalid network payload relationship".into(),
                ));
            }
            match payload.state {
                NetworkPayloadState::Retained | NetworkPayloadState::Truncated
                    if payload.document_id.is_none()
                        || payload.document_id.as_deref() != Some(payload.id.as_str())
                        || payload.document_kind.is_none()
                        || payload.projection_basis.is_none()
                        || payload.sha256.is_none()
                        || payload.byte_provenance
                            != NetworkByteProvenance::CdpDecodedResponseBody
                        || (payload.provider_base64_encoded && payload.text_utf8_normalized) =>
                {
                    let missing = if payload.document_id.as_deref() != Some(payload.id.as_str()) {
                        "document_id"
                    } else if payload.document_kind.is_none() {
                        "document_kind"
                    } else if payload.projection_basis.is_none() {
                        "projection_basis"
                    } else if payload.sha256.is_none() {
                        "sha256"
                    } else if payload.byte_provenance
                        != NetworkByteProvenance::CdpDecodedResponseBody
                    {
                        "byte_provenance"
                    } else {
                        "encoding_provenance"
                    };
                    return Err(SurfaceError::Invalid(format!(
                        "retained network payload has invalid {missing}"
                    )));
                }
                NetworkPayloadState::NotRequested
                | NetworkPayloadState::Unavailable
                | NetworkPayloadState::Unsupported
                    if payload.document_id.is_some()
                        || payload.document_kind.is_some()
                        || payload.projection_basis.is_some()
                        || payload.detected_media_type.is_some()
                        || payload.sha256.is_some()
                        || payload.retained_bytes != 0
                        || payload.byte_provenance != NetworkByteProvenance::None
                        || payload.text_utf8_normalized =>
                {
                    return Err(SurfaceError::Invalid(
                        "unretained network payload claims retained bytes".into(),
                    ));
                }
                _ => {}
            }
            if payload.response_window_id == self.window_id
                && !self.events.iter().any(|event| {
                    let response_sequence_matches = event.sequence == payload.response_sequence;
                    response_sequence_matches
                        && event.request_id == payload.request_id
                        && event.hop == payload.hop
                        && matches!(&event.kind, NetworkEventKind::ResponseReceived { .. })
                })
            {
                return Err(SurfaceError::Invalid(
                    "network payload reference does not address its response event".into(),
                ));
            }
        }
        Ok(())
    }

    /// Converts this contract to a Document carrying the dedicated network schema profile.
    ///
    /// An ordinary `Document::json` containing a similarly named field remains
    /// ordinary source JSON and does not acquire network-window semantics.
    pub fn to_document(&self, id: impl Into<String>) -> Result<Document, SurfaceError> {
        self.validate()?;
        let bytes =
            serde_json::to_vec(self).map_err(|error| SurfaceError::Parse(error.to_string()))?;
        Document::from_profile(
            DocumentId::try_new(id).map_err(|error| SurfaceError::Invalid(error.to_string()))?,
            DocumentProfile::network_observation_v1(),
            bytes,
        )
        .map_err(|error| SurfaceError::Invalid(error.to_string()))
    }

    /// Restores a typed window only from a Document with the dedicated schema profile.
    pub fn from_document(document: &Document) -> Result<Self, SurfaceError> {
        if document.profile().schema() != DocumentSchemaProfile::YosoiNetworkObservationV1 {
            return Err(SurfaceError::Invalid(
                "document does not carry the network observation profile".into(),
            ));
        }
        let window: Self = serde_json::from_slice(document.bytes())
            .map_err(|error| SurfaceError::Parse(error.to_string()))?;
        window.validate()?;
        Ok(window)
    }
}

/// One event from the bounded provider listener.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkEvent {
    /// Monotonic subscription sequence in listener delivery order.
    pub sequence: u64,
    /// Provider request identity, scoped to the Session and tab.
    pub request_id: String,
    /// Whether the corresponding request start was seen before this event.
    /// False preserves an out-of-order or missing-start condition explicitly.
    pub request_start_observed: bool,
    /// Redirect hop for this provider request identity.
    pub hop: u32,
    /// Local UTC receipt time, in Unix microseconds.
    pub observed_at_unix_us: u64,
    /// Provider event time in microseconds, when the provider supplied it.
    pub provider_time_us: Option<u64>,
    /// Clock used for `provider_time_us`; it is not a UTC timestamp.
    pub provider_clock: Option<NetworkProviderClock>,
    /// Browser frame identity when the provider supplied it.
    pub frame_id: Option<String>,
    /// Browser loader identity when the provider supplied it.
    pub loader_id: Option<String>,
    /// Event-specific request, redirect, response, completion, or failure data.
    pub kind: NetworkEventKind,
}

/// Provider clock basis retained separately from local receipt time.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkProviderClock {
    /// Chromium DevTools Protocol monotonic seconds converted to microseconds.
    CdpMonotonic,
}

/// Network event details with URL and header retention already applied.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum NetworkEventKind {
    /// A request started.
    RequestStarted {
        /// Retained URL under the configured URL redaction policy.
        url: String,
        /// HTTP method.
        method: String,
        /// Browser resource category when provided.
        resource_type: Option<String>,
        /// Headers selected by the explicit allowlist policy.
        headers: Vec<NetworkHeader>,
    },
    /// The prior hop received a redirect response before the next request event.
    Redirect {
        /// Retained source URL under the configured URL redaction policy.
        from_url: String,
        /// Retained target URL under the configured URL redaction policy.
        to_url: String,
        /// Redirect response status.
        status: u16,
        /// Headers selected by the explicit allowlist policy.
        headers: Vec<NetworkHeader>,
    },
    /// Response metadata became available.
    ResponseReceived {
        /// Retained response URL under the configured URL redaction policy.
        url: String,
        /// HTTP response status, when supplied by the provider.
        status: Option<u16>,
        /// Content-Type header value observed from the response, including parameters.
        declared_media_type: Option<String>,
        /// Browser-effective MIME value reported by CDP.
        browser_effective_mime: Option<String>,
        /// Browser-effective charset reported by CDP, separate from the raw header value.
        browser_effective_charset: Option<String>,
        /// Declared content encoding, when supplied by the provider.
        content_encoding: Option<String>,
        /// Headers selected by the explicit allowlist policy.
        headers: Vec<NetworkHeader>,
    },
    /// The provider reported that the response completed.
    Finished {
        /// Encoded transfer length reported by the provider, if available.
        encoded_data_length: Option<u64>,
    },
    /// The provider reported a failed or canceled request.
    Failed {
        /// Bounded provider failure label, with secret-bearing URLs removed.
        error: String,
        /// Whether the provider marked the failure as canceled.
        canceled: bool,
    },
}

/// One retained response header under a caller-selected allowlist.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkHeader {
    /// Lowercase header name.
    pub name: String,
    /// Header value after bounds and sensitive-name filtering.
    pub value: String,
}

/// A request known to cross a frozen window boundary without a terminal event.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkInFlight {
    /// Provider request identity, scoped to the Session and tab.
    pub request_id: String,
    /// Current redirect hop.
    pub hop: u32,
    /// Latest retained URL under the configured redaction policy.
    pub url: String,
    /// HTTP method.
    pub method: String,
    /// Whether response metadata was observed before the boundary.
    pub response_seen: bool,
}

/// Explicit losses and limits for one window.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "Coverage records independent observed losses and boundary facts; combining them into exclusive states would lose simultaneous evidence."
)]
pub struct NetworkCoverage {
    /// Network event evidence never claims browser-wide or cross-target completeness.
    pub complete: bool,
    /// Why the provider cannot prove complete network coverage.
    pub reason: String,
    /// Whether a provider event stream overflow was detected.
    pub overflow: bool,
    /// Number of events known to have been dropped by retention bounds.
    pub dropped_events: u64,
    /// Whether the provider disconnected while the subscription was active.
    pub disconnected: bool,
    /// Whether the subscription reached its configured lifetime bound.
    pub expired: bool,
    /// Whether this subscription enabled CDP Network from a previously disabled state.
    pub instrumentation_escalated: bool,
    /// Whether the page had already enabled Network instrumentation before this subscription.
    pub network_was_previously_enabled: bool,
    /// Events received after an earlier window ended but carrying an earlier provider time.
    pub late_events: u64,
    /// Number of events omitted by caller-selected origin or method filters.
    pub filtered_events: u64,
    /// Events whose request start was absent at their delivery time.
    pub starts_not_observed: u64,
    /// Number of payload links omitted by the frozen Document byte bound.
    pub omitted_payload_links: u64,
    /// Whether this window begins with unknown prior in-flight requests.
    pub start_boundary_unknown: bool,
    /// Whether this window ends with requests still in flight.
    pub end_boundary_in_flight: bool,
}

/// A known omission in the provider event sequence or subscription lifetime.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkGap {
    /// Last sequence known to be retained before the gap.
    pub after_sequence: u64,
    /// Bounded, secret-safe gap reason.
    pub reason: String,
    /// Number of events known to have been dropped, when available.
    pub dropped_events: Option<u64>,
}

/// Link from a response event to a separately retained body payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkPayloadRef {
    /// Opaque payload identity, local to this subscription.
    pub id: String,
    /// Provider request identity.
    pub request_id: String,
    /// Redirect hop that produced this response.
    pub hop: u32,
    /// Sequence of the response event that introduced this payload.
    pub response_sequence: u64,
    /// Window that contains the linked response event.
    pub response_window_id: String,
    /// Local UTC time when body capture completed or failed, independent of event window time.
    pub body_capture_at_unix_us: Option<u64>,
    /// Whether bytes were retained, truncated, absent, or unsupported.
    pub state: NetworkPayloadState,
    /// Existing source Document or FileDocument representation used for the bytes.
    pub document_kind: Option<NetworkPayloadKind>,
    /// Basis for choosing that projection, absent when no bytes were retained.
    pub projection_basis: Option<NetworkProjectionBasis>,
    /// Observed Content-Type response header value, including parameters.
    pub declared_media_type: Option<String>,
    /// Browser-effective MIME value reported by CDP.
    pub browser_effective_mime: Option<String>,
    /// Browser-effective charset reported by CDP.
    pub browser_effective_charset: Option<String>,
    /// Detected media type from shared source sniffing or typed file magic.
    pub detected_media_type: Option<String>,
    /// Declared content encoding, when available.
    pub content_encoding: Option<String>,
    /// Whether retained bytes are provider-decoded transfer bytes or exact wire bytes.
    pub byte_provenance: NetworkByteProvenance,
    /// Whether CDP returned a base64 wrapper that Yosoi decoded into retained bytes.
    pub provider_base64_encoded: bool,
    /// Sum of CDP `Network.dataReceived.dataLength` values, absent if unknown.
    pub provider_reported_body_bytes: Option<u64>,
    /// Whether CDP returned Unicode text, retained as its UTF-8 normalized view.
    /// This is distinct from the response header value preserved in `declared_media_type`.
    #[serde(default)]
    pub text_utf8_normalized: bool,
    /// Retained byte count, including zero for a deliberately omitted body.
    pub retained_bytes: u64,
    /// Lowercase SHA-256 of retained bytes, absent when no body was retained.
    pub sha256: Option<String>,
    /// Document/FileDocument identity used to resolve the retained payload offline.
    pub document_id: Option<String>,
    /// Bounded explanation when payload projection or retrieval did not succeed.
    pub reason: Option<String>,
}

/// Projection selected for one retained response body.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkPayloadKind {
    /// Parsed through the existing source HTML Document.
    Html,
    /// Parsed through the existing source JSON Document.
    Json,
    /// Opaque or media bytes classified through the existing FileDocument API.
    File,
}

/// Evidence used to select the retained body's shared Document/FileDocument projection.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkProjectionBasis {
    /// Requests source classification selected the declared media type.
    RequestsDeclared,
    /// Requests source classification selected a structured `+json` or `+xml` suffix.
    RequestsStructuredSuffix,
    /// Requests source classification selected a supported format by bounded sniffing.
    RequestsSniffed,
    /// Existing typed media detection selected a FileDocument from file magic.
    TypedFileMagic,
    /// No supported source format or typed file signature was detected.
    OpaqueBytes,
}

/// Retention choices recorded beside every frozen window.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkRetention {
    /// Maximum subscription lifetime in milliseconds.
    pub max_duration_ms: u64,
    /// Lifetime event journal limit.
    pub max_events: usize,
    /// Maximum queued provider events per typed listener.
    pub max_buffered_events: usize,
    /// Total serialized event metadata cap.
    pub max_event_bytes: usize,
    /// Maximum frozen windows retained by the live reader.
    pub max_windows: usize,
    /// Whether URL paths were retained; credentials and fragments are always removed.
    pub retain_url_path: bool,
    /// Whether URL query strings were retained.
    pub retain_url_query: bool,
    /// Explicitly retained header names. Sensitive headers are always removed.
    pub retained_header_names: Vec<String>,
    /// Whether the caller enabled response-body retention.
    pub retain_bodies: bool,
    /// Maximum response bodies retained by the caller.
    pub max_response_bodies: usize,
    /// Maximum retained bytes for one caller-visible body.
    pub max_body_bytes: usize,
    /// Maximum caller-visible response bytes retained by this subscription.
    pub max_total_body_bytes: usize,
    /// Fixed body count cap across this live Surface session's retained windows.
    /// Absent in windows created before session-bound body accounting.
    #[serde(default)]
    pub session_max_response_bodies: Option<usize>,
    /// Fixed body byte cap across this live Surface session's retained windows.
    /// Cancelling or rearming a subscription does not reset this cap.
    #[serde(default)]
    pub session_max_total_body_bytes: Option<usize>,
    /// Shared Page-lifetime CDP per-resource response buffer bound.
    pub provider_resource_buffer_bytes: usize,
    /// Shared Page-lifetime CDP total response buffer bound.
    pub provider_total_buffer_bytes: usize,
    /// Origin allowlist, empty when no origin filter was selected.
    pub allowed_origins: Vec<String>,
    /// Method allowlist, empty when no method filter was selected.
    pub allowed_methods: Vec<String>,
}

/// Independent limits and redaction choices for one native network subscription.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct NetworkObservationPolicy {
    /// Maximum subscription lifetime, in milliseconds.
    pub max_duration_ms: u64,
    /// Maximum events retained in the subscription journal.
    pub max_events: usize,
    /// Maximum queued provider events per typed listener, independent of journal retention.
    pub max_buffered_events: usize,
    /// Maximum frozen windows retained by the live Surface reader.
    pub max_windows: usize,
    /// Maximum total serialized event metadata retained by the journal.
    pub max_event_bytes: usize,
    /// Maximum response bodies captured by one subscription. Its initial value
    /// also fixes the live Surface session's retained-body count cap.
    pub max_response_bodies: usize,
    /// Maximum bytes returned for one opted-in response body.
    pub max_body_bytes: usize,
    /// Maximum total response bytes retained by one subscription. Its initial
    /// value also fixes the live Surface session's retained-body byte cap.
    pub max_total_body_bytes: usize,
    /// Whether completed response bodies may be captured. Defaults to false.
    pub retain_bodies: bool,
    /// Whether URL paths are retained. Defaults to false.
    pub retain_url_path: bool,
    /// Whether URL query strings are retained. Defaults to false.
    pub retain_url_query: bool,
    /// If nonempty, only these exact HTTP(S) origins are retained.
    pub allowed_origins: Vec<String>,
    /// If nonempty, only these exact methods are retained.
    pub allowed_methods: Vec<String>,
    /// Header names eligible for retention; credentials and cookies are never retained.
    pub header_allowlist: Vec<String>,
}

impl Default for NetworkObservationPolicy {
    fn default() -> Self {
        Self {
            max_duration_ms: 300_000,
            max_events: 2_048,
            max_buffered_events: 256,
            max_windows: 32,
            max_event_bytes: 2 * 1024 * 1024,
            max_response_bodies: 16,
            max_body_bytes: 1024 * 1024,
            max_total_body_bytes: 8 * 1024 * 1024,
            retain_bodies: false,
            retain_url_path: false,
            retain_url_query: false,
            allowed_origins: Vec::new(),
            allowed_methods: Vec::new(),
            header_allowlist: Vec::new(),
        }
    }
}

impl NetworkObservationPolicy {
    /// Rejects unbounded or malformed retention choices before arming a provider.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if !(1..=3_600_000).contains(&self.max_duration_ms)
            || !(1..=4_096).contains(&self.max_events)
            || !(1..=256).contains(&self.max_buffered_events)
            || !(1..=4_096).contains(&self.max_windows)
            || !(1..=16 * 1024 * 1024).contains(&self.max_event_bytes)
            || self.max_response_bodies > 1024
            || !(1..=8 * 1024 * 1024).contains(&self.max_body_bytes)
            || !(1..=64 * 1024 * 1024).contains(&self.max_total_body_bytes)
            || self.allowed_origins.len() > 256
            || self.allowed_methods.len() > 64
            || self.header_allowlist.len() > 64
        {
            return Err(SurfaceError::Invalid(
                "invalid network observation bounds".into(),
            ));
        }
        for origin in &self.allowed_origins {
            let valid_origin = Url::parse(origin).is_ok_and(|url| {
                matches!(url.scheme(), "http" | "https")
                    && url.username().is_empty()
                    && url.password().is_none()
                    && url.path() == "/"
                    && url.query().is_none()
                    && url.fragment().is_none()
                    && url.origin().ascii_serialization() == origin.as_str()
            });
            if origin.is_empty() || origin.len() > 2_048 || !valid_origin {
                return Err(SurfaceError::Invalid(
                    "network origin filters must be bounded HTTP(S) origins".into(),
                ));
            }
        }
        for method in &self.allowed_methods {
            if method.is_empty() || method.len() > 32 || !method.is_ascii() {
                return Err(SurfaceError::Invalid(
                    "network method filters must be bounded ASCII tokens".into(),
                ));
            }
        }
        for name in &self.header_allowlist {
            if name.is_empty()
                || name.len() > 128
                || !name.is_ascii()
                || name
                    .bytes()
                    .any(|byte| !byte.is_ascii_alphanumeric() && byte != b'-')
            {
                return Err(SurfaceError::Invalid(
                    "network header allowlist contains an invalid name".into(),
                ));
            }
        }
        Ok(())
    }

    /// Returns the serializable retention summary stored in each window.
    pub fn retention(&self) -> NetworkRetention {
        NetworkRetention {
            max_duration_ms: self.max_duration_ms,
            max_events: self.max_events,
            max_buffered_events: self.max_buffered_events,
            max_event_bytes: self.max_event_bytes,
            max_windows: self.max_windows,
            retain_url_path: self.retain_url_path,
            retain_url_query: self.retain_url_query,
            retained_header_names: self
                .header_allowlist
                .iter()
                .map(|name| name.to_ascii_lowercase())
                .filter(|name| !is_sensitive_header(name))
                .collect(),
            retain_bodies: self.retain_bodies,
            max_response_bodies: self.max_response_bodies,
            max_body_bytes: self.max_body_bytes,
            max_total_body_bytes: self.max_total_body_bytes,
            session_max_response_bodies: Some(self.max_response_bodies),
            session_max_total_body_bytes: Some(self.max_total_body_bytes),
            provider_resource_buffer_bytes: NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES,
            provider_total_buffer_bytes: NETWORK_PROVIDER_TOTAL_BUFFER_BYTES,
            allowed_origins: self.allowed_origins.clone(),
            allowed_methods: self.allowed_methods.clone(),
        }
    }
}

pub(super) fn is_sensitive_header(name: &str) -> bool {
    matches!(
        name,
        "authorization"
            | "proxy-authorization"
            | "cookie"
            | "set-cookie"
            | "cookie2"
            | "x-api-key"
            | "x-api-token"
            | "x-access-token"
            | "x-refresh-token"
            | "x-session-token"
            | "x-auth-token"
    )
}

/// Outcome of the opt-in response-body path.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkPayloadState {
    /// The caller did not request body retention.
    NotRequested,
    /// A complete body was retained.
    Retained,
    /// A bounded prefix was retained and is incomplete.
    Truncated,
    /// The provider could not return the body after completion.
    Unavailable,
    /// The declared body type has no supported Document projection.
    Unsupported,
}

/// Provenance of the bytes linked to a browser response.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NetworkByteProvenance {
    /// Chromium returned response bytes from `Network.getResponseBody`; this is not wire capture.
    CdpDecodedResponseBody,
    /// No payload bytes were retained.
    None,
}

/// Concrete Document or FileDocument projection for one retained response.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NetworkPayloadValue {
    /// HTML or JSON projected through the existing immutable Document API.
    Document(Document),
    /// Binary or media bytes classified by the existing FileDocument factory.
    File(Box<FileDocument>),
}

impl NetworkPayloadValue {
    /// Returns the exact retained bytes without copying.
    pub fn bytes(&self) -> &[u8] {
        match self {
            Self::Document(document) => document.bytes(),
            Self::File(document) => document.bytes(),
        }
    }
}

/// A separately retained body paired with its exact NetworkPayloadRef.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NetworkPayload {
    /// The response link and body retention state from a frozen NetworkWindow.
    pub reference: NetworkPayloadRef,
    /// The existing source Document or FileDocument carrying these bytes.
    pub value: NetworkPayloadValue,
}

impl NetworkPayload {
    /// Returns the exact retained payload bytes without copying.
    pub fn bytes(&self) -> &[u8] {
        self.value.bytes()
    }

    /// Restores a retained body from a portable Surface outcome without opening a browser.
    pub fn from_outcome(
        outcome: &super::Outcome,
        reference: &NetworkPayloadRef,
        maximum: u64,
    ) -> Result<Self, SurfaceError> {
        let mut belongs_to_outcome = false;
        for source in &outcome.sources {
            if source.profile != Some(DocumentProfile::network_observation_v1()) {
                continue;
            }
            let document = source.restore(outcome.limits.bytes)?;
            let window = NetworkWindow::from_document(&document)?;
            if window.payloads.iter().any(|retained| retained == reference) {
                belongs_to_outcome = true;
                break;
            }
        }
        if !belongs_to_outcome {
            return Err(SurfaceError::Invalid(
                "network payload reference is not retained by this Outcome".into(),
            ));
        }
        if !matches!(
            reference.state,
            NetworkPayloadState::Retained | NetworkPayloadState::Truncated
        ) || reference.document_id.as_deref() != Some(reference.id.as_str())
        {
            return Err(SurfaceError::Unknown);
        }
        let Some(kind) = reference.document_kind else {
            return Err(SurfaceError::Invalid(
                "retained network payload has no projection kind".into(),
            ));
        };
        let value = match kind {
            NetworkPayloadKind::Html | NetworkPayloadKind::Json => {
                let document = outcome.source_document(&reference.id, maximum)?;
                let expected = if kind == NetworkPayloadKind::Html {
                    DocumentClass::SourceHtml
                } else {
                    DocumentClass::SourceJson
                };
                if document.class() != expected {
                    return Err(SurfaceError::Invalid(
                        "network payload source Document has the wrong profile".into(),
                    ));
                }
                NetworkPayloadValue::Document(document)
            }
            NetworkPayloadKind::File => NetworkPayloadValue::File(Box::new(
                outcome.source_file_document(&reference.id, maximum)?,
            )),
        };
        let digest = match &value {
            NetworkPayloadValue::Document(document) => {
                format!("{:x}", sha2::Sha256::digest(document.bytes()))
            }
            NetworkPayloadValue::File(document) => document.sha256().to_owned(),
        };
        if reference.sha256.as_deref() != Some(digest.as_str()) {
            return Err(SurfaceError::Invalid(
                "restored network payload digest differs from its response reference".into(),
            ));
        }
        Ok(Self {
            reference: reference.clone(),
            value,
        })
    }
}
