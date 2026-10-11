//! Bounded offline views over captured browser observations.

use crate::flow;
use std::error as std_error;
use std::fmt;

use serde::{Deserialize, Serialize};

use crate::automation_record::{MAX_OBSERVATION_HTML_BYTES, Observation};
use crate::documents::Document;
use crate::locators::{
    LocateOutcome, NativeCoordinate, NodeReference, Plan, ProjectedValue, css, output,
};

/// Maximum number of DOM rows returned in one View page.
pub const MAX_VIEW_PAGE_SIZE: usize = 100;

/// Maximum UTF-8 bytes retained for the source URL in a View.
pub const MAX_VIEW_URL_BYTES: usize = 8 * 1024;

/// Maximum UTF-8 bytes accepted for an offline CSS assertion selector.
pub const MAX_VIEW_SELECTOR_BYTES: usize = 4 * 1024;

/// Maximum Unicode scalar values retained as a text preview in one row.
pub const MAX_VIEW_TEXT_PREVIEW_CHARS: usize = 512;

/// Exact observation identity and provenance used as the View's source.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ViewSource {
    observation_id: String,
    session_id: String,
    tab_id: String,
    document_epoch: u64,
    url: Option<String>,
}

impl ViewSource {
    /// Borrows the primary captured observation identity, not a live browser handle.
    pub fn observation_id(&self) -> &str {
        &self.observation_id
    }

    /// Borrows recorded Session provenance without reopening browser authority.
    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    /// Borrows recorded tab provenance without granting tab control.
    pub fn tab_id(&self) -> &str {
        &self.tab_id
    }

    /// Returns the captured document generation that scopes the retained DOM evidence.
    pub const fn document_epoch(&self) -> u64 {
        self.document_epoch
    }

    /// Borrows the captured source URL, when available; it is not fetched by the View.
    pub fn url(&self) -> Option<&str> {
        self.url.as_deref()
    }
}

/// A row naming one exact locator-backed DOM element reference.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DomElementRow {
    ordinal: u64,
    node: NodeReference,
    text_preview: String,
    text_truncated: bool,
}

impl DomElementRow {
    /// Returns the deterministic zero-based position among elements of the captured document.
    pub const fn ordinal(&self) -> u64 {
        self.ordinal
    }

    /// Borrows the document-bound locator node reference for this exact row.
    pub const fn node(&self) -> &NodeReference {
        &self.node
    }

    /// Borrows the native source-tree coordinate without resolving a live browser element.
    pub const fn coordinate(&self) -> &NativeCoordinate {
        self.node.coordinate()
    }

    /// Returns the bounded descendant-text preview captured for this element.
    pub fn text_preview(&self) -> &str {
        &self.text_preview
    }

    /// Reports whether the source element's descendant text exceeded the preview.
    pub const fn text_truncated(&self) -> bool {
        self.text_truncated
    }
}

/// Source binding carried by a View and every continuation cursor.
///
/// The observation ID is the primary source identity. `fingerprint` is only a
/// small advisory check that a caller has not reused that identity for changed
/// HTML; it is neither an integrity digest nor a substitute for provenance.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ViewCaptureToken {
    source: ViewSource,
    fingerprint: u64,
}

impl ViewCaptureToken {
    /// Borrows primary observation provenance shared by a View and its continuation cursor.
    pub const fn source(&self) -> &ViewSource {
        &self.source
    }

    /// Returns an advisory, non-cryptographic HTML fingerprint.
    pub const fn advisory_fingerprint(&self) -> u64 {
        self.fingerprint
    }
}

/// Opaque position for requesting the next bounded View page.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ViewCursor {
    capture: ViewCaptureToken,
    offset: u64,
    page_size: u64,
}

impl ViewCursor {
    /// Returns the zero-based element offset requested for the next bounded page.
    pub const fn offset(&self) -> u64 {
        self.offset
    }

    /// Returns the retained requested row bound, validated before continuation.
    pub const fn page_size(&self) -> u64 {
        self.page_size
    }

    /// Borrows observation provenance binding this cursor to one immutable capture.
    pub const fn capture_token(&self) -> &ViewCaptureToken {
        &self.capture
    }
}

/// One bounded page of deterministic DOM element references from an observation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct View {
    source: ViewSource,
    capture: ViewCaptureToken,
    rows: Vec<DomElementRow>,
    total_rows: u64,
    page_size: u64,
    next_cursor: Option<ViewCursor>,
}

impl View {
    /// Builds the first offline DOM page for captured HTML evidence.
    pub fn from_observation(
        observation: &Observation,
        page_size: usize,
    ) -> Result<Self, ViewError> {
        let capture = capture_token(observation)?;
        Self::page(observation, capture, 0, page_size)
    }

    /// Builds the next page after validating the cursor against its source capture.
    pub fn continue_from(
        observation: &Observation,
        cursor: &ViewCursor,
    ) -> Result<Self, ViewError> {
        let capture = capture_token(observation)?;
        validate_cursor_binding(&capture, cursor)?;
        let page_size = usize::try_from(cursor.page_size).map_err(|_| ViewError::InvalidCursor)?;
        Self::page(observation, capture, cursor.offset, page_size)
    }

    /// Borrows the exact observation provenance used to build this offline page.
    pub const fn source(&self) -> &ViewSource {
        &self.source
    }

    /// Borrows the source binding used to reject foreign or stale continuation cursors.
    pub const fn capture_token(&self) -> &ViewCaptureToken {
        &self.capture
    }

    /// Borrows retained bounded DOM rows in deterministic source order.
    pub fn rows(&self) -> &[DomElementRow] {
        &self.rows
    }

    /// Returns the complete captured-document element count, not a live DOM count.
    pub const fn total_rows(&self) -> u64 {
        self.total_rows
    }

    /// Returns the requested maximum rows per page; the final page can contain fewer.
    pub const fn page_size(&self) -> u64 {
        self.page_size
    }

    /// Borrows a bound cursor when captured rows remain, or `None` after the final page.
    pub const fn next_cursor(&self) -> Option<&ViewCursor> {
        self.next_cursor.as_ref()
    }

    /// Verifies a supported assertion against the same immutable observation.
    ///
    /// Exists and CountAtLeast use only the captured HTML and Yosoi's CSS
    /// locator. Visible requires live layout state and returns an explicit
    /// unsupported error for this offline view.
    pub fn verify_condition(
        &self,
        observation: &Observation,
        condition: &flow::Condition,
    ) -> Result<bool, ViewError> {
        let capture = capture_token(observation)?;
        validate_capture_binding(&self.capture, &capture).map_err(|error| match error {
            BindingError::Foreign => ViewError::ForeignObservation,
            BindingError::Stale => ViewError::StaleObservation,
        })?;
        match condition {
            flow::Condition::Exists { selector } => Ok(matching_count(observation, selector)? > 0),
            flow::Condition::CountAtLeast { selector, count } => {
                Ok(matching_count(observation, selector)? >= *count)
            }
            flow::Condition::Visible { .. } => {
                Err(ViewError::UnsupportedCondition { kind: "visible" })
            }
        }
    }

    fn page(
        observation: &Observation,
        capture: ViewCaptureToken,
        offset: u64,
        page_size: usize,
    ) -> Result<Self, ViewError> {
        if page_size == 0 || page_size > MAX_VIEW_PAGE_SIZE {
            return Err(ViewError::InvalidPageSize {
                maximum: MAX_VIEW_PAGE_SIZE,
            });
        }
        let html = observation
            .html
            .as_deref()
            .ok_or(ViewError::HtmlUnavailable)?;
        let observed_html = html.len();
        if observed_html > MAX_OBSERVATION_HTML_BYTES {
            return Err(ViewError::HtmlTooLarge {
                maximum: MAX_OBSERVATION_HTML_BYTES,
                observed: observed_html,
            });
        }
        let offset_usize = usize::try_from(offset).map_err(|_| ViewError::InvalidCursor)?;
        let document = Document::html(observation.id.clone(), html.as_bytes().to_vec())
            .map_err(|error| ViewError::Document(error.to_string()))?;
        let node_selector = css("*").map_err(|error| ViewError::Plan(error.to_string()))?;
        let text_selector = css("*").map_err(|error| ViewError::Plan(error.to_string()))?;
        let node_output = output("dom_element", node_selector.node())
            .map_err(|error| ViewError::Plan(error.to_string()))?;
        let text_output = output("element_text", text_selector.text())
            .map_err(|error| ViewError::Plan(error.to_string()))?;
        let plan = Plan::new([node_output, text_output])
            .map_err(|error| ViewError::Plan(error.to_string()))?;
        let outcome = document.locate(&plan);
        let (element_findings, text_findings) = match &outcome {
            LocateOutcome::Matched { result } => {
                let element_findings = result
                    .findings()
                    .iter()
                    .filter(|finding| finding.output_id().as_str() == "dom_element")
                    .collect::<Vec<_>>();
                let text_findings = result
                    .findings()
                    .iter()
                    .filter(|finding| finding.output_id().as_str() == "element_text")
                    .collect::<Vec<_>>();
                (element_findings, text_findings)
            }
            LocateOutcome::NoMatch { .. } => (Vec::new(), Vec::new()),
            LocateOutcome::Indeterminate { reason_code, .. } => {
                return Err(ViewError::IncompleteEvidence {
                    reason_code: reason_code.clone(),
                });
            }
            LocateOutcome::Failed { failure } => {
                return Err(ViewError::LocateFailed {
                    detail: format!("{failure:?}"),
                });
            }
        };
        if element_findings.len() != text_findings.len() {
            return Err(ViewError::MismatchedLocatorProjection);
        }
        let total_rows =
            u64::try_from(element_findings.len()).map_err(|_| ViewError::RowCountOverflow)?;
        if offset > total_rows || (offset > 0 && offset == total_rows) {
            return Err(ViewError::CursorOutOfRange { offset, total_rows });
        }

        let mut rows =
            Vec::with_capacity(page_size.min(element_findings.len().saturating_sub(offset_usize)));
        for (element, text) in element_findings
            .iter()
            .skip(offset_usize)
            .take(page_size)
            .zip(text_findings.iter().skip(offset_usize).take(page_size))
        {
            if element.coordinate() != text.coordinate() {
                return Err(ViewError::MismatchedLocatorProjection);
            }
            let node = match element.value() {
                ProjectedValue::Node(node) => node.clone(),
                _ => return Err(ViewError::UnexpectedProjection),
            };
            let ProjectedValue::Text(full_text) = text.value() else {
                return Err(ViewError::UnexpectedProjection);
            };
            let (text_preview, text_truncated) = bounded_text_preview(full_text);
            rows.push(DomElementRow {
                ordinal: element.order(),
                node,
                text_preview,
                text_truncated,
            });
        }
        let page_size_u64 = u64::try_from(page_size).map_err(|_| ViewError::RowCountOverflow)?;
        let next_offset = offset
            .checked_add(page_size_u64)
            .ok_or(ViewError::RowCountOverflow)?;
        let next_cursor = if next_offset < total_rows {
            Some(ViewCursor {
                capture: capture.clone(),
                offset: next_offset,
                page_size: page_size_u64,
            })
        } else {
            None
        };
        Ok(Self {
            source: capture.source.clone(),
            capture,
            rows,
            total_rows,
            page_size: page_size_u64,
            next_cursor,
        })
    }
}

fn capture_token(observation: &Observation) -> Result<ViewCaptureToken, ViewError> {
    validate_identity("observation id", &observation.id)?;
    validate_identity("session id", &observation.session_id)?;
    validate_identity("tab id", &observation.tab_id)?;
    if observation.document_epoch == 0 {
        return Err(ViewError::InvalidDocumentEpoch);
    }
    let html = observation
        .html
        .as_deref()
        .ok_or(ViewError::HtmlUnavailable)?;
    if html.len() > MAX_OBSERVATION_HTML_BYTES {
        return Err(ViewError::HtmlTooLarge {
            maximum: MAX_OBSERVATION_HTML_BYTES,
            observed: html.len(),
        });
    }
    if observation
        .url
        .as_ref()
        .is_some_and(|url| url.len() > MAX_VIEW_URL_BYTES)
    {
        return Err(ViewError::UrlTooLong {
            maximum: MAX_VIEW_URL_BYTES,
        });
    }
    Ok(ViewCaptureToken {
        source: ViewSource {
            observation_id: observation.id.clone(),
            session_id: observation.session_id.clone(),
            tab_id: observation.tab_id.clone(),
            document_epoch: observation.document_epoch,
            url: observation.url.clone(),
        },
        fingerprint: advisory_fingerprint(html.as_bytes()),
    })
}

fn validate_cursor_binding(
    capture: &ViewCaptureToken,
    cursor: &ViewCursor,
) -> Result<(), ViewError> {
    let maximum_page_size =
        u64::try_from(MAX_VIEW_PAGE_SIZE).map_err(|_| ViewError::InvalidCursor)?;
    if cursor.page_size == 0 || cursor.page_size > maximum_page_size || cursor.offset == 0 {
        return Err(ViewError::InvalidCursor);
    }
    validate_capture_binding(&cursor.capture, capture).map_err(|error| match error {
        BindingError::Foreign => ViewError::ForeignCursor,
        BindingError::Stale => ViewError::StaleCursor,
    })
}

fn validate_capture_binding(
    expected: &ViewCaptureToken,
    observed: &ViewCaptureToken,
) -> Result<(), BindingError> {
    if expected.source.observation_id != observed.source.observation_id
        || expected.source.session_id != observed.source.session_id
        || expected.source.tab_id != observed.source.tab_id
    {
        return Err(BindingError::Foreign);
    }
    if expected.source.document_epoch != observed.source.document_epoch
        || expected.source.url != observed.source.url
        || expected.fingerprint != observed.fingerprint
    {
        return Err(BindingError::Stale);
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum BindingError {
    Foreign,
    Stale,
}

fn matching_count(observation: &Observation, selector: &str) -> Result<u64, ViewError> {
    if selector.len() > MAX_VIEW_SELECTOR_BYTES {
        return Err(ViewError::SelectorTooLong {
            maximum: MAX_VIEW_SELECTOR_BYTES,
            observed: selector.len(),
        });
    }
    let html = observation
        .html
        .as_deref()
        .ok_or(ViewError::HtmlUnavailable)?;
    if html.len() > MAX_OBSERVATION_HTML_BYTES {
        return Err(ViewError::HtmlTooLarge {
            maximum: MAX_OBSERVATION_HTML_BYTES,
            observed: html.len(),
        });
    }
    let document = Document::html(observation.id.clone(), html.as_bytes().to_vec())
        .map_err(|error| ViewError::Document(error.to_string()))?;
    let selector = css(selector).map_err(|error| ViewError::Plan(error.to_string()))?;
    let named = output("assertion_target", selector.node())
        .map_err(|error| ViewError::Plan(error.to_string()))?;
    let plan = Plan::new([named]).map_err(|error| ViewError::Plan(error.to_string()))?;
    match document.locate(&plan) {
        LocateOutcome::Matched { result } => {
            u64::try_from(result.findings().len()).map_err(|_| ViewError::RowCountOverflow)
        }
        LocateOutcome::NoMatch { .. } => Ok(0),
        LocateOutcome::Indeterminate { reason_code, .. } => {
            Err(ViewError::IncompleteEvidence { reason_code })
        }
        LocateOutcome::Failed { failure } => Err(ViewError::LocateFailed {
            detail: format!("{failure:?}"),
        }),
    }
}

fn validate_identity(field: &'static str, value: &str) -> Result<(), ViewError> {
    if value.trim().is_empty() {
        return Err(ViewError::EmptyIdentity { field });
    }
    if value.len() > 1_024 {
        return Err(ViewError::IdentityTooLong { field });
    }
    Ok(())
}

fn advisory_fingerprint(bytes: &[u8]) -> u64 {
    // FNV-1a is deliberately only an in-process cursor consistency hint.
    let mut fingerprint = 0xcbf2_9ce4_8422_2325_u64;
    for byte in bytes {
        fingerprint ^= u64::from(*byte);
        fingerprint = fingerprint.wrapping_mul(0x0000_0100_0000_01b3);
    }
    fingerprint
}

fn bounded_text_preview(value: &str) -> (String, bool) {
    let mut preview = String::new();
    let mut characters = value.chars();
    for _ in 0..MAX_VIEW_TEXT_PREVIEW_CHARS {
        let Some(character) = characters.next() else {
            return (preview, false);
        };
        preview.push(character);
    }
    (preview, characters.next().is_some())
}

/// Typed failure while constructing or paging an offline View.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ViewError {
    /// A required observation, Session, or tab identity is blank.
    EmptyIdentity {
        /// Provenance identity role whose text was rejected.
        field: &'static str,
    },
    /// A provenance identity exceeds its UTF-8 byte bound.
    IdentityTooLong {
        /// Identity role whose text is oversized.
        field: &'static str,
    },
    /// The source epoch is zero and cannot scope immutable browser evidence.
    InvalidDocumentEpoch,
    /// No captured HTML is available for offline element reconstruction.
    HtmlUnavailable,
    /// Captured HTML exceeds the supported offline byte limit.
    HtmlTooLarge {
        /// Maximum accepted captured HTML bytes.
        maximum: usize,
        /// Actual captured HTML byte length.
        observed: usize,
    },
    /// Captured source URL text exceeds its retained byte bound.
    UrlTooLong {
        /// Maximum retained UTF-8 URL bytes.
        maximum: usize,
    },
    /// An offline assertion selector exceeds its UTF-8 byte limit.
    SelectorTooLong {
        /// Maximum accepted selector bytes.
        maximum: usize,
        /// Actual authored selector byte length.
        observed: usize,
    },
    /// Requested rows per page are zero or exceed the supported maximum.
    InvalidPageSize {
        /// Maximum supported rows per page.
        maximum: usize,
    },
    /// A continuation cursor has invalid structure, page bounds, or platform representation.
    InvalidCursor,
    /// Cursor provenance belongs to another observation, Session, or tab.
    ForeignCursor,
    /// Cursor provenance names the same observation but changed epoch, URL, or HTML fingerprint.
    StaleCursor,
    /// Assertion evidence belongs to another observation, Session, or tab than this View.
    ForeignObservation,
    /// Assertion evidence disagrees on epoch, URL, or the advisory captured-HTML fingerprint.
    StaleObservation,
    /// The condition needs live browser state unavailable in an offline View.
    UnsupportedCondition {
        /// Unsupported condition label, currently visible.
        kind: &'static str,
    },
    /// A continuation position is outside the remaining captured element rows.
    CursorOutOfRange {
        /// Zero-based row position supplied by the cursor.
        offset: u64,
        /// Total captured-document rows established by locator extraction.
        total_rows: u64,
    },
    /// Captured element count cannot fit portable row accounting.
    RowCountOverflow,
    /// Locator output is not the node projection required for exact element rows.
    UnexpectedProjection,
    /// Node and text projections do not form matching ordered element evidence.
    MismatchedLocatorProjection,
    /// Partial or unknown locator evidence prevents an unqualified offline result.
    IncompleteEvidence {
        /// Structural reason that evidence completeness could not be established.
        reason_code: String,
    },
    /// Locator execution failed instead of yielding complete captured evidence.
    LocateFailed {
        /// Retained typed-failure explanation for caller inspection.
        detail: String,
    },
    /// Retained observation HTML could not form the required source Document.
    Document(String),
    /// The internal supported offline locator plan could not be constructed.
    Plan(String),
}

impl fmt::Display for ViewError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyIdentity { field } => write!(formatter, "{field} cannot be empty"),
            Self::IdentityTooLong { field } => write!(formatter, "{field} exceeds 1024 bytes"),
            Self::InvalidDocumentEpoch => {
                formatter.write_str("document epoch must be greater than zero")
            }
            Self::HtmlUnavailable => formatter.write_str("captured HTML is unavailable"),
            Self::HtmlTooLarge { maximum, observed } => write!(
                formatter,
                "captured HTML has {observed} bytes, above the {maximum}-byte View limit"
            ),
            Self::UrlTooLong { maximum } => {
                write!(
                    formatter,
                    "captured URL exceeds the {maximum}-byte View limit"
                )
            }
            Self::SelectorTooLong { maximum, observed } => write!(
                formatter,
                "CSS selector has {observed} bytes, above the {maximum}-byte View limit"
            ),
            Self::InvalidPageSize { maximum } => {
                write!(formatter, "View page size must be between 1 and {maximum}")
            }
            Self::InvalidCursor => formatter.write_str("View cursor is invalid"),
            Self::ForeignCursor => {
                formatter.write_str("View cursor belongs to another observation")
            }
            Self::StaleCursor => {
                formatter.write_str("View cursor belongs to stale observation evidence")
            }
            Self::ForeignObservation => formatter.write_str("View belongs to another observation"),
            Self::StaleObservation => {
                formatter.write_str("View belongs to stale observation evidence")
            }
            Self::UnsupportedCondition { kind } => {
                write!(
                    formatter,
                    "offline View does not support the {kind} condition"
                )
            }
            Self::CursorOutOfRange { offset, total_rows } => write!(
                formatter,
                "View cursor offset {offset} is outside the {total_rows} available rows"
            ),
            Self::RowCountOverflow => formatter.write_str("View row count cannot be represented"),
            Self::UnexpectedProjection => {
                formatter.write_str("DOM locator returned a non-node projection")
            }
            Self::MismatchedLocatorProjection => {
                formatter.write_str("DOM row and text locators returned different source elements")
            }
            Self::IncompleteEvidence { reason_code } => {
                write!(formatter, "DOM evidence is incomplete: {reason_code}")
            }
            Self::LocateFailed { detail } => write!(formatter, "DOM locator failed: {detail}"),
            Self::Document(message) => {
                write!(formatter, "captured HTML Document is invalid: {message}")
            }
            Self::Plan(message) => write!(formatter, "DOM row locator plan is invalid: {message}"),
        }
    }
}

impl std_error::Error for ViewError {}
